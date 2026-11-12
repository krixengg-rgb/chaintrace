"""Readable Ethereum DEX swap steps (free data only: public RPC receipts + eth_call, Blockscout internal txs as an optional extra).
decode(h) -> {"text": "Swapped 10 ETH for 25,000 USDT on Uniswap V3", sold, bought, venue, router, hops, ...} or None.
Decoded = the trader's net token flows (ERC-20 Transfer logs, tx value, WETH unwrap / internal ETH) plus the DEX's own Swap events
(Uniswap V2 & forks, Uniswap V3 & forks, Uniswap V4, Balancer V2, Curve). Pools are identified by factory() / known contracts.
Anything not read directly from an event is listed in "inferred"."""
import asyncio, re, time
import chains, labels
from keccak import to_checksum

T_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
T_V2 = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
T_V3 = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
T_V4 = "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f"
T_BAL = "0x2170c741c41531aec20e7c107c24eecfdd15e69c9bb0a8dd37b1840b9e0b207b"
T_CRV = "0x8b3e96f2b889fa771c53c981b40daf005f63f637f1869f707052d15a3dd97140"
T_CRV_U = "0xd013ca23e77a65003c2c659c5442c00c805371b7fc1ebd4c206c41d1536bd90b"
T_CRV2 = "0xb2e76ae99761dc136e598d4a629bb347eccb9532a5f8bbd72e18467c3c34cc98"
T_WDEP = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"
T_WWD = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
SWAP_TOPICS = {T_V2: "v2", T_V3: "v3", T_V4: "v4", T_BAL: "balancer", T_CRV: "curve", T_CRV_U: "curve", T_CRV2: "curve"}
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
# well-known tokens (avoid eth_calls for the common ones)
TOKENS = {WETH: ("WETH", 18), "0xdac17f958d2ee523a2206206994597c13d831ec7": ("USDT", 6), "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": ("USDC", 6),
          "0x6b175474e89094c44da98b954eedeac495271d0f": ("DAI", 18), "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": ("WBTC", 8),
          "0xae7ab96520de3a18e5e111b5eaab095312d7fe84": ("stETH", 18), "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee": ("ETH", 18), "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0": ("wstETH", 18)}
# factories -> DEX name (public, from the projects' docs / Etherscan); used only to name a pool that emitted a Swap event
FACTORIES = {"0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f": "Uniswap V2", "0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac": "SushiSwap",
             "0x1f98431c8ad98523631ae4a59f267346ea31f984": "Uniswap V3", "0xbaceb8ec6b9355dfc0269c18bac9d6e2bdc29c4f": "SushiSwap V3",
             "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865": "PancakeSwap V3", "0x1097053fd2ea711dad45caccc45eff7548fcb362": "PancakeSwap V2"}
V4_POOLMANAGER = "0x000000000004444c5dc75cb358380d2e3de08a90"
BAL_VAULT = "0xba12222222228d8ba445958a75a0704d566bf2c8"
# routers / aggregators (tx.to) -> display name
ROUTERS = {"0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2 Router 02", "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3 SwapRouter",
           "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap SwapRouter02", "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": "Uniswap Universal Router",
           "0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b": "Uniswap Universal Router (old)", "0x66a9893cc07d91d95644aedd05d03f95e1dba8af": "Uniswap Universal Router (V4)",
           "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": "SushiSwap Router", "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch Aggregation Router v5",
           "0x111111125421ca6dc452d289314280a0f8842a65": "1inch Aggregation Router v6", "0x1111111254fb6c44bac0bed2854e76f90643097d": "1inch Aggregation Router v4",
           "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x Exchange Proxy", "0x9008d19f58aabd9ed0d60971565aa8510560ab41": "CoW Protocol settlement",
           "0xdef171fe48cf0115b1d80b88dc8eab59176fee57": "ParaSwap v5", "0x881d40237659c251811cec9c364ef91dc08d300c": "MetaMask Swap Router",
           BAL_VAULT: "Balancer V2 Vault"}
AGG = ("1inch", "0x ", "CoW", "ParaSwap", "MetaMask")

