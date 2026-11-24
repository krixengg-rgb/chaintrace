"""v33 DRAFT investigator witness statement (statement.py, /api/statement, static/statement.js).
Real public data: the case is the Ethereum payment tx 0x07fb2173… (payer 0x6c5f5438… -> 0x2e3a5deb…, Etherscan label 'Fake_Phishing400' via GraphSense)
plus the phishing address' own lookup. Checks:
- UI (desktop + phone): toolbar button + deep link ?statement=1, prominent DRAFT banner, not-MG11 wording; zip download = DOCX + PDF + the evidence pack + SHA256SUMS;
- PDF: DRAFT banner on every page, not the official MG11, declaration placeholder, methodology with ChainTrace version + data sources, tx hash,
  UTC and UK time, coin amount + GBP, opinion/lead section, exhibits whose SHA-256 values equal the real hashes of the pack files, pack SHA-256, audit-log paragraph;
- DOCX: editable, banner in header, same placeholders; single-format downloads (docx, pdf); bad fmt -> 400.
Screenshots screenshot_v33_statement_{desktop,phone,pdf}*.png. Password from env LP (never printed). Usage: LP=... python3 uitest_statement.py (CT_URL, SHOT_TAG=_live, SHOTS=0)"""
import asyncio, hashlib, io, os, re, shutil, subprocess, sys, tempfile, zipfile
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__))
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v33_statement_{n}{TAG}.png")
TX = "0x07fb2173543345d28a251ecff5a99cc985c5104ec6fcffd64e86bf89d11fd705"; FAKE = "0x2e3a5deb080fcabc9ebefd5c871989ac507c94be"
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
def pdftext(b, layout=False):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush(); return subprocess.run(["pdftotext"] + (["-layout"] if layout else []) + [f.name, "-"], capture_output=True, text=True).stdout
def docxtext(b):
    from docx import Document
    d = Document(io.BytesIO(b)); s = d.sections[0]
    body = "\n".join(p.text for p in d.paragraphs) + "\n" + "\n".join(c.text for t in d.tables for r in t.rows for c in r.cells)
    return body, s.header.paragraphs[0].text

