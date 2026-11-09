"""Sanctions + community-report screening test (API + Playwright UI on desktop and phone + PDF + watch/AutoTrace hooks).
Known sanctioned addresses are taken from the official lists themselves (checked live below against the published OFAC SDN data via
the 0xB10C extract and the UK Sanctions List CSV), plus a clean control. Password comes from env LP (never printed).
Usage: LP=... python3 uitest_screen.py   (CT_URL to target another server, e.g. the live site; SHOTS=0 to skip screenshots)"""
import asyncio, os, sys, json, subprocess, tempfile, time
import httpx
from playwright.async_api import async_playwright
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
H = os.path.dirname(os.path.abspath(__file__)); TAG = os.environ.get("SHOT_TAG", "")
# (chain, address, expected list, expected entry substring): every one of these is published on the list named
KNOWN = [("eth", "0x098B716B8Aaf21512996dC57EB0615e2383E2f96", "ofac", "Lazarus Group"),          # OFAC SDN (DPRK3), Ronin bridge exploiter
         ("btc", "3Lpoy53K625zVeE47ZasiG5jGkAxJ27kh1", "ofac", "GARANTEX"),                       # OFAC SDN + UK list (Garantex Europe)
         ("btc", "3Lpoy53K625zVeE47ZasiG5jGkAxJ27kh1", "uk", "GARANTEX"),
         ("tron", "TFwjPScaJRCbSWVAywE1S1WgaUgSnyYUbD", "ofac", "GARANTEX"),
         ("xrp", "rnXyVQzgxZe7TR1EPzTkGj2jxH4LMJYh66", "ofac", "CHATEX"),
         ("sol", "42RLPACwZPx3vYYmxSueqsogfynBDqXK298EDsNoyoHi", "ofac", "Sokolovski"),
         ("tron", "TCQqA58EmX6AnUZKPCogL2Q441B4ThbJGN", "uk", "EXMO")]                           # UK Sanctions List only
CLEAN = ("eth", "0x28C6c06298d514Db089934071355E5743bf21d60")                                       # Binance 14 hot wallet (exchange, not listed)
REPORTED = ("eth", "0x000000000532b45f47779fce440748893b257865")                                    # Forta phishing dataset label
B10C = "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_{}.txt"
ok = []; bad = []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:220], flush=True)
def live_lists():
    """independent live cross-check: the test addresses really are on the published lists today"""
    a = {"ETH": KNOWN[0][1], "XBT": KNOWN[1][1], "TRX": KNOWN[3][1], "XRP": KNOWN[4][1], "SOL": KNOWN[5][1]}
    for asset, addr in a.items():
        try: t = httpx.get(B10C.format(asset), timeout=30, follow_redirects=True).text
        except Exception as ex: check(f"live: OFAC extract {asset} reachable", False, ex); continue
        check(f"live: {addr[:10]}… on published OFAC SDN {asset} extract", addr.lower() in t.lower(), len(t))
    try:
        with httpx.stream("GET", "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv", timeout=90, follow_redirects=True) as r:
            buf = b"".join(r.iter_bytes())
        for c, addr, l, _ in KNOWN:
            if l == "uk": check(f"live: {addr[:10]}… in UK Sanctions List CSV", addr.encode() in buf, len(buf))
    except Exception as ex: check("live: UK Sanctions List reachable", False, ex)
