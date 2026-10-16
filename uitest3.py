import asyncio, os, json
from playwright.async_api import async_playwright
U = "http://localhost:8090"; AUTH = {"username": "krixen", "password": os.environ["LP"]}
ST = "document.getElementById('status').textContent"
async def wait_trace(pg, t=400000): await pg.wait_for_function(f"{ST}.includes('done')||{ST}.includes('Error')||{ST}.includes('error')", timeout=t)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox","--disable-dev-shm-usage"])
        errs = []
        for label, vp, mob in [("desktop", {"width":1600,"height":950}, False), ("phone", {"width":390,"height":844}, True)]:
            ctx = await b.new_context(viewport=vp, is_mobile=mob, has_touch=mob, http_credentials=AUTH, accept_downloads=True)
            pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("dialog", lambda d: asyncio.ensure_future(d.accept(f"Test case {label}") if d.type == "prompt" else d.accept()))
            # 1) lookup + save case + note + custom label
            await pg.goto(U + "/?q=0x8589427373D6D84E98730D7795D8f6f8731FDA16")
            await pg.wait_for_function("cy.nodes().length>1 && !document.body.classList.contains('busy')", timeout=120000)
            await pg.click("#savebtn"); await pg.wait_for_function("curCase && curCase.name.startsWith('Test case')")
            tgt = await pg.evaluate("cy.nodes().filter(n=>!n.data('kind')&&n.id()!=='0x8589427373D6D84E98730D7795D8f6f8731FDA16').map(n=>n.id())[0]")
            await pg.evaluate(f"cy.getElementById('{tgt}').emit('tap')")
            await pg.fill("#noteTxt", "Suspicious counterparty - check later"); await pg.fill("#clName", "Suspect wallet A"); await pg.select_option("#clKind", "scam")
            await pg.click("text=Apply"); await pg.fill("#caseNote", "Case summary: donation address investigation")
            await pg.wait_for_timeout(1500)
            cid = await pg.evaluate("curCase.id")
            # 2) reload -> persists
            await pg.goto(U + "/"); await pg.click("#casesbtn"); await pg.click(f".citem .nm >> text=Test case {label}")
            await pg.wait_for_function("curCase && cy.nodes().length>1")
            st = await pg.evaluate(f"""({{nodes:cy.nodes().length, note:!!cy.getElementById('{tgt}').data('note'), lbl:cy.getElementById('{tgt}').data('lbl'), kind:cy.getElementById('{tgt}').data('kind'), caseNote:document.getElementById('caseNote').value}})""")
            print(label, "persist after reload:", st, flush=True)
            # 3) export -> delete -> import roundtrip
            await pg.click("#casesbtn")
            async with pg.expect_download() as dlp: await pg.click(".citem.cur >> text=Export")
            f = await (await dlp.value).path(); exp = json.load(open(f))
            await pg.click(".citem.cur >> text=Delete"); await pg.wait_for_timeout(500)
            n_after_del = await pg.evaluate("Store.list().then(l=>l.length)")
            await pg.set_input_files("#impfile", f); await pg.wait_for_timeout(800)
            await pg.evaluate("toggleCases(true)"); await pg.wait_for_timeout(300)
            imp = await pg.evaluate("Store.list().then(l=>l.map(c=>({n:c.name,nodes:c.graph.nodes.length,notes:Object.keys(c.notes.nodes).length,labels:Object.keys(c.labels).length})))")
            print(label, f"export nodes {len(exp['case']['graph']['nodes'])}; after delete {n_after_del}; after import {imp}", flush=True)
            if label == "desktop":
                await pg.click(f".citem .nm >> text=Test case {label}"); await pg.wait_for_function("curCase && cy.nodes().length>1")
                await pg.evaluate(f"cy.getElementById('{tgt}').emit('tap')"); await pg.evaluate("toggleCases(true)"); await pg.wait_for_timeout(600)
                await pg.screenshot(path="screenshot_v3_cases.png"); await pg.evaluate("toggleCases(false)")
            # 4) AutoTrace on chains
            runs = [("0x8589427373D6D84E98730D7795D8f6f8731FDA16","forward","6"), ("1BCWMwpR4M1nYUuuYe2bmzrNuwGoF9ZAbA","forward","6"), ("7dm9am6Qx7cH64RB99Mzf7ZsLbEfmXM7ihXXCvMiT2X1","forward","3")] if label == "desktop" else [("12bG5T6kvj9iWPzCxTjPcWipKaRDLLXZBL","forward","4")]
            for q, d, h in runs:
                await pg.fill("#q", q); await pg.select_option("#dir", d); await pg.select_option("#amax", h); await pg.evaluate("toggleCases(false);document.getElementById('stxt').textContent=''"); await pg.click("#autobtn"); await pg.wait_for_timeout(1500)
                await wait_trace(pg)
                r = await pg.evaluate(f"""({{st:{ST}, eps:document.querySelectorAll('.eptab tr').length-1, hot:cy.edges('.hot,.hotx').length, nodes:cy.nodes().length}})""")
                print(label, "autotrace", q[:10], r, flush=True)
                if label == "desktop" and q.startswith("0x85"):
                    await pg.click("text=Save to case"); await pg.wait_for_timeout(800)
                    await pg.evaluate("document.querySelector('.eptab tr:nth-child(2)')&&document.querySelector('.eptab tr:nth-child(2)').click()"); await pg.wait_for_timeout(700)
                    await pg.screenshot(path="screenshot_v3_autotrace.png")
                    saved = await pg.evaluate("Store.list().then(l=>l.map(c=>c.name+':'+c.mode+':'+(c.trace&&c.trace.endpoints?c.trace.endpoints.length:0)))"); print("saved cases:", saved)
            if label == "phone":
                await pg.screenshot(path="screenshot_v3_phone.png")
                print("phone scrollWidth", await pg.evaluate("document.documentElement.scrollWidth"))
            await ctx.close()
        print("page errors:", errs[:5]); await b.close()
asyncio.run(main())
