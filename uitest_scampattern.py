"""v31 fake-recovery / pig-butchering scam-pattern flags (scampattern.py, /api/scampattern, static/scampattern.js, risk factor).
- engine (synthetic histories): fee-like repeat deposits, fan-in -> exchange consolidation (strong) vs -> unlabelled (weaker), smaller repeat payments
  after a large first payment, recovery-fee pattern after a prior loss (not beyond 365 days, not for an address itself labelled scam),
  labelled services damped, clean history -> no flags; aggregated edges expanded; risk score gains a 10-point 'scam_pattern' factor (weights still 100).
- api (real mainnet): 0x2e3a5deb… labelled 'Fake_Phishing400' (Etherscan label cloud via GraphSense, Forta labelled-datasets):
  fan-in flag, reports cite source URLs, lead wording, Chainabuse status; risk factor > 0.
- ui desktop + phone: deep link &scam=1, banner, flags, cited sources, button; screenshots screenshot_v31_scampattern_*.png
Password from env LP (never printed). Usage: LP=... python3 uitest_scampattern.py   (CT_URL, SHOT_TAG=_live, ENGINE=0, API=0, SHOTS=0)"""
import asyncio, os, sys, time
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v31_scampattern_{n}{TAG}.png")
FAKE = "0x2e3a5deb080fcabc9ebefd5c871989ac507c94be"   # Etherscan label 'Fake_Phishing400' (https://etherscan.io/labelcloud via GraphSense; Forta labelled-datasets)
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)

def engine():
    import scampattern as S, risk
    now = time.time(); D = 86400; C = "0xC0LLECTOR"
    def E(s, t, usd, dt, tx, unit="USDT"): return {"source": s, "target": t, "usd": usd, "amount": usd, "unit": unit, "time": int(now - dt), "tx": tx}
    fee = [E(f"0xV{i % 4}", C, [100, 250, 500][i % 3], 25 * D - i * 3600, f"f{i}") for i in range(12)]
    r = S.analyse({"address": C, "chain": "eth", "nodes": [], "edges": fee})
    f = {x["key"]: x for x in r["flags"]}
    check("fee-like repeat deposits from several payers flagged", "fee_deposits" in f and f["fee_deposits"]["strength"] > 0.5 and f["fee_deposits"]["txs"], f.get("fee_deposits"))
    fan = [E(f"0xS{i}", C, 2000, 5 * D - i * 600, f"s{i}") for i in range(6)] + [E(C, "0xEXDEP", 11500, 4 * D, "o1")]
    r1 = S.analyse({"address": C, "chain": "eth", "nodes": [{"id": "0xEXDEP", "suggested": {"category": "exchange-deposit", "entity": "Binance"}, "name": "Binance deposit? (90%)"}], "edges": fan})
    r2 = S.analyse({"address": C, "chain": "eth", "nodes": [], "edges": fan})
    g1 = {x["key"]: x for x in r1["flags"]}.get("fan_in"); g2 = {x["key"]: x for x in r2["flags"]}.get("fan_in")
    check("fan-in then consolidation to a (suggested) exchange deposit = strong", g1 and g1["strength"] == 1.0 and any("exchange" in e for e in g1["evidence"]), g1)
    check("fan-in then consolidation to an unlabelled address = weaker", g2 and g2["strength"] == 0.5, g2)
    fal = [E("0xVIC", C, 20000, 60 * D, "big"), E("0xVIC", C, 1500, 40 * D, "fee1"), E("0xVIC", C, 2500, 30 * D, "fee2")]
    g = {x["key"]: x for x in S.analyse({"address": C, "chain": "eth", "nodes": [], "edges": fal})["flags"]}.get("fee_after_loss")
    check("smaller repeat payments after a large first payment (same payer) flagged", g and "0xVIC" in g["evidence"][0] and "big" in g["txs"], g)
    V = "0xVICTIM"; nodes = [{"id": "0xSCAM", "kind": "scam", "name": "Fake_Phishing (test)", "sources": [{"source": "forta", "category": "scam", "source_url": "https://github.com/forta-network/labelled-datasets"}]}]
    rec = [E(V, "0xSCAM", 30000, 90 * D, "loss")] + [E(V, "0xRECOVERY", 800 + 100 * i, (40 - 5 * i) * D, f"r{i}") for i in range(3)]
    rr = S.analyse({"address": V, "chain": "eth", "nodes": nodes, "edges": rec}); g = {x["key"]: x for x in rr["flags"]}.get("recovery_fee")
    check("recovery-fee pattern after a prior loss to a labelled scam flagged (victim view)", g and g["fee_recipient"] == "0xRECOVERY" and g["strength"] >= 0.75 and "loss" in g["txs"], g)
    check("counterparty scam label reported with its source URL", any(x["who"] == "counterparty" and x["url"].startswith("https://") for x in rr["reports"]), rr["reports"])
    old = [E(V, "0xSCAM", 30000, 900 * D, "loss")] + [E(V, "0xRECOVERY", 800, (40 - 5 * i) * D, f"r{i}") for i in range(3)]
    check("no recovery-fee flag when the 'fees' come more than a year after the loss", not any(x["key"] == "recovery_fee" for x in S.analyse({"address": V, "chain": "eth", "nodes": nodes, "edges": old})["flags"]))
    rs = S.analyse({"address": V, "chain": "eth", "label": {"kind": "scam"}, "nodes": nodes, "edges": rec})
    check("victim-view rule not applied to an address itself labelled scam", not any(x["key"] == "recovery_fee" for x in rs["flags"]))
    rx = S.analyse({"address": C, "chain": "eth", "label": {"kind": "exchange"}, "nodes": [], "edges": fee})
    check("labelled exchange: same shape damped (normal for a service)", rx["flags"] and all(x["strength"] <= 0.3 for x in rx["flags"]) and "normal for a service" in rx["flags"][0]["evidence"][-1], [x["strength"] for x in rx["flags"]])
    clean = [E("0xA", C, 5000, 100 * D, "c1"), E(C, "0xB", 4900, 99 * D, "c2")]
    rc = S.analyse({"address": C, "chain": "eth", "nodes": [], "edges": clean})
    check("ordinary history: no flags, fraction 0", not rc["flags"] and rc["frac"] == 0, rc["flags"])
    agg = [{"source": "0xV1", "target": C, "usd": 600, "amount": 600, "unit": "USDT", "count": 3, "first": int(now - 20 * D), "last": int(now - 10 * D), "time": int(now - 10 * D), "tx": "a1"},
           {"source": "0xV2", "target": C, "usd": 400, "amount": 400, "unit": "USDT", "count": 2, "first": int(now - 20 * D), "last": int(now - 15 * D), "time": int(now - 15 * D), "tx": "a2"}]
    ga = {x["key"]: x for x in S.analyse({"address": C, "chain": "eth", "nodes": [], "edges": agg})["flags"]}.get("fee_deposits")
    check("aggregated edges (count > 1) expanded so repeat payers are seen", ga and "2 sender(s) paid 2+ times" in ga["evidence"][1], ga)
    check("every result carries the 'heuristic lead, not evidence' wording + method", "not evidence" in r["lead"] and "fee_deposits" in r["method"])
    check("risk weights still sum to 100 with the scam-pattern factor (10 points)", sum(w for _, _, w, _ in risk.FACTORS) == 100 and risk.W["scam_pattern"] == 10)
    sc = risk.score({"address": C, "chain": "eth", "nodes": [], "edges": fee + fan})
    fs = next(x for x in sc["factors"] if x["key"] == "scam_pattern")
    check("risk score: scam-pattern factor awarded from the detectors, within its weight", 0 < fs["points"] <= 10 and fs["evidence"], (fs["points"], fs["evidence"][:1]))

