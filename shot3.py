import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox","--disable-dev-shm-usage"])
        pg = await b.new_page(viewport={"width":1600,"height":950})
        await pg.goto("http://localhost:8090/")
        await pg.fill("#q", "0x8589427373D6D84E98730D7795D8f6f8731FDA16")
        await pg.select_option("#hops", "2"); await pg.select_option("#dir", "both")
        await pg.click("#tracebtn")
        await pg.wait_for_function("document.getElementById('status').textContent.includes('trace done')", timeout=300000)
        info = await pg.evaluate("""(()=>{const ks=cy.nodes().map(n=>n.data('kind')).filter(Boolean);
          const n=cy.nodes().filter(n=>n.data('kind')==='hack')[0]||cy.nodes().filter(n=>n.data('kind')==='mixer')[0];n.emit('tap');n.select();return ks.join(',')})()""")
        print("kinds:", info)
        await pg.wait_for_timeout(700); await pg.screenshot(path="screenshot3.png"); await b.close()
asyncio.run(main())
