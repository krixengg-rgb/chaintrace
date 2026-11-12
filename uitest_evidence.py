"""Test for v12 UK police evidence pack: direct evidence.build_pack() checks + Playwright UI flow (desktop + phone).
Password comes from env LP (never printed). Usage: LP=... python3 uitest_evidence.py   (CT_URL to target another server; SHOT=prefix for screenshots)"""
import asyncio, io, os, re, sys, subprocess, tempfile, hashlib, zipfile
from playwright.async_api import async_playwright
U = os.environ.get("CT_URL", "http://localhost:8090"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOT = os.environ.get("SHOT", "screenshot_v12_evidence")
CASE = "binance-2026-10-29"
BANNER = "DRAFT – NOT A COURT ORDER"
LEAD = "Intelligence lead – not evidence; corroborate (e.g. production order to the VASP)"
FORBIDDEN = [r"\bthis is an order of the court\b", r"\bby order of the court\b", r"\bit is hereby ordered\b", r"\bcourt crest\b", r"\bseal of the court\b"]
ok = []; bad = []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:220], flush=True)
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush(); return " ".join(subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout.split())
def docx_text(b):
    import docx
    d = docx.Document(io.BytesIO(b)); t = [p.text for p in d.paragraphs] + [c.text for tb in d.tables for r in tb.rows for c in r.cells]
    return d.sections[0].header.paragraphs[0].text, "\n".join(t)
def check_zip(z, tag, expect_vasps=1, le=None):
    zf = zipfile.ZipFile(io.BytesIO(z)); names = zf.namelist(); root = names[0].split("/")[0]
    rd = lambda n: zf.read(f"{root}/{n}")
    rel = [n.split("/", 1)[1] for n in names]
    check(f"{tag}: zip has report, drafts, csv, how-to, sums", any(n.endswith(".pdf") for n in rel) and "vasp_schedule.csv" in rel and "HOW_TO_USE.txt" in rel and "SHA256SUMS.txt" in rel, rel)
    sums = dict(l.split("  ", 1)[::-1] for l in rd("SHA256SUMS.txt").decode().splitlines())
    check(f"{tag}: SHA256SUMS match every file", all(hashlib.sha256(rd(n)).hexdigest() == h for n, h in sums.items()) and len(sums) == len(rel) - 1, len(sums))
    drafts = [n for n in rel if n.startswith("vasp_drafts/")]
    check(f"{tag}: >= {expect_vasps} VASP draft(s) as DOCX + TXT", len([n for n in drafts if n.endswith(".docx")]) >= expect_vasps and len([n for n in drafts if n.endswith(".txt")]) >= expect_vasps, drafts)
    alltxt = ""
    for n in drafts:
        if n.endswith(".txt"):
            t = rd(n).decode(); alltxt += t
            check(f"{tag}: {n} DRAFT banner top+bottom", t.lstrip("*\n ").startswith(BANNER) and t.rstrip().endswith("FOR OFFICER REVIEW AND COMPLETION"))
        else:
            h, t = docx_text(rd(n)); alltxt += t
            check(f"{tag}: {n} DRAFT banner in page header", h.startswith(BANNER), h)
    low = alltxt.lower()
    check(f"{tag}: drafts never claim to be a court order", not any(re.search(p, low) for p in FORBIDDEN))
    check(f"{tag}: drafts cite statutory routes + legal-advice + MLA notes", all(x in alltxt for x in ("s.345", "Schedule 1", "s.363", "Sch 2 Pt 1 para 2", "Crime (International Co-operation) Act 2003 s.7", "legal advice", "UK Central Authority")))
    check(f"{tag}: drafts say on-chain data is a lead to corroborate with VASP records", "must be corroborated by the firm's own records" in alltxt)
    check(f"{tag}: drafts disclaim official status", "not an official form or template of the Home Office, NCA" in alltxt)
    if le:
        check(f"{tag}: investigator fields carried into drafts", all(v in alltxt for v in le.values() if len(v) < 60))
    pdf = rd([n for n in rel if n.endswith(".pdf")][0]); pt = pdftext(pdf)
    check(f"{tag}: report PDF keeps lead caveat + UK case details + VASP appendix", LEAD in pt and "UK case details (investigator-entered)" in pt and "Appendix C. Exchange / VASP schedule" in pt and "Europe/London" in pt)
    csvt = rd("vasp_schedule.csv").decode("utf-8-sig")
    return zf, rel, alltxt, pt, csvt
