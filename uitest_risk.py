"""v26 per-address risk score 0-100 (risk.py, static/risk.js, PDF section). Real mainnet data + synthetic factor checks:
- weights sum to 100; each factor's points <= weight; sanctions-list match pins 100; pattern / velocity / age factors on synthetic histories;
- Hydra Market (OFAC SDN) -> 100 severe, pinned; Tornado Cash depositor -> full mixer factor; Binance 14 hot wallet -> low (age not scored: partial history);
- API errors; UI (desktop + phone): deep link &risk=1, banner, factor table with weights; PDF includes the risk section with the banner.
Password from env LP (never printed). Usage: LP=... python3 uitest_risk.py   (CT_URL, SHOT_TAG=_live, ENGINE=0, SHOTS=0)"""
import asyncio, os, sys, subprocess, tempfile, time
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v26_risk_{n}{TAG}.png")
HYDRA = "123WBUDmSJv4GctdVEz6Qq6z8nXSKrJ4KX"; TC_DEP = "0x838eF3eA11397b2be1892cd6bC2F8234b78f6135"; BIN14 = "0x28C6c06298d514Db089934071355E5743bf21d60"
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush(); return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
F = lambda j, k: next(f for f in j["factors"] if f["key"] == k)

def engine():
    import risk
    check("weights sum to 100 across 8 factors (v31 adds scam-pattern flags)", sum(w for _, _, w, _ in risk.FACTORS) == 100 and len(risk.FACTORS) == 8)
    now = time.time(); A = "A"
    pas = [{"source": "S%d" % i, "target": A, "usd": 1000, "amount": 1, "unit": "ETH", "time": now - 86400 * 5 + i * 3600} for i in range(6)] + \
          [{"source": A, "target": "R%d" % i, "usd": 990, "amount": 0.99, "unit": "ETH", "time": now - 86400 * 5 + i * 3600 + 600} for i in range(6)]
    j = risk.score({"address": A, "chain": "eth", "edges": pas, "nodes": [], "label": {}}, None)
    check("synthetic pass-through: velocity + pattern + age factors fire", F(j, "velocity")["points"] > 0 and F(j, "patterns")["points"] > 0 and F(j, "age")["points"] == 5, [(f["key"], f["points"]) for f in j["factors"]])
    check("every factor's points <= its weight, score = sum", all(0 <= f["points"] <= f["weight"] for f in j["factors"]) and j["score"] == round(sum(f["points"] for f in j["factors"])))
    j2 = risk.score({"address": A, "chain": "eth", "edges": pas, "nodes": [], "label": {}, "next": "cursor"}, None)
    check("partial history -> age not scored", F(j2, "age")["points"] == 0 and "not scored" in F(j2, "age")["evidence"][0])
    th = [{"source": A, "target": "T%d" % i, "usd": 9500 + i, "amount": 9.5 + i, "unit": "X", "time": now - 86400 * 400 + i * 86400 * 9} for i in range(3)]
    j3 = risk.score({"address": A, "chain": "eth", "edges": th, "nodes": [], "label": {}}, None)
    check("amounts just under a threshold -> structuring evidence", F(j3, "patterns")["points"] > 0 and any("threshold" in e for e in F(j3, "patterns")["evidence"]), F(j3, "patterns"))
    j4 = risk.score({"address": A, "chain": "eth", "edges": [], "nodes": [], "label": {"sanctions": [{"wording": "matches OFAC SDN list entry X"}]}}, None)
    check("sanctions-list match pins the score to 100", j4["score"] == 100 and j4["pinned"] and j4["raw_score"] == 30)
    X = {"hops": 2, "self": None, "outgoing": {"categories": {"mixer": {"direct_pct": 10.0, "indirect_pct": 20.0, "names": ["T"]}}}, "incoming": {"categories": {"nokyc_swap": {"direct_pct": 0, "indirect_pct": 40.0, "names": ["eXch"]}}}}
    j5 = risk.score({"address": A, "chain": "eth", "edges": [], "nodes": [], "label": {}}, X)
    check("exposure factors: (10% + 20%/2) x2 of 20 = 8; no-KYC (40%/2) x2 of 10 = 4", F(j5, "mixer_gambling")["points"] == 8 and F(j5, "nokyc")["points"] == 4, (F(j5, "mixer_gambling")["points"], F(j5, "nokyc")["points"]))

