import asyncio, os, sys
from playwright.async_api import async_playwright
U = "http://localhost:8090"; AUTH = {"username": "krixen", "password": os.environ["LP"]}
ST = "document.getElementById('status').textContent"
CASES = [("eth","0x8589427373D6D84E98730D7795D8f6f8731FDA16","both"),("btc","bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h","backward"),("sol","9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM","backward")]
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox","--disable-dev-shm-usage"])
        errs = []
        for chain, a, d in CASES:
            ctx = await b.new_context(viewport={"width":1600,"height":950}, http_credentials=AUTH, accept_downloads=True)
            pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U + "/?q=" + a)
            await pg.wait_for_function(f"cy.nodes().length>1 && !document.body.classList.contains('busy')", timeout=120000)
            badge = await pg.inner_text("#chainBadge"); n0 = await pg.evaluate("cy.nodes().length")
            rows0 = await pg.evaluate("document.querySelectorAll('#side table tr').length")
            if await pg.locator("#more").count():
                await pg.click("#more"); await pg.wait_for_function(f"document.querySelectorAll('#side table tr').length>{rows0}", timeout=120000)
            rows1 = await pg.evaluate("document.querySelectorAll('#side table tr').length")
            tgt = await pg.evaluate(f"cy.nodes().filter(n=>n.id()!=='{a}'&&!n.data('kind')&&!n.id().startsWith('tx:')).map(n=>n.id())[0]")
            await pg.evaluate(f"cy.getElementById('{tgt}').emit('dbltap')")
            await pg.wait_for_function(f"cy.nodes().length>{n0} || {ST}.startsWith('Error')", timeout=120000)
            await pg.wait_for_function("!document.body.classList.contains('busy')", timeout=120000)
            n1 = await pg.evaluate("cy.nodes().length")
            await pg.select_option("#hops", "2"); await pg.select_option("#dir", d); await pg.click("#tracebtn")
            await pg.wait_for_function(f"{ST}.includes('trace done')||{ST}.includes('Error')", timeout=600000)
            st = await pg.evaluate(ST); hot = await pg.evaluate("cy.edges('.hot,.hotx').length"); risk = await pg.text_content(".gauge")
            url = pg.url
            # exports
            async with pg.expect_download() as dlp: await pg.evaluate("exportCSV()")
            csvf = await (await dlp.value).path(); ncsv = sum(1 for _ in open(csvf)) - 1
            async with pg.expect_download() as dlp: await pg.evaluate("exportPNG()")
            png = os.path.getsize(await (await dlp.value).path())
            print(f"{chain}: badge {badge!r}; nodes {n0}->expand {n1}; rows {rows0}->{rows1}; {st}; hl {hot}; gauge {risk.split()}; csv rows {ncsv}; png {png//1024}KB; url {url[len(U):][:70]}", flush=True)
            if chain == "eth":
                await pg.evaluate("document.querySelector('.path')&&document.querySelector('.path').click()"); await pg.wait_for_timeout(700)
                await pg.screenshot(path="screenshot_v2_desktop.png")
                # deep link reload reproduces the trace
                pg2 = await ctx.new_page(); await pg2.goto(url)
                await pg2.wait_for_function(f"{ST}.includes('trace done')", timeout=300000)
                print("deep link trace nodes:", await pg2.evaluate("cy.nodes().length"))
                # cancel
                await pg2.fill("#q", "0x28C6c06298d514Db089934071355E5743bf21d60"); await pg2.select_option("#hops", "4"); await pg2.click("#tracebtn")
                await pg2.wait_for_timeout(1500); await pg2.click("#cancelbtn")
                await pg2.wait_for_function(f"{ST}.includes('cancelled')", timeout=60000); print("cancel:", await pg2.evaluate(ST))
            await ctx.close()
        # mobile
        ctx = await b.new_context(viewport={"width":390,"height":844}, device_scale_factor=2, is_mobile=True, has_touch=True, http_credentials=AUTH)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + "/?q=0x8589427373D6D84E98730D7795D8f6f8731FDA16&mode=trace&hops=2&dir=both&topk=3")
        await pg.wait_for_function(f"{ST}.includes('trace done')", timeout=300000); await pg.wait_for_timeout(800)
        await pg.screenshot(path="screenshot_v2_mobile.png", full_page=False)
        sw = await pg.evaluate("document.documentElement.scrollWidth"); print("mobile scrollWidth", sw)
        print("page errors:", errs[:5]); await b.close()
asyncio.run(main())
