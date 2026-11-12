"""Test for v13 readable ETH DEX swap steps: direct swaps.decode() on real historical txs (verified on-chain via public RPC) + Playwright UI (desktop + phone) + PDF.
Password from env LP (never printed). Usage: LP=... python3 uitest_swaps.py   (CT_URL to target another server; SHOT=prefix for screenshots)"""
import asyncio, os, sys, subprocess, tempfile
from playwright.async_api import async_playwright
U = os.environ.get("CT_URL", "http://localhost:8090"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOT = os.environ.get("SHOT", "screenshot_v13_swap")
# real mainnet swaps (block times 11-12 Nov 2026), checked on Etherscan / public RPC receipts
CASES = [
    ("0xdd6976e19ebe5a968bf3086e97130c68c0f8bb60e540497fb0776c7989a23c61", "ETH", "USDT", "Uniswap V3", 2.46264981, True),     # Universal Router, WETH/USDT 0.05% pool
    ("0x3408cecb7499b9e34064360460306b9276fc1f1da0847a90f8bf608a10de89c6", "ETH", "ETHG", "Uniswap V2", 0.16737492353838604, True),
    ("0x37fc2059c1b5bb0ab6bca8689fd8ec1326e80da0f6ff41eb13aefb6c9209630f", "USDC", "THOR", "SushiSwap", 100.0, True),           # 2 hops USDC->WETH->THOR
    ("0xab0b62ee10deda3a129f9693d92beccc4d340d6e7a3a34ca2dca4dc616652945", "XPR", "ETH", "1inch", None, True),                  # 1inch v6 via Uniswap V3
    ("0x9fdb1e125efbb26133e7897917910aade98823004fd53b11d35151edc2f66856", "DAI", "USDT", "Curve", 10069.57108756, True),       # Curve 3pool
]
TRADER = "0x27de622cc44c55b53caF299eCedccdAB29aC98A8"   # sender of CASES[0]
ok = []; bad = []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:220], flush=True)
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush(); return " ".join(subprocess.run(["pdftotext", f.name, "-"], capture_output=True, text=True).stdout.split())
async def direct():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import chains, swaps
    await chains.ensure_prices()
    for h, s_, b_, venue, amt, dec in CASES:
        r = await swaps.decode(h)
        good = bool(r) and r["sold"][0]["symbol"] == s_ and r["bought"][0]["symbol"] == b_ and venue in r["venue"] and r["decoded"] == dec and r["text"].startswith("Swapped ")
        if good and amt is not None: good = abs(r["sold"][0]["amount"] - amt) < 1e-6 * max(1, amt)
        check(f"decode {h[:10]} {s_}->{b_} on {venue}", good, r and r["text"])
    r = await swaps.decode(CASES[2][0]); check("multi-hop route kept (2 SushiSwap hops via WETH)", r and len(r["hops"]) == 2 and r["hops"][0]["sym_out"] == "WETH", r and [x.get("sym_in") for x in r["hops"]])
    r = await swaps.decode(CASES[0][0]); check("pool fee + router named", r and r["hops"][0].get("fee") == "0.05%" and "Universal Router" in (r["router"]["name"] or ""), r and r["router"])
    n, e = swaps.graph(r); check("graph: one swap node + sold/bought legs", n[0]["kind"] == "swap" and n[0]["id"] == "tx:" + CASES[0][0] and [x["swap"]["leg"] for x in e] == ["sold", "bought"])
    nt = await swaps.decode("0x" + "0" * 63 + "1"); check("non-existent tx -> None", nt is None)
