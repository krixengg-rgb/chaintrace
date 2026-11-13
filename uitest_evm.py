"""v16 EVM chains test: BNB Smart Chain, Arbitrum One, Base, Polygon PoS, OP Mainnet (+ Ethereum L1 side of canonical bridges).
Every example is a real mainnet transaction; the expected values were read off the public explorers (bscscan via Binplorer, arbiscan,
basescan, polygonscan, explorer.optimism.io, eth.blockscout.com) and are re-checked live against them first (SKIP if an explorer is
unreachable). Then API, UI (desktop + phone), AutoTrace, loss calculator (BNB / POL / ETH-on-L2 pricing), PDF and evidence pack.
Password from env LP (never printed). Usage: LP=... python3 uitest_evm.py   (CT_URL for another server; SHOTS=0 to skip screenshots)"""
import asyncio, os, re, io, json, html, zipfile, subprocess, tempfile, time
import httpx
from playwright.async_api import async_playwright
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
H = os.path.dirname(os.path.abspath(__file__)); SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", "")
SHOT = lambda n: os.path.join(H, f"screenshot_v16_evm_{n}{TAG}.png")
BIN = "0x8894E0a0c962CB723c1976a4421c95949bE2D4E3"   # Binance hot wallet (same EOA active on all six EVM chains)
SANCT = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"  # OFAC SDN (Lazarus Group, Ronin exploiter) - Ethereum listing applies to the same key on every EVM chain
# chain -> swap example: (tx, trader, venue substring, sold (sym, amt), bought (sym, amt))
SWAPS = {
 "bsc": ("0x2824b1b16d3f9ec8c8315b611dbe05aea73603377ba7e7e2b62d661d71ed14c8", "0x53Fb8100C6a8B575Af1A19878D90A11D12451811", "PancakeSwap", ("BNB", 0.03841235667336442), (None, 2678.025465368519586359)),
 "arb": ("0x4cbd5e44fbbaf857d7ee2653598ab28c9b487df188818559e8c686d38a9b6a7f", "0xC06ebbefD94032B85424D51906e2A335EFAe264B", "Camelot", ("WETH", 0.005), ("USDC", 9.726219)),
 "base": ("0xc2ad80071f82884e7af28d1b414b3526c2ca1f75914ce7fdb8458371fac2e4c9", "0x053B0158", "Aerodrome", (None, 36439.21), ("USDT", 62.08)),
 "polygon": ("0xe0b3228c22a05a481ce1de471ea75808aae398b5a6086496ea359b95b3407f49", "0xe7FeE54F99dD5ee21b7e6c5bF3E664219812A40d", "QuickSwap", ("LGNS", 0.38), ("DAI", 0.058747716)),
 "op": ("0xb3f2e2e2ee9e0cbcb76bf34c74a2c9252280639e7c5f197043e2ec9e65d81193", "0x08311a959503ACd054430B5dca5A74101Fadc47B", "Velodrome", ("STG", 150.08417411331772), ("USDC", 20.169723)),
}
# native-coin transfers (chain, tx, from, to, amount, unit)
NATIVE = [("bsc", "0x7ab00eb86867f4f4065e96bb139ee81015671ffabcce3155779d1c46ce44434b", "0xcab097ac9c015ef98e8369c030dfe442fc798aca", "0x1f54ec845c645c0085e10d3f00a531dd5a53c268", 1.8268219892443176, "BNB"),
          ("polygon", "0xb720cd90fbe24c0ef61bd5ddc5f774b5c288e8c88ffe5cfbfe3a867ab05a7c94", "0x28f40c939ad5cbab524819f2ecd62cb60260eb30", "0xf8fa10d8aba5c5fb06dbe0866136c0117c39fdb3", 100.0, "POL"),
          ("arb", "0x2dd1745bd9bd82bfd15b8911d8bacf7574046a8cbd11c9d4dd52b17952040f72", "0xb90d6929d0fcdaa924e5589a1b678a2b37fd4239", "0xa7fc6929d0fcdaa924e5589a1b678a2b37fd3128", 0.001, "ETH")]
