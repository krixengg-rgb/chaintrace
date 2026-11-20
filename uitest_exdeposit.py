"""v24 exchange deposit detection + production-order draft list (prodorder.py, static/prodorder.js). Real mainnet graphs only:
- Binance 14 hot wallet (ETH): senders that sweep into it -> 'suspected deposit address (sweep pattern)', Binance's published LE portal attached;
- an ETH address that ChainTrace's deposit model scores as a Gate.io deposit -> inference rows with the incoming transfers;
- Bitfinex BTC hot wallet (GraphSense label) -> labelled exchange wallet rows on a UTXO chain, no contact recorded (left blank);
- CSV columns, wording, GBP on the day, UK + UTC time, dust filter, PDF section, evidence-pack CSV, API, UI desktop + phone.
Password from env LP (never printed). Usage: LP=... python3 uitest_exdeposit.py   (CT_URL, SHOT_TAG=_live, SHOTS=0)"""
import asyncio, os, sys, json, io, zipfile, subprocess, tempfile, csv
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v24_prodorder_{n}{TAG}.png")
BIN14 = "0x28C6c06298d514Db089934071355E5743bf21d60"       # Binance 14 (Etherscan label)
GATE_DEP = "0x0001521497d440595f07232e4a094aaa98146c88"     # scored by ChainTrace's deposit model as a Gate.io deposit (sweeps to Gate.io 0x0D0707…)
BFX = "1Kr6QSydW9bFQG1mXiPNNu6WpJGmUa9i1g"                 # Bitfinex BTC hot wallet (GraphSense TagPack)
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush(); return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout

def api():
    cl = httpx.Client(auth=(AUTH["username"], AUTH["password"]), timeout=150)
    G = {}
    for k, q in (("bin", BIN14), ("gate", GATE_DEP), ("bfx", BFX)):
        G[k] = cl.get(U + "/api/lookup", params={"q": q}).json()
    po = lambda g, **o: cl.post(U + "/api/prodorder", json={"nodes": g["nodes"], "edges": g["edges"], "case": {}, "opts": o})
    r = po(G["bin"]).json(); B = {g["exchange"]: g for g in r["groups"]}
    b = B.get("Binance") or {}
    sw = [x for x in b.get("rows", []) if x["type"].startswith("suspected deposit address (sweep")]
    check("Binance 14 graph: Binance group with sweep-pattern deposit candidates", b and sw, (list(B), len(sw)))
    ids = {e.get("tx") for e in G["bin"]["edges"]}
    check("every txid in the list comes from the graph", all(x["txid"] in ids for x in b.get("rows", []) if x.get("txid")))
    check("Binance: published LE portal from the verified contacts file", (b.get("contact") or {}).get("portal", "").startswith("https://app.kodexglobal.com/binance/") and b["contact"].get("verified"), b.get("contact"))
    check("rows carry UTC + UK time, coin amount, GBP on the day", any(x["time_utc"].endswith("UTC") and ("GMT" in x["time_uk"] or "BST" in x["time_uk"]) and x["amount"] and x.get("gbp_then") is not None for x in b.get("rows", [])))
    check("sub-£1 / spam transfers dropped and counted", r.get("dust_dropped", 0) >= 1 and all((x.get("gbp_then") is None) or x["gbp_then"] >= 1 for x in r["rows"]), r.get("dust_dropped"))
    check("wording: draft lead list, not evidence, not legal advice", "not evidence" in r["wording"] and "Not legal advice" in r["wording"])
    r = po(G["gate"]).json(); g = {x["exchange"]: x for x in r["groups"]}.get("Gate.io") or {}
    inf = [x for x in g.get("rows", []) if "inference" in x["type"] and x["address"].lower() == GATE_DEP]
    check("Gate.io: deposit-model candidate with its incoming transfers", inf and inf[0]["confidence"] >= 0.9 and "sweep" in inf[0]["reason"], len(inf))
    check("Gate.io: no contact recorded -> blank (nothing invented)", g.get("contact") is None)
    r = po(G["bfx"]).json(); g = {x["exchange"]: x for x in r["groups"]}.get("Bitfinex") or {}
    hw = [x for x in g.get("rows", []) if x["address"] == BFX]
    check("BTC: Bitfinex hot wallet (GraphSense) listed as a labelled exchange wallet with BTC transfers", hw and hw[0]["type"] == "exchange wallet (label)" and any(x["asset"] == "BTC" for x in hw), len(hw))
    c = po(G["bin"]).status_code; rc = cl.post(U + "/api/prodorder?format=csv", json={"nodes": G["bin"]["nodes"], "edges": G["bin"]["edges"], "case": {}})
    rows = list(csv.reader(io.StringIO(rc.text)))
    check("CSV export: header + rows + wording line", rc.status_code == 200 and rows[0][:4] == ["exchange", "chain", "deposit_address", "type"] and "le_portal" in rows[0] and any("not evidence" in " ".join(x) for x in rows[-3:]), rows[0][:6])
    r = cl.post(U + "/api/prodorder", json={"nodes": [], "edges": "x"}); check("bad body -> 400", r.status_code == 400)
    # PDF + evidence pack
    pl = {"nodes": G["bin"]["nodes"], "edges": G["bin"]["edges"], "case": {"name": "PO test", "labels": {}}, "meta": {"ref": "PO-TEST", "investigator": "uitest"}}
    rp = cl.post(U + "/api/report", json=pl, timeout=240); txt = pdftext(rp.content) if rp.status_code == 200 else ""
    check("PDF: production order draft section with Binance + portal + lead wording", "Production order draft list" in txt and "Binance" in txt and "kodexglobal" in txt and "NOT EVIDENCE" in txt, rp.status_code)
    ep = cl.post(U + "/api/evidence-pack", json=pl, timeout=240)
    names = zipfile.ZipFile(io.BytesIO(ep.content)).namelist() if ep.status_code == 200 else []
    check("evidence pack contains production_order_draft.csv", any(n.endswith("production_order_draft.csv") for n in names), [n.split("/")[-1] for n in names][:12])
    if os.environ.get("LIVECHECK", "1") != "0":
        r = po(G["bfx"], check=True, max_checks=3).json()
        check("optional live check runs on unlabelled end-points (bounded)", len(r.get("checked") or []) >= 1 and len(r["checked"]) <= 3, r.get("checked"))

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w, h, tag in ((1600, 950, "desktop"), (390, 844, "phone")):
            ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials=AUTH, accept_downloads=True)
            pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U + f"/?q={BIN14}&po=1"); await pg.wait_for_function("cy.nodes().length>=5", timeout=120000)
            await pg.wait_for_function("window.CT_LAST_PO&&document.querySelector('#pom .grp')", timeout=90000)
            t = await pg.inner_text("#pom")
            check(f"ui {tag}: deep link &po=1 opens the production-order list with Binance", "Binance" in t and "suspected deposit address" in t)
            check(f"ui {tag}: lead / legal wording + published portal shown", "Not evidence and not legal advice" in t and "kodexglobal.com/binance" in t)
            if tag == "desktop":
                check("ui: toolbar button", await pg.query_selector("#pobtn") is not None)
                async with pg.expect_download() as dl: await pg.click("#pom button:has-text('CSV')")
                data = open(await (await dl.value).path()).read(); check("ui: CSV download", data.startswith("exchange,chain,deposit_address"))
            if SHOTS: await pg.screenshot(path=SHOT(tag))
            check(f"ui {tag}: no JS errors", not errs, errs[:2]); await ctx.close()
        await b.close()

if __name__ == "__main__":
    if os.environ.get("API", "1") != "0": api()
    asyncio.run(ui())
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