def api():
    a = (AUTH["username"], AUTH["password"])
    j = httpx.get(U + "/api/scampattern", params={"q": FAKE}, auth=a, timeout=150).json()
    f = {x["key"]: x for x in j.get("flags") or []}
    check("api: real phishing-labelled address: fan-in then consolidation flagged", "fan_in" in f and "distinct senders" in f["fan_in"]["evidence"][0], list(f))
    check("api: recovery-fee (victim view) not applied to the scam-labelled address itself", "recovery_fee" not in f)
    reps = j.get("reports") or []
    check("api: public scam reports cite a source URL (Etherscan label cloud via GraphSense / Forta)", reps and all(r["url"].startswith("https://") for r in reps) and any("etherscan.io/labelcloud" in r["url"] or "forta" in r["url"] for r in reps), reps[:2])
    check("api: lead wording + Chainabuse status/search link", "not evidence" in j.get("lead", "") and (j.get("chainabuse") or {}).get("search_url", "").startswith("https://chainabuse.com/"), j.get("chainabuse"))
    time.sleep(2)
    rk = httpx.get(U + "/api/risk", params={"q": FAKE}, auth=a, timeout=150).json()
    fs = next((x for x in rk.get("factors") or [] if x["key"] == "scam_pattern"), None)
    check("api: risk score includes the weighted scam-pattern factor", fs and fs["weight"] == 10 and fs["points"] > 0, fs and (fs["points"], fs["evidence"][:1]))
    r = httpx.get(U + "/api/scampattern", params={"q": "not-an-address"}, auth=a, timeout=60)
    check("api: bad input -> 4xx", 400 <= r.status_code < 500, r.status_code)

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w, h, tag in ((1600, 950, "desktop"), (390, 844, "phone")):
            ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials=AUTH)
            pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U + f"/?q={FAKE}&scam=1"); await pg.wait_for_function("cy.nodes().length>=2", timeout=120000)
            await pg.wait_for_function("window.CT_LAST_SCAMPATTERN&&document.querySelector('#spcard .ban')", timeout=120000)
            txt = await pg.inner_text("#spcard")
            check(f"ui {tag}: deep link &scam=1 shows banner + flags", "HEURISTIC LEAD, NOT EVIDENCE" in txt and "Fan-in then consolidation" in txt, txt[:120].replace("\n", " | "))
            links = await pg.evaluate("[...document.querySelectorAll('#spcard .rp a')].map(a=>a.href)")
            check(f"ui {tag}: reports listed with source links", links and all(l.startswith("https://") for l in links), links[:2])
            check(f"ui {tag}: Scam patterns button on the address card + risk link text", await pg.query_selector(".spbtn") is not None and "risk score" in txt.lower())
            ov = await pg.evaluate("document.documentElement.scrollWidth>window.innerWidth+2")
            check(f"ui {tag}: no horizontal overflow", not ov)
            await pg.evaluate("document.getElementById('spcard').scrollIntoView()"); await pg.wait_for_timeout(400)
            if SHOTS: await pg.screenshot(path=SHOT(tag))
            check(f"ui {tag}: no JS errors", not errs, errs[:2]); await ctx.close()
        await b.close()

if __name__ == "__main__":
    os.environ.setdefault("CHAINTRACE_CACHE", "/workspace/scratch/uitest_scampattern_cache.sqlite")
    if os.environ.get("ENGINE", "1") != "0": engine()
    if os.environ.get("API", "1") != "0": api()
    asyncio.run(ui())
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
