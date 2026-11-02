"""API + UI smoke for TRON and XRP Ledger support.
Password from env LP or .env CT_PASS (never printed).
Usage: LP=... python3 uitest_tron_xrp.py   (CT_URL to target another server)
"""
import asyncio, os, sys, json, time
from pathlib import Path
import httpx

H = Path(__file__).resolve().parent
U = os.environ.get("CT_URL", "http://localhost:8090")
# load .env without printing
_env = {}
for line in (H / ".env").read_text().splitlines() if (H / ".env").exists() else []:
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1); _env[k] = v
AUTH = (
    os.environ.get("LU") or os.environ.get("CHAINTRACE_USER") or _env.get("CT_USER") or _env.get("CHAINTRACE_USER"),
    os.environ.get("LP") or os.environ.get("CHAINTRACE_PASSWORD") or _env.get("CT_PASS") or _env.get("CHAINTRACE_PASSWORD"),
)
TRON_HOT = "TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf"
TRON_HEX = None  # filled from addrutil
XRP_HOT = "rDAE53VfMvftPB4ogpWGWvzkQxfht6JPxr"
XRP_HACK = "rK21t6nGLy4MNDqhvy3pGwcLFy25qgfzMx"
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name)
    print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)

def unit_addrutil():
    import addrutil, chains
    check("addrutil: T… checksum ok", addrutil.is_tron_address(TRON_HOT), TRON_HOT)
    hx = addrutil.tron_b58_to_hex(TRON_HOT)
    check("addrutil: hex 41… accepted", addrutil.is_tron_address(hx) and hx.startswith("41"), hx[:10])
    check("addrutil: norm_tron hex->T", addrutil.norm_tron(hx) == TRON_HOT, addrutil.norm_tron(hx))
    check("addrutil: invalid T checksum rejected", not addrutil.is_tron_address("TDqSquXBgUCLYvYC4XZgrprLK589dkhSCg"))
    check("addrutil: XRP classic checksum ok", addrutil.is_xrp_address(XRP_HOT))
    check("addrutil: XRP bad checksum rejected", not addrutil.is_xrp_address("rDAE53VfMvftPB4ogpWGWvzkQxfht6JPxx"))
    check("detect: TRON before SOL", chains.detect(TRON_HOT) == ("tron", "address"))
    check("detect: TRON hex form", chains.detect(hx) == ("tron", "address"))
    check("detect: XRP before SOL", chains.detect(XRP_HOT) == ("xrp", "address"))
    check("detect: BTC unchanged", chains.detect("bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h") == ("btc", "address"))
    check("detect: ETH unchanged", chains.detect("0x28C6c06298d514Db089934071355E5743bf21d60") == ("eth", "address"))

def api():
    a = AUTH
    r = httpx.get(U + f"/api/lookup?q={TRON_HOT}", auth=a, timeout=60)
    check("api: TRON lookup 200", r.status_code == 200, r.status_code)
    if r.status_code != 200:
        print("TRON body", r.text[:300]); return
    j = r.json()
    check("api: TRON chain+unit", j.get("chain") == "tron" and j.get("unit") == "TRX", (j.get("chain"), j.get("unit")))
    check("api: TRON balance present", j.get("balance") is not None, j.get("balance"))
    check("api: TRON edges/txs", (j.get("edges") or j.get("txs")), (len(j.get("edges") or []), len(j.get("txs") or [])))
    lab = (j.get("label") or {}).get("name") or ""
    check("api: TRON exchange label", "Binance" in lab, lab)
    # USDT-TRC20 edge somewhere
    units = {e.get("unit") for e in (j.get("edges") or [])}
    check("api: TRON has USDT and/or TRX edges", "USDT" in units or "TRX" in units, units)
    # prices
    check("api: TRX price wired", (j.get("price_usd") or 0) > 0, j.get("price_usd"))

    r = httpx.get(U + f"/api/lookup?q={XRP_HOT}", auth=a, timeout=60)
    check("api: XRP hot lookup 200", r.status_code == 200, r.status_code)
    j = r.json()
    check("api: XRP chain+unit", j.get("chain") == "xrp" and j.get("unit") == "XRP", (j.get("chain"), j.get("unit")))
    check("api: XRP label Binance", "Binance" in ((j.get("label") or {}).get("name") or ""), j.get("label"))
    # destination tags on some edges or txs
    has_tag = any(e.get("destination_tag") is not None for e in (j.get("edges") or [])) or any(
        t.get("destination_tag") is not None for t in (j.get("txs") or []))
    check("api: XRP destination_tag present on activity", has_tag, "tags on edges/txs")

    r = httpx.get(U + f"/api/lookup?q={XRP_HACK}", auth=a, timeout=60)
    j = r.json()
    check("api: XRP attacker labelled hack", (j.get("label") or {}).get("kind") == "hack" or "hack" in ((j.get("label") or {}).get("name") or "").lower(), j.get("label"))

    # watch check
    r = httpx.post(U + "/api/watch/check", json={"items": [
        {"id": "t", "address": TRON_HOT, "since": int(time.time()) - 86400 * 7},
        {"id": "x", "address": XRP_HACK, "since": int(time.time()) - 86400 * 7},
    ]}, auth=a, timeout=90)
    check("api: watch TRON+XRP 200", r.status_code == 200, r.status_code)
    if r.status_code == 200:
        res = r.json()["results"]
        check("api: watch TRON ok", res[0]["status"] == "ok", res[0])
        check("api: watch XRP ok", res[1]["status"] == "ok", res[1])

    # report checked in amain()


    # case deep link JSON
    r = httpx.get(U + "/static/cases/binance-2026-10-29.json", auth=a, timeout=30)
    check("case: binance JSON loads", r.status_code == 200)
    if r.status_code == 200:
        case = r.json()["case"]
        ids = {n["data"]["id"] for n in case["graph"]["nodes"]}
        check("case: includes TRON victim", TRON_HOT in ids)
        check("case: includes XRP stash", XRP_HACK in ids)