def api():
    cl = httpx.Client(auth=(AUTH["username"], AUTH["password"]), timeout=90)
    j = cl.get(U + "/api/risk", params={"q": HYDRA}).json()
    check("api: Hydra (OFAC SDN) -> 100 severe, pinned, sanctions factor full", j.get("score") == 100 and j.get("level") == "severe" and j.get("pinned") and F(j, "sanctions")["points"] == 30, j.get("score") or j.get("detail"))
    time.sleep(5)
    j = cl.get(U + "/api/risk", params={"q": TC_DEP}).json()
    check("api: Tornado depositor -> full mixer factor (20/20), medium or above", F(j, "mixer_gambling")["points"] == 20 and j["score"] >= 25, (j.get("score"), j.get("level")))
    check("api: banner wording + method", "not evidence" in j["lead"] and "weight" in j["method"])
    time.sleep(5)
    j = cl.get(U + "/api/risk", params={"q": BIN14}).json()
    check("api: Binance 14 hot wallet -> low score, age not scored on partial history", j.get("score", 99) < 25 and F(j, "age")["points"] == 0 and F(j, "sanctions")["points"] == 0, (j.get("score"), F(j, "age")["evidence"]))
    r = cl.get(U + "/api/risk", params={"q": "ba352b4b9d283274767c82c438f25d09b40d328e6711a623ef829e26f9f37726"}); check("api: tx hash rejected (400)", r.status_code == 400, r.status_code)
    pl = {"nodes": [{"id": TC_DEP, "chain": "eth"}], "edges": [], "case": {"name": "Risk test", "query": TC_DEP, "labels": {}}, "trace": {"root": TC_DEP}, "meta": {"ref": "RISK-TEST", "investigator": "uitest"}}
    rp = cl.post(U + "/api/report", json=pl, timeout=240); txt = pdftext(rp.content) if rp.status_code == 200 else ""
    check("PDF: risk score section with banner and factor weights", "Address risk score" in txt and "INDICATIVE LEAD" in txt and "Mixer / privacy / gambling exposure" in txt and "Weight" in txt, rp.status_code)

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w, h, tag in ((1600, 950, "desktop"), (390, 844, "phone")):
            ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials=AUTH)
            pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U + f"/?q={TC_DEP}&risk=1"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000)
            await pg.wait_for_function("window.CT_LAST_RISK&&document.querySelector('#rkcard table')", timeout=60000)
            txt = await pg.inner_text("#rkcard"); rows = await pg.evaluate("document.querySelectorAll('#rkcard tr[data-k]').length")
            check(f"ui {tag}: deep link &risk=1 shows score + banner", "Indicative lead, not evidence" in txt and (await pg.inner_text("#rknum")).strip().isdigit(), txt[:80])
            check(f"ui {tag}: 8 factors with weights shown", rows == 8 and "Sanctions" in txt and "Address age" in txt and "Volume velocity" in txt, rows)
            check(f"ui {tag}: Risk score button on the address card", await pg.query_selector(".rkbtn") is not None)
            await pg.evaluate("document.getElementById('rkcard').scrollIntoView()")
            if SHOTS: await pg.screenshot(path=SHOT(tag))
            check(f"ui {tag}: no JS errors", not errs, errs[:2]); await ctx.close()
        await b.close()

if __name__ == "__main__":
    os.environ.setdefault("CHAINTRACE_CACHE", "/workspace/scratch/uitest_risk_cache.sqlite")
    if os.environ.get("ENGINE", "1") != "0": engine()
    if os.environ.get("API", "1") != "0": api()
    asyncio.run(ui())
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
