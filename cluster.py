"""ChainTrace BTC address clustering (v23): "likely same wallet".

Common-input-ownership heuristic: all inputs of one transaction are usually controlled by one wallet, so addresses that
co-spend are grouped. Transactions that look like CoinJoins (many equal outputs; Wasabi, Whirlpool, JoinMarket shapes)
are skipped, because there the inputs belong to many different people. Optionally the change-address heuristic from
peel.py adds the likely change output (only at high confidence). The search is bounded (transactions, addresses, time).

Everything here is a HEURISTIC LEAD, not attribution: CoinJoin variants that are not recognised, PayJoin, custodial
services (exchanges spend many customers' coins together) and shared wallets all break the heuristic."""
import asyncio, time
from collections import Counter
import chains

LEAD = "Heuristic lead – not attribution. Likely same wallet by the common-input heuristic; corroborate before relying on it."
METHOD = ("Common-input-ownership heuristic: the input addresses of one transaction are assumed to be controlled by the same wallet. "
          "Transactions that look like CoinJoins are excluded: Whirlpool (5 inputs / 5 equal outputs at a pool denomination), Wasabi "
          "(10+ equal outputs, or 50+ inputs and outputs in standard denominations), JoinMarket (3+ equal outputs with at least as many inputs "
          "and up to one change output per participant) and any transaction where at least half of the outputs (3 or more) have the same value. "
          "Optional: the likely change output of the address's own spends (peel.py change heuristics, high confidence only). "
          "Custodial services (exchanges) and unrecognised CoinJoin / PayJoin transactions defeat the heuristic: a cluster that contains a "
          "labelled service is flagged. The search is capped (transactions, addresses, time) and may be incomplete.")
WHIRLPOOL = {100000, 1000000, 5000000, 50000000, 25000000}   # 0.001 / 0.01 / 0.05 / 0.5 BTC pools (+ the retired 0.25)
SERVICE = {"exchange", "bridge", "mixer", "gambling", "defi", "payment"}

def coinjoin(tx):
    """-> reason string if the tx looks like a CoinJoin, else None"""
    vin = [v for v in tx.get("vin") or [] if not v.get("is_coinbase")]
    vals = [o.get("value") or 0 for o in tx.get("vout") or [] if (o.get("value") or 0) > 0]
    if len(vin) < 2 or len(vals) < 2: return None
    big = [x for x in vals if x >= 5000]          # ignore dust (546-sat outputs of token / inscription transactions are not mixes)
    if len(big) < 2: return None
    v, k = Counter(big).most_common(1)[0]
    ni, no = len(vin), len(vals)
    if ni == 5 and no == 5 and k == 5 and v in WHIRLPOOL: return f"Whirlpool-style mix (5 inputs, 5 outputs of {v/1e8:g} BTC)"
    if k >= 10: return f"Wasabi-style CoinJoin ({k} equal outputs of {v/1e8:g} BTC)"
    if ni >= 50 and no >= 50: return f"Wasabi 2-style CoinJoin ({ni} inputs, {no} outputs)"
    if k >= 3 and ni >= k and no <= 2 * k: return f"JoinMarket-style CoinJoin ({k} equal outputs of {v/1e8:g} BTC, {ni} inputs)"
    if k >= 3 and k * 2 >= no: return f"many equal outputs ({k} of {no} outputs are {v/1e8:g} BTC)"
    return None

def _ins(tx): return [(v.get("prevout") or {}).get("scriptpubkey_address") for v in tx.get("vin") or [] if not v.get("is_coinbase")]

async def _txs(a, pages, deadline):
    out, cur = [], None
    for _ in range(pages):
        if time.time() > deadline: break
        try: txs, cur = await asyncio.wait_for(chains.btc_page(a, cur), max(1.0, deadline - time.time()))
        except Exception: break
        out += txs
        if not cur: break
    return out

