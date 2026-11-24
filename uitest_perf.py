"""v34 faster first load: bundled/minified/pre-compressed front end, cache headers, lightweight /healthz, waking-up splash, keep-warm workflow.
- /healthz: no auth, JSON {ok, warm, up_s}, no-store, fast;
- index: brotli/gzip, no-cache + ETag (304 on revalidation), one app bundle + one vendor bundle instead of 26 script tags;
- bundle: content-hashed name, Cache-Control immutable for a year, br / gzip / identity decode to the same bytes, contains every feature module; unknown name -> 404;
- un-hashed /static files: Cache-Control no-cache (never stale after a deploy);
- UI desktop + phone: splash shown while scripts load (bundle delayed in the test) and removed after load, app usable, <= 10 requests on first load, no JS errors;
- keep-warm workflow: opt-in (repository variable), every 14 min, UK daytime gate, Render 750-hour note.
Screenshots screenshot_v34_perf_{splash_desktop,desktop,phone}*.png. Password from env LP (never printed). Usage: LP=... python3 uitest_perf.py (CT_URL, SHOT_TAG=_live, SHOTS=0)"""
import asyncio, gzip, os, re, sys, time
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__))
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v34_perf_{n}{TAG}.png")
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)

def http():
    a = (AUTH["username"], AUTH["password"])
    t = time.time(); r = httpx.get(U + "/healthz", timeout=120); dt = time.time() - t; j = r.json()
    check("healthz: no auth, JSON ok/warm/up_s, no-store", r.status_code == 200 and j.get("ok") is True and "warm" in j and "up_s" in j and r.headers.get("cache-control") == "no-store", (j, round(dt, 2)))
    import brotli
    r = httpx.get(U + "/", auth=a, headers={"Accept-Encoding": "br"}, timeout=60)
    raw = r.content   # httpx decodes br when brotli is installed
    check("index: brotli-encoded, no-cache + ETag", r.headers.get("content-encoding") == "br" and r.headers.get("cache-control") == "no-cache" and r.headers.get("etag"), dict(r.headers))
    r2 = httpx.get(U + "/", auth=a, headers={"If-None-Match": r.headers["etag"]}, timeout=60)
    check("index: revalidation returns 304", r2.status_code == 304, r2.status_code)
    html = raw.decode()
    scripts = re.findall(r'<script src="([^"]+)"', html)
    app = [s for s in scripts if re.match(r"/static/b/app\.[0-9a-f]{12}\.js$", s)]; vend = [s for s in scripts if re.match(r"/static/b/cytoscape\.[0-9a-f]{12}\.js$", s)]
    check("index: one hashed app bundle + one hashed vendor bundle, no per-module script tags", len(app) == 1 and len(vend) == 1 and len(scripts) == 2, scripts)
    check("index: inline 'waking up' splash polling /healthz", 'id="ctboot"' in html and "/healthz" in html)
    rb = httpx.get(U + app[0], auth=a, headers={"Accept-Encoding": "br"}, timeout=60); rg = httpx.get(U + app[0], auth=a, headers={"Accept-Encoding": "gzip"}, timeout=60)
    ri = httpx.get(U + app[0], auth=a, headers={"Accept-Encoding": "identity"}, timeout=60)
    check("bundle: immutable 1-year cache, br/gzip/identity identical", rb.headers.get("cache-control") == "public, max-age=31536000, immutable" and rb.headers.get("content-encoding") == "br"
          and rg.headers.get("content-encoding") == "gzip" and rb.content == rg.content == ri.content, (rb.headers.get("content-length"), rg.headers.get("content-length"), len(ri.content)))
    js = ri.content.decode()
    mods = ["ctXSwap", "ctIntake", "ctScamPattern", "ctCrossCase", "ctStatement", "ctRisk", "ctReportPayload", "ctCluster"]
    check("bundle: contains every feature module", all(m in js for m in mods), [m for m in mods if m not in js])
    check("bundle: compressed transfer much smaller than the sources", int(rb.headers.get("content-length") or 0) < 0.4 * len(ri.content), (rb.headers.get("content-length"), len(ri.content)))
    r404 = httpx.get(U + "/static/b/app.000000000000.js", auth=a, timeout=30)
    check("bundle: unknown hashed name -> 404", r404.status_code == 404, r404.status_code)
    rs = httpx.get(U + "/static/v6.js", auth=a, timeout=30)
    check("un-hashed static files: Cache-Control no-cache", rs.status_code == 200 and rs.headers.get("cache-control") == "no-cache", rs.headers.get("cache-control"))
    rn = httpx.get(U + "/", timeout=30)
    check("index still requires the password", rn.status_code == 401, rn.status_code)

def workflow():
    p = os.path.join(H, ".github", "workflows", "keep-warm.yml"); s = open(p).read()
    check("keep-warm workflow: opt-in via repository variable, every 14 min, UK daytime gate, 750-hour note", "vars.KEEPWARM_URL != ''" in s and "*/14" in s and "Europe/London" in s and "750" in s and "secrets." not in s)

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w, h, tag in ((1600, 950, "desktop"), (390, 844, "phone")):
            ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials=AUTH)
            pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e))); reqs = []; pg.on("request", lambda r: reqs.append(r.url))
            if tag == "desktop":   # hold the app bundle for 2 s so the splash is visible
                async def slow(route):
                    await asyncio.sleep(2); await route.continue_()
                await pg.route(re.compile(r".*/static/b/app\.[0-9a-f]+\.js"), slow)
            t = time.time(); await pg.goto(U + "/", wait_until="commit")
            if tag == "desktop":
                await pg.wait_for_selector("#ctboot", timeout=20000); await pg.wait_for_timeout(600)
                vis = await pg.evaluate("(()=>{const b=document.getElementById('ctboot');return b&&getComputedStyle(b).opacity!=='0'})()")
                check("splash visible while the bundle loads", vis)
                if SHOTS: await pg.screenshot(path=SHOT("splash_desktop"))
            await pg.wait_for_load_state("load"); await pg.wait_for_function("typeof cy!=='undefined'&&!!cy&&!document.getElementById('ctboot')", timeout=60000)
            ready = time.time() - t
            check(f"{tag}: splash removed after load, app ready ({ready:.2f} s)", True)
            btns = await pg.evaluate("['intakebtn','xcbtn','stmtbtn','lossbtn'].map(i=>!!document.getElementById(i))")
            check(f"{tag}: feature buttons present from the bundle", all(btns), btns)
            first = [r for r in reqs if r.startswith(U)]
            check(f"{tag}: <= 10 requests on first load", len(first) <= 10, [r.replace(U, "") for r in first])
            await pg.fill("#q", "0x2e3a5deb080fcabc9ebefd5c871989ac507c94be"); await pg.keyboard.press("Enter")
            await pg.wait_for_function("cy.nodes().length>=3", timeout=120000); await pg.wait_for_timeout(800)
            check(f"{tag}: a lookup works after the faster load", await pg.evaluate("cy.nodes().length") >= 3)
            if SHOTS: await pg.screenshot(path=SHOT(tag))
            check(f"{tag}: no JS errors", not errs, errs[:2]); await ctx.close()
        await b.close()

if __name__ == "__main__":
    http(); workflow(); asyncio.run(ui())
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