def _a(word): return "0x" + word[-40:].lower()
def _u(h): return int(h, 16) if h and h != "0x" else 0
def _s(h):
    v = int(h, 16); return v - (1 << 256) if v >= 1 << 255 else v
def _words(data): d = (data or "0x")[2:]; return [d[i:i + 64] for i in range(0, len(d), 64)]

async def call(to, sel, arg=None):
    data = "0x" + sel + (arg or "")
    try: return await chains.eth_rpc_any("eth_call", [{"to": to, "data": data}, "latest"], 6)
    except Exception: return None
def _str(res):
    if not res or res == "0x": return None
    w = _words(res)
    try:
        if len(w) >= 3 and int(w[0], 16) == 32: n = int(w[1], 16); return bytes.fromhex("".join(w[2:])[: n * 2]).decode("utf-8", "ignore").strip() or None
        return bytes.fromhex(w[0]).rstrip(b"\0").decode("utf-8", "ignore").strip() or None
    except Exception: return None
_TOK = {}
async def token(addr):
    a = addr.lower()
    if a in TOKENS: return TOKENS[a]
    if a in _TOK: return _TOK[a]
    sym, dec = await asyncio.gather(call(a, "95d89b41"), call(a, "313ce567"))
    s = _str(sym) or a[:8]; d = _u(dec) if dec and dec != "0x" else 18
    _TOK[a] = (s[:16], d if d < 80 else 18); return _TOK[a]
_POOL = {}
async def pool_info(addr, kind):
    a = addr.lower()
    if a in _POOL: return _POOL[a]
    info = {"address": addr, "dex": None, "token0": None, "token1": None, "fee": None}
    if kind in ("v2", "v3"):
        f, t0, t1, fee = await asyncio.gather(call(a, "c45a0155"), call(a, "0dfe1681"), call(a, "d21220a7"), call(a, "ddca3f43") if kind == "v3" else asyncio.sleep(0))
        fa = _a(f) if f and len(f) >= 42 else None
        info.update(token0=_a(t0) if t0 and len(t0) >= 42 else None, token1=_a(t1) if t1 and len(t1) >= 42 else None,
                    fee=_u(fee) if isinstance(fee, str) and fee != "0x" else None, factory=fa)
        info["dex"] = FACTORIES.get(fa) or ("Uniswap V2-style pool" if kind == "v2" else "Uniswap V3-style pool")
    elif kind == "v4": info["dex"] = "Uniswap V4"
    elif kind == "balancer": info["dex"] = "Balancer V2"
    elif kind == "curve":
        info["dex"] = "Curve"
        try:
            nm = labels.label("eth", addr).get("name")
            if nm: info["name"] = nm
        except Exception: pass
    _POOL[a] = info; return info

async def _curve_coin(pool, i):
    for sel in ("c6610657", "23746eb8"):
        r = await call(pool, sel, format(i, "064x"))
        if r and len(r) >= 42 and int(r, 16): return _a(r)
    return None

async def _internal_eth(h):
    """Blockscout internal ETH transfers for the tx (optional; None if unavailable)"""
    try:
        d, _ = await chains._cap(chains.get(f"{chains.BS}/transactions/{h}/internal-transactions", ttl=chains.LONG), 5)
        if d is None: return None
        return [(x["from"]["hash"].lower(), x["to"]["hash"].lower(), int(x.get("value") or 0) / 1e18) for x in d.get("items", []) if x.get("from") and x.get("to") and int(x.get("value") or 0) and x.get("success", True)]
    except Exception: return None

def fmt_amt(x):
    if x is None: return "?"
    if abs(x) >= 1000: return f"{x:,.0f}" if abs(x) >= 100000 else f"{x:,.2f}"
    return f"{x:,.6f}".rstrip("0").rstrip(".") or "0"

_DEC = {}
async def decode(h, trader_hint=None):
    h = h.lower() if h.startswith("0x") else "0x" + h.lower()
    k = (h, (trader_hint or "").lower())
    if k in _DEC: return _DEC[k]
    r = await _decode(h, trader_hint)
    if len(_DEC) > 3000: _DEC.clear()
    _DEC[k] = r; return r
