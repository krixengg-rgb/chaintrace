"""ChainTrace BTC change-address heuristics and peel-chain detection (v15).

Change detection scores every output of a Bitcoin transaction with a set of published heuristics and combines them
(log-odds sum, softmax across outputs) into a probability that each output is the sender's change. Every heuristic
reports what it saw, so the reasons can be shown. A peel chain is followed by repeatedly taking the likely change
output to the transaction that spends it, with the smaller 'peeled' payments as branches.

Everything here is a HEURISTIC LEAD. It is never attribution: wallets can defeat each heuristic (e.g. same-type
change, round change, address reuse, coin control, CoinJoin, PayJoin)."""
import asyncio, math, time
import chains
from labels import RISK

MP = chains.MP
LEAD = "Heuristic lead – not attribution; corroborate before relying on it"
# heuristic -> (weight as the probability it is right when it discriminates, short name)
W = {"type": (0.65, "Address type"), "round": (0.60, "Round payment"), "fresh": (0.60, "Fresh vs reused address"), "self": (0.90, "Change back to an input address"),
     "unnecessary": (0.70, "Unnecessary input"), "optimal": (0.65, "Optimal change"), "label": (0.85, "Known service"), "pattern": (0.70, "Peel pattern")}
SERVICE = {"exchange", "bridge", "mixer", "gambling", "sanctioned", "darknet", "scam", "hack", "ransomware", "defi"}
METHOD_NOTE = (
    "Change detection (Bitcoin): each output is scored with these heuristics, each of which only votes when it singles out one output: "
    "address type (the change usually has the same script type as the inputs); round payment (payments are often round amounts, change is not); "
    "fresh vs reused address (change usually goes to an address never used before, payments often to reused ones; change back to an input address is a strong signal); "
    "unnecessary input (a wallet would not add an input it did not need, so an output is unlikely to be change if one input could be dropped while still paying the other outputs and the fee); "
    "optimal change (change is usually smaller than every input); known service (an output to a labelled exchange or other service is a payment); and, when following a chain, "
    "peel pattern (the output is spent next in the same one-input, two-output shape). Votes are combined as a sum of log-odds and normalised across outputs; "
    "an output is proposed as change only when its probability is at least the threshold (default 60%). Weights are ChainTrace's own settings, not published error rates. "
    "These are heuristic leads, not attribution: wallets can defeat every one of them (same-type or round change, address reuse, coin control, CoinJoin, PayJoin).")

def logit(p): return math.log(p / (1 - p))
def tz(v):   # trailing zeros in satoshis
    n = 0
    while v and v % 10 == 0 and n < 8: v //= 10; n += 1
    return n
def btc(s): return round(s / 1e8, 8)
async def _get(u, ttl=chains.LONG): return await chains.get(u, ttl=ttl)
async def get_tx(h): return await _get(f"{MP}/tx/{h}")
async def used_before(a, tx):
    """True if `a` had any confirmed transaction before `tx` (mempool.space returns the address history older than a given txid)"""
    if not tx["status"].get("confirmed"):
        i = await _get(f"{MP}/address/{a}", ttl=300); return (i["chain_stats"]["tx_count"] or 0) > 0
    try: older = await _get(f"{MP}/address/{a}/txs/chain/{tx['txid']}")
    except Exception: return None
    return bool(older)
def shape_peel(t, vout=None):
    """1-2 inputs, 2-3 outputs, one output at least 3x every other one"""
    if not t or not (1 <= len(t["vin"]) <= 2 and 2 <= len(t["vout"]) <= 3): return False
    v = sorted((o["value"] for o in t["vout"]), reverse=True)
    return v[0] >= 3 * v[1]