# canonical bridges: (query tx, query chain, bridge substring, dst chain, dst tx, dst address, amount, unit)
BRIDGES = [("0x819acb1d9d59e84507f91df65173babd7802707da1f0e9cfe39bd012f8e8221d", None, "Arbitrum One canonical bridge (Inbox.depositEth)", "arb",
            "0x2dd1745bd9bd82bfd15b8911d8bacf7574046a8cbd11c9d4dd52b17952040f72", "0xa7fc6929d0fcdaa924e5589a1b678a2b37fd3128", 0.001, "ETH"),
           ("0x3e73ec13aadb6e5ce0f90555fa46ac15bebebbefa3bd63466f1260b02a7cb9e8", None, "Base canonical bridge (OptimismPortal)", "base",
            "0xc949c53eae73370597b8ac9e8cca1df7589f467742d5e0519af528c243c665ce", "0xaeb1e2fd27ef697b648a14ac94ff8e245294f31f", 50.0, "USDT"),
           ("0xc949c53eae73370597b8ac9e8cca1df7589f467742d5e0519af528c243c665ce", "base", "Base canonical bridge (OptimismPortal)", "base",
            "0xc949c53eae73370597b8ac9e8cca1df7589f467742d5e0519af528c243c665ce", "0xaeb1e2fd27ef697b648a14ac94ff8e245294f31f", 50.0, "USDT"),
           ("0x6388277813dccce8c33470177ef59a2fc57c705eda0ff55cfae08e45142117cf", "op", "OP Mainnet canonical bridge (withdrawal)", "eth",
            "0xdd53377d0161703b71068391f19f4a143423ad7e437b7bfe9c3f48b2272736c4", "0x85faa6c1f2450b9caea300838981c2e6e120c35c", 30556.192554, "USDT"),
           ("0x4a68983673bd80b7ff32cdc13c5eea8227353fa146f24c5b5dde951ad3a1c018", "arb", "Arbitrum One canonical bridge (withdrawal)", "eth",
            "0x3f550f877f4cb4f95aba557cc2cd8f73daebcc06816a64817a1bf31fd9b44b22", "0x300afbe08ee4619ec93524f9255ce59a013a5b63", 0.009, "ETH")]
ok, bad, skip = [], [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
def skipped(name, why): skip.append(name); print("SKIP " + name, why, flush=True)
near = lambda a, b, tol=1e-6: a is not None and b is not None and abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))
def page_text(url):
    s = subprocess.run(["curl", "-s", "-m", "25", "-A", "Mozilla/5.0 (X11; Linux x86_64) Chrome/130", url], capture_output=True, text=True).stdout
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)))) if "Just a moment" not in s else ""
def jget(url):
    try: return httpx.get(url, timeout=25, headers={"User-Agent": "chaintrace-uitest"}).json()
    except Exception: return None

def explorers():
    """the pinned values really are what the public explorers show"""
    t = page_text("https://arbiscan.io/tx/" + SWAPS["arb"][0])
    if t: check("explorer: arbiscan Camelot swap sender", SWAPS["arb"][1] in t, t[:0])
    else: skipped("explorer: arbiscan", "unreachable")
    for c, url, need in [("base", "https://basescan.org/tx/" + SWAPS["base"][0], ["Swap 36,439.21", "for 62.08 USDT", "Aerodrome"]),
                         ("polygon", "https://polygonscan.com/tx/" + SWAPS["polygon"][0], ["Swap 0.38 LGNS", "for 0.058747716 DAI", "QuickSwap"]),
                         ("polygon", "https://polygonscan.com/tx/" + NATIVE[1][1], ["Transfer 100 POL"]),
                         ("arb", "https://arbiscan.io/tx/" + NATIVE[2][1], ["Value: 0 . 001 ETH", "ArbitrumDepositTxType"]),
                         ("base", "https://basescan.org/tx/" + BRIDGES[1][4], ["Transfer 50 USDT", "0xAeb1e2fd"])]:
        t = page_text(url)
        if t: check(f"explorer: {url.split('/')[2]} {url[-10:]} shows {need}", all(n in t for n in need), [n for n in need if n not in t])
        else: skipped(f"explorer: {url.split('/')[2]}", "unreachable / bot wall")
    j = jget(f"https://api.binplorer.com/getTxInfo/{SWAPS['bsc'][0]}?apiKey=freekey")
    if j: check("explorer: Binplorer BSC swap value + token received", near(j.get("value"), 0.03841235667336442) and any(int(o["value"]) == 2678025465368519586359 for o in j.get("operations", [])))
    else: skipped("explorer: Binplorer", "unreachable")
    j = jget(f"https://explorer.optimism.io/api/v2/transactions/{SWAPS['op'][0]}/token-transfers")
    if j: check("explorer: OP Blockscout Velodrome transfers 150.084 STG / 20.169723 USDC",
                any(x["token"]["symbol"] == "STG" and near(int(x["total"]["value"]) / 1e18, 150.08417411331772) for x in j["items"]) and any(x["token"]["symbol"] == "USDC" and int(x["total"]["value"]) == 20169723 for x in j["items"]))
    else: skipped("explorer: OP Blockscout", "unreachable")
    j = jget(f"https://eth.blockscout.com/api/v2/transactions/{BRIDGES[3][4]}/token-transfers")
    if j: check("explorer: L1 finalize of OP withdrawal paid 30556.192554 USDT", any(int(x["total"]["value"]) == 30556192554 and x["to"]["hash"].lower() == BRIDGES[3][5] for x in j["items"]))
    j = jget(f"https://eth.blockscout.com/api/v2/transactions/{BRIDGES[4][4]}/internal-transactions")
    if j: check("explorer: L1 Outbox execution paid 0.009 ETH", any(int(x["value"]) == 9 * 10 ** 15 and x["to"]["hash"].lower() == BRIDGES[4][5] for x in j["items"]))

