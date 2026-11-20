"""v25 mixer / privacy / no-KYC swap / gambling exposure (exposure.py, build_exposure.py, static/exposure.js). Real mainnet data only:
- label file: every entry carries a source and URL; curated entries cite project docs / OFAC; known addresses resolve to the right category;
- direct exposure: a real depositor into the Tornado Cash 0.1 ETH pool; a real BTC sender to an OFAC-listed Sinbad address;
- indirect exposure: a wallet that funded that depositor (Tornado reached at hop 2, 0% direct); hops=1 removes it (configurable);
- self flag: the eXch hot wallet is labelled no-KYC swap; propagation maths on a synthetic graph;
- API + UI (desktop + phone): deep link &exposure=1, hops selector, per-category % direct / indirect, cited sources, lead wording.
Password from env LP (never printed). Usage: LP=... python3 uitest_exposure.py   (CT_URL, SHOT_TAG=_live, ENGINE=0, SHOTS=0)"""
import asyncio, os, sys, gzip, json
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v25_exposure_{n}{TAG}.png")
TC_DEP = "0x838eF3eA11397b2be1892cd6bC2F8234b78f6135"   # sent ETH into the Tornado Cash 0.1 / 1 ETH pools
FUNDER = "0x9811DA25ff085E420428C80CEc1aFA805c9901F8"   # largest funder of TC_DEP (indirect, hop 2)
SINBAD_SENDER = "bc1q5rdwjlyglsvkvhf7frce5mfqwehgc63jxxjuu3"  # paid OFAC-listed Sinbad address 1JHdQHkBZiim1cb4hyUh2PbzEbbg6z2TrF
EXCH = "0xf1da173228fcf015f43f3ea15abbb51f0d8f1123"     # eXch hot wallet
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
cats = lambda o: {k: (v["direct_pct"], v["indirect_pct"]) for k, v in o["categories"].items()}

async def engine():
    import exposure
    d = json.load(gzip.open(os.path.join(H, "data", "exposure_labels.json.gz"), "rt"))
    E = d["entries"]
    check("label file: every entry has a source and an http(s) URL", all(e.get("src") and str(e.get("url", "")).startswith("http") for e in E), len(E))
    check("label file: all four categories present", all(d["counts"].get(c) for c in ("mixer", "privacy", "nokyc_swap", "gambling")), d["counts"])
    cur = json.load(open(os.path.join(H, "data", "exposure_curated.json")))
    ce = cur.get("entries", cur) if isinstance(cur, dict) else cur
    check("curated entries each cite a source URL", all(str(e.get("url", "")).startswith("http") for e in ce), len(ce))
    f = exposure.flag("eth", "0x12D66f87A04A9E220743712cE6d9bB1B5616B8Fc"); check("Tornado 0.1 ETH pool -> mixer", f and f["cat"] == "mixer", f and f["name"])
    f = exposure.flag("btc", "1JHdQHkBZiim1cb4hyUh2PbzEbbg6z2TrF"); check("Sinbad (OFAC) BTC address -> mixer with OFAC source", f and f["cat"] == "mixer" and "ofac" in f["url"].lower(), f)
    f = exposure.flag("eth", EXCH.upper().replace("0X", "0x")); check("eXch hot wallet -> no-KYC swap (case-insensitive)", f and f["cat"] == "nokyc_swap", f and f["name"])
    f = exposure.flag("eth", "0xfa7093cdd9ee6932b4eb2c9e1cde7ce00b1fa4b9"); check("Railgun proxy -> privacy", f and f["cat"] == "privacy")
    E2 = [{"source": "A", "target": "B", "usd": 60}, {"source": "A", "target": "C", "usd": 40}, {"source": "B", "target": "M", "usd": 50}, {"source": "B", "target": "D", "usd": 50}]
    _o = exposure.flag; exposure.flag = lambda c, i: {"cat": "mixer", "name": "M", "src": "t", "url": "http://x"} if i in ("M", "C") else None
    try: hits, tot, basis = exposure.propagate("A", E2, "eth", 2, "out")
    finally: exposure.flag = _o
    check("propagation maths: 40% direct + 60%x50% = 30% at hop 2", abs(hits["C"]["share"] - .4) < 1e-9 and abs(hits["M"]["share"] - .3) < 1e-9 and hits["M"]["hop"] == 2 and tot == 100, {k: (v["share"], v["hop"]) for k, v in hits.items()})
    r = await exposure.compute(TC_DEP, hops=2)
    check("Tornado depositor: direct mixer exposure outgoing, source cited", r["outgoing"]["categories"].get("mixer", {}).get("direct_pct", 0) >= 50 and all(h["url"] for h in r["outgoing"]["hits"]), cats(r["outgoing"]))
    r = await exposure.compute(FUNDER, hops=2)
    m = r["outgoing"]["categories"].get("mixer", {})
    check("funder: indirect mixer exposure at hop 2 (0% direct), path via the depositor", m.get("direct_pct") == 0 and m.get("indirect_pct", 0) >= 10 and any(h["hop"] == 2 and h["path"][1].lower() == TC_DEP.lower() for h in r["outgoing"]["hits"]), m)
    r1 = await exposure.compute(FUNDER, hops=1)
    check("hops is configurable: hops=1 -> no indirect exposure", "mixer" not in r1["outgoing"]["categories"] and r1["hops"] == 1, cats(r1["outgoing"]))
    r = await exposure.compute(SINBAD_SENDER, hops=2)
    check("BTC: direct exposure to Sinbad (OFAC) with % of value", r["outgoing"]["categories"].get("mixer", {}).get("direct_pct", 0) > 0 and "Sinbad" in r["outgoing"]["categories"]["mixer"]["names"], cats(r["outgoing"]))
    check("lead + method wording", "not evidence" in r["lead"] and "lower bounds" in r["method"])