async def analyse(tx, spends=None, nxt=None, with_pattern=False):
    """score each output of `tx` (mempool.space JSON) as change. Returns dict with outputs[], change (or None), reasons."""
    vin = [v for v in tx["vin"] if not v.get("is_coinbase")]
    ins = [((v.get("prevout") or {}).get("scriptpubkey_address"), (v.get("prevout") or {}).get("scriptpubkey_type"), (v.get("prevout") or {}).get("value") or 0) for v in vin]
    outs = [(i, o.get("scriptpubkey_address"), o.get("scriptpubkey_type"), o["value"]) for i, o in enumerate(tx["vout"]) if o.get("scriptpubkey_address") and o["value"] > 0]
    res = {"tx": tx["txid"], "time": tx["status"].get("block_time"), "confirmed": tx["status"].get("confirmed"), "fee": btc(tx.get("fee") or 0),
           "inputs": [{"address": a, "type": t, "value": btc(v)} for a, t, v in ins], "outputs": [], "change": None, "heuristics": []}
    if not vin: res["note"] = "coinbase transaction (newly mined coins): no change"; return res
    if len(outs) < 2: res["note"] = "single output: the whole amount moved, no change"; return res
    if len(outs) > 12: res["note"] = f"{len(outs)} outputs (batch payment): change heuristics not applied"; return res
    score = {i: 0.0 for i, *_ in outs}; H = []
    def vote(key, idx, saw):
        w, nm = W[key]; score[idx] += logit(w); H.append({"h": key, "name": nm, "output": idx, "weight": w, "saw": saw})
    def novote(key, saw): H.append({"h": key, "name": W[key][1], "output": None, "weight": W[key][0], "saw": saw})
    in_addr = {a for a, _, _ in ins}; in_types = {t for _, t, _ in ins}; vals = [v for _, _, _, v in outs]; fee = tx.get("fee") or 0
    # 1 address type
    if len(in_types) == 1:
        t0 = next(iter(in_types)); m = [i for i, _, t, _ in outs if t == t0]
        if len(m) == 1: vote("type", m[0], f"only output {m[0]} uses the inputs' script type ({t0}); the others are {', '.join(sorted({t for i, _, t, _ in outs if i != m[0]}))}")
        else: novote("type", f"{len(m)} outputs share the inputs' script type ({t0})" if m else f"no output uses the inputs' type ({t0})")
    else: novote("type", "inputs use mixed script types")
    # 2 round payment
    r = {i: tz(v) for i, _, _, v in outs}; lo = min(r.values()); low = [i for i in r if r[i] == lo]
    if len(low) == 1 and all(r[i] - lo >= 2 and r[i] >= 2 for i in r if i != low[0]):
        vote("round", low[0], f"the other output(s) are round amounts ({', '.join(f'{btc(v)} BTC' for i, _, _, v in outs if i != low[0])}); output {low[0]} is not ({btc(vals[[o[0] for o in outs].index(low[0])])} BTC)")
    else: novote("round", "no single non-round output among round ones")
    # 3 self-change / fresh vs reused
    selfc = [i for i, a, _, _ in outs if a in in_addr]
    if len(selfc) == 1: vote("self", selfc[0], f"output {selfc[0]} goes back to an input address ({next(a for i, a, _, _ in outs if i == selfc[0])})")
    elif selfc: novote("self", "several outputs return to input addresses")
    if not selfc:
        ub = await asyncio.gather(*[used_before(a, tx) for _, a, _, _ in outs], return_exceptions=True)
        ub = {i: (u if isinstance(u, bool) else None) for (i, *_), u in zip(outs, ub)}
        fresh = [i for i, u in ub.items() if u is False]; known = all(u is not None for u in ub.values())
        if known and len(fresh) == 1: vote("fresh", fresh[0], f"output {fresh[0]} goes to a never-used address; the other(s) to addresses already used before this transaction")
        else: novote("fresh", "could not check every output" if not known else (f"{len(fresh)} outputs go to never-used addresses" if fresh else "every output address was used before"))
        res["fresh"] = {str(i): (None if u is None else not u) for i, u in ub.items()}
    # 4 unnecessary input / 5 optimal change (need 2+ inputs to discriminate)
    tin = sum(v for _, _, v in ins); tout = sum(vals)
    if len(ins) >= 2:
        P = [i for i, _, _, v in outs if not any(tin - iv >= (tout - v) + fee for _, _, iv in ins)]
        if len(P) == 1: vote("unnecessary", P[0], f"if any other output were the change, at least one input would have been unnecessary; only output {P[0]} is consistent")
        else: novote("unnecessary", f"{len(P)} outputs are consistent with the inputs used")
        mi = min(v for _, _, v in ins); S = [i for i, _, _, v in outs if v < mi]
        if len(S) == 1: vote("optimal", S[0], f"only output {S[0]} is smaller than every input ({btc(mi)} BTC)")
        else: novote("optimal", f"{len(S)} outputs are smaller than the smallest input")
    else:
        novote("unnecessary", "single input: not informative"); novote("optimal", "single input: not informative")
    # known service (labelled) -> payment
    labs = {}
    for i, a, _, _ in outs:
        n = chains.node("btc", a); labs[i] = n
        if n.get("kind") in SERVICE:
            others = [j for j, *_ in outs if j != i]
            if len(others) == 1: vote("label", others[0], f"output {i} pays a labelled {n.get('kind')} ({n.get('name') or a}), so it is a payment")
    # peel pattern: spent next in the same shape
    if with_pattern and spends:
        pat = [i for i, *_ in outs if (spends.get(i) or {}).get("tx") and shape_peel(spends[i]["tx"])]
        if len(pat) == 1: vote("pattern", pat[0], f"output {pat[0]} is spent next in the same 1-input / 2-output shape with one large output")
        else: novote("pattern", f"{len(pat)} outputs continue in a peel shape")
    mx = max(score.values()); ex = {i: math.exp(s - mx) for i, s in score.items()}; tot = sum(ex.values())
    for i, a, t, v in outs:
        n = labs.get(i) or {}
        res["outputs"].append({"n": i, "address": a, "type": t, "value": btc(v), "p_change": round(ex[i] / tot, 3), "kind": n.get("kind"), "name": n.get("name"),
                               "spent": (spends or {}).get(i, {}).get("spent"), "spent_by": (spends or {}).get(i, {}).get("txid")})
    res["heuristics"] = H
    best = max(res["outputs"], key=lambda o: o["p_change"])
    ties = [o for o in res["outputs"] if abs(o["p_change"] - best["p_change"]) < 1e-9]
    res["best"] = best["n"] if len(ties) == 1 else None
    res["p_best"] = best["p_change"]
    res["reasons"] = [h["saw"] for h in H if h["output"] == res["best"]]
    res["against"] = [h["saw"] for h in H if h["output"] is not None and h["output"] != res["best"]]
    return res