async def direct():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import evidence
    le = {"rf_ref": "NFRC-UNIT-1", "offence": "Fraud by false representation (Fraud Act 2006 s.2)", "officer_name": "DC Unit Test", "force": "Test Constabulary"}
    p = {"meta": {"ref": "UNIT/EV/1", "le": dict(le, junk="x" * 5)}, "case": {"name": "unit", "query": "rSubj"},
         "nodes": [{"id": "rSubj", "chain": "xrp"}, {"id": "rEb8TK3gBgk5auZkwc6sHnwrGVJH8DuaLh", "chain": "xrp", "kind": "exchange", "name": "Binance 1"},
                   {"id": "0xdd", "chain": "eth", "suggested": {"entity": "OKX", "category": "exchange-deposit", "confidence": 0.7, "method": "unit"}}, {"id": "0xaa", "chain": "eth"}],
         "edges": [{"source": "rSubj", "target": "rEb8TK3gBgk5auZkwc6sHnwrGVJH8DuaLh", "amount": 10, "unit": "XRP", "tx": "A" * 64, "time": 1760003000, "destination_tag": 123456, "destination_tags": [123456, 777], "count": 2, "first": 1759990000, "last": 1760003000},
                   {"source": "0xaa", "target": "0xdd", "amount": 1, "unit": "ETH", "tx": "0x" + "4" * 64, "time": 1760002000, "usd": 3000}]}
    z, info = await evidence.build_pack(p)
    zf, rel, alltxt, pt, csvt = check_zip(z, "direct", 2, le)
    check("direct: unknown LE keys dropped", "junk" not in str(info) and "xxxxx" not in pt)
    check("direct: XRP destination tags listed (draft + csv)", "123456, 777" in alltxt and "123456;777" in csvt)
    check("direct: UK + UTC times in schedule", "BST" in alltxt and "UTC" in alltxt)
    check("direct: inferred VASP marked as lead", any(v["entity"] == "OKX" and v["lead_only"] for v in info["vasps"]) and LEAD in alltxt)
    # report with no LE fields still works (fields optional)
    import report
    pdf, inf2 = await report.build({"meta": {}, "case": {"name": "plain"}, "nodes": [{"id": "0xaa", "chain": "eth"}], "edges": []})
    check("direct: plain report unaffected (no UK section when no fields)", pdf[:5] == b"%PDF-" and "UK case details" not in pdftext(pdf))
async def main():
    await direct()
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
        errs = []
        ctx = await b.new_context(viewport={"width": 1500, "height": 950}, http_credentials=AUTH, accept_downloads=True)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + f"/?case={CASE}&pack=1")
        await pg.wait_for_selector("#rptm.on", timeout=120000); await pg.wait_for_timeout(600)
        check("deep link ?pack=1 opens the evidence-pack form", await pg.evaluate("document.getElementById('lepack').open"))
        lev = await pg.inner_text("#lev"); check("VASP preview lists exchanges", "Binance" in lev, lev)
        le = {"le_crime_ref": "UITEST/CR/42", "le_rf_ref": "NFRC-UITEST-0001", "le_offence": "Money laundering (POCA 2002 s.327) – UI test", "le_officer_name": "DC Ui Test",
              "le_officer_rank": "DC", "le_officer_number": "1234", "le_force": "Test Constabulary ECU", "le_officer_email": "dc.test@example.invalid"}
        await pg.fill("#rptref", "OP-EVIDENCE-UITEST")
        for k, v in le.items(): await pg.fill("#" + k, v)
        await pg.fill("#le_period_from", "2026-10-29"); await pg.fill("#le_period_to", "2026-10-31"); await pg.fill("#le_facts", "UI test: exchange hot-wallet compromise; tracing to VASPs.")
        async with pg.expect_download(timeout=150000) as dl: await pg.click("#packgo")
        d = await dl.value; z = open(await d.path(), "rb").read()
        check("download is a zip", z[:2] == b"PK", d.suggested_filename)
        zf, rel, alltxt, pt, csvt = check_zip(z, "ui", 1, {k: v for k, v in le.items() if k != "le_offence"})
        check("ui: period converted to UK dates", "29/10/2026 to 31/10/2026" in alltxt)
        res = await pg.evaluate("window.CT_LAST_PACK||{}")
        check("ui: pack SHA-256 shown + matches file", res.get("sha") == hashlib.sha256(z).hexdigest() and res.get("sha") in await pg.inner_text("#rptres"))
        check("ui: officer details remembered on device", "DC Ui Test" in (await pg.evaluate("localStorage.ct_officer||''")))
        await pg.evaluate("document.querySelector('#rptm .card').scrollTop=0"); await pg.screenshot(path=f"{SHOT}_desktop.png")
        await pg.evaluate("const c=document.querySelector('#rptm .card');c.scrollTop=c.scrollHeight"); await pg.screenshot(path=f"{SHOT}_desktop_result.png")
        await ctx.close()
        # phone
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2, http_credentials=AUTH, accept_downloads=True)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + f"/?case={CASE}&pack=1"); await pg.wait_for_selector("#rptm.on", timeout=120000); await pg.wait_for_timeout(800)
        r = await pg.evaluate("(()=>{const c=document.querySelector('#rptm .card').getBoundingClientRect();const ins=[...document.querySelectorAll('#lepack input,#lepack textarea')].map(e=>e.getBoundingClientRect());return{l:c.left,r:c.right,sw:document.documentElement.scrollWidth,maxr:Math.max(...ins.map(x=>x.right)),minl:Math.min(...ins.map(x=>x.left)),fs:getComputedStyle(document.getElementById('le_offence')).fontSize}})()")
        check("phone: form within viewport, inputs 16px (no iOS zoom)", r["l"] >= 0 and r["r"] <= 391 and r["sw"] <= 392 and r["maxr"] <= 391 and r["minl"] >= 0 and r["fs"] == "16px", r)
        await pg.screenshot(path=f"{SHOT}_phone.png")
        await pg.fill("#le_crime_ref", "PHONE/1")
        await pg.evaluate("document.getElementById('packgo').scrollIntoView()")
        async with pg.expect_download(timeout=150000) as dl: await pg.tap("#packgo")
        d = await dl.value; z = open(await d.path(), "rb").read(); check("phone: pack downloads", z[:2] == b"PK", d.suggested_filename)
        await pg.wait_for_timeout(400); await pg.screenshot(path=f"{SHOT}_phone_result.png")
        await ctx.close()
        check("no page errors", not errs, errs[:3])
        await b.close()
    print(f"\n{len(ok)} passed, {len(bad)} failed", bad)
    sys.exit(1 if bad else 0)
asyncio.run(main())
