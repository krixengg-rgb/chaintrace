"""v29 cross-chain swap tracing (bridges.py Chainflip + THORChain/Maya, xswap.py instant-swapper leads, AutoTrace, PDF + evidence pack). Real mainnet data only:
- Chainflip: Bitcoin deposit tx -> swap #1501259 -> USDC egress on Ethereum (deterministic, chainflip-swap.chainflip.io);
- THORChain: BTC -> ETH memo swap (Midgard), as in uitest_bridge;
- instant swapper: a 0.1 ETH payment into a one-off FixedFloat deposit address that swept to the FixedFloat wallet labelled by GraphSense
  (etherscan labelcloud) -> payout leads from labelled swapper wallets, marked heuristic, value/time window enforced, confidence <= 60%;
- swapper label file: every row cites a public source URL; hacker / deployer / token / scam look-alike rows excluded;
- AutoTrace: Chainflip deposit channel detected by tx hash and crossed deterministically; instant swapper reached -> heuristic leads (not followed);
- PDF section 4 + evidence pack cross_chain_hops.csv carry deterministic vs heuristic;
- UI desktop + phone: tx view '🔀 Swap hops' card, deep link &xswap=1, add lead -> dotted amber edge.
Password from env LP (never printed). Usage: LP=... python3 uitest_xswap.py   (CT_URL, SHOT_TAG=_live, ENGINE=0, API=0, SHOTS=0)"""
import asyncio, csv, io, json, os, subprocess, sys, tempfile, time, zipfile
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v29_xswap_{n}{TAG}.png")
CF_BTC = "ae1de0ca58d7ad7dcd94a051c24903e0f59d661d5d2eb5f990f59ca653751073"     # BTC deposit into a Chainflip deposit channel (swap #1501259)
CF_OUT = "0xab26c7b3a3b8bfa258ae728b3d50942c6fbf93b990ffcead76a056be44b648cf"   # its USDC egress on Ethereum
CF_DEST = "0x81330a9e8b22aa9b671b94f02c9ad8072dc5b675"
CF_CHANNEL = "bc1ptkm2hj04x4ch60cw2ez70ggvfxmdyddnhu2afm50xk34753uemsqqqxqer"
THOR_BTC = "FC6E6B0863C394BCECBF4C070F2E6129A165E5C3175091D7733FA3CF9663DA34"      # THORChain BTC -> ETH swap (uitest_bridge)
FF_IN = "0xcddc69c3af130228bd8b85ffdb0608a50652a51c0f360e99558eafea00010331"     # 0.1 ETH into a one-off deposit address that swept to FixedFloat
FF_DEP = "0x62a4d956775b1755764a03316c7250068b1827a6"
FF_WALLET = "0x4e5b2e1dc63f6b91cb6cd759936495434c7e972f"                         # FixedFloat (GraphSense TagPack, etherscan labelcloud)
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush(); return " ".join(subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout.split())

async def engine():
    import bridges, xswap
    rows = json.load(open(os.path.join(H, "data", "swappers.json")))["entries"]
    check("swapper labels: every row has a source + http URL; no hacker/deployer/token/scam rows", rows and all(r["src"] and r["url"].startswith("http") for r in rows)
          and not any(any(w in r["name"].lower() for w in ("hacker", "deployer", "token", "scam", "endaoment")) for r in rows), len(rows))
    check("swapper labels: FixedFloat wallet present with its GraphSense source", (xswap.is_swapper("eth", FF_WALLET) or {}).get("service") == "FixedFloat")
    ms = await bridges.chainflip_tx(CF_BTC); m = ms[0] if ms else {}
    check("Chainflip: BTC deposit -> swap #1501259 -> USDC egress on Ethereum, deterministic",
          m and m["method"] == "deterministic" and m["confidence"] >= 0.99 and m["src"]["chain"] == "btc" and m["dst"]["chain"] == "eth" and (m["dst"]["tx"] or "").lower() == CF_OUT
          and (m["dst"]["address"] or "").lower() == CF_DEST and m["dst"]["unit"] == "USDC" and abs(m["src"]["amount"] - 0.012) < 1e-9 and "1501259" in m["ref"], m and (m["dst"], m["ref"]))
    check("Chainflip: deposit channel address is the source side (one-off address, noted)", m and m["src"]["address"] == CF_CHANNEL and any("deposit address" in n for n in m["notes"]))
    check("Chainflip: unknown hash -> no match (no invention)", await bridges.chainflip_tx("0" * 64) == [])
    r = await bridges.match_tx(THOR_BTC)
    check("THORChain: BTC -> ETH memo swap stays deterministic (Midgard)", any(x["provider"] == "midgard" and x["method"] == "deterministic" for x in r["matches"]), [x["bridge"] for x in r["matches"]])

