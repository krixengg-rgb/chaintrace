"""v28 shareable read-only case links (share.py, static/share.js, /share viewer). Real addresses for the UI snapshot.
- engine: encrypt/open round trip, audit hash, notes + private labels excluded unless opted in, tampered / expired / other-key links refused,
  SHARE_KEY vs CHAINTRACE_PASSWORD-derived key, nothing written to disk;
- API: preview, create, public open without the site password (rate limited), everything else still needs the password;
- UI: Share button -> preview -> link; the viewer opens WITHOUT credentials: read-only banner, expiry, audit hash check, graph + table (desktop + phone).
Password from env LP (never printed). Usage: LP=... python3 uitest_share.py   (CT_URL, SHOT_TAG=_live, ENGINE=0, SHOTS=0)"""
import asyncio, os, sys, time, glob, json
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v28_share_{n}{TAG}.png")
HYDRA = "123WBUDmSJv4GctdVEz6Qq6z8nXSKrJ4KX"
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
PL = {"nodes": [{"id": HYDRA, "chain": "btc", "name": "Hydra Market (OFAC SDN)", "kind": "sanctioned", "private_note": "x"}, {"id": "3ES6pqCuKmPKmXuJmGuoqnJX4yuqjjZw6E", "chain": "btc"}],
      "edges": [{"source": HYDRA, "target": "3ES6pqCuKmPKmXuJmGuoqnJX4yuqjjZw6E", "amount": 1.5, "unit": "BTC", "tx": "ab" * 32, "time": 1650000000}],
      "case": {"name": "Share test", "notes": {"case": "CONFIDENTIAL victim name", "nodes": {}, "edges": {}}, "labels": {HYDRA: {"name": "Suspect wallet A", "kind": "scam"}}},
      "meta": {"ref": "OP-SECRET", "investigator": "DC Example"}, "log": [{"a": "x"}]}

def engine():
    import share
    before = set(glob.glob(os.path.join(H, "data", "*")))
    r = share.make(PL, "24h"); o = share.open_token(r["token"]); s = o["snapshot"]; blob = json.dumps(s)
    check("round trip: snapshot opens, audit hash matches", o["hash_ok"] and o["audit_sha256"] == r["audit_sha256"] and len(s["nodes"]) == 2)
    check("default: notes, private labels, report meta and log excluded", "notes" not in s and "labels" not in s and "CONFIDENTIAL" not in blob and "Suspect wallet A" not in blob and "OP-SECRET" not in blob and "private_note" not in blob, r["excluded"])
    check("excluded items are listed for the preview", "case notes" in r["excluded"] and any("private label" in x for x in r["excluded"]))
    s2 = share.open_token(share.make(PL, "24h", True, True)["token"])["snapshot"]
    check("opt-in: notes and private labels included", "CONFIDENTIAL" in json.dumps(s2) and s2["labels"][HYDRA]["name"] == "Suspect wallet A")
    t = r["token"]; bad_t = t[:-6] + ("A" if t[-6] != "A" else "B") + t[-5:]
    try: share.open_token(bad_t); check("tampered link refused", False)
    except share.ShareError as e: check("tampered link refused (400)", e.code == 400, str(e))
    try: share.open_token(t, now=time.time() + 2 * 86400); check("expired link refused", False)
    except share.ShareError as e: check("expired link refused (410)", e.code == 410, str(e))
    old = os.environ.get("SHARE_KEY"); os.environ["SHARE_KEY"] = "test-key-rotation-0123456789"
    try:
        try: share.open_token(t); check("link made with another key refused (key rotation revokes)", False)
        except share.ShareError as e: check("link made with another key refused (key rotation revokes)", e.code == 400)
        t2 = share.make(PL, "1h")["token"]; check("SHARE_KEY used when set", share.key_source() == "SHARE_KEY" and share.open_token(t2)["hash_ok"])
    finally:
        if old is None: os.environ.pop("SHARE_KEY", None)
        else: os.environ["SHARE_KEY"] = old
    check("fallback key derived from CHAINTRACE_PASSWORD when SHARE_KEY unset", old is not None or share.key_source() == "derived from CHAINTRACE_PASSWORD")
    try: share.make(PL, "99y"); check("bad expiry refused", False)
    except share.ShareError: check("bad expiry refused", True)
    check("nothing written to disk", set(glob.glob(os.path.join(H, "data", "*"))) == before)