async def _decode(h, trader_hint=None):
    tx, rc = await asyncio.gather(chains.eth_rpc_any("eth_getTransactionByHash", [h], 8), chains.eth_rpc_any("eth_getTransactionReceipt", [h], 8))
    if not tx or not rc: return None
    if rc.get("status") not in ("0x1", 1, None): return None
    logs = rc.get("logs") or []
    kinds = [(SWAP_TOPICS[(l.get("topics") or [""])[0]], l) for l in logs if (l.get("topics") or [""])[0] in SWAP_TOPICS]
    sender = (tx.get("from") or "").lower(); to = (tx.get("to") or "").lower()
    trader = (trader_hint or sender).lower()
    value = _u(tx.get("value")) / 1e18
    # net flows per address (raw units per token) from Transfer logs; WETH deposit/withdraw tracked separately
    net = {}; touched = set(); unwrap = []
    for l in logs:
        tp = l.get("topics") or []
        if not tp: continue
        if tp[0] == T_TRANSFER and len(tp) == 3:
            tk = l["address"].lower(); v = _u(l.get("data"))
            f_, t_ = _a(tp[1]), _a(tp[2]); touched.add(tk)
            net.setdefault(f_, {}).setdefault(tk, 0); net.setdefault(t_, {}).setdefault(tk, 0)
            net[f_][tk] -= v; net[t_][tk] += v
        elif tp[0] == T_WWD and l["address"].lower() == WETH and len(tp) >= 2: unwrap.append((_a(tp[1]), _u(l.get("data"))))
    if not kinds and not (net.get(trader) and len([1 for v in net[trader].values() if v > 0]) and (value or any(v < 0 for v in net[trader].values()))):
        return None
    t_info = {}
    for tk in touched: t_info[tk] = await token(tk)
    inferred = []; method = "decoded from DEX swap event logs" if kinds else "inferred from token transfers (no known DEX swap event)"
    sold, bought = {}, {}
    for tk, v in (net.get(trader) or {}).items():
        if not v: continue
        sym, dec = t_info[tk]; amt = abs(v) / 10 ** dec
        (bought if v > 0 else sold)[tk] = [sym, amt]
    if value: sold["eth"] = ["ETH", value + (sold.pop("eth", [None, 0])[1])]
    # ETH paid out to the trader inside the tx (router unwraps WETH then sends ETH): read internal txs, else infer from the WETH unwrap
    eth_in = 0.0; it = await _internal_eth(h) if (unwrap or kinds) else None
    if it is not None:
        eth_in = sum(v for f_, t_, v in it if t_ == trader) - sum(v for f_, t_, v in it if f_ == trader)
    elif unwrap and not bought:
        eth_in = sum(v for _, v in unwrap) / 1e18; inferred.append("ETH received inferred from the WETH unwrap (internal transfers unavailable)")
    if eth_in > 1e-12:
        if "eth" in sold:   # refund of excess ETH
            sold["eth"][1] -= eth_in
            if sold["eth"][1] <= 1e-12: sold.pop("eth")
        else: bought["eth"] = ["ETH", eth_in]
    recipient = trader
    if not bought:   # output went to another address (e.g. swap-and-send): the largest non-pool receiver of a token the trader didn't sell
        pools = {l["address"].lower() for _, l in kinds} | {to, V4_POOLMANAGER, BAL_VAULT}
        best = None
        for adr, m in net.items():
            if adr in pools or adr == trader or adr == "0x" + "0" * 40: continue
            for tk, v in m.items():
                if v > 0 and tk not in sold:
                    sym, dec = t_info[tk]; amt = v / 10 ** dec
                    if not best or amt * (chains.usd_of(1, sym) or 0) > best[3] * (chains.usd_of(1, best[2]) or 0): best = (adr, tk, sym, amt)
        if best:
            recipient = best[0]; bought[best[1]] = [best[2], best[3]]; inferred.append("output recipient differs from the sender (largest receiver of the bought token)")
    if not sold or not bought: return None
    # hops from swap events
    hops = []
    for kind, l in kinds[:12]:
        tp = l.get("topics") or []; w = _words(l.get("data")); pa = l["address"]
        try:
            pi = await pool_info(pa, kind); hop = {"dex": pi.get("dex"), "pool": pa, "kind": kind}
            if kind == "v2" and len(w) >= 4 and pi.get("token0"):
                a0i, a1i, a0o, a1o = (_u(x) for x in w[:4]); t0, t1 = pi["token0"], pi["token1"]
                ti, to_ = (t0, t1) if a0i > 0 else (t1, t0); ai, ao = (a0i, a1o) if a0i > 0 else (a1i, a0o)
            elif kind == "v3" and len(w) >= 2 and pi.get("token0"):
                a0, a1 = _s(w[0]), _s(w[1]); t0, t1 = pi["token0"], pi["token1"]
                ti, to_, ai, ao = (t0, t1, a0, -a1) if a0 > 0 else (t1, t0, a1, -a0)
                if pi.get("fee"): hop["fee"] = f"{pi['fee'] / 10000:g}%"
            elif kind == "balancer" and len(tp) >= 4 and len(w) >= 2:
                ti, to_, ai, ao = _a(tp[2]), _a(tp[3]), _u(w[0]), _u(w[1]); hop["pool_id"] = tp[1]
            elif kind == "curve" and len(w) >= 4:
                i, ai, j, ao = _u(w[0]), _u(w[1]), _u(w[2]), _u(w[3])
                ti, to_ = await _curve_coin(pa, i), await _curve_coin(pa, j)
                if pi.get("name"): hop["dex"] = f"Curve ({re.sub(r'^curve[a-z]*_', '', pi['name'], flags=re.I).split('-')[0]})"
            elif kind == "v4" and len(w) >= 2:
                hop.update(token_in=None, token_out=None, note="pool tokens not resolved (Uniswap V4 pool id); amounts from the trader's transfers"); hop["pool_id"] = tp[1] if len(tp) > 1 else None
                hops.append(hop); continue
            else: hops.append(hop); continue
            for tk in (ti, to_):
                if tk and tk not in t_info: t_info[tk] = await token(tk)
            si, di = t_info.get(ti, ("?", 18)), t_info.get(to_, ("?", 18))
            hop.update(token_in=ti, token_out=to_, sym_in=si[0], sym_out=di[0], amount_in=ai / 10 ** si[1], amount_out=ao / 10 ** di[1])
        except Exception as ex: hop = {"dex": "?", "pool": pa, "kind": kind, "error": type(ex).__name__}
        hops.append(hop)
    if any(hh.get("kind") == "v4" for hh in hops): inferred.append("Uniswap V4 pool tokens not resolved; pair taken from the trader's net transfers")
    dexes = list(dict.fromkeys(hh["dex"] for hh in hops if hh.get("dex")))
    rname = ROUTERS.get(to)
    if not rname:
        try: rname = labels.label("eth", tx.get("to")).get("name")
        except Exception: rname = None
    if rname and any(x in rname for x in AGG): venue = f"{rname.split(' Aggregation')[0].split(' Exchange')[0].split(' settlement')[0]}" + (f" (via {', '.join(dexes[:3])})" if dexes else "")
    else: venue = " → ".join(dexes[:3]) if dexes else (rname or "an unidentified contract")
    if not dexes: inferred.append("no recognised DEX swap event; venue taken from the called contract")
    blk = None
    try: blk = await chains.eth_rpc_any("eth_getBlockByNumber", [tx.get("blockNumber"), False], 6)
    except Exception: pass
    ts = _u(blk.get("timestamp")) if blk else None
    S = [{"token": tk if tk != "eth" else None, "symbol": s, "amount": a, "usd": chains.usd_of(a, s)} for tk, (s, a) in sold.items() if a > 0]
    B = [{"token": tk if tk != "eth" else None, "symbol": s, "amount": a, "usd": chains.usd_of(a, s)} for tk, (s, a) in bought.items() if a > 0]
    if not S or not B: return None
    S.sort(key=lambda x: -(x["usd"] or 0)); B.sort(key=lambda x: -(x["usd"] or 0))
    txt = f"Swapped {' + '.join(fmt_amt(x['amount']) + ' ' + x['symbol'] for x in S)} for {' + '.join(fmt_amt(x['amount']) + ' ' + x['symbol'] for x in B)} on {venue}"
    return {"tx": h, "time": ts, "block": _u(tx.get("blockNumber")), "trader": checksum(trader), "recipient": checksum(recipient),
            "sender": checksum(tx.get("from")), "router": {"address": checksum(tx.get("to")), "name": rname}, "venue": venue, "dexes": dexes, "hops": hops,
            "sold": S, "bought": B, "text": txt, "method": method, "inferred": inferred, "decoded": bool(kinds) and not any("V4" in x for x in inferred),
            "usd_basis": "trace-time price (not historical)", "source": "Ethereum public RPC receipt logs" + (" + Blockscout internal transactions" if it is not None else "")}

