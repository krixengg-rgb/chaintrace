"""Cross-chain swap tracing (v29).

Deterministic swap hops (THORChain / Maya via Midgard, Chainflip via its public swap backend) come from bridges.py: the protocol's own
indexer links the inbound tx to the outbound tx and destination address (memo / swap id). This module adds the *heuristic* layer for
instant custodial swappers (ChangeNOW, FixedFloat, Changelly, eXch, ...): those services pay out from their own hot wallets, so there is
no on-chain or API link between what went in and what came out. We look for payouts from swapper hot wallets that are labelled in
documented public datasets (data/swappers.json, one source URL per address) shortly after the input, with a USD value close to the input
less a typical fee. Every such match is a LEAD ONLY: confirm it with the service (production order / disclosure request)."""
import asyncio, json, os, time
from datetime import datetime, timezone
import chains, bridges, evmcfg

LEAD = "Heuristic lead – not evidence. Instant swappers pay out from pooled hot wallets, so no on-chain link exists between input and output; a timing + amount coincidence is only a lead. Confirm with the service (disclosure request / production order)."
METHOD = ("Input value in USD (hourly Coinbase close for the coin; stablecoins at $1) is compared with every payout from labelled swapper hot wallets "
          "within {win} h after the input. A payout matches when its USD value is {lo:.0%}–{hi:.0%} of the input (service fee + spread + network fee). "
          "Confidence starts at 0.30, rises with closeness in value and time and with a confirmed swapper deposit (direct payment, or the receiving address "
          "swept to a labelled swapper wallet), falls with the number of competing candidates, and is capped at 0.60. Payout sources checked: "
          "Ethereum (native ETH + ERC-20 via Blockscout) and BNB Chain (BEP-20 via public RPC logs). Payouts on other chains are not visible to this check.")
WIN = 3 * 3600; LO, HI = 0.85, 1.02
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_SW = None
def swappers():
    global _SW
    if _SW is None:
        try: rows = json.load(open(os.path.join(D, "swappers.json")))["entries"]
        except Exception: rows = []
        _SW = {(r["c"], r["a"].lower() if r["a"].startswith("0x") else r["a"]): r for r in rows}
    return _SW
def bare(a): return evmcfg.bare(a) if a else a
def is_swapper(c, a):
    a = bare(a or ""); return swappers().get((c, a.lower() if a.startswith("0x") else a))
SERVICES = ("ChangeNOW", "FixedFloat", "Changelly", "eXch", "SideShift", "SimpleSwap", "StealthEX")
def service_of(n):
    """instant-swapper service for a node: labelled swapper wallet, or an inferred per-order deposit address of one"""
    if n.get("swapper"): return n["swapper"]["service"]
    sg = n.get("suggested") or {}
    txt = f"{sg.get('entity') or ''} {sg.get('label') or ''}".lower().replace(" ", "")
    return next((s for s in SERVICES if s.lower() in txt), None) if sg else None
def decorate(n, c):
    """tag a node that is a labelled instant swapper (keeps any stronger label)"""
    s = is_swapper(c, n.get("id") or "")
    if s:
        n["swapper"] = {"service": s["service"], "name": s["name"], "src": s["src"], "url": s["url"]}
        n["tags"] = sorted(set(n.get("tags") or []) | {"instant swapper", s["service"]})
        if not n.get("kind") or n.get("kind") in ("other", "exchange"): n.update(kind=n.get("kind") or "exchange", name=n.get("name") or s["name"])
    return n

# ---------------- prices (hourly) ----------------
PXSYM = {"BTC": "BTC", "WBTC": "BTC", "CBBTC": "BTC", "BTCB": "BTC", "ETH": "ETH", "WETH": "ETH", "SOL": "SOL", "XRP": "XRP", "LTC": "LTC", "DOGE": "DOGE",
         "BCH": "BCH", "BNB": "BNB", "WBNB": "BNB", "POL": "POL", "MATIC": "POL", "TRX": None}