def level(p): return "high" if p >= 0.85 else "medium" if p >= 0.7 else "low"
def pick(A, min_conf):
    if A.get("best") is None or A["p_best"] < min_conf: return None
    o = next(o for o in A["outputs"] if o["n"] == A["best"])
    return {**o, "confidence": A["p_best"], "level": level(A["p_best"]), "reasons": A["reasons"], "against": A["against"]}

async def change(txid, min_conf=0.6):
    tx = await get_tx(txid); sp = await _spends(tx)
    A = await analyse(tx, sp, with_pattern=True); A["change"] = pick(A, min_conf); A["min_conf"] = min_conf; A["method_note"] = METHOD_NOTE; A["lead"] = LEAD
    return A

async def _spends(tx):
    """{vout: {spent, txid, tx}} with the spending tx fetched for up to 3 outputs (needed for the peel-pattern vote and to continue a chain)"""
    try: os_ = await _get(f"{MP}/tx/{tx['txid']}/outspends", ttl=600)
    except Exception: return {}
    out = {}; fetch = []
    for i, s in enumerate(os_ or []):
        out[i] = {"spent": bool(s.get("spent")), "txid": s.get("txid")}
        if s.get("spent") and s.get("txid") and len(tx["vout"]) <= 3: fetch.append(i)
    got = await asyncio.gather(*[get_tx(out[i]["txid"]) for i in fetch], return_exceptions=True)
    for i, g in zip(fetch, got):
        if not isinstance(g, Exception): out[i]["tx"] = g
    return out

async def start_tx(q):
    """a tx hash, or an address -> its earliest spending tx on the latest history page"""
    c, kind = chains.detect(q)
    if c != "btc": raise ValueError("peel chains are Bitcoin only: give a BTC tx hash or address")
    if kind == "tx": return q
    txs = await _get(f"{MP}/address/{q}/txs", ttl=300)
    sp = [t for t in txs if any((v.get("prevout") or {}).get("scriptpubkey_address") == q for v in t["vin"])]
    if not sp: raise ValueError("this address has not spent any funds in its latest transactions; start from a transaction hash")
    sp.sort(key=lambda t: t["status"].get("block_time") or 9e12); return sp[0]["txid"]