def checksum(a):
    try: return to_checksum(a) if a else a
    except Exception: return a

def graph(sw, canon=None, tid=None):
    """swap -> one grouped step: trader -> [swap node] -> recipient. Node id is tx:<hash> so existing tx handling (expand, report) applies."""
    canon = canon or {}
    c = lambda a: canon.get((a or "").lower()) or checksum(a)
    tid = tid or "tx:" + sw["tx"]; tr, rc = c(sw["trader"]), c(sw["recipient"])
    short = f"{fmt_amt(sw['sold'][0]['amount'])} {sw['sold'][0]['symbol']} → {fmt_amt(sw['bought'][0]['amount'])} {sw['bought'][0]['symbol']}"
    node = {"id": tid, "chain": "eth", "kind": "swap", "name": f"Swap · {short}", "swap": sw, "tags": [], "risk": 0}
    edges = []
    for x in sw["sold"]:
        edges.append({"source": tr, "target": tid, "amount": x["amount"], "unit": x["symbol"], "usd": x["usd"], "tx": sw["tx"], "time": sw["time"],
                      "swap": {"leg": "sold", "venue": sw["venue"], "text": sw["text"], "decoded": sw["decoded"]}})
    for x in sw["bought"]:
        edges.append({"source": tid, "target": rc, "amount": x["amount"], "unit": x["symbol"], "usd": x["usd"], "tx": sw["tx"], "time": sw["time"],
                      "swap": {"leg": "bought", "venue": sw["venue"], "text": sw["text"], "decoded": sw["decoded"]}})
    nodes = [node] + [chains.node("eth", a) for a in dict.fromkeys([tr, rc]) if a]
    return nodes, edges