STABLE = {"USDT", "USDC", "DAI", "USDC.E", "BSC-USD", "FDUSD", "USDT0", "PYUSD", "TUSD", "BUSD"}
async def px(sym, t):
    sym = (sym or "").upper().replace("⇄", "")
    if sym in STABLE: return 1.0
    p = PXSYM.get(sym)
    if not p:
        if sym == "TRX":
            try: return float((await chains.get(f"https://api.binance.com/api/v3/klines?symbol=TRXUSDT&interval=1h&startTime={int(t // 3600 * 3600 * 1000)}&limit=1", ttl=chains.LONG))[0][4])
            except Exception: return None
        return None
    h = int(t // 3600 * 3600); iso = lambda x: datetime.fromtimestamp(x, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rows = await chains.get(f"https://api.exchange.coinbase.com/products/{p}-USD/candles?granularity=3600&start={iso(h - 3600)}&end={iso(h + 3600)}",
                                ttl=chains.LONG if h < time.time() - 7200 else 600)
        best = min(rows or [], key=lambda r: abs(r[0] - h), default=None)
        return float(best[4]) if best else None
    except Exception: return None

# ---------------- payouts from labelled swapper wallets ----------------
BS = "https://eth.blockscout.com/api"
async def _eth_block(ts):
    d = await chains.get(f"{BS}?module=block&action=getblocknobytime&timestamp={int(ts)}&closest=after", ttl=chains.LONG if ts < time.time() - 600 else 60)
    return int((d.get("result") or {}).get("blockNumber"))
BS2 = "https://eth.blockscout.com/api/v2"
def _iso(t):
    try: return int(datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp())
    except Exception: return None
