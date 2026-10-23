"""Cross-chain bridge tracing.

Given a transaction (or an address) that touches a bridge, find the matching transfer on the other chain.

Deterministic matches come from each bridge's own public indexer, which links the source and destination
transactions by protocol message / order id (free, keyless endpoints):
  Wormhole (wormholescan), deBridge DLN (stats-api.dln.trade), Mayan (explorer-api.mayan.finance),
  Across (app.across.to), THORChain + Maya (Midgard: memo-based swaps, the BTC<->ETH route),
  LayerZero / Stargate (scan.layerzero-api.com), Relay (api.relay.link, v2 - retiring Nov 2026).
Heuristic matches (lead only): same address + same asset + amount within fee tolerance + time window on
EVM L2s, using public RPC eth_getLogs. Never treated as evidence and never followed automatically.
"""
import asyncio, time, json, re, os
import httpx, chains
from keccak import to_checksum

# ---------------- chains ----------------
# key: (display name, tx url prefix, address url prefix, evm?)
CH = {
 "eth": ("Ethereum", "https://etherscan.io/tx/", "https://etherscan.io/address/", True),
 "sol": ("Solana", "https://solscan.io/tx/", "https://solscan.io/account/", False),
 "btc": ("Bitcoin", "https://mempool.space/tx/", "https://mempool.space/address/", False),
 "base": ("Base", "https://basescan.org/tx/", "https://basescan.org/address/", True),
 "arb": ("Arbitrum", "https://arbiscan.io/tx/", "https://arbiscan.io/address/", True),
 "op": ("Optimism", "https://optimistic.etherscan.io/tx/", "https://optimistic.etherscan.io/address/", True),
 "polygon": ("Polygon", "https://polygonscan.com/tx/", "https://polygonscan.com/address/", True),
 "bsc": ("BNB Chain", "https://bscscan.com/tx/", "https://bscscan.com/address/", True),
 "avax": ("Avalanche", "https://snowtrace.io/tx/", "https://snowtrace.io/address/", True),
 "linea": ("Linea", "https://lineascan.build/tx/", "https://lineascan.build/address/", True),
 "zksync": ("zkSync Era", "https://era.zksync.network/tx/", "https://era.zksync.network/address/", True),
 "scroll": ("Scroll", "https://scrollscan.com/tx/", "https://scrollscan.com/address/", True),
 "blast": ("Blast", "https://blastscan.io/tx/", "https://blastscan.io/address/", True),
 "mantle": ("Mantle", "https://mantlescan.xyz/tx/", "https://mantlescan.xyz/address/", True),
 "unichain": ("Unichain", "https://uniscan.xyz/tx/", "https://uniscan.xyz/address/", True),
 "hyperevm": ("HyperEVM", "https://hyperevmscan.io/tx/", "https://hyperevmscan.io/address/", True),
 "worldchain": ("World Chain", "https://worldscan.org/tx/", "https://worldscan.org/address/", True),
 "ink": ("Ink", "https://explorer.inkonchain.com/tx/", "https://explorer.inkonchain.com/address/", True),
 "soneium": ("Soneium", "https://soneium.blockscout.com/tx/", "https://soneium.blockscout.com/address/", True),
 "zora": ("Zora", "https://explorer.zora.energy/tx/", "https://explorer.zora.energy/address/", True),
 "mode": ("Mode", "https://explorer.mode.network/tx/", "https://explorer.mode.network/address/", True),
 "lisk": ("Lisk", "https://blockscout.lisk.com/tx/", "https://blockscout.lisk.com/address/", True),
 "gnosis": ("Gnosis", "https://gnosisscan.io/tx/", "https://gnosisscan.io/address/", True),
 "sonic": ("Sonic", "https://sonicscan.org/tx/", "https://sonicscan.org/address/", True),
 "berachain": ("Berachain", "https://berascan.com/tx/", "https://berascan.com/address/", True),
 "celo": ("Celo", "https://celoscan.io/tx/", "https://celoscan.io/address/", True),
 "fantom": ("Fantom", "https://ftmscan.com/tx/", "https://ftmscan.com/address/", True),
 "moonbeam": ("Moonbeam", "https://moonscan.io/tx/", "https://moonscan.io/address/", True),
 "sei": ("Sei EVM", "https://seitrace.com/tx/", "https://seitrace.com/address/", True),
 "plasma": ("Plasma", "https://plasmascan.to/tx/", "https://plasmascan.to/address/", True),
 "tron": ("Tron", "https://tronscan.org/#/transaction/", "https://tronscan.org/#/address/", False),
 "doge": ("Dogecoin", "https://blockchair.com/dogecoin/transaction/", "https://blockchair.com/dogecoin/address/", False),
 "ltc": ("Litecoin", "https://blockchair.com/litecoin/transaction/", "https://blockchair.com/litecoin/address/", False),
 "bch": ("Bitcoin Cash", "https://blockchair.com/bitcoin-cash/transaction/", "https://blockchair.com/bitcoin-cash/address/", False),
 "xrp": ("XRP Ledger", "https://xrpscan.com/tx/", "https://xrpscan.com/account/", False),
 "gaia": ("Cosmos Hub", "https://www.mintscan.io/cosmos/tx/", "https://www.mintscan.io/cosmos/address/", False),
 "thor": ("THORChain", "https://runescan.io/tx/", "https://runescan.io/address/", False),
 "maya": ("Maya", "https://www.explorer.mayachain.info/tx/", "https://www.explorer.mayachain.info/address/", False),
 "zec": ("Zcash", "https://blockchair.com/zcash/transaction/", "https://blockchair.com/zcash/address/", False),
 "dash": ("Dash", "https://blockchair.com/dash/transaction/", "https://blockchair.com/dash/address/", False),
 "sui": ("Sui", "https://suiscan.xyz/mainnet/tx/", "https://suiscan.xyz/mainnet/account/", False),
 "aptos": ("Aptos", "https://explorer.aptoslabs.com/txn/", "https://explorer.aptoslabs.com/account/", False),
 "near": ("NEAR", "https://nearblocks.io/txns/", "https://nearblocks.io/address/", False),
}
NATIVE = {"eth", "btc", "sol"}   # chains ChainTrace can expand further
WH = {1: "sol", 2: "eth", 4: "bsc", 5: "polygon", 6: "avax", 10: "fantom", 14: "celo", 15: "near", 16: "moonbeam", 21: "sui", 22: "aptos",
      23: "arb", 24: "op", 30: "base", 34: "scroll", 35: "mantle", 36: "blast", 38: "linea", 39: "berachain", 40: "sei", 44: "unichain",
      45: "worldchain", 46: "ink", 47: "hyperevm", 52: "sonic"}
