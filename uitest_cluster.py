"""v23 BTC 'likely same wallet' clustering (cluster.py, static/cluster.js). Real mainnet data only:
- CoinJoin detector on real transactions (Wasabi-style 0.0625 BTC round, JoinMarket-style, dust token tx = not a mix, ordinary payment);
  Whirlpool shape is checked on a synthetic tx (the Whirlpool coordinator shut down in April 2024);
- clustering of OFAC-listed addresses: every 'co-spent' member is re-checked against its evidence transaction (both addresses are inputs);
  an address whose history contains CoinJoins gets them excluded; caps stop the search and say so;
- API + UI (desktop + phone): panel, CSV, add to graph, collapse into one compound node, lead wording.
Password from env LP (never printed). Usage: LP=... python3 uitest_cluster.py   (CT_URL, SHOT_TAG=_live, ENGINE=0, SHOTS=0)"""
import asyncio, os, sys, json, time
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v23_cluster_{n}{TAG}.png")
MP = "https://mempool.space/api"
HYDRA = "123WBUDmSJv4GctdVEz6Qq6z8nXSKrJ4KX"        # Hydra Market (OFAC SDN, April 2022)
CJ_ADDR = "14kqryJUxM3a7aEi117KX9hoLUw592WsMR"      # OFAC SDN (Tian Yinyin, Lazarus laundering, March 2020): history includes CoinJoins
BIG = "bc1q48er9g2qngym6fleuzlz6k0frmyvwy3ggsnxw0"  # busy co-spending wallet (hits the caps)
TX = {"wasabi": "06924da2357cd71810b41dbfd84336a8f57d27101abe2b522be3e2c679cd5101", "joinmarket": "bda452831f0b7a13ad42b768c1061c8382507aed4c219db119cf40d721aa6c0d",
      "dust": "602629c235a65d82bf7a19f79f07cb521cbfce88a0735e382167fef6e844f040", "payment": "ba352b4b9d283274767c82c438f25d09b40d328e6711a623ef829e26f9f37726"}
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
def tx(h): return httpx.get(f"{MP}/tx/{h}", timeout=30).json()
def inputs(t): return {(v.get("prevout") or {}).get("scriptpubkey_address") for v in t["vin"]}

async def engine():
    import cluster
    check("real Wasabi-style CoinJoin detected", (cluster.coinjoin(tx(TX["wasabi"])) or "").startswith("Wasabi"), cluster.coinjoin(tx(TX["wasabi"])))
    check("real JoinMarket-style CoinJoin detected", "JoinMarket" in (cluster.coinjoin(tx(TX["joinmarket"])) or ""), cluster.coinjoin(tx(TX["joinmarket"])))
    check("dust token tx (6 x 546 sats) is NOT a CoinJoin", cluster.coinjoin(tx(TX["dust"])) is None)
    check("ordinary 4-input payment is NOT a CoinJoin", cluster.coinjoin(tx(TX["payment"])) is None)
    wp = {"vin": [{"prevout": {"scriptpubkey_address": f"a{i}", "value": 1000500}} for i in range(5)], "vout": [{"value": 1000000} for _ in range(5)]}
    check("Whirlpool shape (synthetic: 5 in / 5 x 0.01 BTC) detected", "Whirlpool" in (cluster.coinjoin(wp) or ""))
    r = await cluster.cluster(HYDRA)
    co = [m for m in r["addresses"] if m["reason"] == "common-input"]
    check("Hydra: cluster found (root labelled OFAC)", r["size"] >= 3 and "OFAC" in (r["addresses"][0].get("name") or ""), (r["size"], r["addresses"][0].get("name")))
    good = all(m["address"] in inputs(tx(m["tx"])) and m["with"] in inputs(tx(m["tx"])) for m in co[:6])
    check("Hydra: every co-spent member really co-spends with its partner (re-checked on mempool.space)", co and good, len(co))
    r2 = await cluster.cluster(CJ_ADDR)
    check("CoinJoins in the history are excluded and listed", r2["coinjoin_count"] >= 1 and all(cluster.coinjoin(tx(c["tx"])) for c in r2["coinjoin_skipped"][:3]), (r2["coinjoin_count"], r2["size"]))
    cjtx = {c["tx"] for c in r2["coinjoin_skipped"]}
    check("no member was added through an excluded CoinJoin", not any(m.get("tx") in cjtx for m in r2["addresses"]))
    r3 = await cluster.cluster(BIG, max_addrs=30, max_secs=15)
    check("caps: address cap stops the search and says so", r3["size"] <= 30 and r3["truncated"], (r3["size"], r3["truncated"]))
    check("lead + method wording", "not attribution" in r["lead"] and "CoinJoin" in r["method"])

