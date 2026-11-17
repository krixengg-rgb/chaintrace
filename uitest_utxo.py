"""v22 Litecoin, Dogecoin and Bitcoin Cash (utxo.py; keyless). Real mainnet addresses and transactions:
1) engine: address detection / validation (base58 version bytes, bech32 ltc1, CashAddr checksum, legacy<->CashAddr), every source and
   fallback (Blockbook, litecoinspace Esplora, BlockCypher, Blockchain.com Haskoin) agree on the same transaction;
2) API: lookups (prefixed ids, balances, amounts re-checked against a second public explorer), sanctions screening (OFAC listings for
   LTC / DOGE / BCH incl. a BCH listing published in legacy format), loss calculator with on-the-day prices, AutoTrace, PDF report;
3) UI desktop + phone: deep links, chain selector, badge, explorer links, chain colours, pasted CashAddr / legacy BCH.
Password from env LP (never printed). Usage: LP=... python3 uitest_utxo.py   (CT_URL for another server; SHOT_TAG=_live; SHOTS=0 to skip)"""
import asyncio, os, sys, json, time, subprocess, tempfile
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v22_utxo_{n}{TAG}.png")
LTC_A = "LPv9e17z73UVMcWymL81rSQvrdMATUiFfN"
LTC_TX = "88d60e59875a3a0de4b3bd0e60aaf4e154b51c7ad961d4fb2799fbc0d509dec7"   # pays MM5iULdT… 0.27165283 LTC + LPv9… 42.59665717 LTC
DOGE_TX = "b70be51979d4b354c4ebbb7d8ab8a6c55b207abfc1ca7a9b68d7b6d56eb96ccc"  # DRmCnxz… -> DEyhKMn… 324.5639666 DOGE, change back
DOGE_FROM, DOGE_TO = "DRmCnxzL9U11EJzLmWkm2ikaZikPFbLuQD", "DEyhKMnB2Em1kNWWFazyPZfeh83ny2Tr1x"
BCH_A, BCH_LEG = "qprth0vvwwhm4752kx6nfjm8lup06pfa5sfvw0t76d", "17T1Cry5rHrYCpFb3vmayZ4pvkBDEuHBAL"
BCH_TX = "beff5a3debc38e245ad420a7d17c02f5ad53c4a506911de8fcb3e5e08f75ab45"
SANCT = [("bch", "18M8bJWMzWHDBMxoLqjHHAffdRy4SrzkfB", "Secondeye"), ("doge", "DHzAVdEoL3PjGeLWNdEJwwMA1CeQ9J9Cpo", "Rashevskyi"),
         ("ltc", "LNf2JDiuunBz7GMDKFYHN4rq5meXWxiwfb", "")]
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
near = lambda a, b, t=1e-8: a is not None and b is not None and abs(a - b) <= t
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush(); return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout

async def engine():
    import utxo, chains
    check("detect LTC base58 L…", chains.detect(LTC_A)[0] == "ltc"); check("detect LTC bech32 ltc1…", chains.detect("ltc1qzta6t0s2sxfrl242ed62d8kqh59zghzsgpfg8q")[0] == "ltc")
    check("detect DOGE D…", chains.detect(DOGE_TO)[0] == "doge"); check("detect BCH CashAddr", chains.detect(BCH_A)[0] == "bch" and chains.detect("bitcoincash:" + BCH_A)[0] == "bch")
    check("legacy 1… stays Bitcoin without a hint", chains.detect(BCH_LEG)[0] == "btc")
    check("bch: prefix + legacy -> CashAddr", utxo.bare("bch", BCH_LEG) == BCH_A, utxo.bare("bch", BCH_LEG))
    check("CashAddr -> legacy round trip", utxo.cash_to_legacy(BCH_A) == BCH_LEG)
    check("bad CashAddr checksum rejected", utxo.validate("bch", BCH_A[:-1] + ("q" if BCH_A[-1] != "q" else "p")))
    check("bad base58 checksum rejected", utxo.validate("doge", DOGE_TO[:-1] + ("a" if DOGE_TO[-1] != "a" else "b")))
    check("valid addresses accepted", utxo.validate("doge", DOGE_TO) is None and utxo.validate("bch", BCH_A) is None and utxo.validate("ltc", LTC_A) is None)
    for c, h in (("ltc", LTC_TX), ("doge", DOGE_TX), ("bch", BCH_TX)):
        import chains as C
        fb = {"ltc": (f"{utxo.LTC_ESPLORA}/tx/{h}", utxo._norm_es), "doge": (f"{utxo.BCY}/txs/{h}?limit=100", utxo._norm_bcy), "bch": (f"{utxo.HASKOIN}/transaction/{h}", utxo._norm_hk)}[c]
        vals = {}
        try: vals["blockbook"] = await utxo._bbtx(utxo.BLOCKBOOK[c][0], h, c)
        except Exception as ex: vals["blockbook"] = ex
        try: vals["fallback"] = await utxo._wrap(C.get(fb[0], ttl=C.LONG), fb[1], c)
        except Exception as ex: vals["fallback"] = ex
        v = [x for x in vals.values() if isinstance(x, dict)]
        check(f"{c}: Blockbook and the fallback source agree on inputs, outputs and fee", len(v) == 2 and v[0]["ins"] == v[1]["ins"] and v[0]["outs"] == v[1]["outs"] and near(v[0]["fee"], v[1]["fee"]),
              {k: (repr(x)[:60] if isinstance(x, Exception) else (len(x["ins"]), len(x["outs"]), x["fee"])) for k, x in vals.items()})
        t = await utxo.tx(c, h); check(f"{c}: tx {h[:10]} loaded", t and t.get("outs"), t and t.get("source"))