async def run(b, w, h, tag):
    ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials=AUTH, accept_downloads=True)
    pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(U + f"/?q={TX}"); await pg.wait_for_function("cy.nodes().length>=3", timeout=120000); await pg.wait_for_timeout(800)
    await pg.evaluate("(async()=>{curCase=blankCase('Statement test · phishing payment');await Store.put(curCase);try{ctAudit('test.note',{why:'uitest'})}catch(e){}})()")
    await pg.goto(U + "/?statement=1"); await pg.wait_for_selector("#stm.on", timeout=30000)
    has_btn = await pg.query_selector("#stmtbtn") is not None
    txt = await pg.inner_text("#stm")
    check(f"{tag}: Statement button + deep link open the draft form with the DRAFT banner and not-MG11 wording", has_btn and "DRAFT – CHECK AND AMEND BEFORE SIGNING" in txt and "not the official MG11" in txt, txt[:90])
    # reopen the saved case so the payload has the graph
    await pg.evaluate("(async()=>{const l=await Store.list();const c=l.find(x=>x.name==='Statement test · phishing payment');await openCase(c.id)})()"); await pg.wait_for_timeout(800)
    for k, v in (("name", "Test Officer"), ("role", "DC 0000"), ("force", "Test Constabulary"), ("prefix", "TO")): await pg.fill(f"#st_{k}", v)
    ov = await pg.evaluate("document.documentElement.scrollWidth>window.innerWidth+2"); check(f"{tag}: no horizontal overflow", not ov)
    if tag == "phone":
        if SHOTS: await pg.screenshot(path=SHOT(tag))
        check(f"{tag}: no JS errors", not errs, errs[:2]); await ctx.close(); return
    async with pg.expect_download(timeout=180000) as dli: await pg.click("#st_zip")
    d = await dli.value; zb = open(await d.path(), "rb").read()
    await pg.wait_for_function("window.CT_LAST_STATEMENT", timeout=10000); meta = await pg.evaluate("window.CT_LAST_STATEMENT")
    z = zipfile.ZipFile(io.BytesIO(zb)); names = [n.split("/", 1)[1] for n in z.namelist()]
    check("zip: DOCX + PDF + evidence pack + SHA256SUMS", any(n.endswith(".docx") for n in names) and any(n.endswith(".pdf") for n in names) and any(n.startswith("ChainTrace-evidence-pack-") for n in names) and "SHA256SUMS.txt" in names, names)
    rd = lambda suf: next(z.read(n) for n in z.namelist() if n.endswith(suf))
    pdf_b, docx_b, pack_b = rd(".pdf"), rd(".docx"), next(z.read(n) for n in z.namelist() if "evidence-pack" in n)
    sums = rd("SHA256SUMS.txt").decode()
    check("zip: SHA256SUMS matches every file", all(f"{hashlib.sha256(z.read(n)).hexdigest()}  {n.split('/', 1)[1]}" in sums for n in z.namelist() if not n.endswith("SHA256SUMS.txt")))
    pack_sha = hashlib.sha256(pack_b).hexdigest()
    check("UI reports the pack SHA-256 cited in the draft", meta["pack"] == pack_sha and meta["exhibits"] >= 3, meta)
    t = pdftext(pdf_b); tl = re.sub(r"\s+", " ", t)
    pages = t.count("\f") or 1
    check("PDF: DRAFT banner on every page", t.count("DRAFT – CHECK AND AMEND BEFORE SIGNING") >= pages, (pages, t.count("DRAFT – CHECK AND AMEND BEFORE SIGNING")))
    check("PDF: generic layout, not the official MG11 + declaration placeholder", "not the official MG11" in tl and "PLACEHOLDER – insert your force-approved statement of truth" in tl)
    check("PDF: officer fields used, unknown ones left as placeholders", "Test Officer" in tl and "Test Constabulary" in tl and "[date of signing]" in tl)
    check("PDF: methodology names ChainTrace version + data sources + sanctions list dates", re.search(r"ChainTrace version \d+\.\d+\.\d+", tl) and "Blockscout" in tl and "as of" in tl)
    hexs = re.sub(r"\s+", "", t)
    check("PDF: finding with the tx hash, UTC and UK time, coin amount and GBP", TX[2:] in hexs and "UTC (" in tl and ("UK G" in tl or "UK B" in tl), None)
    check("PDF: block time of the payment given (08/02/2018 12:41:51 UTC), no 'time unknown'", "08/02/2018 12:41:51 UTC" in tl and "time unknown" not in tl)
    check("PDF: amount in ETH and £ value", re.search(r"\d ETH", tl) and "£" in tl)
    check("PDF: opinion / lead section present", "Opinion and heuristic leads" in tl)
    # exhibits: SHA-256 of each pack file must appear in the PDF
    pz = zipfile.ZipFile(io.BytesIO(pack_b)); hs = [hashlib.sha256(pz.read(n)).hexdigest() for n in pz.namelist()]
    found = sum(1 for x in hs if x in hexs)
    check("PDF: exhibits list = pack files with their real SHA-256 (TO/1…)", found == len(hs) and "TO/1" in tl, (found, len(hs)))
    check("PDF: the pack's own SHA-256 is cited", pack_sha in hexs)
    check("PDF: audit-log paragraph (hash-chained entries, verification)", "hash-chained entries" in tl and "intact" in tl, tl[tl.find("Case audit log"):][:200])
    body, hdr = docxtext(docx_b)
    check("DOCX: editable Word file with banner in header + placeholders", hdr == "DRAFT – CHECK AND AMEND BEFORE SIGNING" and "PLACEHOLDER" in body and TX in body and "TO/1" in body, hdr)
    if SHOTS:
        await pg.evaluate("document.getElementById('st_res').scrollIntoView()"); await pg.screenshot(path=SHOT(tag))
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "s.pdf"); open(f, "wb").write(pdf_b)
            subprocess.run(["pdftoppm", "-png", "-r", "70", "-f", "1", "-l", "1", f, os.path.join(td, "p")], check=True)
            pp = [x for x in os.listdir(td) if x.endswith(".png")][0]; shutil.move(os.path.join(td, pp), SHOT("pdf"))
    # single-format downloads via the API with the same payload
    pl = await pg.evaluate("(()=>{const p=ctReportPayload({ref:'',investigator:'',marking:'',notes:'',img:false,noise:false});p.meta.evidence_pack=true;p.meta.statement={name:'Test Officer'};return p})()")
    a = (AUTH["username"], AUTH["password"])
    r1 = httpx.post(U + "/api/statement", params={"fmt": "docx"}, json=pl, auth=a, timeout=180)
    check("api: fmt=docx returns a Word file", r1.status_code == 200 and r1.content[:2] == b"PK" and "wordprocessingml" in r1.headers.get("content-type", ""), r1.status_code)
    r2 = httpx.post(U + "/api/statement", params={"fmt": "pdf"}, json=pl, auth=a, timeout=180)
    check("api: fmt=pdf returns a PDF", r2.status_code == 200 and r2.content[:4] == b"%PDF" and len(r2.headers.get("X-Pack-SHA256", "")) == 64, r2.status_code)
    r3 = httpx.post(U + "/api/statement", params={"fmt": "rtf"}, json=pl, auth=a, timeout=60)
    check("api: bad fmt -> 400", r3.status_code == 400, r3.status_code)
    check(f"{tag}: no JS errors", not errs, errs[:2]); await ctx.close()

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        await run(b, 1600, 950, "desktop"); await run(b, 390, 844, "phone")
        await b.close()
if __name__ == "__main__":
    asyncio.run(main())
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
