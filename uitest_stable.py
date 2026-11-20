"""v27 USDT / USDC across chains (stable.py, static/stable.js, CCTP in bridges.py, AutoTrace stables-only). Real mainnet data only:
- official token contracts each cite the issuer page; look-alike contracts are not official;
- blacklist read on-chain: Lazarus Group (OFAC) ETH address blacklisted by Tether USDT + Circle USDC; Binance 14 not; TRON OFAC address blacklisted with frozen USDT;
- Circle CCTP: real ETH -> Arbitrum burn matched to its mint (Circle attestation + mint re-checked on Arbitrum); reverse lookup from the mint tx;
- AutoTrace stables-only follows the CCTP hop deterministically; TRC-20 USDT flows summarised;
- UI (desktop + phone): deep link &stable=1 shows BLACKLISTED + frozen balance; stablecoin-only graph filter; AutoTrace '💵 stables' with the CCTP hop.
Password from env LP (never printed). Usage: LP=... python3 uitest_stable.py   (CT_URL, SHOT_TAG=_live, ENGINE=0, SHOTS=0)"""
import asyncio, os, sys, time
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v27_stable_{n}{TAG}.png")
LAZ = "0x08723392ed15743cc38513c4925f5e6be5c17243"        # Lazarus Group (OFAC SDN)
BIN8 = "0xF977814e90dA44bFA03b6295A0616a897441aceC"   # Binance 8 hot wallet (not blacklisted when written)
TRON_BL = "TA3941uFAvmVibSkQ6fMJXxmaSNovX86mz"           # OFAC SDN (Cheil Credit Bank) TRON address
BURN = "0x8d44f3d43b2f3ed4494b2d2e0e8e7175177191d0b1e2fa65eb8b91e27fa01d44"   # CCTP V1 burn, Ethereum -> Arbitrum, 11 USDC
MINT = "0xe8a50286a54d3e22e07e323e2680b54c4cbf85a246816e0615c2c14fd9e3fe8a"   # its mint on Arbitrum
CCTP_USER = "0xc435249D0e837efa5eb431ad74C9Fa8889f2c905"
TC_DEP = "0x838eF3eA11397b2be1892cd6bC2F8234b78f6135"    # mixed ETH + USDT + USDC history
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)

