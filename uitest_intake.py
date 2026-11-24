"""v30 victim intake form (static/intake.js + static/minipdf.js). Real public chain data for the payment and the suspect address:
- payment: 2 ETH sent on 2018-02-08 to 0x2e3a5deb…94be, an address publicly tagged 'Fake_Phishing400' (Etherscan label cloud via GraphSense TagPacks);
- the victim details typed in the test are obviously fake test values and must never reach the server: every request URL and body is recorded and checked;
- the case is built (tx on the graph, 'victim' / 'suspect' labels, loss calculator prefilled), the summary is plain English, says it is not an official form,
  and the PDF is generated in the browser (downloaded, parsed with pdftotext); the case object and its export hold no victim personal data;
- desktop + phone screenshots.
Password from env LP (never printed). Usage: LP=... python3 uitest_intake.py   (CT_URL, SHOT_TAG=_live, SHOTS=0)"""
import asyncio, os, subprocess, sys, tempfile
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__))
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v30_intake_{n}{TAG}.png")
PAY_TX = "0x07fb2173543345d28a251ecff5a99cc985c5104ec6fcffd64e86bf89d11fd705"   # 2 ETH -> Fake_Phishing400 (2018-02-08)
PAYER = "0x6c5f5438b90199c0af169abd7aac5e0bad657f55"
SUSPECT = "0x2e3a5deb080fcabc9ebefd5c871989ac507c94be"                          # Etherscan 'Fake_Phishing400' (GraphSense TagPack, etherscan.io/labelcloud)
PD = {"name": "Testy McTestface-Intake", "phone": "07700 900983", "email": "intake.uitest@example.invalid", "addr": "ZZ9 9ZZ", "story": "UNIQUE-STORY-MARKER-7731 a person on a dating app showed me a trading site."}
SECRETS = [PD["name"], PD["email"], "07700", "900983", "ZZ9", "UNIQUE-STORY-MARKER-7731", "McTestface"]
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush(); return " ".join(subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout.split())

