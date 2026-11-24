"""v32 multi-case link finder (static/crosscase.js), browser-only.
- engine (in the page, placeholder ids): shared exchange deposit = strong, shared exchange hot wallet = weak, shared suspect = strong,
  shared tx, BTC co-spend cluster root seen in another case, pairs table counts, merged graph marks shared nodes (xc > 1);
- real public data: case A = 0x2e3a5deb… (Etherscan 'Fake_Phishing400' via GraphSense) lookup, case B = the payment tx 0x07fb2173… (payer 0x6c5f5438… -> phishing address),
  case C = an exported case file read from disk (never stored, never uploaded): links found = the phishing address + tx 0x07fb2173…;
- nothing is sent to the server while finding links or merging (every request recorded); CSV download; merged graph opens as a new local case;
- desktop + phone screenshots screenshot_v32_crosscase_*.png
Password from env LP (never printed). Usage: LP=... python3 uitest_crosscase.py   (CT_URL, SHOT_TAG=_live, SHOTS=0)"""
import asyncio, json, os, sys, tempfile
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__))
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v32_crosscase_{n}{TAG}.png")
FAKE = "0x2e3a5deb080fcabc9ebefd5c871989ac507c94be"; PAYER = "0x6c5f5438b90199c0af169abd7aac5e0bad657f55"
TX = "0x07fb2173543345d28a251ecff5a99cc985c5104ec6fcffd64e86bf89d11fd705"
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)

ENGINE_JS = """(()=>{const N=(id,extra={})=>({data:{id,lbl:id.slice(0,8),info:{id,chain:'eth',...(extra.info||{})},...extra.d},position:{x:0,y:0}});
 const D='0x'+'d'.repeat(40),HOT='0x'+'b'.repeat(40),S='0x'+'5'.repeat(40),Q='0x'+'1'.repeat(40);
 const c1={name:'E1',labels:{[S]:{name:'suspect'}},graph:{nodes:[N(D,{info:{suggested:{category:'exchange-deposit',entity:'X'}},d:{sugg:1}}),N(HOT,{d:{kind:'exchange'}}),N(S),N('bc1qroot',{info:{chain:'btc',cluster:{root:'bc1qroot',size:4}}})],edges:[{id:'e1',source:S,target:D,info:{tx:'0xabc'}}]}};
 const c2={name:'E2',labels:{},graph:{nodes:[N(D.toUpperCase().replace('0X','0x')),N(HOT,{d:{kind:'exchange'}}),N(S),N('bc1qmember',{info:{chain:'btc',cluster:{root:'bc1qroot',size:4}}})],edges:[{id:'e2',source:Q,target:S,info:{tx:'0xabc'}}]}};
 const c3={name:'E3',labels:{},graph:{nodes:[N(Q)],edges:[]}};
 const R=ctCrossCaseAnalyse([c1,c2,c3]);const by=t=>R.entities.filter(e=>e.type===t);
 return {dep:by('exchange deposit').map(e=>[e.key,e.strength]),svc:by('service').map(e=>[e.key,e.strength]),addr:by('address').map(e=>[e.key,e.strength,e.cases.map(x=>x.role)]),
  tx:by('transaction').map(e=>e.key),clu:by('cluster').map(e=>[e.key,e.cases.length]),pairs:R.pairs,first:R.entities[0].strength}})()"""

