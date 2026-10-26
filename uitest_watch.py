"""UI + API test for the v9 watchlist & alerts (Playwright + system Chrome) and the box CLI watch_check.py.
Password comes from env LP (never printed). Usage: LP=... python3 uitest_watch.py   (CT_URL to target another server)"""
import asyncio, os, sys, json, subprocess, tempfile, time
import httpx
from playwright.async_api import async_playwright
U = os.environ.get("CT_URL", "http://localhost:8090"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
H = os.path.dirname(os.path.abspath(__file__))
B14 = "0x28C6c06298d514Db089934071355E5743bf21d60"        # Binance 14 (ETH hot wallet, very busy)
BBTC = "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h"       # Binance BTC hot wallet
BSOL = "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9"     # Binance 2 (SOL)
ok = []; bad = []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:220], flush=True)
W = "CT_WATCH()"
async def add_via_form(pg, addr, name, since="1", out=None):
    await pg.evaluate("ctWatchAdd()"); await pg.fill("#wf-a", addr); await pg.fill("#wf-n", name)
    if out: await pg.fill("#wf-out", str(out))
    await pg.select_option("#wf-since", since); await pg.click("#wf-save")
async def wait_checked(pg, n, t=120000):
    await pg.wait_for_function(f"{W}.items.filter(x=>x.last&&x.last.checked).length>={n}&&!document.querySelector('#wstat .run')", timeout=t)
def api():
    a = (AUTH["username"], AUTH["password"])
    r = httpx.post(U + "/api/watch/check", json={"items": [{"address": B14}] * 9}, auth=a, timeout=30); check("api: >8 items rejected", r.status_code == 413, r.status_code)
    r = httpx.post(U + "/api/watch/check", json={"items": [{"address": "nope"}]}, auth=a, timeout=30)
    check("api: bad address -> error result", r.status_code == 200 and r.json()["results"][0]["status"] == "error", r.text[:120])
    r = httpx.post(U + "/api/watch/check", json={"items": [{"id": "s", "address": BSOL, "since": int(time.time()) - 3600}]}, auth=a, timeout=40); j = r.json()
    if j["results"][0]["status"] == "error":  # cold start / upstream hiccup: retry once
        time.sleep(5); j = httpx.post(U + "/api/watch/check", json={"items": [{"id": "s", "address": BSOL, "since": int(time.time()) - 3600}]}, auth=a, timeout=40).json()
    res = j["results"][0]; check("api: SOL hot wallet check ok + events", res["status"] == "ok" and len(res["events"]) > 0 and res["cursor"]["seen"], (res["status"], len(res["events"]), j["elapsed"]))
    r2 = httpx.post(U + "/api/watch/check", json={"items": [{"id": "s", "address": BSOL, "cursor": res["cursor"]}]}, auth=a, timeout=40).json()["results"][0]
    old = {e["tx"] for e in res["events"] if e.get("tx")}
    r3 = httpx.post(U + "/api/watch/check", json={"items": [{"id": "f", "address": BSOL, "since": int(time.time()) - 86400}]}, auth=a, timeout=40).json()["results"][0]
    fl = [e for e in r3["events"] if e.get("flagged") and e.get("counterparty", {}).get("cat")]
    check("api: labelled/inferred counterparty flagged + rule fired", bool(fl) and any(any(x.startswith(("to ", "from ")) for x in e["rules"]) for e in fl), [(e["counterparty"].get("name") or e["counterparty"].get("suggested"), e["rules"]) for e in fl[:2]])
    check("api: cursor prevents repeat alerts", r2["status"] == "ok" and not ({e.get("tx") for e in r2["events"]} & old), len(r2["events"]))
    check("api: unauthenticated rejected", httpx.post(U + "/api/watch/check", json={"items": []}, timeout=20).status_code == 401)
