import asyncio, os
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx = await b.new_context(viewport={"width":390,"height":844}, device_scale_factor=2, is_mobile=True, has_touch=True, http_credentials={"username":"krixen","password":os.environ["LP"]})
        pg = await ctx.new_page()
        await pg.goto("http://localhost:8090/?q=0x8589427373D6D84E98730D7795D8f6f8731FDA16&mode=trace&hops=2&dir=both&topk=3")
        try: await pg.wait_for_function("document.getElementById('status').textContent.includes('trace done')", timeout=200000)
        except Exception: print("status:", await pg.evaluate("document.getElementById('status').textContent"))
        await pg.wait_for_timeout(900); await pg.screenshot(path="screenshot_v2_mobile.png")
        print("scrollWidth", await pg.evaluate("document.documentElement.scrollWidth"), "nodes", await pg.evaluate("cy.nodes().length"))
        await b.close()
asyncio.run(main())