def api(cl):
    j = cl.get(U + "/api/evm/chains").json()
    check("api: /api/evm/chains lists 6 EVM chains", [c["chain"] for c in j["chains"]] == ["eth", "bsc", "arb", "base", "polygon", "op"], [(c["chain"], c["history_source"]) for c in j["chains"]])
    j = cl.get(U + "/api/evm/scan", params={"addr": BIN}).json()
    check("api: all-EVM scan finds the Binance EOA active on every chain", set(j["active"]) >= {"eth", "bsc", "arb", "base", "polygon", "op"}, j["active"])
    bsc = next(c for c in j["chains"] if c["chain"] == "bsc")
    check("api: scan BSC balance in BNB with USD + outgoing tx count", bsc["unit"] == "BNB" and bsc["balance"] is not None and bsc["balance_usd"] and bsc["nonce"] > 1000000, bsc)
    for c, (h, *_r) in SWAPS.items():
        j = cl.get(U + "/api/evm/detect", params={"tx": h}).json()
        check(f"api: tx-hash chain detection {h[:10]} -> {c}", j.get("chains") == [c] or j.get("found_on") == [c] or (isinstance(j, dict) and c in str(j) and len([x for x in ("eth", "bsc", "arb", "base", "polygon", "op") if f"'{x}'" in str(j)]) == 1), j)
    for c, h, f, t, amt, unit in NATIVE:
        j = cl.get(U + "/api/lookup", params={"q": h}).json()   # Auto mode: chain found by detection
        es = [e for e in j.get("edges", []) if near(e.get("amount"), amt) and (f in e["source"].lower() or t in e["target"].lower())]
        check(f"api: {c} tx (auto-detected) {amt:g} {unit} {f[:8]}->{t[:8]} priced", j.get("chain") == c and len(es) >= 2 and all(e.get("unit") == unit for e in es)
              and all(e["source"].startswith((c + ":", "tx:")) and e["target"].startswith((c + ":", "tx:")) for e in es) and any(e.get("usd") for e in es), (j.get("chain"), j.get("found_on"), [(e["source"][:16], e["amount"], e.get("unit")) for e in j.get("edges", [])][:4]))
    for c, (h, tr, venue, sold, bought) in SWAPS.items():
        j = cl.post(U + "/api/eth/swaps", json={"txs": [h], "chain": c}).json()
        s = (j.get("swaps") or [None])[0]
        good = bool(s) and venue in s["venue"] and s["chain"] == c and s["trader"].lower().startswith(tr.lower()) \
            and any((sold[0] is None or x["symbol"] == sold[0]) and near(x["amount"], sold[1], 1e-4) for x in s["sold"]) \
            and any((bought[0] is None or x["symbol"] == bought[0]) and near(x["amount"], bought[1], 1e-4) for x in s["bought"])
        check(f"api: {c} swap decoded on {venue}", good, s and s["text"])
    for c in ("bsc", "op"):
        j = cl.get(U + "/api/lookup", params={"q": f"{c}:{BIN}"}).json()
        L = j.get("label") or {}
        check(f"api: {c}:Binance address lookup (prefixed id, label = exchange)", j.get("chain") == c and j.get("address", "").startswith(c + ":") and L.get("kind") == "exchange" and "Binance" in (L.get("name") or ""),
              (j.get("chain"), j.get("address"), L.get("name"), L.get("kind"), (j.get("warnings") or [""])[0][:80]))
    j = cl.get(U + "/api/lookup", params={"q": "base:0x28C6c06298d514Db089934071355E5743bf21d60"}).json(); L = j.get("label") or {}
    check("api: base: Ethereum label carried over as a lead (marked, lower confidence)", "(Ethereum label)" in (L.get("name") or "") and L.get("kind") == "exchange" and (L.get("confidence") or 1) < 0.8
          and all("(Ethereum, same address)" in x["source"] for x in L.get("sources") or [{"source": ""}]), (L.get("name"), L.get("confidence")))
    # loss calculator API: POL and ETH-on-Arbitrum valued with on-the-day prices
    for c, h, f, t, amt, unit in NATIVE[1:]:
        g = cl.get(U + "/api/lookup", params={"q": f"{c}:{h}"}).json()
        vic = next(n["id"] for n in g["nodes"] if f in n["id"].lower()); sus = next(n["id"] for n in g["nodes"] if t in n["id"].lower())
        r = cl.post(U + "/api/loss", json={"nodes": g["nodes"], "edges": g["edges"], "loss": {"victims": [vic], "suspect": sus, "method": "proportional"}}, timeout=120)
        T = {x["asset"]: x for x in (r.json().get("totals") or [])} if r.status_code == 200 else {}
        check(f"api: loss calculator {c}: {amt:g} {unit} lost, valued on the day", unit in T and near(T[unit]["amount"], amt) and T[unit].get("usd_then"), T or r.text[:200])
    j = cl.get(U + "/api/lookup", params={"q": BIN, "chain": "arb"}).json()
    check("api: chain= hint routes a bare 0x address to Arbitrum", j.get("chain") == "arb" and j.get("address", "").startswith("arb:"), (j.get("chain"), j.get("address")))
    for c in ("bsc", "base", "polygon"):
        j = cl.get(U + "/api/screen", params={"addr": f"{c}:{SANCT}"}).json()
        check(f"api: sanctions screening on {c} (OFAC listing of the same key)", j.get("verdict") == "sanctioned" and any("lazarus" in (x.get("entry") or "").lower() for x in j.get("sanctions") or []), (j.get("verdict"), [x.get("entry") for x in j.get("sanctions") or []][:2]))
    for h, qc, br, dc, dtx, da, amt, unit in BRIDGES:
        j = cl.get(U + "/api/bridge", params={"q": h, **({"chain": qc} if qc else {})}, timeout=120).json()
        m = [x for x in j.get("matches", []) if br in x["bridge"]]
        m0 = m[0] if m else {}
        check(f"api: bridge {br} {h[:10]} -> {dc} {dtx[:10]} {amt:g} {unit} (deterministic)", m0 and m0["method"] == "deterministic" and (m0["dst"]["tx"] or "").lower() == dtx and (m0["dst"]["address"] or "").lower() == da
              and near(m0["dst"]["amount"], amt) and m0["dst"]["unit"] == unit and m0["status"] == "completed", m0 and (m0["status"], m0["dst"]["tx"], m0["dst"]["amount"], m0["evidence"]) or [x["bridge"] for x in j.get("matches", [])])
    # AutoTrace on Polygon from the POL sender
    jb = cl.post(U + "/api/autotrace", params={"q": "polygon:" + NATIVE[1][2], "max_hops": 2, "max_nodes": 40, "max_secs": 60, "min_usd": 1}).json()
    t0 = time.time(); r = {}
    while time.time() - t0 < 100:
        r = cl.get(U + f"/api/trace/{jb['job']}").json()
        if r.get("status") in ("done", "error", "stopped", "timeout"): break
        time.sleep(3)
    ns = r.get("nodes") or (r.get("result") or {}).get("nodes") or []
    check("api: AutoTrace runs on Polygon with prefixed ids", r.get("status") == "done" and len(ns) >= 2 and all(n["id"].startswith(("polygon:", "tx:")) or n.get("grp") or n.get("meta") or ":" in n["id"] for n in ns), (r.get("status"), len(ns), [n["id"][:20] for n in ns][:4], r.get("error")))