def api():
    cl = httpx.Client(auth=(AUTH["username"], AUTH["password"]), timeout=120)
    d = cl.get(U + "/api/lookup", params={"q": LTC_A}).json()
    check("api ltc: bare L… address detected, prefixed id", d.get("chain") == "ltc" and d.get("address") == "ltc:" + LTC_A, (d.get("chain"), d.get("address"), d.get("detail")))
    es = httpx.get(f"https://litecoinspace.org/api/address/{LTC_A}", timeout=30).json(); cs = es["chain_stats"]; ms = es["mempool_stats"]
    bal = (cs["funded_txo_sum"] - cs["spent_txo_sum"] + ms["funded_txo_sum"] - ms["spent_txo_sum"]) / 1e8
    check("api ltc: balance matches litecoinspace.org", near(d.get("balance"), bal, 1e-8), (d.get("balance"), bal))
    check("api ltc: counterparties + txs", len(d.get("edges") or []) >= 5 and len(d.get("txs") or []) >= 5, (len(d.get("edges") or []), len(d.get("txs") or [])))
    check("api ltc: Load more cursor", bool(d.get("next")), d.get("next"))
    if d.get("next"):
        d2 = cl.get(U + "/api/lookup", params={"q": "ltc:" + LTC_A, "cursor": d["next"]}).json()
        new = {t["tx"] for t in d2.get("txs") or []} - {t["tx"] for t in d.get("txs") or []}
        check("api ltc: page 2 returns older txs", new and max(t["time"] for t in d2["txs"]) <= max(t["time"] for t in d["txs"]), (len(new), d2.get("detail")))
    t = cl.get(U + "/api/lookup", params={"q": "ltc:" + LTC_TX}).json()
    o = {e["target"]: e["amount"] for e in t.get("edges") or [] if e["source"].startswith("tx:")}
    check("api ltc tx: outputs 0.27165283 + 42.59665717 LTC", near(o.get("ltc:MM5iULdT21Wrrbt4FA3eP7fsFXtXJUPHuQ"), 0.27165283) and near(o.get("ltc:" + LTC_A), 42.59665717), o)
    g = cl.get(U + "/api/lookup", params={"q": "doge:" + DOGE_TX}).json()
    bcy = httpx.get(f"https://api.blockchair.com/dogecoin/dashboards/transaction/{DOGE_TX}", timeout=30)
    o = {e["target"]: e["amount"] for e in g.get("edges") or [] if e["source"].startswith("tx:")}
    check("api doge tx: 324.5639666 DOGE to DEyh…, change back to sender", near(o.get("doge:" + DOGE_TO), 324.5639666) and ("doge:" + DOGE_FROM) in o, o)
    if bcy.status_code == 200:
        bo = {x["recipient"]: x["value"] / 1e8 for x in bcy.json()["data"][DOGE_TX]["outputs"]}
        check("api doge tx: amounts match Blockchair", all(near(o.get("doge:" + k), v) for k, v in bo.items()), bo)
    vic = "doge:" + DOGE_FROM; sus = "doge:" + DOGE_TO
    r = cl.post(U + "/api/loss", json={"nodes": g["nodes"], "edges": g["edges"], "loss": {"victims": [vic], "suspect": sus, "method": "proportional"}})
    T = {x["asset"]: x for x in (r.json().get("totals") or [])} if r.status_code == 200 else {}
    check("api loss doge: 324.5639666 DOGE lost (change to self not counted), priced now", "DOGE" in T and near(T["DOGE"]["amount"], 324.5639666) and T["DOGE"].get("usd_now"), T or r.text[:200])
    g2 = cl.get(U + "/api/lookup", params={"q": "ltc:" + LTC_TX}).json()
    src = next((e["source"] for e in g2["edges"] if e["target"].startswith("tx:")), None)
    r = cl.post(U + "/api/loss", json={"nodes": g2["nodes"], "edges": g2["edges"], "loss": {"victims": [src], "suspect": "ltc:MM5iULdT21Wrrbt4FA3eP7fsFXtXJUPHuQ", "method": "fifo"}})
    T = {x["asset"]: x for x in (r.json().get("totals") or [])} if r.status_code == 200 else {}
    check("api loss ltc: valued on the day (Coinbase LTC-USD daily close) + GBP", "LTC" in T and T["LTC"].get("usd_then") and T["LTC"].get("gbp_then"), T or r.text[:200])
    for leg in (False, True):
        q = ("bch:" + BCH_LEG) if leg else ("bitcoincash:" + BCH_A)
        b = cl.get(U + "/api/lookup", params={"q": q}).json()
        check(f"api bch: {'legacy with bch: prefix' if leg else 'bitcoincash: CashAddr'} -> CashAddr id", b.get("chain") == "bch" and b.get("address") == "bch:" + BCH_A and len(b.get("txs") or []) == 2, (b.get("address"), len(b.get("txs") or []), b.get("detail")))
    b = cl.get(U + "/api/lookup", params={"q": BCH_LEG, "chain": "bch"}).json()
    check("api bch: chain=bch hint routes a legacy 1… address to BCH", b.get("chain") == "bch" and b.get("address") == "bch:" + BCH_A, (b.get("chain"), b.get("address")))
    for c, a, who in SANCT:
        j = cl.get(U + "/api/screen", params={"addr": a, "chain": c}).json()
        check(f"api screen {c}: OFAC listing {a[:10]}… -> sanctioned", j.get("verdict") == "sanctioned" and j.get("chain") == c and (not who or who.lower() in json.dumps(j).lower()), (j.get("verdict"), j.get("chain")))
    j = cl.get(U + "/api/screen", params={"addr": "bitcoincash:qpgf0ztxq3mwfq6eg5versgfdzq9c3pwv5jsk6wnay"}).json()
    check("api screen bch: CashAddr form of a legacy-format listing still matches", j.get("verdict") == "sanctioned", j.get("verdict"))
    j = cl.get(U + "/api/screen", params={"addr": LTC_A}).json(); check("api screen ltc: unlisted address -> no match", j.get("verdict") == "no match", j.get("verdict"))
    s = cl.get(U + "/api/lookup", params={"q": "doge:" + SANCT[1][1]}).json(); L = s.get("label") or {}
    check("api lookup doge sanctioned: label + severe risk", L.get("kind") == "sanctioned" and (s.get("risk") or {}).get("level") == "severe", (L.get("name"), (s.get("risk") or {}).get("level")))
    jb = cl.post(U + "/api/autotrace", params={"q": "doge:" + DOGE_FROM, "max_hops": 2, "max_nodes": 30, "max_secs": 60, "min_usd": 1}).json()
    t0 = time.time(); r = {}
    while time.time() - t0 < 100 and jb.get("job"):
        r = cl.get(U + f"/api/trace/{jb['job']}").json()
        if r.get("status") in ("done", "error", "stopped", "timeout"): break
        time.sleep(3)
    ns = r.get("nodes") or []
    check("api AutoTrace on Dogecoin with prefixed ids", r.get("status") == "done" and len(ns) >= 2 and all(n["id"].startswith(("doge:", "tx:")) or ":" in n["id"] for n in ns), (r.get("status"), len(ns), r.get("detail") or jb.get("detail")))
    pl = {"nodes": g["nodes"], "edges": g["edges"], "case": {"name": "UTXO test", "labels": {}}, "meta": {"ref": "UTXO-TEST", "investigator": "uitest"},
          "loss": {"victims": [vic], "suspect": sus, "method": "proportional"}}
    r = cl.post(U + "/api/report", json=pl, timeout=180); txt = pdftext(r.content) if r.status_code == 200 else ""
    open("/workspace/scratch/utxo_pdf.txt", "w").write(txt)
    check("PDF report: DOGE graph, chain code + amounts + methodology source", r.status_code == 200 and "DOGE" in txt and "324.5639666" in txt.replace(",", "") and "Blockbook" in txt, (r.status_code, len(txt)))

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1600, "height": 950}, http_credentials=AUTH)
        pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + f"/?q=ltc:{LTC_A}"); await pg.wait_for_function("cy.nodes().length>=5", timeout=120000); await pg.wait_for_timeout(1500)
        check("ui desktop: ltc deep link sets selector=Litecoin + LTC badge", await pg.input_value("#chainSel") == "ltc" and "LTC" in await pg.inner_text("#chainBadge"))
        check("ui desktop: explorer link is litecoinspace", await pg.evaluate("[...document.querySelectorAll('#side a')].some(a=>a.href.startsWith('https://litecoinspace.org/address/'))"))
        check("ui desktop: LTC balance shown", "LTC" in await pg.inner_text("#side"))
        check("ui desktop: nodes painted in the Litecoin colour + legend", await pg.evaluate("cy.nodes().filter(n=>n.data('cc')===CH.ltc.c).length>=3") and "Litecoin" in await pg.inner_text("#legend"))
        if SHOTS: await pg.screenshot(path=SHOT("desktop"))
        await pg.fill("#q", "bitcoincash:" + BCH_A); await pg.evaluate("setBadge()")
        check("ui desktop: pasted CashAddr detected as BCH", "BCH" in await pg.inner_text("#chainBadge"))
        await pg.evaluate("go()"); await pg.wait_for_function("cy.nodes().length>=3", timeout=120000); await pg.wait_for_timeout(1200)
        check("ui desktop: BCH lookup -> selector=Bitcoin Cash, CashAddr shown", await pg.input_value("#chainSel") == "bch" and BCH_A in await pg.inner_text("#side"))
        await pg.fill("#q", "bc1q6fgk474qn7kkj26ddwsd9qtynx7qca0phsynp4"); q = await pg.evaluate("normQ()")
        check("ui desktop: a BTC address after a BCH search goes to Bitcoin (selector resets)", q == "bc1q6fgk474qn7kkj26ddwsd9qtynx7qca0phsynp4" and await pg.input_value("#chainSel") == "auto", q)
        await pg.select_option("#chainSel", "doge"); await pg.fill("#q", DOGE_TX); await pg.evaluate("go()")
        await pg.wait_for_function("cy.nodes().length>=3", timeout=120000); await pg.wait_for_timeout(1200)
        sd = await pg.inner_text("#side")
        check("ui desktop: DOGE tx hash with Dogecoin selected -> transaction view", "transaction" in sd.lower() and "DOGE" in sd and await pg.evaluate(f"cy.getElementById('doge:{DOGE_TO}').length===1"), sd[:200])
        if SHOTS: await pg.screenshot(path=SHOT("doge_tx_desktop"))
        check("ui desktop: no JS errors", not errs, errs[:2]); await ctx.close()
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, http_credentials=AUTH)
        pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + f"/?q={SANCT[0][1]}&chain=bch"); await pg.wait_for_function("cy.nodes().length>=3", timeout=120000); await pg.wait_for_timeout(1500)
        body = await pg.inner_text("body")
        check("ui phone: legacy BCH + chain=bch deep link -> CashAddr, sanctioned label", await pg.input_value("#chainSel") == "bch" and "qpgf0ztxq3mwfq6eg5versgfdzq9c3pwv5jsk6wnay" in body and "Secondeye" in body)
        check("ui phone: no horizontal overflow", await pg.evaluate("document.documentElement.scrollWidth<=window.innerWidth+2"))
        if SHOTS: await pg.screenshot(path=SHOT("phone"))
        check("ui phone: no JS errors", not errs, errs[:2]); await ctx.close(); await b.close()

if __name__ == "__main__":
    os.environ.setdefault("CHAINTRACE_CACHE", "/workspace/scratch/uitest_utxo_cache.sqlite")
    if os.environ.get("ENGINE", "1") != "0": asyncio.run(engine())
    if os.environ.get("API", "1") != "0": api()
    asyncio.run(ui())
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