async def follow(q, max_hops=12, min_conf=0.6, budget=22.0, via=None):
    """follow likely change outputs from a start tx. Returns steps, verdict and a graph (nodes, edges) for the UI."""
    t0 = time.time(); h = await start_tx(q.strip()); steps = []; stop = None; seen = set(); prev_addr = via
    cur = await get_tx(h)
    while len(steps) < max_hops:
        if time.time() - t0 > budget: stop = f"time budget ({budget:.0f}s) reached: continue from the last change address"; break
        if cur["txid"] in seen: stop = "loop"; break
        seen.add(cur["txid"])
        sp = await _spends(cur); A = await analyse(cur, sp, with_pattern=True); ch = pick(A, min_conf)
        src = prev_addr if prev_addr and any(i["address"] == prev_addr for i in A["inputs"]) else (A["inputs"][0]["address"] if A["inputs"] else None)
        step = {"tx": cur["txid"], "time": A["time"], "fee": A["fee"], "from": src, "inputs": A["inputs"], "in_value": round(sum(i["value"] for i in A["inputs"]), 8),
                "shape": shape_peel(cur), "change": ch, "payments": [o for o in A["outputs"] if not ch or o["n"] != ch["n"]], "heuristics": A["heuristics"], "note": A.get("note"),
                "outputs": A["outputs"]}
        steps.append(step)
        if not ch: stop = A.get("note") or f"no output reaches the change threshold ({int(min_conf * 100)}%; best {int((A.get('p_best') or 0) * 100)}%)"; break
        if ch.get("kind") in SERVICE: stop = f"change candidate is a labelled {ch['kind']}"; break
        if ch["address"] == src: stop = "change returned to the same address (address reuse): continue from that address"; break
        s = sp.get(ch["n"]) or {}
        if not s.get("spent"): stop = f"change output unspent: {ch['value']} BTC still at {ch['address']}"; break
        nxt = s.get("tx") or await get_tx(s["txid"])
        if len(nxt["vin"]) > 3: stop = f"change merged with {len(nxt['vin']) - 1} other inputs in tx {nxt['txid'][:12]}… (consolidation): chain ends"; steps[-1]["merged_into"] = nxt["txid"]; break
        prev_addr = ch["address"]; cur = nxt
    if not stop: stop = f"max hops ({max_hops}) reached"
    chained = [s for s in steps if s["change"]]
    is_peel = len(chained) >= 3 and sum(1 for s in chained if s["shape"]) >= max(3, int(0.7 * len(chained)))
    pid = steps[0]["tx"][:16] if steps else None
    total_peeled = round(sum(p["value"] for s in chained for p in s["payments"]), 8)
    last = chained[-1]["change"] if chained else None
    verdict = (f"Peel-chain pattern: {len(chained)} successive transactions each send a small payment and pass most of the value to a likely change address (heuristic lead)."
               if is_peel else f"{len(chained)} likely change hop(s) followed; not enough consistent hops to call it a peel chain.")
    nodes, edges = graph(steps, pid, is_peel)
    return {"start": h, "id": pid, "steps": steps, "hops": len(chained), "is_peel": is_peel, "verdict": verdict, "stop_reason": stop, "min_conf": min_conf,
            "total_peeled": total_peeled, "payments": sum(len(s["payments"]) for s in chained), "end": ({"address": last["address"], "value": last["value"]} if last else None),
            "continue_from": (last["address"] if last and stop.startswith("time budget") else None),
            "nodes": nodes, "edges": edges, "method_note": METHOD_NOTE, "lead": LEAD, "elapsed": round(time.time() - t0, 1)}

def graph(steps, pid, is_peel):
    nodes = {}; edges = []
    hops = sum(1 for s in steps if s["change"])
    def nd(a, chain_idx=None):
        if a not in nodes: nodes[a] = chains.node("btc", a)
        if chain_idx is not None and is_peel: nodes[a]["peel"] = {"id": pid, "hops": hops, "index": chain_idx}
        return nodes[a]
    for k, s in enumerate(steps):
        if not s["from"]: continue
        nd(s["from"], k)
        ch = s["change"]
        if ch:
            nd(ch["address"], k + 1)
            edges.append({"source": s["from"], "target": ch["address"], "amount": ch["value"], "unit": "BTC", "tx": s["tx"], "time": s["time"], "count": 1,
                          "heur": True, "peel": {"id": pid, "step": k + 1, "is_peel": is_peel},
                          "change": {"confidence": ch["confidence"], "level": ch["level"], "reasons": ch["reasons"], "against": ch["against"], "vout": ch["n"]}})
            for p in s["payments"]:
                if p["address"] == s["from"]: continue
                nd(p["address"])
                edges.append({"source": s["from"], "target": p["address"], "amount": p["value"], "unit": "BTC", "tx": s["tx"], "time": s["time"], "count": 1,
                              "peeled": {"id": pid, "step": k + 1}})
    for e in edges: e["usd"] = chains.usd_of(e["amount"], "BTC")
    return list(nodes.values()), edges