async def ui(b):
    errs = []
    ctx = await b.new_context(viewport={"width": 1500, "height": 950}, http_credentials=AUTH, accept_downloads=True)
    pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    # 1 deep link with chain prefix: selector follows, badge, explorer link, chain colour
    await pg.goto(U + f"/?q=bsc:{BIN}"); await pg.wait_for_function("cy.nodes().length>=5", timeout=90000); await pg.wait_for_timeout(1500)
    check("UI: bsc: deep link sets selector=BSC and badge", await pg.input_value("#chainSel") == "bsc" and "BSC" in await pg.inner_text("#chainBadge"))
    check("UI: BSC explorer link is bscscan", await pg.evaluate("[...document.querySelectorAll('#side a')].some(a=>a.href.startsWith('https://bscscan.com/address/'))"))
    check("UI: BSC nodes carry the BSC chain colour + legend", await pg.evaluate("cy.nodes('[cc]').length>=3 && cy.nodes('[cc]')[0].data('cc')==='#f3ba2f'") and "BNB Smart Chain" in await pg.inner_text("#legend"))
    if SHOTS: await pg.screenshot(path=SHOT("bsc_desktop"))
    # 2 Auto mode bare 0x: Ethereum + "also active on"
    await pg.goto(U + f"/?q={BIN}"); await pg.wait_for_selector(".evmalso", timeout=90000)
    al = await pg.inner_text(".evmalso")
    check("UI: Auto mode lookup offers the other active chains", all(x in al for x in ("BSC", "ARB", "BASE", "POL", "OP")), al)
    await pg.click(".evmalso button:has-text('OP')"); await pg.wait_for_function("cur&&cur.chain==='op'", timeout=90000)
    check("UI: one tap switches to OP Mainnet (selector + prefixed query)", await pg.input_value("#chainSel") == "op" and (await pg.input_value("#q")).startswith("op:0x"))
    # 3 All EVM scan
    await pg.goto(U + f"/?q={BIN}&chain=all"); await pg.wait_for_selector(".evmscan", timeout=90000)
    t = await pg.inner_text(".evmscan")
    check("UI: All-EVM scan card lists 6 chains with balances", t.count("active") >= 6 and "BNB" in t and "POL" in t, t[:200])
    check("UI: scan graph has one node per active chain", await pg.evaluate("cy.nodes().length") == 6)
    if SHOTS: await pg.screenshot(path=SHOT("allscan_desktop"))
    # 4 swap card on Base (Aerodrome) via tx lookup
    await pg.goto(U + f"/?q=base:{SWAPS['base'][0]}"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000)
    await pg.wait_for_timeout(1500); await pg.evaluate(f"cy.getElementById('tx:{SWAPS['base'][0]}').emit('tap')")
    try: await pg.wait_for_selector(".swapcard", timeout=60000); sc = await pg.inner_text(".swapcard")
    except Exception: sc = ""
    check("UI: Base swap card (Aerodrome, basescan link)", "Aerodrome" in sc and await pg.evaluate("[...document.querySelectorAll('.swapcard a')].some(a=>a.href.startsWith('https://basescan.org/tx/'))"), sc[:160])
    if SHOTS: await pg.screenshot(path=SHOT("base_swap_desktop"))
    # 5 bridge: L1 deposit -> Arbitrum, expand the L2 side
    await pg.goto(U + f"/?q={BRIDGES[0][0]}"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000)
    await pg.evaluate(f"(async()=>{{const j=await ctBridgeApi('{BRIDGES[0][0]}',null,true);document.getElementById('det').innerHTML=ctBridgeList(j,'test');ctBridgeAdd(0)}})()")
    try:
        await pg.wait_for_function("cy.edges('[xchain]').length>=1", timeout=60000)
        xe = await pg.evaluate("cy.edges('[xchain]').map(e=>[e.target().id(),e.data('xchain')&&1])")
    except Exception: xe = []
    check("UI: canonical Arbitrum deposit drawn as a cross-chain hop to arb:0xA7Fc…", any(str(x[0]).lower() in ("arb:" + BRIDGES[0][5], "tx:" + BRIDGES[0][4]) or BRIDGES[0][5] in str(x[0]).lower() for x in xe), xe)
    await pg.wait_for_timeout(2500); await pg.evaluate("cy.fit(undefined,70)")
    if SHOTS: await pg.screenshot(path=SHOT("bridge_desktop"))
    # 6 loss calculator: BNB pricing on the BSC swap payment, then PDF + evidence pack
    await pg.goto(U + f"/?q=bsc:{NATIVE[0][1]}"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000); await pg.wait_for_timeout(1500)
    trader = await pg.evaluate(f"cy.nodes().map(n=>n.id()).find(i=>i.toLowerCase().includes('{NATIVE[0][2]}'))")
    router = await pg.evaluate(f"cy.nodes().map(n=>n.id()).find(i=>i.toLowerCase().includes('{NATIVE[0][3]}'))")
    check("UI: BSC transfer graph has sender and recipient", bool(trader and router), (trader, router))
    if trader and router:
        await pg.click("#lossbtn"); await pg.wait_for_selector("#lossm.on")
        await pg.fill("#lossv", trader); await pg.fill("#losst", ""); await pg.fill("#losss", router); await pg.click("#lossgo")
        await pg.wait_for_function("window.CT_LOSS_LAST||document.querySelector('#lossres .warnbox')", timeout=120000)
        j = await pg.evaluate("window.CT_LOSS_LAST||null")
        T = {x["asset"]: x for x in (j or {}).get("totals", [])}
        check("UI: loss calculator values the BNB payment (on-the-day USD)", "BNB" in T and near(T["BNB"]["amount"], NATIVE[0][4], 1e-6) and T["BNB"].get("usd_then"), T or (await pg.inner_text("#lossres"))[:200])
        await pg.evaluate("ctLossClose()")
    await pg.click("#rptbtn"); await pg.wait_for_selector("#rptm.on"); await pg.fill("#rptref", "EVM/UITEST/1")
    async with pg.expect_download(timeout=150000) as dl: await pg.click("#rptgo")
    pdf = open(await (await dl.value).path(), "rb").read()
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf); f.flush(); txt = " ".join(subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout.split())
    check("PDF: BSC case report names BNB Smart Chain, BNB amounts and bscscan links", ("BNB Smart Chain" in txt or "BSC" in txt) and "BNB" in txt and "bscscan.com" in txt, txt[:200])
    async with pg.expect_download(timeout=150000) as dl: await pg.click("#packgo")
    z = zipfile.ZipFile(io.BytesIO(open(await (await dl.value).path(), "rb").read())); names = z.namelist()
    lc = [n for n in names if n.endswith("victim_loss_summary.csv")]; sums = [n for n in names if n.endswith("SHA256SUMS.txt")]
    lct = z.read(lc[0]).decode("utf-8", "ignore") if lc else ""
    check("evidence pack: report PDF + BSC victim-loss CSV (tx hash, BNB) listed in SHA256SUMS", lc and sums and NATIVE[0][1] in lct.lower() and "BNB" in lct
          and all(x.split("/")[-1] in z.read(sums[0]).decode() for x in lc + [n for n in names if n.endswith(".pdf")]), names)
    await ctx.close()
    # 7 phone width: Polygon tx deep link + all-EVM scan
    ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, http_credentials=AUTH)
    pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(U + f"/?q={BIN}&chain=all"); await pg.wait_for_selector(".evmscan", timeout=90000); await pg.wait_for_timeout(800)
    r = await pg.evaluate("(()=>{const c=document.querySelector('.evmscan').getBoundingClientRect();return{l:c.left,r:c.right,sw:document.documentElement.scrollWidth}})()")
    check("phone: All-EVM scan card fits the viewport", r["l"] >= 0 and r["r"] <= 392 and r["sw"] <= 392, r)
    s = await pg.evaluate("(()=>{const s=document.querySelector('#chainSel').getBoundingClientRect();return{l:s.left,r:s.right}})()")
    check("phone: chain selector visible inside the viewport", s["l"] >= 0 and s["r"] <= 390, s)
    if SHOTS: await pg.screenshot(path=SHOT("allscan_phone"))
    await pg.goto(U + f"/?q=polygon:{NATIVE[1][1]}"); await pg.wait_for_function("cy.nodes().length>=2", timeout=90000); await pg.wait_for_timeout(1000)
    sd = await pg.inner_text("#side"); ed = await pg.evaluate("cy.edges().map(e=>[(e.data('info')||{}).amount??e.data('amount'),(e.data('info')||{}).unit??e.data('unit')])")
    check("phone: Polygon tx panel (POL badge, polygonscan) + 100 POL flow on the graph", "POL" in sd and any(x[0] == 100 and x[1] == "POL" for x in ed), (sd[:80], ed[:4]))
    if SHOTS: await pg.screenshot(path=SHOT("polygon_phone"))
    await ctx.close()
    check("UI: no page errors", not errs, errs[:3])

async def main():
    explorers()
    with httpx.Client(auth=(AUTH["username"], AUTH["password"]), timeout=90) as cl: api(cl)
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
        try: await ui(b)
        finally: await b.close()
    print(f"\n{len(ok)} passed, {len(bad)} failed, {len(skip)} skipped", bad)
asyncio.run(main())