EVM = {1: "eth", 10: "op", 56: "bsc", 100: "gnosis", 130: "unichain", 137: "polygon", 146: "sonic", 250: "fantom", 324: "zksync", 480: "worldchain",
       999: "hyperevm", 1135: "lisk", 1284: "moonbeam", 1329: "sei", 1868: "soneium", 5000: "mantle", 8453: "base", 9745: "plasma", 34443: "mode",
       42161: "arb", 42220: "celo", 43114: "avax", 57073: "ink", 59144: "linea", 80094: "berachain", 81457: "blast", 534352: "scroll",
       7777777: "zora", 34268394551451: "sol", 792703809: "sol", 8253038: "btc", 7565164: "sol", 728126428: "tron"}
LZ = {"ethereum": "eth", "solana": "sol", "bsc": "bsc", "arbitrum": "arb", "optimism": "op", "base": "base", "polygon": "polygon",
      "avalanche": "avax", "linea": "linea", "scroll": "scroll", "mantle": "mantle", "blast": "blast", "zksync": "zksync", "unichain": "unichain",
      "hyperliquid": "hyperevm", "ink": "ink", "sonic": "sonic", "sei": "sei", "berachain": "berachain", "gnosis": "gnosis", "tron": "tron"}
THOR = {"BTC": "btc", "ETH": "eth", "BSC": "bsc", "AVAX": "avax", "BASE": "base", "DOGE": "doge", "LTC": "ltc", "BCH": "bch", "GAIA": "gaia",
        "TRON": "tron", "XRP": "xrp", "THOR": "thor", "MAYA": "maya", "ARB": "arb", "DASH": "dash", "ZEC": "zec", "SOL": "sol"}
def cname(c): return CH.get(c, (c or "?",))[0]
def is_evm(c): return c in CH and CH[c][3] or str(c).startswith("evm:")
def norm_addr(c, a):
    if not a: return a
    a = str(a)
    if is_evm(c) and re.fullmatch(r"0x[0-9a-fA-F]{40}", a): return to_checksum(a)
    if is_evm(c) and re.fullmatch(r"0x0{24}[0-9a-fA-F]{40}", a): return to_checksum("0x" + a[-40:])   # bytes32-padded
    return a
def norm_tx(c, h):
    if not h: return h
    h = str(h)
    if (is_evm(c) or c == "btc") and re.fullmatch(r"(0x)?[0-9a-fA-F]{64}", h):
        h = h.lower().removeprefix("0x"); return h if c == "btc" else "0x" + h
    return h
def node_id(c, a):
    """graph node id: plain for chains ChainTrace can expand, chain-prefixed otherwise (same EVM address on another chain is a different account)"""
    return a if c in NATIVE else f"{c}:{a}"
def side(c, tx=None, address=None, amount=None, unit=None, t=None, usd=None, status=None):
    c = c or "?"; address = norm_addr(c, address); tx = norm_tx(c, tx)
    info = CH.get(c)
    return {"chain": c, "chain_name": cname(c), "tx": tx, "address": address, "amount": _f(amount), "unit": unit, "time": chains.ts_of(t) if t else None,
            "usd": _f(usd), "status": status, "tx_url": (info[1] + tx) if (info and tx) else None,
            "address_url": (info[2] + address) if (info and address) else None, "expandable": c in NATIVE}
def _f(x):
    try: return None if x is None or x == "" else float(x)
    except Exception: return None
def M(bridge, provider, method, confidence, status, src, dst, evidence, usd=None, ref=None, notes=None):
    return {"bridge": bridge, "provider": provider, "method": method, "confidence": round(confidence, 2), "status": status, "src": src, "dst": dst,
            "evidence": evidence, "usd": _f(usd) if usd is not None else (src.get("usd") or dst.get("usd") or chains.usd_of(src.get("amount"), src.get("unit")) or chains.usd_of(dst.get("amount"), dst.get("unit"))),
            "ref": ref, "notes": notes or []}

# ---------------- HTTP helpers ----------------
async def _get(url, ttl=120, **kw):
    try: return await chains.get(url, ttl=ttl, **kw)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (400, 404): return None
        raise
async def _post(url, body, ttl=120):
    k = ("POST", url, json.dumps(body, sort_keys=True))
    if k in chains._cache and time.time() - chains._cache[k][0] < ttl: return chains._cache[k][1]
    r = await chains.client.post(url, json=body, timeout=10); r.raise_for_status(); d = r.json(); chains._cache[k] = (time.time(), d); return d
def _hex_ok(h): return bool(re.fullmatch(r"0x[0-9a-fA-F]{64}", h or ""))
def _btc_ok(h): return bool(re.fullmatch(r"[0-9a-fA-F]{64}", h or ""))
def _sol_ok(h): return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{80,90}", h or ""))

# ---------------- Wormhole ----------------
WH_APPS = {"PORTAL_TOKEN_BRIDGE": "Wormhole Portal", "NATIVE_TOKEN_TRANSFER": "Wormhole NTT", "CCTP_WORMHOLE_INTEGRATION": "Wormhole CCTP",
           "MAYAN": "Mayan (Wormhole)", "OMNI_BRIDGE": "NEAR Omni Bridge (Wormhole)", "CONNECT": "Wormhole Connect", "USDT_TRANSFER": "USDT0 (Wormhole)",
           "ETH_BRIDGE": "Wormhole ETH bridge", "GENERIC_RELAYER": "Wormhole relayer", "CCTP_MANUAL": "Circle CCTP (Wormhole)", "MAYAN_SWIFT": "Mayan Swift",
           "MAYAN_MCTP": "Mayan MCTP", "LIQUIDITY_LAYER": "Wormhole Liquidity Layer"}
def _wh(o):
    sp = (o.get("content") or {}).get("standarizedProperties") or {}; s = o.get("sourceChain") or {}; t = o.get("targetChain") or {}; dd = o.get("data") or {}
    apps = [a for a in (sp.get("appIds") or []) if a != "UNKNOWN"]; name = next((WH_APPS[a] for a in apps if a in WH_APPS), "Wormhole" + (f" ({apps[0]})" if apps else ""))
    sc = WH.get(s.get("chainId") or sp.get("fromChain"), f"wh:{s.get('chainId')}"); tc = WH.get(t.get("chainId") or sp.get("toChain"), f"wh:{sp.get('toChain')}")
    recip = sp.get("toAddress")
    bc = [b for b in (t.get("balanceChanges") or []) if b.get("tokenAddress") != "native" and not str(b.get("amount", "")).startswith("-")]
    if tc == "sol" and bc: recip = bc[0].get("recipient") or recip   # Solana: owner wallet rather than the token account
    if not recip and t.get("to") and tc != "sol": recip = t.get("to")
    amt = dd.get("tokenAmount"); sym = dd.get("symbol"); usd = dd.get("usdAmount")
    ttx = (t.get("transaction") or {}).get("txHash"); done = bool(ttx) and (t.get("status") in (None, "completed", "confirmed"))
    src = side(sc, (s.get("transaction") or {}).get("txHash"), s.get("from"), amt, sym, s.get("timestamp"), usd)
    dst = side(tc, ttx, recip, amt, sym, t.get("timestamp"), usd, t.get("status"))
    return M(name, "wormholescan", "deterministic", 0.99 if done else 0.85, "completed" if done else "in flight / not redeemed", src, dst,
             f"Wormhole VAA {o.get('id')} links both transactions (api.wormholescan.io)", usd, f"https://wormholescan.io/#/tx/{src['tx']}",
             [] if done else ["Destination not redeemed yet (or redemption not indexed): recipient comes from the signed message"])