def api():
    cl = httpx.Client(auth=(AUTH["username"], AUTH["password"]), timeout=60)
    j = cl.get(U + "/api/btc/cluster", params={"address": HYDRA}).json()
    check("api: cluster for Hydra", j.get("size", 0) >= 3 and j.get("lead") and j.get("caps"), (j.get("size"), j.get("detail")))
    j = cl.get(U + "/api/btc/cluster", params={"address": "0x28C6c06298d514Db089934071355E5743bf21d60"})
    check("api: non-BTC address rejected (400)", j.status_code == 400)
    j = cl.get(U + "/api/btc/cluster", params={"address": HYDRA, "change": 1}).json()
    check("api: optional change heuristic runs (members only added at high confidence)", "size" in j and all((m.get("confidence") or 1) >= 0.85 for m in j["addresses"] if m["reason"] == "change"), j.get("by_reason"))

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w, h, tag in ((1600, 950, "desktop"), (390, 844, "phone")):
            ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials=AUTH, accept_downloads=True)
            pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U + f"/?q={HYDRA}&cluster=1"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000)
            await pg.wait_for_function("window.CT_LAST_CLUSTER&&document.querySelector('#clucard .lst')", timeout=60000)
            txt = await pg.inner_text("#clucard")
            check(f"ui {tag}: deep link &cluster=1 opens the 'Likely same wallet' panel", "Likely same wallet" in txt and "co-spent" in txt)
            check(f"ui {tag}: lead wording shown", "not attribution" in txt)
            check(f"ui {tag}: button on the address card", await pg.query_selector(".clubtn") is not None)
            n = await pg.evaluate("CT_LAST_CLUSTER.size")
            if tag == "desktop":
                async with pg.expect_download() as dl: await pg.click("#clucard button:has-text('CSV')")
                csv = open(await (await dl.value).path()).read(); check("ui: CSV export (one row per address + lead line)", csv.startswith("address,reason") and csv.count("\n") >= n + 1 and "not attribution" in csv)
                await pg.click("#cluadd"); await pg.wait_for_timeout(3500)
                gi = await pg.evaluate(f"(()=>{{const g=cy.getElementById('grp:wal:{HYDRA}');return [g.length,g.children().length,!!g.data('collapsed'),cy.nodes('[?grp]').map(x=>x.id())]}})()")
                check("ui: Add to graph -> compound group with every member", gi[0] and gi[1] == n, gi)
                await pg.evaluate(f"ctSplit('grp:wal:{HYDRA}')")
            await pg.click("#clucol"); await pg.wait_for_timeout(1500)
            st = await pg.evaluate(f"(()=>{{const g=cy.getElementById('grp:wal:{HYDRA}');return {{c:!!g.data('collapsed'),lbl:g.data('lbl'),vis:cy.nodes('.gmem').length}}}})()")
            check(f"ui {tag}: Collapse into one node -> single compound node", st["c"] and st["vis"] == n and "Likely same wallet" in (st["lbl"] or ""), st)
            await pg.evaluate("document.getElementById('clucard').scrollIntoView()") if tag == "phone" else None
            if SHOTS: await pg.screenshot(path=SHOT(tag))
            check(f"ui {tag}: no JS errors", not errs, errs[:2]); await ctx.close()
        await b.close()

if __name__ == "__main__":
    os.environ.setdefault("CHAINTRACE_CACHE", "/workspace/scratch/uitest_cluster_cache.sqlite")
    if os.environ.get("ENGINE", "1") != "0": asyncio.run(engine())
    api(); asyncio.run(ui())
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