def api():
    cl = httpx.Client(auth=(AUTH["username"], AUTH["password"]), timeout=150)
    j = cl.get(U + "/api/xswap", params={"tx": CF_BTC}).json()
    d = [m for m in j.get("deterministic", []) if m["provider"] == "chainflip"]
    check("api: /api/xswap Chainflip match is deterministic, a swap, with a cross-chain graph edge", d and d[0]["swap"] and d[0]["graph"]["edges"][0]["xchain"] and d[0]["graph"]["edges"][0]["method"] == "deterministic", j.get("detail") or [m["bridge"] for m in j.get("deterministic", [])])
    time.sleep(3)
    j = cl.get(U + "/api/xswap", params={"tx": FF_IN}).json(); h = j.get("heuristic") or {}
    if any("timed out" in str(n) for n in h.get("notes") or []):   # cold host: the card says 'retry (results are cached)' - do what a user would
        print("note: first instant-swapper search timed out (cold host); retrying once", flush=True); time.sleep(5)
        j = cl.get(U + "/api/xswap", params={"tx": FF_IN}).json(); h = j.get("heuristic") or {}
    cs = h.get("candidates") or []; sw = h.get("swapper") or {}
    check("api: FixedFloat input recognised (deposit address swept to the labelled FixedFloat wallet)", sw.get("service") == "FixedFloat" and sw.get("kind") == "sweep" and sw.get("wallet", "").lower() == FF_WALLET and sw.get("url", "").startswith("http"), sw)
    check("api: instant-swapper payouts returned as heuristic leads with value/time limits and confidence <= 60%",
          cs and all(x["method"] == "heuristic" and x["confidence"] <= 0.6 and 0.85 <= x["ratio"] <= 1.02 and -60 <= x["dt_min"] <= 180 and xswap_labelled(x) for x in cs), [(x["service"], x["ratio"], x["dt_min"], x["confidence"]) for x in cs[:4]])
    check("api: each lead carries a dotted heuristic graph edge + the lead caveat", cs and all(x["graph"]["edges"][0]["heur"] and x["graph"]["edges"][0]["bridge"]["method"] == "heuristic" for x in cs) and "not evidence" in h.get("lead", ""))
    check("api: /api/bridges lists Chainflip (deterministic) and instant swappers (heuristic)", any("Chainflip" in s["bridge"] for s in cl.get(U + "/api/bridges").json()["supported"]))
    time.sleep(3)
    # AutoTrace: Chainflip deposit channel crossed deterministically
    r = cl.post(U + "/api/autotrace", params={"q": CF_BTC, "direction": "forward", "max_hops": 2, "min_usd": 10, "topk": 3, "follow_bridges": "true", "max_secs": 60}).json()
    for _ in range(40):
        time.sleep(4); t = cl.get(U + f"/api/trace/{r['job']}").json()
        if t["status"] not in ("queued", "running"): break
    bs = t.get("bridges") or []
    check("api: AutoTrace detects the Chainflip deposit channel and crosses BTC -> ETH deterministically", any(b["bridge"] == "Chainflip swap" and b["method"] == "deterministic" and b["dst"]["chain"] == "eth" for b in bs)
          and any(n["id"].lower() == CF_DEST for n in t["nodes"]), [(b["bridge"], b["method"]) for b in bs])
    time.sleep(10)
    r = cl.post(U + "/api/autotrace", params={"q": FF_IN, "direction": "forward", "max_hops": 3, "min_usd": 10, "topk": 3, "follow_bridges": "true", "max_secs": 90}).json()
    for _ in range(50):
        time.sleep(4); t2 = cl.get(U + f"/api/trace/{r['job']}").json()
        if t2["status"] not in ("queued", "running"): break
    hb = [b for b in t2.get("bridges") or [] if b["method"] == "heuristic"]
    check("api: AutoTrace reaching FixedFloat lists heuristic payout leads (dotted, not followed)", hb and all(b["provider"] == "xswap" and b["confidence"] <= 0.6 for b in hb)
          and all(e.get("heur") for e in t2["edges"] if e.get("xswap")), (t2.get("stop_reason"), len(hb), t2.get("errors", [])[:2]))
    time.sleep(5)
    # evidence pack with both kinds of hop
    nodes = {n["id"]: n for n in t["nodes"] + t2["nodes"]}; edges = t["edges"] + t2["edges"]
    p = {"meta": {"ref": "XSWAP-UITEST"}, "case": {"name": "xswap uitest", "query": CF_BTC}, "nodes": list(nodes.values()), "edges": edges, "trace": {"bridges": bs + hb}}
    z = cl.post(U + "/api/evidence-pack", json=p)
    zf = zipfile.ZipFile(io.BytesIO(z.content)) if z.status_code == 200 else None
    cn = [n for n in (zf.namelist() if zf else []) if n.endswith("cross_chain_hops.csv")]
    rows = list(csv.DictReader(io.StringIO(zf.read(cn[0]).decode()))) if cn else []
    check("evidence pack: cross_chain_hops.csv has the deterministic Chainflip swap and heuristic swapper leads", any(r_["method"] == "deterministic" and r_["type"] == "swap" and r_["dst_tx"].lower() == CF_OUT for r_ in rows)
          and any(r_["method"].startswith("heuristic") for r_ in rows), (z.status_code, len(rows)))
    pdf = zf.read(next(n for n in zf.namelist() if n.endswith(".pdf"))) if zf else b""
    t_ = pdftext(pdf) if pdf else ""
    check("PDF: section 4 'Cross-chain bridge and swap hops' shows Chainflip DETERMINISTIC and a HEURISTIC instant-swap lead", "Cross-chain bridge and swap hops" in t_ and "Chainflip swap" in t_ and "DETERMINISTIC" in t_ and "HEURISTIC" in t_ and "instant swap" in t_, t_[:100])