def api():
    cl = httpx.Client(auth=(AUTH["username"], AUTH["password"]), timeout=60); pub = httpx.Client(timeout=60)
    pv = cl.post(U + "/api/share", params={"ttl": "24h", "preview": "true"}, json=PL).json()
    check("api: preview (counts, hash, excluded) without a token", pv.get("nodes") == 2 and "token" not in pv and pv.get("audit_sha256") and "case notes" in pv.get("excluded", []), pv.get("excluded"))
    r = cl.post(U + "/api/share", params={"ttl": "24h"}, json=PL).json()
    check("api: link created, snapshot in the URL fragment", "/share#t=v1." in r.get("url", ""), r.get("url", "")[:60])
    o = pub.post(U + "/api/share/open", json={"token": r["token"]})
    check("api: public open WITHOUT the site password returns the read-only snapshot", o.status_code == 200 and o.json()["read_only"] and o.json()["audit_sha256"] == r["audit_sha256"], o.status_code)
    check("api: snapshot from the server has no notes / private labels", "CONFIDENTIAL" not in o.text and "Suspect wallet A" not in o.text)
    check("api: other endpoints still need the password", pub.get(U + "/api/lookup", params={"q": HYDRA}).status_code == 401 and pub.post(U + "/api/share", json=PL).status_code == 401 and pub.get(U + "/").status_code == 401)
    v = pub.get(U + "/share")
    check("api: viewer page is public, no-store / no-referrer", v.status_code == 200 and "no-store" in v.headers.get("cache-control", "") and v.headers.get("referrer-policy") == "no-referrer")
    check("api: altered token refused (400)", pub.post(U + "/api/share/open", json={"token": r["token"][:-3] + "AAA"}).status_code == 400)

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1600, "height": 950}, http_credentials=AUTH)
        pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + f"/?q={HYDRA}"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000); await pg.wait_for_timeout(1500)
        await pg.click("#sharebtn"); await pg.click("#shprev"); await pg.wait_for_selector("#shpvbox", timeout=30000)
        pv = await pg.inner_text("#shpvbox")
        check("ui: Share -> preview shows counts, exclusions, expiry and audit hash", "nodes" in pv and "Left out" in pv and "Audit SHA-256" in pv and "Expires" in pv, pv[:120])
        await pg.click("#shgo"); await pg.wait_for_function("window.CT_LAST_SHARE&&document.getElementById('shurl')", timeout=30000)
        url = await pg.input_value("#shurl"); n = await pg.evaluate("CT_LAST_SHARE.nodes")
        check("ui: link created", "/share#t=v1." in url)
        if SHOTS: await pg.screenshot(path=SHOT("create_desktop"))
        check("ui: no JS errors (creator)", not errs, errs[:2]); await ctx.close()
        for w, h, tag in ((1600, 950, "desktop"), (390, 844, "phone")):
            vc = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone")   # NO credentials
            vp = await vc.new_page(); ve = []; vp.on("pageerror", lambda e: ve.append(str(e)))
            await vp.goto(url); await vp.wait_for_function("window.CT_SHARE&&window.cy&&cy.nodes().length>0", timeout=60000)
            ban = await vp.inner_text("#ban")
            check(f"viewer {tag}: opens without the password; read-only banner, expiry, audit hash verified", "read-only" in ban and "expires" in ban and "✓ matches content" in ban, ban[:120])
            check(f"viewer {tag}: same graph as shared, no edit / lookup controls", await vp.evaluate("cy.nodes().length") == n and await vp.query_selector("#q") is None and await vp.query_selector("#autobtn") is None)
            if SHOTS: await vp.screenshot(path=SHOT(tag))
            check(f"viewer {tag}: no JS errors", not ve, ve[:2]); await vc.close()
        vc = await b.new_context(); vp = await vc.new_page()
        await vp.goto(url[:-4] + "AAAA"); await vp.wait_for_selector("#msg.err", timeout=30000)
        check("viewer: altered link shows an error, no data", "invalid" in (await vp.inner_text("#msg")) and await vp.evaluate("!window.CT_SHARE"))
        await vc.close(); await b.close()

if __name__ == "__main__":
    if os.environ.get("ENGINE", "1") != "0": engine()
    if os.environ.get("API", "1") != "0": api()
    asyncio.run(ui())
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
