import asyncio, os
from playwright.async_api import async_playwright
U="http://localhost:8090"; AUTH={"username":"krixen","password":os.environ["LP"]}
ETH=open('/tmp/inf.txt').read().split()[0]
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox","--disable-dev-shm-usage"]); errs=[]
        for label,vp,mob in [("desktop",{"width":1600,"height":950},False),("phone",{"width":390,"height":844},True)]:
            ctx=await b.new_context(viewport=vp,is_mobile=mob,has_touch=mob,http_credentials=AUTH); pg=await ctx.new_page(); pg.on("pageerror",lambda e:errs.append(str(e)))
            await pg.goto(U+"/?q="+ETH); await pg.wait_for_selector("#side .sugg",timeout=90000)
            print(label,"lookup card:",(await pg.inner_text("#side .sugg"))[:160].replace("\n"," | "))
            print(label,"dashed node:",await pg.evaluate(f"cy.getElementById('{ETH.lower()}').length? cy.getElementById('{ETH.lower()}').style('border-style'):cy.nodes('[sugg]').map(n=>n.style('border-style'))"))
            await pg.goto(U+"/?q=2oUVDCMTKKCDHiuMmCgZX6Vq9irR92K2vjxTxQsNNrdS"); await pg.wait_for_function("cy.nodes().length>0",timeout=90000)
            await pg.select_option("#amax","3"); await pg.click("#autobtn"); await pg.wait_for_selector(".eptab .sbadge",timeout=120000)
            print(label,"endpoint row:",(await pg.inner_text(".eptab tr:nth-child(2)")).replace("\n"," | "))
            await pg.evaluate("cy.nodes('[sugg]')[0].emit('tap')"); await pg.wait_for_selector("#det .sugg")
            if label=="desktop": await pg.screenshot(path="screenshot_v4_suggested.png")
            else: await pg.screenshot(path="screenshot_v4_phone.png"); print("scrollWidth",await pg.evaluate("document.documentElement.scrollWidth"))
            await ctx.close()
        print("errors",errs); await b.close()
asyncio.run(main())