def api():
    a = (AUTH["username"], AUTH["password"]); cl = httpx.Client(auth=a, timeout=60)
    st = None
    for i in range(12):   # Render cold start
        try:
            r = cl.get(U + "/api/screen/status")
            if r.status_code == 200: st = r.json(); break
        except Exception: pass
        time.sleep(10)
    check("api: status loaded", st and st["loaded"] and "ofac" in st["lists"], st and {k: st["lists"][k].get("as_of") for k in st["lists"]})
    for c, addr, l, ent in KNOWN:
        j = cl.get(U + "/api/screen", params={"addr": addr}).json()
        h = [x for x in j.get("sanctions") or [] if x["list"] == l]
        check(f"api: {c} {addr[:10]}… sanctioned on {l}", j.get("verdict") == "sanctioned" and h and ent.lower() in (h[0]["entry"] or "").lower()
              and h[0]["as_of"] and "confirm before action" in h[0]["wording"] and h[0]["url"], h[:1] and h[0]["wording"])
    j = cl.get(U + "/api/screen", params={"addr": CLEAN[1]}).json()
    check("api: clean control not sanctioned", j["verdict"] in ("no match",) and not j["sanctions"], (j["verdict"], j.get("name")))
    j = cl.get(U + "/api/screen", params={"addr": REPORTED[1]}).json()
    check("api: community-reported address = amber lead", j["verdict"] == "reported" and j["reports"]["count"] >= 1 and "unverified" in j["reports"]["status"], j.get("reports", {}).get("categories"))
    ca = j.get("chainabuse") or {}
    check("api: Chainabuse degrades without key / reports status", ca.get("status") in ("no_key", "not_checked", "cached", "ok") and ca.get("search_url", "").startswith("https://chainabuse.com/address/"), ca.get("status"))
    txt = "\n".join(x[1] for x in KNOWN) + f"\n{CLEAN[1]}, {REPORTED[1]} notanaddress"
    j = cl.post(U + "/api/screen/batch", json={"text": txt}).json()
    check("api: batch summary", j["summary"]["sanctioned"] == len({x[1] for x in KNOWN}) and j["summary"]["reported"] == 1 and j["summary"]["no match"] == 1 and j["summary"]["not an address"] == 1, j["summary"])
    check("api: batch >500 rejected", cl.post(U + "/api/screen/batch", json={"addresses": [f"x{i}" for i in range(501)]}).status_code == 413)
    for i in range(3):
        r = cl.get(U + "/api/lookup", params={"q": KNOWN[0][1]})
        if r.status_code == 200: break
        time.sleep(8)
    d = r.json() if r.status_code == 200 else {}
    lab = d.get("label") or {}; rs = d.get("risk") or {}
    check("api: lookup focus node carries SDN hit + risk 100", lab.get("sanctions") and rs.get("score") == 100 and rs.get("reasons", [""])[0].startswith("⛔"), (rs.get("score"), (rs.get("reasons") or [""])[0][:90]))
    r = cl.post(U + "/api/autotrace", params={"q": KNOWN[0][1], "max_hops": 1, "max_nodes": 20, "max_secs": 40, "min_usd": 1000})
    if r.status_code == 200:
        job = r.json()["job"]; j = {}
        for i in range(40):
            j = cl.get(U + f"/api/trace/{job}").json()
            if j["status"] not in ("queued", "running"): break
            time.sleep(3)
        check("api: AutoTrace flags sanctioned root", j.get("status") == "done" and any(x["id"] == KNOWN[0][1] for x in j.get("sanctions") or []) and (j.get("warnings") or [""])[0].startswith("⛔")
              and j["risk"]["score"] == 100, (j.get("status"), (j.get("warnings") or [""])[0][:80]))
    else: check("api: AutoTrace started", False, r.status_code)
def direct():
    sys.path.insert(0, H); import report, watch
    p = {"meta": {"ref": "SCREEN/1"}, "case": {"name": "screen unit", "query": KNOWN[0][1]},
         "nodes": [{"id": KNOWN[0][1], "chain": "eth"}, {"id": REPORTED[1], "chain": "eth"}, {"id": CLEAN[1], "chain": "eth"}],
         "edges": [{"source": KNOWN[0][1], "target": REPORTED[1], "amount": 1, "unit": "ETH", "tx": "0x" + "3" * 64, "time": 1760000000, "usd": 3000}]}
    pdf, info = asyncio.run(report.build(p))
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf); f.flush(); t = " ".join(subprocess.run(["pdftotext", f.name, "-"], capture_output=True, text=True).stdout.split())
    check("pdf: sanctions section + official wording", "Sanctions and community-report screening" in t and "matches OFAC SDN list entry Lazarus Group" in t and "confirm before action" in t)
    check("pdf: community reports caveat", "Community reports: unverified leads" in t and "not evidence" in t)
    e = watch.enrich("eth", KNOWN[0][1], {})
    check("watch: sanctioned counterparty -> category sanctioned with wording", e["cat"] == "sanctioned" and e.get("sanctions") and "confirm before action" in e["sanctions"][0]["wording"], e["cat"])