async def wormhole_tx(h):
    d = await _get(f"https://api.wormholescan.io/api/v1/operations?txHash={h}", ttl=120)
    return [_wh(o) for o in (d or {}).get("operations") or []]
async def wormhole_addr(a):
    d = await _get(f"https://api.wormholescan.io/api/v1/operations?address={a}&page=0&pageSize=25", ttl=300)
    return [_wh(o) for o in (d or {}).get("operations") or []]

# ---------------- deBridge DLN ----------------
DLN = "https://stats-api.dln.trade/api"
def _sv(x):
    if isinstance(x, dict):
        if "stringValue" in x: return x["stringValue"]
        if "bigIntegerValue" in x: return x["bigIntegerValue"]
        return {k: _sv(v) for k, v in x.items() if "logo" not in k.lower()}
    if isinstance(x, list): return [_sv(i) for i in x]
    return x
def _dln(o):
    o = _sv(o); g = o.get("giveOfferWithMetadata") or {}; t = o.get("takeOfferWithMetadata") or {}; pre = o.get("preswapData") or {}
    gc = EVM.get(int(g.get("chainId") or 0), f"dln:{g.get('chainId')}"); tc = EVM.get(int(t.get("chainId") or 0), f"dln:{t.get('chainId')}")
    def amt(x, dec): 
        try: return int(x) / 10 ** int(dec)
        except Exception: return None
    if pre.get("inAmount"):
        sa, su = amt(pre["inAmount"], (pre.get("tokenInMetadata") or {}).get("decimals", 18)), (pre.get("tokenInMetadata") or {}).get("symbol")
    else: sa, su = amt(g.get("amount"), g.get("decimals") or (g.get("metadata") or {}).get("decimals", 18)), g.get("symbol") or (g.get("metadata") or {}).get("symbol")
    ta = amt(t.get("amount"), t.get("decimals") or (t.get("metadata") or {}).get("decimals", 18)); tu = t.get("symbol") or (t.get("metadata") or {}).get("symbol")
    cr = o.get("createdSrcEventMetadata") or {}; fu = o.get("fulfilledDstEventMetadata") or {}; st = o.get("state") or o.get("status") or "?"
    done = st in ("Fulfilled", "SentUnlock", "ClaimedUnlock") and fu.get("transactionHash")
    src = side(gc, cr.get("transactionHash"), o.get("makerSrc") or cr.get("initiator"), sa, su, cr.get("blockTimeStamp"))
    dst = side(tc, fu.get("transactionHash"), o.get("receiverDst"), ta, tu, fu.get("blockTimeStamp"), status=st)
    usd = ta if (tu or "").upper() in ("USDC", "USDT") else (sa if (su or "").upper() in ("USDC", "USDT") else None)
    return M("deBridge DLN", "dln.trade", "deterministic", 0.99 if done else 0.8, "completed" if done else f"order {st}", src, dst,
             f"DLN order {o.get('orderId')} (stats-api.dln.trade): create tx on source, fulfil tx on destination", usd,
             f"https://app.debridge.finance/order?orderId={o.get('orderId')}", [] if done else [f"Order state {st}: not (yet) fulfilled"])
async def debridge_tx(h):
    d = await _get(f"{DLN}/Transaction/{h}/orderIds", ttl=120)
    ids = [_sv(x) for x in (d or {}).get("orderIds") or []][:4]
    out = []
    for i in ids:
        o = await _get(f"{DLN}/Orders/{i}", ttl=120)
        if o: out.append(_dln(o))
    return out
async def debridge_addr(a):
    d = await _post(f"{DLN}/Orders/filteredList", {"skip": 0, "take": 25, "creator": a}, ttl=300)
    return [_dln(o) for o in (d or {}).get("orders") or []]

# ---------------- Mayan ----------------
def _mayan(x):
    sc = WH.get(int(x.get("sourceChain") or 0), f"wh:{x.get('sourceChain')}"); dc = WH.get(int(x.get("destChain") or 0), f"wh:{x.get('destChain')}")
    st = x.get("clientStatus") or x.get("status"); ftx = x.get("fulfillTxHash") or x.get("redeemTxHash"); rtx = x.get("refundTxHash")
    done = st == "COMPLETED" and ftx
    price = _f(x.get("fromTokenPrice")); usd = (price * _f(x.get("fromAmount"))) if price and _f(x.get("fromAmount")) else None
    src = side(sc, x.get("sourceTxHash"), x.get("trader"), x.get("fromAmount"), x.get("fromTokenSymbol"), x.get("initiatedAt"), usd)
    if rtx and not ftx: dst = side(sc, rtx, x.get("trader"), x.get("refundAmount"), x.get("refundTokenSymbol"), x.get("completedAt"), status="refunded")
    else: dst = side(dc, ftx, x.get("destAddress"), x.get("toAmount"), x.get("toTokenSymbol"), x.get("completedAt") or x.get("statusUpdatedAt"), status=st)
    svc = x.get("service") or ""
    return M("Mayan" + (f" ({svc.replace('_', ' ').title()})" if svc else ""), "mayan.finance", "deterministic", 0.99 if done else 0.8,
             "completed" if done else ("refunded" if rtx else f"{st}".lower()), src, dst, f"Mayan swap {x.get('orderId') or x.get('id')} (explorer-api.mayan.finance)",
             usd, f"https://explorer.mayan.finance/swap/{x.get('sourceTxHash')}", ["Refunded to the sender on the source chain"] if rtx and not ftx else [])
async def mayan_tx(h):
    d = await _get(f"https://explorer-api.mayan.finance/v3/swap/trx/{h}", ttl=120)
    return [_mayan(d)] if d and d.get("sourceTxHash") else []
async def mayan_addr(a):
    d = await _get(f"https://explorer-api.mayan.finance/v3/swaps?trader={a}&limit=25", ttl=300)
    return [_mayan(x) for x in (d or {}).get("data") or []]