async def main():
    api()
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
        errs = []
        ctx = await b.new_context(viewport={"width": 1600, "height": 950}, http_credentials=AUTH, accept_downloads=True)
        await ctx.grant_permissions(["notifications"], origin=U)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("dialog", lambda d: asyncio.ensure_future(d.accept("Watch test case")))
        await pg.goto(U + "/?q=" + BBTC); await pg.wait_for_function("cy.nodes().length>1", timeout=90000)
        await pg.click("#wbtn"); check("drawer opens", await pg.evaluate("document.getElementById('wdrawer').classList.contains('open')"))
        check("empty state shown", "No alerts yet" in await pg.inner_text("#wbody"))
        # 1) from the node menu
        await pg.evaluate("ctWatch(false);const n=cy.getElementById(%r);n.select();n.emit('tap')" % BBTC); await pg.wait_for_selector("#det .wbtn", timeout=5000)
        await pg.click("#det .wbtn"); v = await pg.input_value("#wf-a"); check("node menu prefills form", v == BBTC, v)
        await pg.select_option("#wf-since", "1"); await pg.fill("#wf-bal", "0.01"); await pg.click("#wf-save")
        # 2) from the add form: busy ETH hot wallet, outflow rule
        await add_via_form(pg, B14, "Binance 14 (test)", "1", 50000)
        await wait_checked(pg, 2)
        st = await pg.evaluate(f"({{n:{W}.items.length,ev:{W}.events.length,st:{W}.items.map(x=>x.last.status+':'+(x.last.error||'')),u:{W}.events.filter(e=>e.unread).length}})")
        check("both addresses checked", all(s.startswith("ok") for s in st["st"]), st)
        check("hot wallets produced alert events", st["ev"] > 0, st)
        check("alert badge shows unread", await pg.evaluate("document.getElementById('wn').classList.contains('on')"), await pg.inner_text("#wn"))
        await pg.evaluate("ctWTab('alerts')")
        cards = await pg.evaluate("[...document.querySelectorAll('#wbody .wev')].length"); txt = await pg.inner_text("#wbody")
        check("alert feed renders event cards", cards > 0 and ("GMT" in txt or "BST" in txt or "unconfirmed" in txt) and "$" in txt, cards)
        check("event cards: amount + counterparty", await pg.evaluate("[...document.querySelectorAll('#wbody .wev')].some(c=>c.querySelector('.amt')&&c.querySelector('.cp'))"))
        lab = await pg.evaluate(f"{W}.events.some(e=>(e.flagged||[]).length&&e.counterparty&&e.counterparty.cat)")
        if lab: check("labelled counterparty flagged in UI (exchange / deposit)", lab)
        else: print("INFO no labelled counterparty in this window's UI events (data-dependent; API check covers flagging)")
        await pg.screenshot(path=os.path.join(H, "screenshot_v8_watch.png"))
        # 3) re-check: no duplicates
        n0 = st["ev"]; await pg.click("#wchk"); await pg.wait_for_timeout(500); await pg.wait_for_function("!document.querySelector('#wstat .run')", timeout=120000)
        ids = await pg.evaluate(f"{W}.events.map(e=>e.id)"); check("re-check adds no duplicate alerts", len(ids) == len(set(ids)) and len(ids) >= n0, (n0, len(ids)))
        # 4) open in graph
        tx = await pg.evaluate(f"({W}.events.find(e=>e.type==='tx')||{{}}).tx")
        await pg.evaluate("ctWatch(true);ctWTab('alerts')"); await pg.click("#wbody .wev .btn.pri")
        await pg.wait_for_function("cy.nodes().length>1", timeout=90000); q = await pg.input_value("#q")
        check("open in graph loads the tx", q == tx, q[:20])
        # 5) counterparties panel entry point
        await pg.goto(U + "/?q=" + BSOL); await pg.wait_for_function("cy.nodes().length>1", timeout=90000)
        await pg.evaluate("ctCpShow(%r)" % BSOL); await pg.click("#cpmore"); await pg.wait_for_selector("#cpp table tr .wbtn", timeout=60000)
        await pg.click("#cpp table tr .wbtn"); cpa = await pg.input_value("#wf-a"); check("counterparties row has Watch", bool(cpa) and cpa != BSOL, cpa[:14])
        await pg.click("#wform .btn:not(.pri)")
        # 6) persistence + case entry point
        await pg.reload(); await pg.wait_for_function("window.CT_WATCH&&CT_WATCH().items.length>=2", timeout=20000); check("watchlist persists in IndexedDB", True)
        await pg.click("#savebtn"); await pg.wait_for_selector("#wcase", timeout=5000); await pg.click("#wcase")
        check("case card: Watch subject prefills", await pg.input_value("#wf-a") == BSOL and await pg.input_value("#wf-r") != "")
        await pg.click("#wform .btn:not(.pri)")
        # 7) notifications toggle
        await pg.click("#wnotify"); await pg.wait_for_timeout(800)
        perm = await pg.evaluate("window.Notification?Notification.permission:'none'")
        check("notifications enable", await pg.evaluate(f"{W}.settings.notify===true"), perm)
        # 8) export -> CLI -> import round trip
        async with pg.expect_download() as dl: await pg.evaluate("ctWExport()")
        ex = json.load(open(await (await dl.value).path()))
        check("export format", ex.get("format") == "chaintrace-watchlist" and len(ex["items"]) >= 2 and all(i.get("cursor") for i in ex["items"]), len(ex["items"]))
        with tempfile.TemporaryDirectory() as td:
            wl = os.path.join(td, "watchlist.json"); json.dump(ex, open(wl, "w"))
            r = subprocess.run([sys.executable, os.path.join(H, "watch_check.py"), "--list", wl, "--state", os.path.join(td, "state.json"), "--format", "json"], capture_output=True, text=True, timeout=240)
            try: run = json.loads(r.stdout)
            except Exception: run = {}
            check("CLI runs on exported file (json)", r.returncode == 0 and run.get("format") == "chaintrace-watch-run" and run.get("watched") == len(ex["items"]), (r.returncode, r.stderr[-200:]))
            check("CLI reuses browser cursors (no baseline)", run.get("baselined") == 0 and all(a["status"] == "ok" for a in run.get("addresses", [])), [a.get("status") for a in run.get("addresses", [])])
            r2 = subprocess.run([sys.executable, os.path.join(H, "watch_check.py"), "--list", wl, "--state", os.path.join(td, "state.json"), "--max", "5"], capture_output=True, text=True, timeout=240)
            check("CLI markdown output", r2.returncode == 0 and r2.stdout.startswith("**ChainTrace watchlist**"), r2.stdout[:120])
            r3 = subprocess.run([sys.executable, os.path.join(H, "watch_check.py"), "--list", wl, "--state", os.path.join(td, "state.json"), "--export-browser", os.path.join(td, "back.json")], capture_output=True, text=True, timeout=60)
            back = json.load(open(os.path.join(td, "back.json"))); back["items"].append({"address": "0x71660c4005BA85c37ccec55d0C4493E66Fe775d3", "name": "Coinbase 1 (imported)"})
            json.dump(back, open(os.path.join(td, "back.json"), "w"))
            await pg.evaluate("ctWatch(true)"); await pg.set_input_files("#wimp", os.path.join(td, "back.json")); await pg.wait_for_timeout(600)
            n = await pg.evaluate(f"{W}.items.length"); check("import merges (1 new, rest updated)", n == len(ex["items"]) + 1, n)
        await ctx.close()
        # phone
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, http_credentials=AUTH)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + "/"); await pg.wait_for_timeout(800); await pg.click("#wbtn")
        await add_via_form(pg, B14, "Binance 14", "1", 50000); await wait_checked(pg, 1)
        await pg.evaluate("ctWTab('alerts')"); await pg.wait_for_timeout(300)
        r = await pg.evaluate("(()=>{const d=document.getElementById('wdrawer').getBoundingClientRect();return{l:d.left,r:d.right,w:innerWidth,sw:document.documentElement.scrollWidth,cards:document.querySelectorAll('#wbody .wev').length,bw:document.getElementById('wbody').scrollWidth,bc:document.getElementById('wbody').clientWidth}})()")
        check("phone: drawer fits, cards render, no overflow", r["l"] >= 0 and r["r"] <= 391 and r["sw"] <= 392 and r["cards"] > 0 and r["bw"] <= r["bc"] + 1, r)
        await pg.screenshot(path=os.path.join(H, "screenshot_v8_watch_phone.png")); await ctx.close()
        check("no page errors", not errs, errs[:3])
        await b.close()
    print(f"\n{len(ok)} passed, {len(bad)} failed", bad)
    sys.exit(1 if bad else 0)
asyncio.run(main())