async def main():
    await direct()
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
        errs = []
        ctx = await b.new_context(viewport={"width": 1500, "height": 950}, http_credentials=AUTH, accept_downloads=True)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        # 1) tx deep link: the swap tx itself
        await pg.goto(U + "/?q=" + CASES[0][0]); await pg.wait_for_function("cy.nodes('[kind=\"swap\"]').length>0", timeout=120000); await pg.wait_for_timeout(1500)
        lbl = await pg.evaluate("cy.nodes('[kind=\"swap\"]')[0].data('lbl')"); check("tx link: swap node with readable label", "ETH → " in lbl and "USDT" in lbl and "Uniswap V3" in lbl, lbl)
        await pg.evaluate("cy.nodes('[kind=\"swap\"]')[0].emit('tap')"); await pg.wait_for_selector(".swapcard", timeout=5000)
        t = await pg.inner_text(".swapcard"); check("swap card: pair, venue, pool, decoded", "USDT" in t and "Uniswap V3" in t and "Hop 1" in t and "Decoded" in t, t[:200])
        await pg.screenshot(path=f"{SHOT}_tx_desktop.png")
        # 2) address lookup: candidates decoded automatically
        await pg.goto(U + "/?q=" + TRADER); await pg.wait_for_function("cy.nodes('[kind=\"swap\"]').length>0", timeout=150000); await pg.wait_for_timeout(2500)
        ns = await pg.evaluate("cy.nodes('[kind=\"swap\"]').length"); check("address lookup: swaps decoded into steps", ns >= 1, ns)
        legs = await pg.evaluate("cy.edges('[?swapleg]').map(e=>e.data('lbl'))"); check("swap legs drawn with amounts + USD", len(legs) >= 2 and any("$" in x for x in legs), legs[:4])
        # noise filter still works and does not remove decoded swap legs above the threshold
        hid = await pg.evaluate("cy.edges('.noise').filter(e=>e.data('swapleg')&&(e.data('usd')||0)>=5).length"); check("noise filter leaves real swap legs visible", hid == 0, hid)
        await pg.evaluate("cy.fit(cy.nodes('[kind=\"swap\"]').closedNeighborhood(),60)"); await pg.wait_for_timeout(500)
        await pg.screenshot(path=f"{SHOT}_desktop.png")
        # 3) PDF report has the readable step
        await pg.click("#rptbtn"); await pg.wait_for_selector("#rptm.on"); await pg.fill("#rptref", "OP-SWAP-UITEST")
        async with pg.expect_download(timeout=120000) as dl: await pg.click("#rptgo")
        d = await dl.value; t = pdftext(open(await d.path(), "rb").read())
        check("PDF: section 3.1 DEX swaps with readable step", "3.1 DEX swaps as readable steps" in t and "Swapped" in t and "Uniswap V3" in t and "Decoded (event logs)" in t)
        check("PDF: trail marks swap legs", "swap: sold" in t and "swap: bought" in t)
        await ctx.close()
        # phone
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2, http_credentials=AUTH)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + "/?q=" + CASES[0][0]); await pg.wait_for_function("cy.nodes('[kind=\"swap\"]').length>0", timeout=120000); await pg.wait_for_timeout(1500)
        await pg.evaluate("cy.nodes('[kind=\"swap\"]')[0].emit('tap')"); await pg.wait_for_selector(".swapcard", timeout=5000); await pg.wait_for_timeout(700)
        r = await pg.evaluate("(()=>{const c=document.querySelector('.swapcard').getBoundingClientRect();return{l:c.left,r:c.right,sw:document.documentElement.scrollWidth}})()")
        check("phone: swap card within viewport", r["l"] >= 0 and r["r"] <= 391 and r["sw"] <= 392, r)
        await pg.screenshot(path=f"{SHOT}_phone_graph.png")
        await pg.evaluate("document.querySelector('.swapcard').scrollIntoView()"); await pg.wait_for_timeout(500); await pg.screenshot(path=f"{SHOT}_phone.png")
        await ctx.close()
        check("no page errors", not errs, errs[:3])
        await b.close()
    print(f"\n{len(ok)} passed, {len(bad)} failed", bad)
    sys.exit(1 if bad else 0)
asyncio.run(main())