async def ui():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
        errs = []
        for nm, vp, mob in (("desktop", {"width": 1600, "height": 950}, False), ("phone", {"width": 390, "height": 844}, True)):
            ctx = await b.new_context(viewport=vp, is_mobile=mob, has_touch=mob, http_credentials=AUTH, device_scale_factor=2 if mob else 1)
            pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U + "/?q=" + KNOWN[0][1], timeout=120000)
            await pg.wait_for_function("cy.nodes('[?sanc]').length>0 && document.querySelector('#side .sdnbox')", timeout=150000)
            check(f"{nm}: sanctioned node marked red + side panel box", await pg.evaluate("cy.getElementById('%s').data('sanc')===1" % KNOWN[0][1]))
            txt = await pg.inner_text("#side .sdnbox"); check(f"{nm}: wording in side panel", "matches OFAC SDN list entry Lazarus Group" in txt and "confirm before action" in txt, txt[:120])
            check(f"{nm}: risk gauge shows 100", await pg.evaluate("document.querySelector('#side .gauge').textContent.includes('100')"))
            n0 = await pg.evaluate("cy.nodes().not('[?grp]').length")
            await pg.click("#scrflt"); await pg.wait_for_timeout(500)
            vis = await pg.evaluate("cy.nodes().not('[?grp]').not('.unflag').length")
            check(f"{nm}: flagged-only filter", 1 <= vis <= n0, (vis, n0))
            await pg.evaluate("cy.getElementById('%s').emit('tap')" % KNOWN[0][1]); await pg.wait_for_timeout(400)
            check(f"{nm}: node detail shows SDN box", await pg.evaluate("!!document.querySelector('#det .sdnbox')"))
            sw = await pg.evaluate("document.documentElement.scrollWidth"); check(f"{nm}: no horizontal overflow", sw <= vp["width"] + 2, sw)
            if os.environ.get("SHOTS", "1") != "0":
                await pg.evaluate("ctFlagOnly(false)"); await pg.evaluate("cy.animate({fit:{padding:40}},{duration:10})"); await pg.wait_for_timeout(600)
                if mob: await pg.evaluate("document.querySelector('#side .sdnbox').scrollIntoView({block:'center'})")
                await pg.screenshot(path=os.path.join(H, f"screenshot_v11_sanctioned_{nm}{TAG}.png"))
            # batch modal
            await pg.goto(U + "/?screen=" + ",".join(dict.fromkeys(x[1] for x in KNOWN)) + "," + CLEAN[1] + "," + REPORTED[1], timeout=120000)
            await pg.wait_for_selector("#scrm.on"); await pg.wait_for_function("document.querySelectorAll('#scrout tr').length>3", timeout=60000)
            nsan = await pg.evaluate("document.querySelectorAll('#scrout .vpill.sanctioned').length")
            check(f"{nm}: batch table sanctioned rows", nsan == len({x[1] for x in KNOWN}), nsan)
            r = await pg.evaluate("(()=>{const c=document.querySelector('#scrm .card').getBoundingClientRect();return{l:c.left,r:c.right,sw:document.documentElement.scrollWidth}})()")
            check(f"{nm}: batch modal fits viewport", r["l"] >= 0 and r["r"] <= vp["width"] + 1, r)
            if os.environ.get("SHOTS", "1") != "0": await pg.screenshot(path=os.path.join(H, f"screenshot_v11_batch_{nm}{TAG}.png"))
            await ctx.close()
        check("no page errors", not errs, errs[:3])
        await b.close()
if __name__ == "__main__":
    if os.environ.get("LIVE_LISTS", "1") != "0": live_lists()
    api()
    if os.environ.get("DIRECT", "1") != "0": direct()
    asyncio.run(ui())
    print(f"\n{len(ok)} passed, {len(bad)} failed", bad); sys.exit(1 if bad else 0)