def xswap_labelled(x):
    import xswap
    return bool(xswap.is_swapper(x["chain"], x["wallet"]))

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w, h, tag in ((1600, 950, "desktop"), (390, 844, "phone")):
            ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials=AUTH)
            pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U + f"/?q={CF_BTC}&xswap=1"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000)
            await pg.wait_for_function("window.CT_LAST_XSWAP&&document.querySelector('#xscard .det')", timeout=90000)
            txt = await pg.inner_text("#xscard")
            check(f"ui {tag}: deep link &xswap=1 -> Chainflip swap deterministic card", "Chainflip swap" in txt and "DETERMINISTIC" in txt.upper(), txt[:160])
            await pg.wait_for_timeout(1500)
            n = await pg.evaluate(f"cy.edges().filter(e=>e.data('xchain')&&!e.data('heur')).length")
            check(f"ui {tag}: deterministic swap drawn as a dashed cross-chain edge to the ETH recipient", n >= 1 and await pg.evaluate(f"cy.nodes().some(x=>x.id().toLowerCase()==='{CF_DEST}')"), n)
            check(f"ui {tag}: '🔀 Swap hops' button on the tx card", await pg.query_selector(".xsbtn") is not None)
            if tag == "desktop":
                await pg.evaluate("cy.fit(undefined,60);document.getElementById('xscard').scrollIntoView()")
                if SHOTS: await pg.screenshot(path=SHOT("chainflip_desktop"))
            await pg.goto(U + f"/?q={FF_IN}&xswap=1"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000)
            await pg.wait_for_function("window.CT_LAST_XSWAP&&document.querySelector('#xscard .cand, #xscard .xnote')", timeout=90000)
            txt = await pg.inner_text("#xscard")
            check(f"ui {tag}: FixedFloat leads listed as heuristic with caveat + source link", "FixedFloat" in txt and "lead only" in txt.lower() and "not evidence" in txt and await pg.query_selector("#xscard .cand") is not None, txt[:200])
            await pg.click("#xscard .xsadd"); await pg.wait_for_timeout(1200)
            hn = await pg.evaluate("cy.edges().filter(e=>e.data('heur')&&e.data('xchain')).length")
            check(f"ui {tag}: added lead is a dotted amber (heuristic) edge", hn >= 1, hn)
            ov = await pg.evaluate("document.documentElement.scrollWidth")
            if tag == "phone": check("ui phone: no horizontal overflow", ov <= 392, ov)
            await pg.evaluate("cy.fit(undefined,50);document.getElementById('xscard').scrollIntoView()")
            if SHOTS: await pg.screenshot(path=SHOT(tag))
            check(f"ui {tag}: no JS errors", not errs, errs[:2]); await ctx.close()
        await b.close()

if __name__ == "__main__":
    os.environ.setdefault("CHAINTRACE_CACHE", "/workspace/scratch/uitest_xswap_cache.sqlite")
    if os.environ.get("ENGINE", "1") != "0": asyncio.run(engine())
    if os.environ.get("API", "1") != "0": api()
    asyncio.run(ui())
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