async def _eth_payouts_v2(w, t0, t1):
    """fallback when Blockscout's legacy (etherscan-style) API refuses a shared host: the v2 REST API (outgoing only, filter=from).
    v2 pages newest-first with a (block_number, index) cursor, so the window's block range (from the public RPC, 12 s slots, padded)
    is cut into segments that are paged in parallel, each from its top block down to its bottom."""
    h = int(await chains.rpc(chains.ETH_RPC, "eth_blockNumber", [], ttl=30), 16)
    hb = await chains.rpc(chains.ETH_RPC, "eth_getBlockByNumber", [hex(h), False], ttl=30); ht = int(hb["timestamp"], 16)
    b1 = min(h, int(h - (ht - t1) / 12.0) + 300); b0 = max(1, int(h - (ht - t0) / 12.0) - 300)
    nseg = 6; step = max(1, (b1 - b0) // nseg + 1)
    segs = [(b0 + i * step, min(b1, b0 + (i + 1) * step - 1)) for i in range(nseg) if b0 + i * step <= b1]
    out = {}
    async def seg(kind, lo, hi):
        prm = {"filter": "from", "block_number": hi, "index": 0}
        for _ in range(6):
            q = "&".join(f"{k}={v}" for k, v in prm.items())
            d = await chains.get(f"{BS2}/addresses/{w}/{kind}?{q}", ttl=chains.LONG if t1 < time.time() - 3600 else 120)
            its = (d or {}).get("items") or []; stop = False
            for x in its:
                if int(x.get("block_number") or 0) < lo: stop = True; continue
                t = _iso(x.get("timestamp"))
                if t is None or t < t0 or t > t1: continue
                if kind == "transactions":
                    if (x.get("from") or {}).get("hash", "").lower() != w or x.get("status") not in (None, "ok"): continue
                    v = int(x.get("value") or 0) / 1e18
                    if v > 0: out[(x["hash"], "ETH", "")] = {"chain": "eth", "tx": x["hash"], "to": ((x.get("to") or {}).get("hash") or "").lower(), "amount": v, "unit": "ETH", "time": t}
                else:
                    tk = x.get("token") or {}; tot = x.get("total") or {}
                    try: v = int(tot.get("value")) / 10 ** int(tot.get("decimals") or tk.get("decimals") or 18)
                    except Exception: continue
                    txh = x.get("transaction_hash") or x.get("tx_hash"); to = ((x.get("to") or {}).get("hash") or "").lower()
                    out[(txh, to, str(x.get("log_index")))] = {"chain": "eth", "tx": txh, "to": to, "amount": v, "unit": (tk.get("symbol") or "?").upper(), "time": t,
                                                              "token": (tk.get("address_hash") or tk.get("address") or "").lower()}
            nx = (d or {}).get("next_page_params")
            if stop or not nx or not its: break
            prm = {k: v for k, v in nx.items() if v is not None}
    await asyncio.gather(*[seg(k, lo, hi) for k in ("transactions", "token-transfers") for lo, hi in segs])
    return list(out.values())
LEGACY_DEAD = {"t": 0}
async def _eth_payouts(w, t0, t1):
    if time.time() - LEGACY_DEAD["t"] > 600:
        try: return await asyncio.wait_for(_eth_payouts_legacy(w, t0, t1), 10)
        except Exception: LEGACY_DEAD["t"] = time.time()   # rate-limited / refused on this host: use v2 for the next 10 minutes
    return await _eth_payouts_v2(w, t0, t1)
async def _eth_payouts_legacy(w, t0, t1):
    b0 = await _eth_block(t0); b1 = await _eth_block(min(t1, time.time() - 30)) if t1 < time.time() - 30 else 99999999
    out = []
    for act in ("txlist", "tokentx"):
        d = await chains.get(f"{BS}?module=account&action={act}&address={w}&startblock={b0}&endblock={b1}&sort=asc&page=1&offset=1000", ttl=chains.LONG if t1 < time.time() - 3600 else 120)
        for x in (d or {}).get("result") or []:
            if not isinstance(x, dict) or (x.get("from") or "").lower() != w or x.get("isError") == "1": continue
            if act == "txlist":
                v = int(x.get("value") or 0) / 1e18
                if v <= 0: continue
                out.append({"chain": "eth", "tx": x["hash"], "to": x.get("to"), "amount": v, "unit": "ETH", "time": int(x["timeStamp"])})
            else:
                try: v = int(x["value"]) / 10 ** int(x.get("tokenDecimal") or 18)
                except Exception: continue
                out.append({"chain": "eth", "tx": x["hash"], "to": x.get("to"), "amount": v, "unit": (x.get("tokenSymbol") or "?").upper(), "time": int(x["timeStamp"]), "token": x.get("contractAddress")})
    return out
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
BSC_TOK = {"0x55d398326f99059ff775485246999027b3197955": ("USDT", 18), "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": ("USDC", 18),
           "0x2170ed0880ac9a755fd29b2688956bd959f933f8": ("ETH", 18), "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c": ("BTCB", 18)}   # Binance-Peg tokens (BscScan)
async def _bsc_payouts(w, t0, t1):
    rpcs = [evmcfg.EVM["bsc"]["logs"]["rpc"]] + [u for u in evmcfg.EVM["bsc"]["rpcs"] if u != evmcfg.EVM["bsc"]["logs"]["rpc"]]
    async def r(m, p):
        last = None
        for u in rpcs:
            try: return await chains.rpc(u, m, p, ttl=30 if m == "eth_blockNumber" else 86400)
            except Exception as e: last = e
        raise last
    head = int(await r("eth_blockNumber", []), 16); hb = await r("eth_getBlockByNumber", [hex(head), False]); ht = int(hb["timestamp"], 16)
    pb = await r("eth_getBlockByNumber", [hex(head - 100000), False]); bt = (ht - int(pb["timestamp"], 16)) / 100000
    b0 = max(1, int(head - (ht - t0) / bt) - 50); b1 = min(head, int(head - (ht - t1) / bt) + 50); out = []
    topic = "0x" + "0" * 24 + w[2:]
    rng = list(range(b0, b1 + 1, 5000))[:8]
    res = await asyncio.gather(*[r("eth_getLogs", [{"address": tk, "fromBlock": hex(f), "toBlock": hex(min(b1, f + 4999)), "topics": [TRANSFER, topic]}]) for f in rng for tk in BSC_TOK])   # publicnode needs a token address
    for logs in res:
        for lg in logs or []:
            tk = BSC_TOK.get(lg["address"].lower())
            if not tk: continue
            out.append({"chain": "bsc", "tx": lg["transactionHash"], "to": "0x" + lg["topics"][2][-40:], "amount": int(lg["data"], 16) / 10 ** tk[1], "unit": tk[0],
                        "token": lg["address"].lower(), "block": int(lg["blockNumber"], 16)})
    for o in out: o["time"] = int(t0 + (o.pop("block") - b0 - 50) * bt) if o.get("block") else None   # approximate (block time), refined below
    return out

# ---------------- input leg ----------------
def _legs(d, c):
    """value-carrying transfers in a tx: (sender, recipient, amount, unit, time)"""
    tid = "tx:" + str(d.get("tx") or ""); t = chains.ts_of(d.get("time")) if d.get("time") else None
    ins = {e["source"] for e in d["edges"] if e["target"] == tid}
    legs = []
    for e in d["edges"]:
        if not e.get("amount") or e["target"] == tid or (e["source"] == tid and e["target"] in ins): continue
        src = e["source"] if e["source"] != tid else (sorted(ins)[0] if ins else None)
        legs.append({"from": src, "to": e["target"], "amount": float(e["amount"]), "unit": (e.get("unit") or d.get("unit") or "").replace("⇄", "").upper(),
                     "time": chains.ts_of(e.get("time")) or t})
    return sorted(legs, key=lambda x: -(x["amount"] * (1 if x["unit"] in STABLE else 1)))
async def _swept_to_swapper(lookup, c, a, t0):
    """did address a forward funds to a labelled swapper wallet within the window? (typical per-order deposit address)"""
    try: d = await asyncio.wait_for(lookup(a, c), 20)
    except Exception: return None
    for e in d.get("edges") or []:
        tt = chains.ts_of(e.get("time")) if e.get("time") else None
        if bare(e["source"]).lower() == bare(a).lower() and is_swapper(c, e["target"]) and (tt is None or 0 <= tt - t0 <= WIN):
            return {"to": e["target"], "tx": e.get("tx"), "time": tt, **is_swapper(c, e["target"])}
    return None

async def leads(h, lookup, chain=None, budget=40):
    """heuristic instant-swapper leads for input tx h"""
    t_start = time.time(); notes = []
    c, kind = chains.detect(h, chain)
    if kind != "tx": raise ValueError("give a transaction hash (the payment into the swapper)")
    d = await asyncio.wait_for(lookup(h, c), 25); c = d.get("chain") or c
    legs = _legs(d, c)
    if not legs: return {"query": h, "chain": c, "candidates": [], "notes": ["no value transfer found in this transaction"], "lead": LEAD}
    # pick the leg into a swapper (direct), else the largest leg; check for a sweep to a swapper
    leg = next((l for l in legs if is_swapper(c, l["to"])), None); how = None
    if leg: s = is_swapper(c, leg["to"]); how = {"kind": "direct", "service": s["service"], "wallet": leg["to"], "name": s["name"], "src": s["src"], "url": s["url"]}
    else:
        leg = legs[0]
        if c in ("eth", "bsc", "tron") or c in chains.EVM_NEW:
            sw = await _swept_to_swapper(lookup, c, leg["to"], leg["time"] or time.time())
            if sw: how = {"kind": "sweep", "service": sw["service"], "wallet": sw["to"], "name": sw["name"], "src": sw["src"], "url": sw["url"], "sweep_tx": sw.get("tx")}
        if not how: notes.append("The receiving address is not a labelled swapper wallet and was not seen sweeping to one: any match below is weaker (no confirmed swapper deposit).")
    t0 = leg["time"]; pre = 3600 if how and how["kind"] == "direct" else 0   # a sweep into a hot wallet can come after the payout
    if not t0: return {"query": h, "chain": c, "candidates": [], "notes": notes + ["transaction time unknown (unconfirmed?)"], "lead": LEAD}
    p = await px(leg["unit"], t0)
    if not p: return {"query": h, "chain": c, "input": leg, "candidates": [], "notes": notes + [f"no hourly USD price for {leg['unit']}: cannot compare values"], "lead": LEAD}
    usd_in = leg["amount"] * p
    wallets = [(k, v) for k, v in swappers().items() if k[0] in ("eth", "bsc") and "deposit" not in v["name"].lower()]
    if how: wallets.sort(key=lambda kv: kv[1]["service"] != how["service"])   # same service first
    sems = {"eth": asyncio.Semaphore(1), "bsc": asyncio.Semaphore(2)}; pays = []; checked = []   # Blockscout's legacy API rate-limits shared hosts: scan Ethereum wallets one at a time
    async def one(k, v):
        async with sems[k[0]]:
            if time.time() - t_start > budget: notes.append(f"{v['service']} {k[0]} {k[1][:10]}: not checked (time budget reached; retry, results are cached)"); return
            try:
                ps = await asyncio.wait_for((_eth_payouts if k[0] == "eth" else _bsc_payouts)(k[1], t0 - pre, t0 + WIN), 28)
                checked.append({"chain": k[0], "wallet": k[1], "service": v["service"], "payouts": len(ps)})
                for q_ in ps: q_.update(service=v["service"], wallet=k[1], wallet_name=v["name"], src=v["src"], url=v["url"])
                pays.extend(ps)
            except Exception as e: notes.append(f"{v['service']} {k[0]} {k[1][:10]}: payout scan failed ({type(e).__name__}{': ' + str(e)[:60] if str(e) else ''})")
    await asyncio.gather(*[one(k, v) for k, v in wallets])
    cands = []
    for q_ in pays:
        if q_.get("time") is None or not (-pre <= q_["time"] - t0 <= WIN): continue
        if q_["chain"] == c and q_["unit"] == leg["unit"] and abs(q_["amount"] - leg["amount"]) < 1e-12: continue
        pp = await px(q_["unit"], q_["time"])
        if not pp: continue
        usd = q_["amount"] * pp; r = usd / usd_in if usd_in else 0
        if not (LO <= r <= HI): continue
        cands.append({**q_, "usd": round(usd, 2), "ratio": round(r, 4), "dt_min": round((q_["time"] - t0) / 60, 1)})
    for x in cands:
        close = 1 - min(1, abs(0.985 - x["ratio"]) / 0.12); quick = 1 - min(1, abs(x["dt_min"]) / (WIN / 60))
        conf = 0.30 + 0.12 * close + 0.08 * quick + (0.10 if how else 0) + (0.05 if how and x["service"] == how["service"] else 0)
        conf -= 0.05 * max(0, len(cands) - 1)
        x["confidence"] = round(max(0.1, min(0.6, conf)), 2); x["method"] = "heuristic"
        x["evidence"] = (f"{x['service']} wallet {x['wallet_name']} paid {x['amount']:g} {x['unit']} (${x['usd']:,.2f}) {x['dt_min']:g} min after the input of "
                         f"{leg['amount']:g} {leg['unit']} (${usd_in:,.2f}); value ratio {x['ratio']:.3f}")
    cands.sort(key=lambda x: (-x["confidence"], x["dt_min"]))
    if len(cands) > 1: notes.append(f"{len(cands)} candidate payouts: ambiguity lowers every candidate's confidence")
    if not cands: notes.append(f"No payout from the {len(checked)} labelled swapper wallet(s) checked matched within {WIN // 3600} h and {LO:.0%}–{HI:.0%} of the input value.")
    return {"query": h, "chain": c, "input": {**leg, "usd": round(usd_in, 2), "price": p}, "swapper": how, "candidates": cands[:10], "checked": checked,
            "notes": notes, "lead": LEAD, "method": METHOD.format(win=WIN // 3600, lo=LO, hi=HI), "window_h": WIN / 3600}

def fragment(r, x):
    """graph nodes + one dotted heuristic edge (input sender/receiver -> payout recipient) for candidate x"""
    leg = r["input"]; c = r["chain"]; frm = leg["to"]
    tgt = x["to"]; tc = x["chain"]; tid = tgt if tc == "eth" else f"{tc}:{tgt}"
    n = chains.node(tc, tgt) if tc in chains.ADDR else {"id": tid, "chain": tc, "name": None, "kind": None, "tags": [], "risk": 0}
    n["chain"] = tc
    b = {"bridge": f"{x['service']} instant swap (heuristic)", "provider": "xswap", "method": "heuristic", "confidence": x["confidence"], "status": "candidate",
         "src": {"chain": c, "tx": r["query"], "address": frm, "amount": leg["amount"], "unit": leg["unit"], "time": leg["time"], "usd": r["input"].get("usd")},
         "dst": {"chain": tc, "tx": x["tx"], "address": tgt, "amount": x["amount"], "unit": x["unit"], "time": x["time"], "usd": x["usd"]},
         "evidence": x["evidence"], "usd": x["usd"], "ref": x["url"], "notes": [LEAD, f"Swapper wallet label: {x['wallet_name']} – {x['src']} ({x['url']})"]}
    e = {"source": frm, "target": n["id"], "amount": x["amount"], "unit": x["unit"] + "⇄", "tx": r["query"], "dst_tx": x["tx"], "time": x["time"], "usd": x["usd"], "count": 1,
         "xchain": True, "heur": True, "xswap": True, "swap": True, "method": "heuristic", "confidence": x["confidence"], "bridge": b}
    return [n], [e]