async def run(b, w, h, tag):
    ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials=AUTH, accept_downloads=True)
    pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    # real cases saved in this browser
    for q, nm in ((FAKE, "XC-A phishing address"), (TX, "XC-B payment tx")):
        await pg.goto(U + f"/?q={q}"); await pg.wait_for_function("cy.nodes().length>=2", timeout=120000); await pg.wait_for_timeout(600)
        await pg.evaluate(f"(async()=>{{curCase=blankCase({json.dumps(nm)});await Store.put(curCase)}})()")
    if tag == "desktop":
        e = await pg.evaluate(ENGINE_JS)
        check("engine: shared exchange deposit (case-insensitive 0x) = strong", e["dep"] and e["dep"][0][1] == 3, e["dep"])
        check("engine: shared exchange hot wallet = weak service link", e["svc"] and e["svc"][0][1] == 1, e["svc"])
        check("engine: shared suspect address = strong, roles per case", any(x[1] == 3 and "suspect" in x[2] for x in e["addr"]), e["addr"])
        check("engine: shared transaction + BTC co-spend cluster across cases", e["tx"] == ["0xabc"] and e["clu"] and e["clu"][0][1] == 2, (e["tx"], e["clu"]))
        check("engine: pair table counts and strongest first", any(p["deposits"] == 1 and p["txs"] == 1 for p in e["pairs"]) and e["first"] == 3, e["pairs"][:2])
    # exported case file C (an export of case B with a new id), read from disk in the browser
    exp = await pg.evaluate("(async()=>{const l=await Store.list();const c=l.find(x=>x.name==='XC-B payment tx');return JSON.stringify({format:'chaintrace-case',version:1,exported:new Date().toISOString(),case:{...c,id:'file-'+c.id,name:'XC-C exported file'}})})()")
    fn = os.path.join(tempfile.gettempdir(), f"chaintrace-case-xc-c-{tag}.json"); open(fn, "w").write(exp)
    sent = []; pg.on("request", lambda r: sent.append(r.url))
    n0 = await pg.evaluate("Store.list().then(l=>l.length)")
    await pg.goto(U + "/?crosscase=1"); await pg.wait_for_selector("#xcm.on", timeout=30000); await pg.wait_for_timeout(500)
    sent.clear()
    await pg.set_input_files("#xcfile", fn); await pg.wait_for_function("document.querySelectorAll('#xcm .xcc').length>=3", timeout=10000)
    msg = await pg.inner_text("#xcfmsg")
    check(f"{tag}: exported case file read in the browser (not saved, not uploaded)", "not uploaded" in msg and await pg.evaluate("Store.list().then(l=>l.length)") == n0, msg)
    # compare only the XC cases
    await pg.evaluate("document.querySelectorAll('#xcm .xcc').forEach(x=>{x.checked=/XC-/.test(x.parentElement.innerText)})")
    await pg.click("#xcrun"); await pg.wait_for_function("window.CT_LAST_CROSSCASE", timeout=20000)
    R = await pg.evaluate("window.CT_LAST_CROSSCASE")
    keys = {e["key"].lower(): e for e in R["entities"]}
    check(f"{tag}: real cases linked by the phishing address (all 3 cases)", FAKE in keys and len(keys[FAKE]["cases"]) == 3, [(k[:10], len(v["cases"])) for k, v in list(keys.items())[:4]])
    check(f"{tag}: real cases linked by the shared transaction 0x07fb2173…", any(e["type"] == "transaction" and TX in e["key"].lower() for e in R["entities"]))
    tab = await pg.inner_text("#xctab"); prs = await pg.inner_text("#xcpairs")
    check(f"{tag}: cross-case table + pairs table shown with leads caveat", "Fake_Phishing400" in tab and "XC-C exported file" in prs and "Leads, not evidence" in await pg.inner_text("#xcout"), tab[:100])
    if tag == "desktop":
        async with pg.expect_download() as dli: await pg.click("#xccsv")
        d = await dli.value; p = await d.path(); txt = open(p).read()
        check("CSV download of the cross-case table", d.suggested_filename.endswith(".csv") and FAKE in txt.lower() and "strength" in txt, d.suggested_filename)
    ov = await pg.evaluate("document.documentElement.scrollWidth>window.innerWidth+2")
    check(f"{tag}: no horizontal overflow", not ov)
    await pg.evaluate("document.getElementById('xcout').scrollIntoView()"); await pg.wait_for_timeout(300)
    if SHOTS: await pg.screenshot(path=SHOT(tag))
    await pg.click("#xcmerge"); await pg.wait_for_function("curCase&&curCase.name.startsWith('Merged')", timeout=20000); await pg.wait_for_timeout(800)
    mg = await pg.evaluate("({n:cy.nodes().length,sh:cy.nodes('[xc>1]').map(n=>n.id().toLowerCase()),name:curCase.name,saved:true})")
    check(f"{tag}: merged graph opened as a new local case, shared nodes marked", mg["n"] > 5 and FAKE in mg["sh"] and mg["name"].startswith("Merged"), (mg["n"], len(mg["sh"]), mg["name"]))
    api = [u for u in sent if "/api/" in u]
    check(f"{tag}: nothing sent to the server while finding links / merging ({len(sent)} requests, 0 to the API)", not api, api[:3])
    if SHOTS and tag == "desktop": await pg.screenshot(path=SHOT("merged_desktop"))
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