# ---------------- Across ----------------
TOK = {  # (chain, lower address) -> (symbol, decimals); native = zero address
 ("eth", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"): ("USDC", 6), ("eth", "0xdac17f958d2ee523a2206206994597c13d831ec7"): ("USDT", 6),
 ("eth", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"): ("WETH", 18), ("eth", "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"): ("WBTC", 8),
 ("eth", "0x6b175474e89094c44da98b954eedeac495271d0f"): ("DAI", 18),
 ("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"): ("USDC", 6), ("arb", "0xaf88d065e77c8cc2239327c5edb3a432268e5831"): ("USDC", 6),
 ("arb", "0xff970a61a04b1ca14834a43f5de4533ebddb5cc8"): ("USDC.e", 6), ("arb", "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"): ("USDT", 6),
 ("arb", "0x82af49447d8a07e3bd95bd0d56f35241523fbab1"): ("WETH", 18), ("op", "0x0b2c639c533813f4aa9d7837caf62653d097ff85"): ("USDC", 6),
 ("op", "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58"): ("USDT", 6), ("polygon", "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"): ("USDC", 6),
 ("polygon", "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"): ("USDT", 6), ("polygon", "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619"): ("WETH", 18),
 ("bsc", "0x55d398326f99059ff775485246999027b3197955"): ("USDT", 18), ("bsc", "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"): ("USDC", 18),
 ("hyperevm", "0xb88339cb7199b77e23db6e890353e22632ba630f"): ("USDC", 6), ("linea", "0x176211869ca2b568f2a7d4ee941e073a821ee1ff"): ("USDC", 6),
 ("unichain", "0x078d782b760474a361dda0af3839290b0ef57ad6"): ("USDC", 6), ("worldchain", "0x79a02482a880bce3f13e09da970dc34db4cd24d1"): ("USDC", 6),
 ("sol", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"): ("USDC", 6), ("sol", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"): ("USDT", 6),
 ("sol", "So11111111111111111111111111111111111111112"): ("SOL", 9),
}
def _tok(c, addr):
    a = str(addr or ""); k = (c, a if c == "sol" else a.lower())
    if k in TOK: return TOK[k]
    if re.fullmatch(r"0x0{40}", a.lower()) or (is_evm(c) and a.lower() == "0x4200000000000000000000000000000000000006"): return ("ETH" if c not in ("bsc", "polygon", "avax") else {"bsc": "BNB", "polygon": "POL", "avax": "AVAX"}[c]) if a.lower().startswith("0x000") else "WETH", 18
    return None
def _across(x):
    oc = EVM.get(int(x.get("originChainId") or 0), f"evm:{x.get('originChainId')}"); dc = EVM.get(int(x.get("destinationChainId") or 0), f"evm:{x.get('destinationChainId')}")
    ti, to_ = _tok(oc, x.get("inputToken")), _tok(dc, x.get("outputToken"))
    ia = int(x["inputAmount"]) / 10 ** ti[1] if ti and x.get("inputAmount") else None; oa = int(x["outputAmount"]) / 10 ** to_[1] if to_ and x.get("outputAmount") else None
    iu = ti[0] if ti else "token " + str(x.get("inputToken"))[:8]; ou = to_[0] if to_ else "token " + str(x.get("outputToken"))[:8]
    usd = (ia * _f(x.get("inputPriceUsd"))) if ia and _f(x.get("inputPriceUsd")) else (ia if iu in ("USDC", "USDT", "DAI", "USDC.e") else None)
    st = x.get("status"); fill = x.get("fillTx") or x.get("fillTxnRef"); rf = x.get("depositRefundTxHash") or x.get("depositRefundTxnRef")
    src = side(oc, x.get("depositTxHash") or x.get("depositTxnRef"), x.get("depositor"), ia, iu, x.get("depositBlockTimestamp"), usd)
    if rf and not fill: dst = side(oc, rf, x.get("depositor"), ia, iu, None, status="refunded")
    else: dst = side(dc, fill, x.get("recipient"), oa, ou, x.get("fillBlockTimestamp"), status=st)
    notes = []
    if (x.get("message") or "0x") not in ("0x", "", None): notes.append("Deposit carries a message: the recipient may be a contract that forwards funds again (e.g. an aggregator)")
    if not ti or not to_: notes.append("Token decimals unknown to ChainTrace: amount not shown")
    return M("Across", "across.to", "deterministic", 0.99 if st == "filled" and fill else 0.8, "completed" if st == "filled" else (st or "?"), src, dst,
             f"Across deposit {x.get('depositId') or x.get('id')} on {cname(oc)} filled by relayer (app.across.to)", usd,
             f"https://app.across.to/transactions", notes)
async def across_tx(h):
    if not _hex_ok(h) and not _sol_ok(h): return []
    d = await _get(f"https://app.across.to/api/deposit?depositTxHash={h}", ttl=120)
    dep = (d or {}).get("deposit")
    return [_across(dep)] if dep else []
async def across_addr(a):
    out = []
    for k in ("depositor", "recipient"):
        d = await _get(f"https://app.across.to/api/deposits?{k}={a}&limit=25", ttl=300)
        out += [_across(x) for x in (d if isinstance(d, list) else [])]
    return out

# ---------------- THORChain / Maya (Midgard) ----------------
MIDGARD = {"THORChain": ["https://gateway.liquify.com/chain/thorchain_midgard/v2", "https://vanaheimex.com"], "Maya Protocol": ["https://midgard.mayachain.info/v2"]}
def _asset(a):
    a = str(a or ""); sep = "." if "." in a else ("~" if "~" in a else ("-" if a.count("-") else "."))
    ch, _, rest = a.partition(".") if "." in a else a.partition("~")
    sym = rest.split("-")[0] if rest else ch
    return THOR.get(ch.upper(), ch.lower()), sym
def _mid(a, name, inq=None):
    ins = a.get("in") or []; outs = a.get("out") or []; meta = a.get("metadata") or {}; sw = meta.get("swap") or meta.get("refund") or {}
    memo = sw.get("memo") or ""; dest = memo.split(":")[2] if memo.count(":") >= 2 else None
    i = next((x for x in ins if not inq or x.get("txID", "").upper() == inq), ins[0] if ins else {})
    coin = (i.get("coins") or [{}])[0]; ic, isym = _asset(coin.get("asset"))
    cand = [o for o in outs if o.get("txID") and o.get("txID").strip("0")]
    o = next((x for x in cand if dest and x.get("address", "").lower() == dest.lower()), None) or next((x for x in cand if not (x.get("coins") or [{}])[0].get("asset", "").startswith(("THOR.", "MAYA."))), None) or (cand[0] if cand else None)
    if not o and outs: o = next((x for x in outs if dest and x.get("address", "").lower() == dest.lower()), None)
    t = int(a.get("date") or 0) / 1e9 or None
    px = _f(sw.get("inPriceUSD")); iamt = int(coin.get("amount") or 0) / 1e8; usd = px * iamt if px else None
    src = side(ic, i.get("txID"), i.get("address"), iamt, isym, t, usd)
    if o:
        oc_ = (o.get("coins") or [{}])[0]; oc, osym = _asset(oc_.get("asset"))
        dst = side(oc, o.get("txID") if (o.get("txID") or "").strip("0") else None, o.get("address"), int(oc_.get("amount") or 0) / 1e8, osym, t, status=a.get("status"))
    else:
        tgt = memo.split(":")[1] if memo.count(":") >= 1 else ""
        dst = side(_asset(tgt)[0] if "." in tgt else "?", None, dest, None, None, None, status=a.get("status"))
    done = a.get("status") == "success" and dst.get("tx")
    typ = a.get("type"); refund = typ == "refund"
    return M(name + (" swap" if typ == "swap" else f" {typ}"), "midgard", "deterministic", 0.99 if done else 0.8,
             "refunded" if refund else ("completed" if done else (a.get("status") or "?")), src, dst,
             f"{name} {typ} at height {a.get('height')}: inbound tx + memo '{memo[:60]}' -> outbound tx signed by the network (Midgard)", usd,
             (f"https://runescan.io/tx/{(i.get('txID') or '')}" if name == "THORChain" else f"https://www.explorer.mayachain.info/tx/{i.get('txID')}"),
             (["Refund: the swap failed and funds were returned"] if refund else []) + (["Outbound not sent yet (streaming / scheduled)"] if not done and not refund else []))
async def _midgard(name, q):
    last = None
    for base in MIDGARD[name]:
        try: return await _get(f"{base}/actions?{q}", ttl=120)
        except Exception as e: last = e
    raise last or Exception("midgard unavailable")
async def midgard_tx(h):
    q = h.upper().removeprefix("0X") if (_hex_ok(h) or _btc_ok(h)) else h
    if not (_hex_ok(h) or _btc_ok(h)): return []
    out = []
    for name in MIDGARD:
        try: d = await asyncio.wait_for(_midgard(name, f"txid={q}"), 8)
        except Exception: continue
        out += [_mid(a, name, q) for a in (d or {}).get("actions") or [] if a.get("type") in ("swap", "refund")]
    return out
async def midgard_addr(a):
    out = []
    for name in MIDGARD:
        try: d = await asyncio.wait_for(_midgard(name, f"address={a}&limit=25"), 8)
        except Exception: continue
        out += [_mid(x, name) for x in (d or {}).get("actions") or [] if x.get("type") in ("swap", "refund")]
    return out

# ---------------- LayerZero / Stargate ----------------
SG_ASSET = {1: "USDC", 2: "USDT", 13: "ETH", 14: "METIS", 15: "mETH"}
def _lz_payload(p):
    """Stargate v2 taxi: type(1)=1 | assetId(2) | receiver(32) | amountSD(8) | compose. Generic OFT: sendTo(32) | amountSD(8) | compose."""
    try: b = bytes.fromhex((p or "").removeprefix("0x"))
    except Exception: return None, None, None
    if len(b) >= 43 and b[0] == 1: return "0x" + b[3:35].hex(), int.from_bytes(b[35:43], "big") / 1e6, SG_ASSET.get(int.from_bytes(b[1:3], "big"))
    if len(b) >= 40 and b[:12] == b"\x00" * 12: return "0x" + b[12:32].hex(), None, None
    return None, None, None
def _lz(x, txh):
    pw = x.get("pathway") or {}; s = x.get("source") or {}; d = x.get("destination") or {}
    sc = LZ.get(((pw.get("sender") or {}).get("chain") or "").lower(), (pw.get("sender") or {}).get("chain") or f"lz:{pw.get('srcEid')}")
    dc = LZ.get(((pw.get("receiver") or {}).get("chain") or "").lower(), (pw.get("receiver") or {}).get("chain") or f"lz:{pw.get('dstEid')}")
    app = (pw.get("sender") or {}).get("name") or (pw.get("sender") or {}).get("id") or "LayerZero app"
    stx = (s.get("tx") or {}); dtx = (d.get("tx") or {}); st = d.get("status") or (x.get("status") or {}).get("name")
    rec, amt, sym = (None, None, None)
    if "stargate" in str((pw.get("sender") or {}).get("id") or "").lower() or True: rec, amt, sym = _lz_payload(stx.get("payload"))
    notes = []
    if dc == "sol" or sc == "sol": rec = None
    if not rec: notes.append("Recipient not decoded from the message payload: open the destination tx")
    comp = (d.get("lzCompose") or {}).get("txs") or []
    if comp: notes.append("Message triggers a compose call on the destination: funds may be forwarded again by a contract")
    done = st == "SUCCEEDED" and dtx.get("txHash")
    src = side(sc, stx.get("txHash"), stx.get("from"), amt, sym, stx.get("blockTimestamp"), amt if sym in ("USDC", "USDT") else None)
    dst = side(dc, dtx.get("txHash"), rec, amt, sym, dtx.get("blockTimestamp"), status=st)
    return M(f"{app} (LayerZero)", "layerzeroscan", "deterministic", 0.97 if done else 0.75, "completed" if done else (st or "?").lower(), src, dst,
             f"LayerZero message {pw.get('srcEid')}→{pw.get('dstEid')} nonce {pw.get('nonce')} (scan.layerzero-api.com)", src.get("usd"),
             f"https://layerzeroscan.com/tx/{stx.get('txHash')}", notes)
async def layerzero_tx(h):
    if not _hex_ok(h) and not _sol_ok(h): return []
    d = await _get(f"https://scan.layerzero-api.com/v1/messages/tx/{h}", ttl=120)
    return [_lz(x, h) for x in (d or {}).get("data") or []][:5]
async def layerzero_addr(a):
    d = await _get(f"https://scan.layerzero-api.com/v1/messages/wallet/{a}?limit=25", ttl=300)
    return [_lz(x, None) for x in (d or {}).get("data") or []]

# ---------------- Relay (v2 public endpoint; retiring 24 Nov 2026) ----------------
def _relay(r):
    d = r.get("data") or {}; m = d.get("metadata") or {}; ci = m.get("currencyIn") or {}; co = m.get("currencyOut") or {}
    it = (d.get("inTxs") or [{}])[0]; ot = (d.get("outTxs") or [{}])[0]
    ic = EVM.get(int(it.get("chainId") or (ci.get("currency") or {}).get("chainId") or 0), f"evm:{it.get('chainId')}")
    oc = EVM.get(int(ot.get("chainId") or (co.get("currency") or {}).get("chainId") or 0), f"evm:{ot.get('chainId')}")
    st = r.get("status"); done = st == "success" and ot.get("hash")
    src = side(ic, it.get("hash"), r.get("user") or m.get("sender"), ci.get("amountFormatted"), (ci.get("currency") or {}).get("symbol"), it.get("timestamp"), ci.get("amountUsd"))
    dst = side(oc, ot.get("hash"), r.get("recipient") or m.get("recipient"), co.get("amountFormatted"), (co.get("currency") or {}).get("symbol"), ot.get("timestamp"), co.get("amountUsd"), st)
    return M("Relay", "relay.link", "deterministic", 0.98 if done else 0.75, "completed" if done else (st or "?"), src, dst,
             f"Relay request {r.get('id')} (api.relay.link): solver fill linked to the deposit", ci.get("amountUsd"), f"https://relay.link/transaction/{r.get('id')}",
             ["Solver-filled: the destination funds come from the solver's own wallet, not from the bridge contract"])
async def _relay_get(url, ttl):
    """single attempt, no 429 back-off loop: the public v2 endpoint is rate-limited, fail fast instead of holding the request"""
    k = ("GET", url, "{}")
    if k in chains._cache and time.time() - chains._cache[k][0] < ttl: return chains._cache[k][1]
    r = await chains.client.get(url, timeout=6)
    if r.status_code == 429: raise Exception("Relay public API rate limited")
    if r.status_code in (400, 404): return None
    r.raise_for_status(); d = r.json(); chains._cache[k] = (time.time(), d); return d
async def relay_tx(h):
    d = await _relay_get(f"https://api.relay.link/requests/v2?hash={h}", ttl=120)
    return [_relay(r) for r in (d or {}).get("requests") or []][:3]
async def relay_addr(a):
    d = await _relay_get(f"https://api.relay.link/requests/v2?user={a}&limit=20", ttl=300)
    return [_relay(r) for r in (d or {}).get("requests") or []]

# ---------------- registry ----------------
TX_PROVIDERS = {  # name -> (fn, which hash formats)
 "wormhole": (wormhole_tx, ("eth", "sol")), "debridge": (debridge_tx, ("eth", "sol")), "mayan": (mayan_tx, ("eth", "sol")),
 "across": (across_tx, ("eth",)), "thorchain/maya": (midgard_tx, ("eth", "btc")), "layerzero": (layerzero_tx, ("eth",)), "relay": (relay_tx, ("eth", "sol", "btc")),
}
ADDR_PROVIDERS = {
 "wormhole": (wormhole_addr, ("eth", "sol")), "debridge": (debridge_addr, ("eth", "sol")), "mayan": (mayan_addr, ("eth", "sol")),
 "across": (across_addr, ("eth",)), "thorchain/maya": (midgard_addr, ("eth", "btc")), "layerzero": (layerzero_addr, ("eth",)), "relay": (relay_addr, ("eth", "sol")),
}
SUPPORTED = [
 {"bridge": "Wormhole (Portal, NTT, CCTP, Connect)", "chains": "ETH, SOL, L2s, BSC, …", "method": "deterministic", "source": "api.wormholescan.io"},
 {"bridge": "deBridge DLN", "chains": "ETH, SOL, L2s, BSC", "method": "deterministic", "source": "stats-api.dln.trade"},
 {"bridge": "Mayan (Swift, MCTP, WH)", "chains": "ETH, SOL, L2s", "method": "deterministic", "source": "explorer-api.mayan.finance"},
 {"bridge": "Across", "chains": "ETH, L2s (deposit side lookup)", "method": "deterministic", "source": "app.across.to"},
 {"bridge": "THORChain / Maya", "chains": "BTC, ETH, BSC, AVAX, DOGE, LTC, …", "method": "deterministic (memo swaps)", "source": "Midgard"},
 {"bridge": "LayerZero / Stargate", "chains": "ETH, L2s, BSC", "method": "deterministic (message id)", "source": "scan.layerzero-api.com"},
 {"bridge": "Relay", "chains": "ETH, SOL, BTC, L2s", "method": "deterministic (best effort, v2 API retiring 24 Nov 2026)", "source": "api.relay.link"},
 {"bridge": "Any other bridge (ERC-20 USDC/USDT/WETH/WBTC to Arbitrum, Optimism, Base, Polygon)", "chains": "ETH → L2", "method": "heuristic: lead only", "source": "public RPC eth_getLogs"},
]
PROV_T = float(os.environ.get("CHAINTRACE_BRIDGE_PROVIDER_TIMEOUT", "9"))
def _bdb():
    chains.DB.execute("CREATE TABLE IF NOT EXISTS bridge(k TEXT PRIMARY KEY, ts REAL, ttl REAL, v TEXT)"); return chains.DB
def _cget(k):
    try:
        r = _bdb().execute("SELECT ts, ttl, v FROM bridge WHERE k=?", (k,)).fetchone()
        if r and time.time() - r[0] < r[1]: return json.loads(r[2])
    except Exception: pass
    return None
def _cput(k, v, ttl):
    try: _bdb().execute("INSERT OR REPLACE INTO bridge VALUES(?,?,?,?)", (k, time.time(), ttl, json.dumps(v))); chains.DB.commit()
    except Exception as e: print("bridge cache write failed", e)
def _dedupe(ms):
    seen = {}; 
    for m in ms:
        k = (m["src"].get("tx"), m["dst"].get("tx"), m["dst"].get("address"), m["src"].get("amount"))
        if k not in seen or m["confidence"] > seen[k]["confidence"]: seen[k] = m
    return list(seen.values())
async def _run(provs, arg, fmt):
    names = [n for n, (_, fm) in provs.items() if fmt in fm]
    async def cap(n):
        try: return await asyncio.wait_for(provs[n][0](arg), PROV_T), None
        except asyncio.TimeoutError: return None, f"timed out after {PROV_T:g}s"
        except Exception as e: return None, (str(e) or type(e).__name__)[:120]
    res = (await asyncio.gather(*[cap(n) for n in names], chains.ensure_prices()))[:-1]
    out, tried = [], []
    for n, (v, err) in zip(names, res):
        tried.append({"provider": n, "ok": err is None, "matches": len(v or []), "error": err})
        out += v or []
    return _dedupe(out), tried
async def match_tx(h, chain=None, heuristic=True):
    """all bridge transfers linked to transaction h (either side). Deterministic first; heuristic fallback only if none."""
    h = h.strip(); fmt = chain or ("eth" if _hex_ok(h) else "btc" if _btc_ok(h) else "sol" if _sol_ok(h) else None)
    if not fmt: raise ValueError("not a transaction hash")
    if fmt == "eth": h = h.lower()
    always = heuristic == "always"
    k = f"tx:{h}" + (":h" if always else ""); c = _cget(k)
    if c: c["cached"] = True; return c
    ms, tried = await _run(TX_PROVIDERS, h, fmt)
    hn = h.lower().removeprefix("0x")
    ms = [m for m in ms if hn in ((m["src"].get("tx") or "").lower().removeprefix("0x"), (m["dst"].get("tx") or "").lower().removeprefix("0x"))]   # indexer must echo our hash
    PN = {"wormholescan": "wormhole", "dln.trade": "debridge", "mayan.finance": "mayan", "across.to": "across", "midgard": "thorchain/maya", "layerzeroscan": "layerzero", "relay.link": "relay"}
    for t in tried: t["matches"] = sum(1 for m in ms if PN.get(m["provider"]) == t["provider"])
    for m in ms: m["side"] = "src" if (m["src"].get("tx") or "").lower() == h.lower() else ("dst" if (m["dst"].get("tx") or "").lower() == h.lower() else "src")
    res = {"query": h, "chain": fmt, "kind": "tx", "matches": ms, "tried": tried, "heuristic": [], "heuristic_note": None}
    if (always or (not ms and heuristic)) and fmt == "eth":
        try: res["heuristic"], res["heuristic_note"] = await asyncio.wait_for(heuristic_eth(h), 14)
        except asyncio.TimeoutError: res["heuristic_note"] = "heuristic search timed out"
        except Exception as e: res["heuristic_note"] = f"heuristic search failed: {type(e).__name__}: {e}"
    done = ms and all(m["status"] in ("completed", "refunded") for m in ms)
    errs = any(not t["ok"] for t in tried)
    _cput(k, res, 30 * 86400 if done else (600 if not ms and not errs else 90))
    return res
async def match_address(a, chain):
    a = a.strip(); k = f"addr:{chain}:{a.lower() if chain == 'eth' else a}"; c = _cget(k)
    if c: c["cached"] = True; return c
    ms, tried = await _run(ADDR_PROVIDERS, a, chain)
    al = a.lower() if chain == "eth" else a
    for m in ms:
        sa = (m["src"].get("address") or ""); da = (m["dst"].get("address") or "")
        m["side"] = "src" if (sa.lower() if chain == "eth" else sa) == al else ("dst" if (da.lower() if chain == "eth" else da) == al else "src")
    ms.sort(key=lambda m: -(m["src"].get("time") or m["dst"].get("time") or 0))
    res = {"query": a, "chain": chain, "kind": "address", "matches": ms[:60], "tried": tried}
    _cput(k, res, 600 if not any(not t["ok"] for t in tried) else 90)
    return res

# ---------------- heuristic: same address, same asset, amount within fee tolerance, time window (ETH -> L2) ----------------
H_RPC = {"arb": ["https://arb1.arbitrum.io/rpc"], "op": ["https://mainnet.optimism.io"], "base": ["https://base.gateway.tenderly.co", "https://base-rpc.publicnode.com"],
         "polygon": ["https://polygon.gateway.tenderly.co", "https://polygon-bor-rpc.publicnode.com"]}
H_STEP = {"base": 1000, "polygon": 3000, "arb": 30000, "op": 4000}
H_TOK = {"USDC": {"arb": "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "op": "0x0b2c639c533813f4aa9d7837caf62653d097ff85", "base": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "polygon": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"},
         "USDT": {"arb": "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9", "op": "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58", "polygon": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"},
         "WETH": {"arb": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1", "op": "0x4200000000000000000000000000000000000006", "base": "0x4200000000000000000000000000000000000006", "polygon": "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619"},
         "WBTC": {"arb": "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f", "op": "0x68f180fcce6836688e9084f035309e29bf0a2095", "polygon": "0x1bfd67037b42cf73acf2047067bd4f2c47d9bfd6"}}
DEC = {"USDC": 6, "USDT": 6, "WETH": 18, "WBTC": 8}
ALIAS = {"USDC": "USDC", "USDC.E": "USDC", "USDT": "USDT", "WETH": "WETH", "ETH": "WETH", "WBTC": "WBTC"}
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
WINDOW = 3 * 3600; TOL = 0.05
async def _rpc(c, method, params):
    last = None
    for u in H_RPC[c]:
        try: return await chains.rpc(u, method, params, ttl=60 if method == "eth_blockNumber" else 86400)
        except Exception as e: last = e
    raise last or Exception("no rpc")
async def _block_at(c, ts):
    head = int(await _rpc(c, "eth_blockNumber", []), 16)
    hb = await _rpc(c, "eth_getBlockByNumber", [hex(head), False]); ht = int(hb["timestamp"], 16)
    probe = max(1, head - 200000); pb = await _rpc(c, "eth_getBlockByNumber", [hex(probe), False]); pt = int(pb["timestamp"], 16)
    bt = (ht - pt) / (head - probe) or 1
    est = int(head - (ht - ts) / bt); est = max(1, min(head, est))
    eb = await _rpc(c, "eth_getBlockByNumber", [hex(est), False]); et = int(eb["timestamp"], 16)
    est = int(est - (et - ts) / bt); return max(1, min(head, est)), bt, head
async def _scan(c, token, to, t0, sym, amount):
    b0, bt, head = await _block_at(c, t0); b1 = min(head, b0 + int(WINDOW / bt) + 1); step = H_STEP[c]; out = []
    topic = "0x" + "0" * 24 + to.lower()[2:]
    rng = list(range(b0, b1 + 1, step))[:12]
    async def one(f):
        return await _rpc(c, "eth_getLogs", [{"address": token, "fromBlock": hex(f), "toBlock": hex(min(b1, f + step - 1)), "topics": [TRANSFER, None, topic]}])
    res = await asyncio.gather(*[chains._cap(one(f), 8) for f in rng])
    errs = sum(1 for v, e in res if e)
    for v, e in res:
        for lg in v or []:
            try: val = int(lg["data"], 16) / 10 ** DEC[sym]
            except Exception: continue
            if amount * (1 - TOL) <= val <= amount * 1.0005: out.append((c, lg, val))
    return out, errs, len(rng)
async def heuristic_eth(h):
    """ETH-mainnet tx sending a bridgeable ERC-20 into a bridge: look for the same asset arriving at the same address on L2s shortly after."""
    d = await asyncio.wait_for(chains.TX["eth"](h), 9)
    t0 = chains.ts_of(d.get("time"))
    by = {n["id"]: n for n in d["nodes"]}
    sender = next((e["source"] for e in d["edges"] if e["target"] == "tx:" + h), None)
    legs = []
    for e in d["edges"]:
        sym = ALIAS.get((e.get("unit") or "").upper()); tgt = by.get(e["target"]) or {}
        if not sym or not e.get("amount"): continue
        if e["source"].lower() != (sender or "").lower(): continue
        legs.append((sym, float(e["amount"]), e["target"], tgt.get("kind") == "bridge"))
    legs.sort(key=lambda x: (not x[3], -x[1]))   # transfers into a labelled bridge first
    if not t0 or not sender: return [], "source transaction details unavailable"
    if not legs:
        return [], "no USDC/USDT/WETH/WBTC (or native ETH) leaving the sender in this tx, so there is nothing to match heuristically"
    out = []; notes = []
    for sym, amt, via, _ in legs[:2]:
        tasks = [(c, H_TOK[sym][c]) for c in H_RPC if c in H_TOK.get(sym, {})]
        if sym == "WETH": notes.append("native-ETH arrivals on L2s are invisible to log scans; only WETH transfers are checked")
        res = await asyncio.gather(*[chains._cap(_scan(c, tok, sender, t0, sym, amt), 12) for c, tok in tasks])
        for (c, _), (v, err) in zip(tasks, res):
            if err: notes.append(f"{cname(c)}: scan failed ({err})"); continue
            hits, errs, n = v
            if errs: notes.append(f"{cname(c)}: {errs}/{n} log chunks failed")
            for _, lg, val in hits:
                gap = abs(1 - val / amt)
                bn = int(lg["blockNumber"], 16)
                try: tb = int((await _rpc(c, "eth_getBlockByNumber", [hex(bn), False]))["timestamp"], 16)
                except Exception: tb = None
                dt = (tb - t0) if tb else None
                if dt is not None and (dt < 0 or dt > WINDOW): continue
                conf = 0.35 + 0.15 * (1 - gap / TOL) + (0.1 * (1 - dt / WINDOW) if dt is not None else 0)
                src = side("eth", h, sender, amt, sym, t0, amt if sym in ("USDC", "USDT") else None)
                dst = side(c, lg["transactionHash"], sender, val, sym, tb)
                out.append(M("Unknown bridge (heuristic)", "rpc-logs", "heuristic", min(conf, 0.6), "candidate", src, dst,
                             f"Same address received {val:g} {sym} on {cname(c)} {int(dt/60) if dt is not None else '?'} min later; amount within {gap*100:.2f}% of the {amt:g} sent (fee tolerance {TOL*100:.0f}%)",
                             src.get("usd"), None, ["Heuristic lead only: amount + time + same address coincidence, NOT a protocol-level link. Verify before relying on it."]))
    if len(out) > 1:
        for m in out: m["confidence"] = round(max(0.15, m["confidence"] - 0.1 * (len(out) - 1)), 2); m["notes"].append(f"{len(out)} candidates found: ambiguity lowers confidence")
    out.sort(key=lambda m: -m["confidence"])
    return out[:5], ("; ".join(dict.fromkeys(notes)) or None) if out or notes else "no matching arrival on Arbitrum, Optimism, Base or Polygon within 3h (same address, ±5%)"

# ---------------- graph fragment ----------------
def fragment(m, anchor=None, which="dst"):
    """nodes + one cross-chain edge for a match. Default: anchor (or source address) -> destination recipient."""
    s, d = m["src"], m["dst"]
    def mk(sd):
        a = sd.get("address")
        if not a and sd.get("tx"): nid = node_id(sd["chain"], "tx:" + sd["tx"]) if sd["chain"] not in NATIVE else "tx:" + sd["tx"]; n = {"id": nid, "chain": sd["chain"], "kind": "tx", "name": f"{cname(sd['chain'])} tx {sd['tx'][:10]}", "tags": [], "risk": 0}
        elif not a: return None
        elif sd["chain"] in NATIVE: n = chains.node(sd["chain"], a); nid = n["id"]
        else: nid = node_id(sd["chain"], a); n = {"id": nid, "chain": sd["chain"], "name": None, "kind": None, "tags": [], "risk": 0}
        n["foreign"] = sd["chain"] not in NATIVE; n["chain_name"] = cname(sd["chain"]); n["address_url"] = sd.get("address_url"); return n
    if which == "src":   # we are on the destination side: link source sender -> anchor
        sn = mk(s); dn = None; tgt = anchor or (mk(d) or {}).get("id")
        if not sn or not tgt: return [], []
        nodes = [sn] + ([] if anchor else [mk(d)]); src_id, dst_id = sn["id"], tgt
    else:
        dn = mk(d); src_id = anchor or (mk(s) or {}).get("id")
        if not dn or not src_id: return [], []
        nodes = [dn] + ([] if anchor else [mk(s)]); dst_id = dn["id"]
    amt = d.get("amount") if d.get("amount") is not None else s.get("amount"); unit = d.get("unit") or s.get("unit") or ""
    e = {"source": src_id, "target": dst_id, "amount": amt or 0, "unit": f"{unit}⇄", "usd": m.get("usd"), "tx": s.get("tx"), "dst_tx": d.get("tx"),
         "time": s.get("time"), "count": 1, "xchain": True, "bridge": {k: v for k, v in m.items() if k != "graph"}}
    return [n for n in nodes if n], [e]

# ---------------- live THORChain / Maya vault labels (vaults rotate, so fetched from the nodes, cached 1h) ----------------
VAULTS = {}; _vts = [0.0]
VAULT_SRC = [("THORChain", "https://gateway.liquify.com/chain/thorchain_api/thorchain/inbound_addresses"), ("Maya Protocol", "https://mayanode.mayachain.info/mayachain/inbound_addresses")]
async def refresh_vaults():
    if time.time() - _vts[0] < 3600: return VAULTS
    _vts[0] = time.time(); new = {}
    for name, u in VAULT_SRC:
        try: d = await asyncio.wait_for(_get(u, ttl=3600), 5)
        except Exception as e: print("vault fetch failed", name, e); _vts[0] = time.time() - 3300; continue
        for x in d or []:
            c = THOR.get(x.get("chain"))
            if c not in NATIVE: continue
            for a, what in ((x.get("address"), "vault"), (x.get("router"), "router")):
                if a: new[(c, a.lower() if c == "eth" else a)] = f"{name} {what} ({x.get('chain')})"
    if new: VAULTS.clear(); VAULTS.update(new)
    return VAULTS
KNOWN = {  # bridge contracts the bundled label set misses (names verified against Blockscout contract names / bridge docs)
 ("eth", "0xef4fb24ad0916217251f553c0596f8edc630eb66"): "deBridge: DlnSource", ("eth", "0xe7351fd770a37282b91d153ee690b63579d6dd7f"): "deBridge: DlnDestination",
 ("eth", "0x337685fdab40d39bd02028545a4ffa7d287cc3e2"): "Mayan: Forwarder", ("eth", "0xc38e4e6a15593f908255214653d3d947ca1c2338"): "Mayan: Swift",
 ("eth", "0xa5f565650890fba1824ee0f21ebbbf660a179934"): "Relay: Receiver", ("eth", "0xd37bbe5744d730a1d98d8dc97c42f0ca46ad7146"): "THORChain: Router",
}
def decorate_vault(n, chain):
    """label a current THORChain/Maya inbound vault/router as a bridge endpoint (only if the node has no stronger label)"""
    a = n.get("id") or ""; k = (chain, a.lower() if chain == "eth" else a)
    nm = VAULTS.get(k) or KNOWN.get(k)
    if nm and not n.get("kind"):
        n.update(kind="bridge", name=nm, risk=max(n.get("risk") or 0, 5), tags=sorted(set(n.get("tags") or []) | {"bridge"}))
        n["sources"] = list(n.get("sources") or []) + [{"source": "thornode inbound_addresses" if k in VAULTS else "chaintrace bridge list", "name": nm, "category": "bridge",
                                                        "licence": "public node API" if k in VAULTS else "contract names from Blockscout / bridge docs", "confidence": 0.95 if k in VAULTS else 0.9}]
    return n

# ---------------- AutoTrace helper ----------------
async def hop(chain, node_id_, edge, direction):
    """deterministic cross-chain continuation for an AutoTrace edge that reached a bridge.
    forward: edge = a -> bridge, find where it landed; backward: edge = bridge -> a, find where it came from."""
    out = []
    h = edge.get("tx")
    if not h: return out
    try: r = await asyncio.wait_for(match_tx(h, None, heuristic=False), 20)
    except Exception: return out
    want = "src" if direction == "forward" else "dst"
    for m in r.get("matches", []):
        if m["method"] != "deterministic" or m["confidence"] < 0.95 or m.get("side") != want: continue
        nodes, edges = fragment(m, node_id_, "dst" if want == "src" else "src")
        if nodes and edges: out.append((m, nodes, edges))
    return out
