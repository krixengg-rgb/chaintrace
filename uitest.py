import asyncio, sys
from playwright.async_api import async_playwright
CASES = [("eth","0x8589427373D6D84E98730D7795D8f6f8731FDA16","both"),
         ("btc","bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h","backward"),
         ("sol","9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM","backward")]
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox","--disable-dev-shm-usage"])
        only = sys.argv[1:]
        for chain, a, d in CASES:
            if only and chain not in only: continue
            pg = await b.new_page(viewport={"width":1600,"height":950})
            await pg.goto("http://localhost:8090/?q="+a)
            await pg.wait_for_function("cy.nodes().length>1 && document.getElementById('status').textContent===''", timeout=120000)
            n0 = await pg.evaluate("cy.nodes().length")
            rows0 = await pg.evaluate("document.querySelectorAll('#side table tr').length")
            has_more = await pg.locator("#more").count()
            if has_more:
                await pg.click("#more")
                await pg.wait_for_function(f"document.querySelectorAll('#side table tr').length>{rows0}", timeout=120000)
            rows1 = await pg.evaluate("document.querySelectorAll('#side table tr').length")
            # expand an unlabelled neighbour via double-tap
            tgt = await pg.evaluate(f"cy.nodes().filter(n=>n.id()!=='{a}'&&!n.data('kind')&&!n.id().startsWith('tx:')).map(n=>n.id())[0]")
            await pg.evaluate(f"cy.getElementById('{tgt}').emit('dbltap')")
            await pg.wait_for_function(f"cy.nodes().length>{n0} || document.getElementById('status').textContent.startsWith('error')", timeout=120000)
            await pg.wait_for_function("!document.getElementById('status').textContent.startsWith('loading')", timeout=120000)
            n1 = await pg.evaluate("cy.nodes().length")
            # multi-hop trace via UI
            await pg.select_option("#hops", "2"); await pg.select_option("#dir", d)
            await pg.click("#tracebtn")
            await pg.wait_for_function("document.getElementById('status').textContent.includes('trace done')||document.getElementById('status').textContent.includes('error')", timeout=600000)
            st = await pg.evaluate("document.getElementById('status').textContent"); hot = await pg.evaluate("cy.edges('.hot,.hotx').length")
            print(f"{chain}: nodes {n0} -> expand {tgt[:10]} -> {n1}; history rows {rows0} -> load more {rows1}; trace: {st}; highlighted edges {hot}", flush=True)
            if chain == "eth":
                await pg.wait_for_timeout(800); await pg.screenshot(path="screenshot2.png")
        await b.close()
asyncio.run(main())
