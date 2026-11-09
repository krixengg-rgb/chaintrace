"""Progressive ETH lookup test: first graph quickly, slow Blockscout streams arrive via auto-refresh.
Password from env LP (never printed). Usage: LP=... python3 uitest_fast.py [address ...]   (CT_URL for another server)"""
import asyncio, os, sys, time
from playwright.async_api import async_playwright
U = os.environ.get("CT_URL", "http://localhost:8090"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
ADDRS = sys.argv[1:] or ["0xDFd5293D8e347dFe59E90eFd55b2956a1343963d", "0x897c80d1a9729e94460e2bd93178bd5215158df3"]
ok = []; bad = []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:220], flush=True)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
        for i, a in enumerate(ADDRS):
            for label, vp in (("desktop", {"width": 1500, "height": 900}), ("phone", {"width": 390, "height": 844})):
                ctx = await b.new_context(http_credentials=AUTH, viewport=vp, is_mobile=label == "phone")
                pg = await ctx.new_page(); resp = []
                pg.on("response", lambda r: resp.append((time.time(), r.url, r.status)) if "/api/lookup" in r.url else None)
                t0 = time.time(); await pg.goto(U + "/?q=" + a)
                await pg.wait_for_function("cy.nodes().length>1 && !document.getElementById('status').textContent.startsWith('Loading')", timeout=60000)
                t1 = time.time() - t0
                pend = await pg.evaluate("cur&&cur.pending?cur.pending.join(','):''")
                check(f"{label} {a[:10]}: first graph < 12s", t1 < 12, f"{t1:.1f}s nodes={await pg.evaluate('cy.nodes().length')} pending={pend or '-'} timing={await pg.evaluate('JSON.stringify(cur.timing||{})')}")
                if pend and label == "desktop" or pend and i == 0: await pg.screenshot(path=f"screenshot_v10_progressive_{label}.png")
                if pend:
                    await pg.wait_for_function("cur && !(cur.pending&&cur.pending.length)", timeout=30000)
                    check(f"{label} {a[:10]}: auto-refresh completed", True, f"{time.time() - t0:.1f}s, lookups={len(resp)}, nodes={await pg.evaluate('cy.nodes().length')}")
                warn = await pg.evaluate("[...document.querySelectorAll('.warnbox')].map(x=>x.textContent).join(' | ')")
                check(f"{label} {a[:10]}: no 'still loading' banner after refresh", "Still loading" not in warn, warn[:150])
                if i == 0: await pg.screenshot(path=f"screenshot_v10_fast_{label}.png")
                await ctx.close()
        await b.close()
    print(f"\n{len(ok)} passed, {len(bad)} failed"); sys.exit(1 if bad else 0)
asyncio.run(main())
