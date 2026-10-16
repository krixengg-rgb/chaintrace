import asyncio, os
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=await b.new_context(viewport={"width":1600,"height":950},http_credentials={"username":"krixen","password":os.environ["LP"]}); pg=await ctx.new_page()
        await pg.goto("http://localhost:8090/?q=0x8589427373D6D84E98730D7795D8f6f8731FDA16"); await pg.wait_for_function("cy.nodes().length>1",timeout=90000)
        await pg.click("#autobtn"); await pg.wait_for_selector(".eptab .sbadge",timeout=200000); await pg.wait_for_timeout(1500)
        await pg.evaluate("const n=cy.nodes('[sugg]')[0];n.emit('tap');n.select();cy.fit(undefined,60)"); await pg.wait_for_timeout(800)
        await pg.evaluate("document.querySelector('#det .sugg').scrollIntoView()")
        await pg.screenshot(path="screenshot_v4_suggested.png"); await b.close()
asyncio.run(main())