async def cluster(root, depth=2, max_txs=200, max_addrs=150, pages=2, max_secs=25.0, use_change=False, change_conf=0.85, max_change=10):
    t0 = time.time(); deadline = t0 + max_secs
    M = {root: {"address": root, "reason": "root", "hop": 0, "tx": None}}
    skipped, scanned, seen_tx, notes = [], 0, set(), []
    frontier, truncated = [root], None
    changes_done = 0
    sem = asyncio.Semaphore(4)
    async def fetch(a):
        async with sem: return a, await _txs(a, pages, deadline)
    for hop in range(1, depth + 1):
        if not frontier: break
        res = await asyncio.gather(*[fetch(a) for a in frontier])
        nxt = []
        for a, txs in res:
            for tx in txs:
                if tx["txid"] in seen_tx: continue
                if scanned >= max_txs: truncated = truncated or f"transaction cap ({max_txs}) reached"; break
                seen_tx.add(tx["txid"]); scanned += 1
                ins = _ins(tx)
                if a not in ins: continue     # only the address's own spends say anything about its wallet
                cj = coinjoin(tx)
                if cj: skipped.append({"tx": tx["txid"], "why": cj, "time": tx["status"].get("block_time")}); continue
                for x in ins:
                    if x and x not in M:
                        if len(M) >= max_addrs: truncated = truncated or f"address cap ({max_addrs}) reached"; break
                        M[x] = {"address": x, "reason": "common-input", "hop": hop, "tx": tx["txid"], "with": a, "time": tx["status"].get("block_time")}; nxt.append(x)
                if use_change and changes_done < max_change and time.time() < deadline - 3:
                    changes_done += 1
                    try:
                        import peel
                        A = await asyncio.wait_for(peel.analyse(tx, {}), max(1.0, min(8.0, deadline - time.time() - 1)))
                        ch = peel.pick(A, change_conf)
                        if ch and ch["address"] not in M and len(M) < max_addrs:
                            M[ch["address"]] = {"address": ch["address"], "reason": "change", "hop": hop, "tx": tx["txid"], "with": a, "time": tx["status"].get("block_time"),
                                                "confidence": ch["confidence"], "why": "; ".join(ch.get("reasons") or [])[:300]}
                            nxt.append(ch["address"])
                    except Exception as ex: notes.append(f"change heuristic skipped on {tx['txid'][:10]}: {type(ex).__name__}")
            if time.time() > deadline: truncated = truncated or f"time cap ({max_secs:g}s) reached"; break
        frontier = nxt
        if time.time() > deadline: truncated = truncated or f"time cap ({max_secs:g}s) reached"; break
    if frontier and depth and hop == depth and not truncated: notes.append(f"{len(frontier)} address(es) found at the last hop were not expanded further (depth {depth})")
    services = []
    for x, m in M.items():
        n = chains.node("btc", x)
        if n.get("name"): m["name"] = n["name"]
        if n.get("kind"): m["kind"] = n["kind"]
        if n.get("kind") in SERVICE or n.get("kind") == "exchange": services.append(f"{n.get('name') or x} ({n.get('kind')})")
    if services: notes.insert(0, "The cluster contains labelled service address(es): " + ", ".join(services[:5]) + ". Custodial wallets spend many customers' coins together, so this cluster may represent the service, not one person.")
    mem = sorted(M.values(), key=lambda m: (m["hop"], m.get("time") or 0))
    return {"root": root, "chain": "btc", "addresses": mem, "size": len(mem), "by_reason": dict(Counter(m["reason"] for m in mem)),
            "coinjoin_skipped": skipped[:50], "coinjoin_count": len(skipped), "txs_scanned": scanned, "truncated": truncated, "notes": notes,
            "caps": {"depth": depth, "max_txs": max_txs, "max_addrs": max_addrs, "pages": pages, "max_secs": max_secs, "change": use_change},
            "secs": round(time.time() - t0, 1), "lead": LEAD, "method": METHOD}