async def run(b, w, h, tag):
    ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials=AUTH, accept_downloads=True)
    pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    sent = []; pg.on("request", lambda r: sent.append((r.url, r.post_data or "")))
    await pg.goto(U + "/?intake=1"); await pg.wait_for_selector("#inm.on", timeout=30000)
    check(f"{tag}: intake opens from deep link, says it is not the official form", "not the official reporting form" in await pg.inner_text("#inm"))
    for k, v in PD.items(): await pg.fill(f"#in_{k}", v)
    await pg.select_option("#in_type", "romance"); await pg.fill("#in_where", "a dating app"); await pg.fill("#in_first", "2018-01-20"); await pg.fill("#in_found", "2018-02-20")
    await pg.fill("#in_pays .pay .p_tx", PAY_TX); await pg.fill("#in_pays .pay .p_from", PAYER); await pg.fill("#in_pays .pay .p_date", "2018-02-08")
    await pg.click("text=+ Add payment"); p2 = (await pg.query_selector_all("#in_pays .pay"))[1]
    await (await p2.query_selector(".p_from")).fill("my exchange account"); await (await p2.query_selector(".p_amt")).fill("500"); await (await p2.query_selector(".p_asset")).fill("usdt")
    await pg.fill("#in_sus", SUSPECT); await pg.click("text=+ Add contact channel"); await pg.fill("#in_chs .c_val", "https://fake-trading-platform.example.invalid")
    await pg.click("#in_build"); await pg.wait_for_function("window.CT_INTAKE_DONE", timeout=120000)
    done = await pg.evaluate("window.CT_INTAKE_DONE")
    check(f"{tag}: case built: payment confirmed on-chain, suspect labelled", done["verified"] == 1 and done["suspects"] == 1, done)
    st = await pg.evaluate(f"""(()=>({{tx:cy.getElementById('tx:{PAY_TX}').length,sus:cy.nodes().some(n=>n.id().toLowerCase()==='{SUSPECT}'),
        labels:Object.entries(curCase.labels).map(([k,v])=>[k.toLowerCase(),v.name]),loss:window.CT_LOSS,name:curCase.name}}))()""")
    lab = dict(st["labels"])
    check(f"{tag}: graph has the payment tx and the suspect; labels 'victim' + 'suspect'", st["tx"] and st["sus"] and lab.get(SUSPECT) == "suspect" and lab.get(PAYER) == "victim", (st["labels"], st["name"]))
    check(f"{tag}: loss calculator prefilled (victim payment, victim address, suspect)", PAY_TX in st["loss"]["victim_txs"] and any(v.lower() == PAYER for v in st["loss"]["victims"]) and st["loss"]["suspect"].lower() == SUSPECT, st["loss"])
    s = await pg.input_value("#insum")
    check(f"{tag}: summary: required heading + not-official disclaimer + Report Fraud details", s.startswith("SUMMARY IN A FORMAT SUITABLE FOR REPORTING TO ACTION FRAUD / REPORT FRAUD") and "not an official Action Fraud or Report Fraud form" in s and "reportfraud.police.uk" in s and "0300 123 2040" in s)
    check(f"{tag}: summary: plain-English payments (on-chain confirmed with UK + UTC time; manual one marked as entered)", "I sent 2 ETH on Ethereum" in s and PAY_TX in s and "Confirmed on the public blockchain" in s and "UTC" in s and "(UK time)" in s and "500 USDT" in s and "No transaction ID given" in s, s[s.find("3. PAYMENTS"):][:300])
    check(f"{tag}: summary: victim details included (opted in) + suspect + channel", PD["name"] in s and PD["email"] in s and SUSPECT in s and "fake-trading-platform.example.invalid" in s and "romance scam" in s.lower())
    leaks = [u for u, d in sent if any(x.lower() in (u + d).lower() for x in SECRETS)]
    check(f"{tag}: no victim personal data in any request to the server ({len(sent)} requests checked)", not leaks and len(sent) > 5, leaks[:2])
    cj = await pg.evaluate("JSON.stringify(curCase)")
    check(f"{tag}: case object (saved / exported / reported) holds no victim personal data", not any(x.lower() in cj.lower() for x in SECRETS) and "romance" in cj)
    pdl = await pg.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('ct_intake_pd:')).length")
    check(f"{tag}: victim details kept in this browser only (localStorage)", pdl == 1, pdl)
    async with pg.expect_download(timeout=30000) as dl: await pg.click("#in_pdf")
    pdf = open(await (await dl.value).path(), "rb").read(); t = pdftext(pdf)
    check(f"{tag}: PDF made in the browser: valid, heading, disclaimer, payment + victim name", pdf[:5] == b"%PDF-" and "suitable for reporting to action fraud / report fraud" in t.lower() and "not an official" in t and PAY_TX[:20] in t.replace(" ", "") and PD["name"] in t, t[:160])
    leaks = [u for u, d in sent if any(x.lower() in (u + d).lower() for x in SECRETS)]
    check(f"{tag}: still no personal data sent after PDF export", not leaks)
    await pg.evaluate("document.getElementById('in_out').scrollIntoView({block:'center'})")
    if SHOTS: await pg.screenshot(path=SHOT(tag))
    if tag == "phone": check("phone: no horizontal overflow", await pg.evaluate("document.documentElement.scrollWidth") <= 392)
    await pg.uncheck("#in_incl"); await pg.click("#in_sumb"); await pg.wait_for_function("document.getElementById('insum').value.includes('left out')", timeout=60000)
    s2 = await pg.input_value("#insum")
    check(f"{tag}: opting out leaves personal details out of the summary", not any(x.lower() in s2.lower() for x in SECRETS) and "Personal details left out" in s2)
    await pg.click("text=Forget victim details")
    check(f"{tag}: 'Forget victim details' removes them from the browser", await pg.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('ct_intake_pd:')).length") == 0)
    await pg.evaluate("ctIntake(false);ctLossOpen()"); await pg.wait_for_selector("#lossm.on")
    lv = await pg.input_value("#lossv"); lt = await pg.input_value("#losst")
    check(f"{tag}: loss calculator form opens prefilled", PAYER in lv.lower() and PAY_TX in lt, (lv[:50], lt[:50]))
    if tag == "desktop":
        await pg.evaluate("ctLossClose();cy.fit(undefined,50)"); await pg.wait_for_timeout(600)
        if SHOTS: await pg.screenshot(path=SHOT("case_desktop"))
    check(f"{tag}: no JS errors", not errs, errs[:2]); await ctx.close()

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        await run(b, 1500, 950, "desktop"); await run(b, 390, 844, "phone")
        await b.close()
if __name__ == "__main__":
    asyncio.run(main())
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
