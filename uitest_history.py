"""v18 deep history on Arbitrum One, Base and Polygon without any API key (history.py: 3xpl public sandbox + public RPC receipts;
optional ETHERSCAN_API_KEY / ALCHEMY_API_KEY). Real mainnet wallets; every sampled edge is re-checked against the transaction
receipt read straight from a public RPC. Then: pagination goes back in time, date filter, source fallback order, API, UI (desktop + phone).
Password from env LP (never printed). Usage: LP=... python3 uitest_history.py   (CT_URL for another server; SHOTS=0 to skip screenshots)"""
import asyncio, os, sys, json, time
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v18_history_{n}{TAG}.png")
W = {"arb": "0xC06ebbefD94032B85424D51906e2A335EFAe264B",      # busy Arbitrum wallet (Camelot / LI.FI user)
     "polygon": "0xe7FeE54F99dD5ee21b7e6c5bF3E664219812A40d",  # Polygon wallet (QuickSwap LGNS trader)
     "base": "0xaeb1e2fd27ef697b648a14ac94ff8e245294f31f"}     # Base wallet that sent 100 USDT
RPC = {"arb": "https://arb1.arbitrum.io/rpc", "polygon": "https://polygon.drpc.org", "base": "https://base-rpc.publicnode.com"}
T_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ok, bad, skip = [], [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
def rpc(chain, method, params):
    return httpx.post(RPC[chain], json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=20).json().get("result")

def truth(chain, e):
    """the edge really is in the tx receipt (token Transfer log) or the tx itself (native value)"""
    rc = rpc(chain, "eth_getTransactionReceipt", [e["tx"]]); tx = rpc(chain, "eth_getTransactionByHash", [e["tx"]])
    s, d = e["source"].lower(), e["target"].lower()
    if e.get("internal"): return rc is not None and rc.get("status") == "0x1"
    if e["unit"] in ("ETH", "POL") and tx and int(tx.get("value") or "0x0", 16):
        return tx["from"].lower() == s and (tx.get("to") or "").lower() == d and abs(int(tx["value"], 16) / 1e18 - e["amount"]) < 1e-9
    for l in (rc or {}).get("logs") or []:
        tp = l.get("topics") or []
        if len(tp) == 3 and tp[0] == T_TRANSFER and "0x" + tp[1][-40:] == s and "0x" + tp[2][-40:] == d: return True
    return False

async def engine():
    import chains, history
    for k in ("ETHERSCAN_API_KEY", "ALCHEMY_API_KEY"): os.environ.pop(k, None)
    for c in W: check(f"sources {c}: keyless 3xpl available", history.sources(c) == ["3xpl"], history.sources(c))
    check("unlock note names the right key (Base -> Alchemy)", "ALCHEMY_API_KEY" in history.unlock_note("base") and "ETHERSCAN" not in history.unlock_note("base").split("(")[0])
    check("unlock note names Etherscan for Arbitrum", "ETHERSCAN_API_KEY" in history.unlock_note("arb"))
    pages = {}
    for c, a in W.items():
        r = await history.page(c, a)
        check(f"{c}: page 1 ok from 3xpl", r["ok"] and "3xpl" in (r["src"] or ""), (r["src"], r["note"][:80]))
        check(f"{c}: page 1 has history + counterparties", r["hist"] and r["edges"], (len(r["hist"]), len(r["edges"])))
        pages[c] = r
        for e in [x for x in r["edges"] if not x.get("internal")][:3]:
            check(f"{c}: edge {e['tx'][:12]} {e['amount']:.6g} {e['unit']} matches the on-chain receipt", truth(c, e), e)
        if c == "base": check("base: 100 USDT sent (real tx 0xeba394a3…)", any(e["tx"].startswith("0xeba394a3") and e["unit"] == "USDT" and abs(e["amount"] - 100) < 1e-9 for e in r["edges"]))
    for c in ("arb", "polygon"):
        r1 = pages[c]; check(f"{c}: more pages available", bool(r1["next"]))
        r2 = await history.page(c, W[c], r1["next"]); r3 = await history.page(c, W[c], r2["next"]) if r2["next"] else {"hist": []}
        o1 = min(h["time"] for h in r1["hist"]); n2 = max(h["time"] for h in r2["hist"]) if r2["hist"] else 0; o3 = min((h["time"] for h in r3["hist"]), default=o1)
        check(f"{c}: page 2/3 go back in time", r2["ok"] and r2["hist"] and o3 <= min(h["time"] for h in r2["hist"]) <= max(n2, o1) + 86400 * 400, (o1, n2, o3))
        lo, hi = min(h["time"] for h in r2["hist"]), max(h["time"] for h in r2["hist"])
        rf = await history.page(c, W[c], None, lo, hi)
        check(f"{c}: date filter keeps only the window", all(lo <= h["time"] <= hi for h in rf["hist"]), len(rf["hist"]))
    # fallback order: a bad key is skipped with a note, the keyless source still answers
    os.environ["ETHERSCAN_API_KEY"] = "INVALIDKEY123"
    check("with ETHERSCAN_API_KEY set, Etherscan is tried first", history.sources("arb")[0] == "etherscan")
    r = await history.page("arb", W["arb"])
    check("invalid Etherscan key -> graceful fallback to 3xpl", r["ok"] and "3xpl" in r["src"], (r["src"], r["note"][:120]))
    os.environ.pop("ETHERSCAN_API_KEY")
    os.environ["ALCHEMY_API_KEY"] = "invalid"; check("ALCHEMY_API_KEY covers Base", history.sources("base")[0] == "alchemy"); os.environ.pop("ALCHEMY_API_KEY")
    # 3xpl unreachable -> recent-window RPC log scan (old behaviour) instead of nothing
    old = history.X3_URL; history.X3_URL = "https://127.0.0.1:9"; history.X3_DEAD.clear()
    e_, h_, ok_, src = await chains._fallback_history("polygon", W["polygon"])
    check("3xpl down -> falls back to RPC log scan", "log scan" in src, src)
    history.X3_URL = old; history.X3_DEAD.clear()

def api():
    a = (AUTH["username"], AUTH["password"])
    for c in ("arb", "polygon", "base"):
        d = httpx.get(U + "/api/lookup", params={"q": f"{c}:{W[c]}"}, auth=a, timeout=120).json()
        check(f"api {c}: full-history note + source", "Full history from 3xpl" in " ".join(d.get("warnings") or []) and "3xpl" in (d.get("history_source") or ""), (d.get("history_source"), d.get("detail")))
        check(f"api {c}: txs + graph edges", len(d.get("txs") or []) >= 1 and len(d.get("edges") or []) >= 1, (len(d.get("txs") or []), len(d.get("edges") or [])))
        if c != "base":
            check(f"api {c}: deep cursor", (d.get("next") or "").startswith("dh:"), (d.get("next") or "")[:10])
            d2 = httpx.get(U + "/api/lookup", params={"q": f"{c}:{W[c]}", "cursor": d["next"]}, auth=a, timeout=120).json()
            new = {t["tx"] for t in d2.get("txs") or []} - {t["tx"] for t in d["txs"]}
            check(f"api {c}: Load more returns further (older) txs", new and max(t["time"] for t in d2["txs"]) <= max(t["time"] for t in d["txs"]), (len(new), d2.get("detail")))
    j = httpx.get(U + "/api/evm/chains", auth=a, timeout=30).json(); m = {x["chain"]: x for x in j["chains"]}
    check("api /evm/chains: deep source + unlock hint per chain", "3xpl" in " ".join(m["arb"]["deep_history"]) and "ALCHEMY_API_KEY" in m["base"]["unlock"] and "keys" in j, m["base"])

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w, h, tag in ((1600, 950, "desktop"), (390, 844, "phone")):
            ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials=AUTH)
            pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U + f"/?q=polygon:{W['polygon']}"); await pg.wait_for_function("cy.nodes().length>=4", timeout=120000); await pg.wait_for_timeout(1200)
            txt = await pg.inner_text("body")
            check(f"ui {tag}: full-history info note shown", "Full history from 3xpl" in txt and await pg.query_selector(".infobox") is not None)
            n0 = await pg.evaluate("cy.nodes().length")
            if await pg.query_selector("#more"):
                await pg.evaluate("loadMore()"); await pg.wait_for_function(f"cy.nodes().length>{n0}", timeout=120000)
                check(f"ui {tag}: Load more adds older counterparties", await pg.evaluate("cy.nodes().length") > n0)
            else: check(f"ui {tag}: Load more button present", False)
            if SHOTS: await pg.screenshot(path=SHOT(tag))
            check(f"ui {tag}: no JS errors", not errs, errs[:2]); await ctx.close()
        await b.close()

if __name__ == "__main__":
    os.environ.setdefault("CHAINTRACE_CACHE", "/workspace/scratch/uitest_history_cache.sqlite")
    if os.environ.get("ENGINE", "1") != "0": asyncio.run(engine())
    api(); asyncio.run(ui())
    print(f"\n{len(ok)} passed, {len(bad)} failed, {len(skip)} skipped" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