async def engine():
    import stable
    check("official contracts: each cites an http source; ETH USDT/USDC + TRON USDT + SOL present",
          all(v[3].startswith("http") for v in stable.OFFICIAL.values()) and stable.official("eth", "0xdAC17F958D2ee523a2206206994597C13D831ec7") and stable.official("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t") and stable.official("sol", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"))
    check("a look-alike 'USDT' contract is not official", stable.official("eth", "0x0000000000000000000000000000000000000001") is None and stable.is_stable_unit("USDT0") and not stable.is_stable_unit("ETH"))
    bl = {b["symbol"]: b for b in await stable.blacklist("eth", LAZ)}
    check("Lazarus Group: blacklisted by Tether (isBlackListed + getBlackListStatus) and Circle (isBlacklisted)", bl["USDT"]["blacklisted"] and all(bl["USDT"]["calls"].values()) and bl["USDC"]["blacklisted"], {k: v["calls"] for k, v in bl.items()})
    bl = await stable.blacklist("eth", BIN8)
    check("Binance 8: not blacklisted (control)", all(b["blacklisted"] is False for b in bl))
    bl = await stable.blacklist("tron", TRON_BL)
    check("TRON OFAC address: Tether USDT blacklisted with frozen balance read on-chain", bl[0]["blacklisted"] and (bl[0]["frozen_balance"] or 0) > 0, (bl[0]["calls"], bl[0]["frozen_balance"]))
    ms = await stable.cctp_tx(BURN)
    m = ms[0] if ms else {}
    check("CCTP burn -> mint: deterministic, Ethereum -> Arbitrum, mint tx from Circle, re-checked on-chain", m and m["method"] == "deterministic" and m["confidence"] == 0.99 and m["src"]["chain"] == "eth" and m["dst"]["chain"] == "arb" and m["dst"]["tx"].lower() == MINT and m["src"]["amount"] == 11.0, m and (m["dst"]["tx"], m["notes"]))
    check("CCTP recipient = mint recipient from Circle's attested message", m and m["dst"]["address"].lower() == CCTP_USER.lower())
    ms = await stable.cctp_tx(MINT)
    check("CCTP reverse: from the Arbitrum mint tx back to the Ethereum burn", ms and (ms[0]["src"]["tx"] or "").lower() == BURN, ms and ms[0]["src"]["tx"])

def api():
    cl = httpx.Client(auth=(AUTH["username"], AUTH["password"]), timeout=120)
    j = cl.get(U + "/api/stable", params={"q": TRON_BL}).json()
    f = (j.get("flows") or [{}])[0]
    check("api: TRON address -> blacklisted + TRC-20 USDT flows (official contract)", j["blacklist"][0]["blacklisted"] and f.get("unit") == "USDT" and f.get("official") is True and f.get("in", 0) > 0, (f.get("unit"), f.get("in")))
    time.sleep(4)
    j = cl.get(U + "/api/bridge", params={"tx": BURN}).json()
    check("api: bridge matcher includes the Circle CCTP match", any(x["bridge"] == "Circle CCTP" and x["method"] == "deterministic" for x in j.get("matches", [])), [x["bridge"] for x in j.get("matches", [])])
    j = cl.get(U + "/api/cctp", params={"tx": BURN}).json()
    check("api: /api/cctp", j["matches"] and j["matches"][0]["dst"]["tx"].lower() == MINT)
    time.sleep(4)
    r = cl.post(U + "/api/autotrace", params={"q": CCTP_USER, "direction": "forward", "max_hops": 2, "min_usd": 5, "topk": 4, "follow_bridges": "true", "stables": "true", "max_secs": 60}).json()
    for _ in range(40):
        time.sleep(4); t = cl.get(U + f"/api/trace/{r['job']}").json()
        if t["status"] not in ("queued", "running"): break
    units = {(e.get("unit") or "").rstrip("⇄") for e in t["edges"]}
    check("api: AutoTrace stables-only keeps only USDT/USDC and follows the CCTP hop to Arbitrum", units and units <= {"USDC", "USDT", "USDT0"} and any(b["bridge"] == "Circle CCTP" and b["dst"]["chain"] == "arb" for b in t.get("bridges", [])), (units, [b["bridge"] for b in t.get("bridges", [])]))

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w, h, tag in ((1600, 950, "desktop"), (390, 844, "phone")):
            ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials=AUTH)
            pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U + f"/?q={TRON_BL}&stable=1"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000)
            await pg.wait_for_function("window.CT_LAST_STABLE&&document.querySelector('#stcard .bl')", timeout=60000)
            txt = await pg.inner_text("#stcard")
            check(f"ui {tag}: deep link &stable=1 -> USDT BLACKLISTED with frozen balance + flows", "BLACKLISTED" in txt and "frozen" in txt and "USDT" in txt and "official contract" in txt, txt[:160])
            check(f"ui {tag}: Stablecoins button on the address card", await pg.query_selector(".stbtn") is not None)
            await pg.evaluate("document.getElementById('stcard').scrollIntoView()")
            if SHOTS: await pg.screenshot(path=SHOT(tag))
            if tag == "desktop":
                await pg.goto(U + f"/?q={TC_DEP}&stable=1"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000)
                await pg.wait_for_function("window.CT_LAST_STABLE&&document.querySelector('#stbtog')", timeout=60000)
                await pg.wait_for_timeout(2500); await pg.click("#stbtog"); await pg.wait_for_timeout(1500)
                st = await pg.evaluate("(()=>{const v=cy.edges().filter(e=>!e.data('meta')&&!e.hasClass('stbhide'));return {hid:cy.edges('.stbhide').length,vis:v.map(e=>(e.data('info')||{}).unit)}})()")
                check("ui: stablecoin-only filter hides non-stable edges, keeps USDT/USDC", st["hid"] > 0 and st["vis"] and all(u in ("USDT", "USDC") for u in st["vis"]), (st["hid"], set(st["vis"])))
                await pg.goto(U + f"/?q={CCTP_USER}"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000)
                await pg.evaluate("$('amax').value='3';$('amin').value='5';$('stbonly').checked=true;$('xfollow').checked=true")
                await pg.click("#autobtn"); await pg.wait_for_function("[...document.querySelectorAll('.xcard')].some(x=>/Circle CCTP/.test(x.innerText))", timeout=150000)
                xt = await pg.evaluate("[...document.querySelectorAll('.xcard')].map(x=>x.innerText).join(' ')")
                check("ui: AutoTrace '💵 stables' shows the deterministic CCTP hop Ethereum -> Arbitrum", "Circle CCTP" in xt and "det" in xt, xt[:160])
                await pg.wait_for_timeout(3000); await pg.evaluate("cy.fit(undefined,40);[...document.querySelectorAll('.xcard')].pop().scrollIntoView()")
                if SHOTS: await pg.screenshot(path=SHOT("autotrace_cctp_desktop"))
            check(f"ui {tag}: no JS errors", not errs, errs[:2]); await ctx.close()
        await b.close()

if __name__ == "__main__":
    os.environ.setdefault("CHAINTRACE_CACHE", "/workspace/scratch/uitest_stable_cache.sqlite")
    if os.environ.get("ENGINE", "1") != "0": asyncio.run(engine())
    if os.environ.get("API", "1") != "0": api()
    asyncio.run(ui())
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