def candidates(focus, raw_edges, cap=10):
    """txs where `focus` sent one asset and received a different one (likely swaps), newest first"""
    fl = focus.lower(); by = {}
    for e in raw_edges or []:
        h = e.get("tx")
        if not h or not str(h).startswith("0x"): continue
        s_, t_ = e["source"].lower(), e["target"].lower()
        if s_ == t_: continue
        d = by.setdefault(h, {"out": set(), "in": set(), "time": None, "usd": 0})
        if s_ == fl and (e.get("amount") or 0) > 0: d["out"].add(e.get("unit"))
        elif t_ == fl and (e.get("amount") or 0) > 0: d["in"].add(e.get("unit"))
        else: continue
        t = e.get("time"); t = t if isinstance(t, (int, float)) else chains.ts_of(t)
        d["time"] = max(d["time"] or 0, t or 0); d["usd"] += chains.usd_of(e.get("amount"), e.get("unit"), e.get("rate")) or 0
    out = [{"tx": h, "time": d["time"]} for h, d in by.items() if d["out"] and d["in"] and (d["in"] - d["out"])]
    out.sort(key=lambda x: -(x["time"] or 0)); return out[:cap]

async def decode_many(hashes, trader=None, budget=20):
    sem = asyncio.Semaphore(3); t0 = time.time()
    async def one(h):
        async with sem:
            if time.time() - t0 > budget: return None
            try: return await asyncio.wait_for(decode(h, trader), max(3, budget - (time.time() - t0)))
            except Exception: return None
    return [x for x in await asyncio.gather(*[one(h) for h in hashes]) if x]