def api():
    cl = httpx.Client(auth=(AUTH["username"], AUTH["password"]), timeout=90)
    j = cl.get(U + "/api/exposure", params={"q": EXCH}).json()
    check("api: eXch hot wallet flagged itself as no-KYC swap", (j.get("self") or {}).get("cat") == "nokyc_swap", (j.get("self") or {}).get("name") or j.get("detail"))
    j = cl.get(U + "/api/exposure", params={"q": "ba352b4b9d283274767c82c438f25d09b40d328e6711a623ef829e26f9f37726"})
    check("api: a transaction hash is rejected (400)", j.status_code == 400)

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w, h, tag in ((1600, 950, "desktop"), (390, 844, "phone")):
            ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials=AUTH)
            pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U + f"/?q={FUNDER}&exposure=1"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000)
            await pg.wait_for_function("window.CT_LAST_EXPOSURE&&document.querySelector('#excard table')", timeout=60000)
            txt = await pg.inner_text("#excard")
            check(f"ui {tag}: deep link &exposure=1 opens the exposure card with an indirect mixer row", "Mixer" in txt and "Indirect" in txt and "hop 2" in txt, txt[:200])
            check(f"ui {tag}: source + lead wording shown", "source:" in txt and "not evidence" in txt)
            check(f"ui {tag}: Exposure button on the address card", await pg.query_selector(".exbtn") is not None)
            if tag == "desktop":
                await pg.select_option("#exhops", "1"); await pg.wait_for_function("window.CT_LAST_EXPOSURE&&CT_LAST_EXPOSURE.hops===1&&document.querySelector('#excard #exhops')", timeout=60000)
                check("ui: hops selector re-runs (hops=1 -> no indirect mixer)", not await pg.evaluate("!!CT_LAST_EXPOSURE.outgoing.categories.mixer"))
                await pg.select_option("#exhops", "2"); await pg.wait_for_function("window.CT_LAST_EXPOSURE&&CT_LAST_EXPOSURE.hops===2&&document.querySelector('#excard table')", timeout=60000)
            await pg.evaluate("document.getElementById('excard').scrollIntoView()")
            if SHOTS: await pg.screenshot(path=SHOT(tag))
            check(f"ui {tag}: no JS errors", not errs, errs[:2]); await ctx.close()
        await b.close()

if __name__ == "__main__":
    os.environ.setdefault("CHAINTRACE_CACHE", "/workspace/scratch/uitest_exposure_cache.sqlite")
    if os.environ.get("ENGINE", "1") != "0": asyncio.run(engine())
    if os.environ.get("API", "1") != "0": api()
    asyncio.run(ui())
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
