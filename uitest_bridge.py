"""UI test for v7 cross-chain bridge tracing (Playwright + system Chrome). Password comes from env LP (never printed)."""
import asyncio, os, sys
from playwright.async_api import async_playwright
U = os.environ.get("CT_URL", "http://localhost:8090"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
ST = "document.getElementById('stxt').textContent"
THOR_BTC = "FC6E6B0863C394BCECBF4C070F2E6129A165E5C3175091D7733FA3CF9663DA34"
WH_ETH = "0x7e7d977682585c059f6c8130ffaa13db4bd2c362ee3950276b368de521950ba5"
ACROSS = "0x7b2deaad3e79d1cd5b9a63646c11eb4249d9048af2dcaec84033ddb9db966e69"
WH_ADDR = "0x96949fd549d0da5ca279662264085a93138bdb17"
AT_ROOT = "0xd3CCc5Bebc006fF7C4E5f0ddA65831733A571170"   # ETH -> THORChain router -> BTC
ok = []; bad = []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, info, flush=True)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
        errs = []
        for label, vp, mob in [("desktop", {"width": 1600, "height": 950}, False), ("phone", {"width": 390, "height": 844}, True)]:
            ctx = await b.new_context(viewport=vp, is_mobile=mob, has_touch=mob, http_credentials=AUTH)
            pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
            # 1) BTC tx that is a THORChain swap -> auto cross-chain card + dashed edge to ETH recipient
            await pg.goto(U + "/?q=" + THOR_BTC)
            await pg.wait_for_function("document.querySelector('#xtx .xm')||(document.getElementById('xtx')&&/Not a recognised|warnbox/.test(document.getElementById('xtx').innerHTML))", timeout=90000)
            r = await pg.evaluate("({x:cy.edges('[?xchain]').length, t:document.getElementById('xtx').innerText.slice(0,400)})")
            check(f"{label}: THORChain BTC->ETH deterministic card", "THORChain" in r["t"] and "DETERMINISTIC" in r["t"].upper(), r["t"][:120].replace("\n", " | "))
            check(f"{label}: cross-chain edge drawn", r["x"] >= 1, r)
            await pg.evaluate("cy.edges('[?xchain]')[0].emit('tap')"); await pg.wait_for_timeout(300)
            det = await pg.evaluate("document.getElementById('det').innerText")
            check(f"{label}: edge tap shows bridge card", "Cross-chain hop" in det and "0x7bB344" in det.replace("…", "") or "0x7bB3" in det, det[:100].replace("\n", " | "))
            check(f"{label}: caveat shown", "not evidence" in det)
            dash = await pg.evaluate("cy.edges('[?xchain]')[0].style('line-style')")
            check(f"{label}: dashed style", dash == "dashed", dash)
            if label == "phone":
                sw = await pg.evaluate("document.documentElement.scrollWidth"); check("phone: no horizontal overflow", sw <= 392, sw)
                await pg.screenshot(path="screenshot_v7_bridge_phone.png")
                await ctx.close(); continue
            # 2) Wormhole ETH -> SOL
            await pg.goto(U + "/?q=" + WH_ETH)
            await pg.wait_for_function("document.querySelector('#xtx .xm')||/Not a recognised|warnbox/.test(document.getElementById('xtx')?.innerHTML||'')", timeout=90000)
            t = await pg.evaluate("document.getElementById('xtx').innerText")
            check("Wormhole ETH->SOL match", "Wormhole" in t and "SOL" in t and "uvYSTe" in t, t[:100].replace("\n", " | "))
            n = await pg.evaluate("cy.nodes().filter(n=>n.id()==='CKuBTzPwzrCisqQMQfAjNn6jKcfny8ny4rJVN3cxLjcf').length")
            check("Wormhole SOL recipient node added", n == 1)
            # 3) address cross-chain activity
            await pg.goto(U + "/?q=" + WH_ADDR)
            await pg.wait_for_selector(".xbtn", timeout=90000); await pg.click(".xbtn")
            await pg.wait_for_function("document.querySelector('#xact .xm')||/warnbox|No bridge/.test(document.getElementById('xact')?.innerHTML||'')", timeout=60000)
            k = await pg.evaluate("document.querySelectorAll('#xact .xm').length"); check("address cross-chain activity list", k >= 3, k)
            # 4) heuristic lead (forced alongside deterministic) -> add as lead -> dotted amber edge
            res = await pg.evaluate(f"""(async()=>{{const j=await ctBridgeApi('{ACROSS}',null,'always');document.getElementById('det').innerHTML=ctBridgeList(j,'test');return {{d:(j.matches||[]).length,h:(j.heuristic||[]).length}}}})()""")
            check("Across deterministic + heuristic both found", res["d"] >= 1 and res["h"] >= 1, res)
            await pg.click("#det >> text=Add as lead (dashed)"); await pg.wait_for_timeout(500)
            hv = await pg.evaluate("cy.edges('[?heur]').length"); check("heuristic lead edge added", hv >= 1, hv)
            lab = await pg.evaluate("document.getElementById('det').innerText"); check("heuristic labelled lead only", "lead only" in lab.lower())
            # 5) expand guard on foreign (Arbitrum) node
            await pg.evaluate("expand(cy.nodes('[?xnode]')[0].id())"); await pg.wait_for_timeout(300)
            tt = await pg.evaluate("document.getElementById('toast').textContent"); check("foreign node not expandable", "context only" in tt, tt)
            # 6) AutoTrace with bridge following: ETH -> THORChain -> BTC
            await ctx.close(); ctx = await b.new_context(viewport=vp, http_credentials=AUTH); pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U + "/"); await pg.fill("#q", AT_ROOT); await pg.fill("#amin", "1"); await pg.select_option("#amax", "4")
            check("AutoTrace bridge checkbox", await pg.is_checked("#xfollow"))
            await pg.evaluate("document.getElementById('stxt').textContent=''"); await pg.click("#autobtn")
            await pg.wait_for_function(f"{ST}.includes('done')||{ST}.toLowerCase().includes('error')", timeout=200000)
            r = await pg.evaluate("({x:cy.edges('[?xchain]').length, btc:cy.nodes().filter(n=>(n.data('info')||{}).chain==='btc').length, card:[...document.querySelectorAll('.xcard')].map(e=>e.innerText).join(' ').slice(0,300)})")
            check("AutoTrace crossed into BTC", r["x"] >= 1 and r["btc"] >= 1, r)
            await pg.evaluate("cy.fit(undefined,50);const e=cy.edges('[?xchain]')[0];cy.elements().unselect();e.select();e.emit('tap')")
            await pg.wait_for_timeout(1200)
            await pg.evaluate("(()=>{const d=document.getElementById('det');let e=d.parentElement;while(e&&!(e.scrollHeight>e.clientHeight+5&&/auto|scroll/.test(getComputedStyle(e).overflowY)))e=e.parentElement;if(e)e.scrollTop+=d.getBoundingClientRect().top-e.getBoundingClientRect().top-8;else d.scrollIntoView()})()"); await pg.wait_for_timeout(400); await pg.screenshot(path="screenshot_v7_bridge.png")
            await ctx.close()
        check("no page errors", not errs, errs[:3])
        await b.close()
    print(f"\n{len(ok)} passed, {len(bad)} failed", bad)
    sys.exit(1 if bad else 0)
asyncio.run(main())