async def ui():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome",
                                    args=["--no-sandbox", "--disable-dev-shm-usage"])
        errs = []
        ctx = await b.new_context(viewport={"width": 1280, "height": 800},
                                  http_credentials={"username": AUTH[0], "password": AUTH[1]})
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + "/?q=" + TRON_HOT)
        await pg.wait_for_function("cy && cy.nodes().length>=1", timeout=120000)
        badge = await pg.inner_text("#chainBadge")
        check("ui: TRON badge", "TRX" in badge or "TRON" in badge.upper() or "T " in badge, badge)
        await pg.screenshot(path=str(H / "screenshot_tron_desktop.png"))
        # phone
        await ctx.close()
        ctx = await b.new_context(viewport={"width": 390, "height": 844},
                                  http_credentials={"username": AUTH[0], "password": AUTH[1]},
                                  is_mobile=True, user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)")
        pg = await ctx.new_page()
        await pg.goto(U + "/?addrs=" + TRON_HOT)
        await pg.wait_for_function("cy && cy.nodes().length>=1", timeout=120000)
        await pg.screenshot(path=str(H / "screenshot_tron_phone.png"))
        await pg.goto(U + "/?addrs=" + XRP_HACK)
        await pg.wait_for_function("cy && cy.nodes().length>=1", timeout=120000)
        badge = await pg.inner_text("#chainBadge")
        check("ui: XRP badge", "XRP" in badge or "✕" in badge, badge)
        await pg.screenshot(path=str(H / "screenshot_xrp_phone.png"))
        await ctx.close()
        # desktop XRP
        ctx = await b.new_context(viewport={"width": 1440, "height": 900},
                                  http_credentials={"username": AUTH[0], "password": AUTH[1]})
        pg = await ctx.new_page()
        await pg.goto(U + "/?addrs=" + XRP_HOT)
        await pg.wait_for_function("cy && cy.nodes().length>=1", timeout=120000)
        await pg.screenshot(path=str(H / "screenshot_xrp_desktop.png"))
        check("ui: no page errors", not errs, errs[:3])
        await b.close()

async def amain():
    if not AUTH[0] or not AUTH[1]:
        print("FAIL missing auth"); sys.exit(2)
    unit_addrutil()
    # report build (async)
    import report as _report, tempfile, subprocess
    payload = {"meta": {"ref": "TRON-XRP/1", "investigator": "Tester"},
               "case": {"name": "TRON/XRP smoke", "query": TRON_HOT, "notes": {"case": "uitest"}},
               "nodes": [{"id": TRON_HOT, "chain": "tron", "name": "Binance TRON", "kind": "exchange"},
                         {"id": XRP_HACK, "chain": "xrp", "name": "XRP stash", "kind": "hack"}],
               "edges": [{"source": TRON_HOT, "target": "TG5iBMQPrDzJJAUM8GMVBf1hRaJ1wvzsGi",
                          "amount": 612729468, "unit": "USDT", "tx": "a"*64, "time": 1793305365}]}
    pdf, info = await _report.build(payload)
    check("report: PDF with TRON/XRP nodes", pdf[:5] == b"%PDF-" and info.get("pages", 0) > 0, info)
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf); f.flush()
        txt = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
    check("report: methodology mentions TRON", "TRON" in txt or "TronGrid" in txt)
    check("report: methodology mentions XRP", "XRP" in txt or "rippled" in txt or "XRPL" in txt)
    api()
    try:
        await ui()
    except Exception as e:
        check("ui: playwright ran", False, type(e).__name__ + ": " + str(e)[:160])
    print(f"\n{len(ok)} passed, {len(bad)} failed")
    if bad: sys.exit(1)

if __name__ == "__main__":
    asyncio.run(amain())
