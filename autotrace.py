"""AutoTrace: follow funds hop-by-hop until they reach labelled endpoints (exchange, mixer, bridge,
sanctioned, scam, ...) or a cap is hit. Runs as a cancellable background job sharing trace.JOBS."""
import asyncio, time, uuid, chains, trace, deposits, bridges
from labels import EXPO, RISK
ENDPOINT = set(RISK) - {"other", "miner"}
ENDPOINT_AT = 0.85
SEM = {"sol": 1, "btc": 3, "eth": 3, "tron": 2, "xrp": 2, "bsc": 2, "arb": 2, "base": 2, "polygon": 2, "op": 2}
def _sh(x): return x if x.startswith("tx:") else x[:8] + "…"
MAX_BRIDGE_HOPS = 8
NATIVE_UNIT = {"btc": "BTC", "eth": "ETH", "sol": "SOL", "tron": "TRX", "xrp": "XRP", **{c: v["unit"] for c, v in chains.EVM.items()}}
async def run(job, q, direction, max_hops, max_nodes, max_secs, min_usd, topk, skip_unpriced, follow_bridges=False, follow_change=False):
    J = trace.JOBS[job]; c, kind = chains.detect(q); J.update(chain=c, status="running"); t0 = time.time()
    nodes, edges, parent, depth_of = {}, {}, {}, {}
    sems = {k: asyncio.Semaphore(v) for k, v in SEM.items()}; stop = None
    chain_of = {}; ch = lambda a: chain_of.get(a, c)   # per-node chain: bridge hops move the trace onto another chain
    bseen, J["bridges"] = set(), []
    try: await asyncio.wait_for(bridges.refresh_vaults(), 6)
    except Exception: pass
    def keep(e, cc=None):   # dust / spam filter
        if set(e.get("flags") or []) & trace.NOISE: return False
        if e.get("usd") is None: return not skip_unpriced and e.get("unit") == NATIVE_UNIT.get(cc or c)
        return e["usd"] >= min_usd
    def take(a, e, other, d, nxt, lab, cc=None):
        cc = cc or ch(a)
        if other not in nodes:
            if len(nodes) >= max_nodes: J["capped"] = True; return
            nodes[other] = lab.get(other) or chains.node(cc, other); chain_of[other] = cc
            if cc != c: nodes[other]["chain"] = cc
            if not nodes[other].get("kind") and cc in deposits.NATIVE: deposits.decorate(nodes[other], deposits.lookup_batch(cc, other), ENDPOINT_AT)
            if not nodes[other].get("kind"): bridges.decorate_vault(nodes[other], cc)
        edges[(e["source"], e["target"], e.get("unit"))] = e
        if other not in parent: parent[other] = (a, e); depth_of[other] = d; nxt.append(other)
    if kind == "address":
        d0 = await chains.ADDR[c](q); d0.pop("cp", None); root = d0["address"]
        J["summary"] = {k: d0.get(k) for k in ("balance", "unit", "tx_count", "address", "balance_usd")}
        J["summary"]["balance_usd"] = chains.usd_of(d0.get("balance"), d0.get("unit"))
        nodes[root] = next((n for n in d0["nodes"] if n["id"] == root), chains.node(c, root)); cache = {root: d0}; frontier = [root]
    else:
        await chains.ensure_prices(); d0 = await chains.TX[c](q); root = "tx:" + (d0.get("tx") or q); cache = {}
        for n in d0["nodes"]:
            if n["id"] == root: nodes[root] = n
        lab = {n["id"]: n for n in d0["nodes"]}; frontier = []
        for e in d0["edges"]:
            e.setdefault("usd", chains.usd_of(e.get("amount"), e.get("unit") or d0.get("unit")))
            if direction == "forward" and e["source"] == root: take(root, e, e["target"], 1, frontier, lab)
            if direction == "backward" and e["target"] == root: take(root, e, e["source"], 1, frontier, lab)
    parent[root] = None; depth_of[root] = 0; J["root"] = root; seen = set()
    if (nodes.get(root) or {}).get("sanctions"): J["warnings"] = [f"⛔ The starting address {nodes[root]['sanctions'][0]['wording']}. Tracing continues for intelligence purposes."]
    async def fetch(a):
        if a in cache: return cache.pop(a)
        async with sems.get(ch(a), sems["eth"]):
            d_ = await chains.ADDR[ch(a)](a); d_.pop("cp", None); return d_
    async def cross(hop_, nxt):   # follow bridges reached on the previous hop (deterministic matches only)
        todo_b = [a for a in list(nodes) if nodes[a].get("kind") == "bridge" and a not in bseen and a in parent and parent[a] and depth_of.get(a) == hop_]
        for a in todo_b[:max(0, MAX_BRIDGE_HOPS - len(bseen))]:
            bseen.add(a); e = parent[a][1]
            J["progress"] = f"hop {hop_ + 1}/{max_hops}: checking bridge {nodes[a].get('name') or a[:10]} for the cross-chain leg"
            try: found = await bridges.hop(ch(a), a, e, direction)
            except Exception as ex: J["errors"].append(f"bridge {a[:10]}: {ex}"); continue
            for m, ns, es in found:
                x = es[0]; other = x["target"] if direction == "forward" else x["source"]
                on = next(n for n in ns if n["id"] == other); oc = on.get("chain")
                x["usd"] = x.get("usd") if x.get("usd") is not None else chains.usd_of(x.get("amount"), (x.get("unit") or "").rstrip("⇄"))
                J["bridges"].append({"via": a, "bridge": m["bridge"], "method": m["method"], "confidence": m["confidence"], "provider": m["provider"],
                                     "src": m["src"], "dst": m["dst"], "node": other})
                if other in nodes: edges[(x["source"], x["target"], x.get("unit"))] = x; continue
                if len(nodes) >= max_nodes: J["capped"] = True; break
                nodes[other] = on; chain_of[other] = oc
                edges[(x["source"], x["target"], x.get("unit"))] = x
                parent[other] = (a, x); depth_of[other] = hop_ + 1
                if oc in chains.ADDR and not on.get("kind") in ENDPOINT: nxt.append(other)
            J["nodes"], J["edges"] = list(nodes.values()), list(edges.values())
    while frontier and not stop:
        hop = depth_of[frontier[0]]
        todo = [a for a in frontier if a not in seen and not a.startswith("tx:") and a != "coinbase" and ch(a) in chains.ADDR
                and (a == root or nodes.get(a, {}).get("kind") not in ENDPOINT)]
        frontier = []
        if hop >= max_hops: stop = f"max hops ({max_hops}) reached"; break
        nxt = []
        if follow_bridges and hop > 0 and time.time() - t0 < max_secs: await cross(hop, nxt)
        J["progress"] = f"hop {hop + 1}/{max_hops}: following {len(todo)} branch(es) · {len(nodes)} nodes · {int(time.time() - t0)}s"
        for i in range(0, len(todo), 6):   # small batches keep memory and API pressure bounded
            if time.time() - t0 > max_secs: stop = f"time limit ({max_secs}s) reached"; break
            batch = todo[i:i + 6]; seen.update(batch)
            res = await asyncio.gather(*[fetch(a) for a in batch], return_exceptions=True)
            for a, d in zip(batch, res):
                if isinstance(d, Exception): J["errors"].append(f"{a[:12]}: {d}"); continue
                lab = {n["id"]: n for n in d["nodes"]}
                if a in lab and lab[a].get("kind") and not nodes.get(a, {}).get("kind"): nodes[a] = lab[a]
                if a != root and ch(a) in deposits.NATIVE and not nodes.get(a, {}).get("kind") and not nodes.get(a, {}).get("suggested"):
                    try: deposits.decorate(nodes[a], deposits.suggest(ch(a), a, d), ENDPOINT_AT)   # on-the-fly deposit inference
                    except Exception as ex: J["errors"].append(f"suggest {a[:10]}: {ex}")
                    if nodes[a].get("kind") in ENDPOINT: J["nodes"] = list(nodes.values()); continue   # high-confidence deposit = endpoint
                elif a != root and nodes.get(a, {}).get("kind") in ENDPOINT: continue
                if follow_change and direction == "forward" and ch(a) == "btc":
                    try: fc = await _follow_change(a, d, J)
                    except Exception as ex: fc = None; J["errors"].append(f"change {a[:10]}: {type(ex).__name__}")
                    if fc:
                        for e, follow_it in fc:
                            other = e["target"]
                            if follow_it: take(a, e, other, hop + 1, nxt, lab)
                            else:   # peeled payment: shown as a branch, not followed
                                junk = []; take(a, e, other, hop + 1, junk, lab)
                        J["nodes"], J["edges"] = list(nodes.values()), list(edges.values()); continue
                if direction == "forward": cand = [e for e in d["edges"] if e["source"] == a and e["target"] != a and keep(e, ch(a))]
                else: cand = [e for e in d["edges"] if e["target"] == a and e["source"] != a and keep(e, ch(a))]
                for e in trace._rank(cand, lab, a)[:topk]:
                    take(a, e, e["target"] if direction == "forward" else e["source"], hop + 1, nxt, lab)
                J["nodes"], J["edges"] = list(nodes.values()), list(edges.values())
            if len(nodes) >= max_nodes: stop = f"node cap ({max_nodes}) reached"; break
        frontier = nxt
    if not stop: stop = "all branches reached endpoints or dead ends"
    # ---- endpoints + paths
    def path_to(nid):
        ns, es, cur = [nid], [], nid
        while parent.get(cur):
            p, e = parent[cur]; es.append([e["source"], e["target"], e.get("unit")]); ns.append(p); cur = p
        return ns[::-1], es[::-1]
    eps, paths = {}, []
    for nid, n in nodes.items():
        if nid == root or n.get("kind") not in ENDPOINT or nid not in parent: continue
        inc = [e for e in edges.values() if (e["target"] if direction == "forward" else e["source"]) == nid]
        ns, es = path_to(nid)
        bott = min([edges[(s, t, u)].get("usd") or 0 for s, t, u in es] or [0])
        eps[nid] = {"id": nid, "name": n.get("name"), "category": n["kind"], "usd": round(sum(e.get("usd") or 0 for e in inc), 2),
                    "hops": len(es), "paths": len(inc), "bottleneck_usd": round(bott, 2),
                    "sources": sorted({s["source"] for s in n.get("sources", [])}) or (["inferred"] if n.get("suggested") else []),
                    "suggested": ({"confidence": n["suggested"]["confidence"], "method": n["suggested"]["method"]} if n.get("suggested") else None)}
        paths.append({"target": nid, "kind": n["kind"], "name": n.get("name"), "hops": len(es), "nodes": ns, "edges": es, "dir": direction,
                      "sources": ", ".join(eps[nid]["sources"])})
    endpoints = sorted(eps.values(), key=lambda x: (-RISK.get(x["category"], 0) >= -40, -x["usd"]))
    endpoints.sort(key=lambda x: (0 if x["category"] in EXPO else 1, -x["usd"]))
    leaves = [nid for nid in nodes if nid not in seen and nid != root and nodes[nid].get("kind") not in ENDPOINT and not nid.startswith("tx:")]
    own = nodes.get(root) or {}; score = own.get("risk", 0); reasons = []
    if own.get("kind") in EXPO: reasons.append(f"root labelled {own['kind']} ({own.get('name')})")
    for p in sorted(paths, key=lambda p: (0 if p["kind"] in EXPO else 1, p["hops"])):
        if p["kind"] in EXPO: score = max(score, int(EXPO[p["kind"]] * 0.75 ** (p["hops"] - 1)))
        reasons.append(f"{direction} {p['hops']} hop(s) to {p['kind']} {p.get('name') or p['target'][:12]} [{p['sources']}]: " + " → ".join(_sh(x) for x in p["nodes"]))
    lvl = "severe" if score >= 75 else "high" if score >= 45 else "medium" if score >= 20 else "low"
    sanc = [{"id": nid, "name": n.get("name"), "hops": depth_of.get(nid), "wording": n["sanctions"][0]["wording"], "lists": sorted({h["short"] for h in n["sanctions"]})}
            for nid, n in nodes.items() if n.get("sanctions")]
    if sanc:
        score = max(score, 100 if (nodes.get(root) or {}).get("sanctions") else EXPO["sanctioned"])
        reasons = [f"⛔ {'root' if x['id'] == root else 'branch stopped at'} {x['id'][:12]}… {x['wording']}" for x in sanc[:4]] + reasons
        lvl = "severe" if score >= 75 else "high" if score >= 45 else "medium" if score >= 20 else "low"
    J["sanctions"] = sanc
    J.update(nodes=list(nodes.values()), edges=list(edges.values()), paths=paths, endpoints=endpoints[:50], unresolved=len(leaves),
             stop_reason=stop, risk={"score": score, "level": lvl, "reasons": reasons[:12]}, status="done",
             progress=f"done · {len(endpoints)} endpoint(s) · {stop}", elapsed=round(time.time() - t0, 1))
async def _follow_change(a, d, J, min_conf=0.6):
    """BTC 'follow change': for each spend from `a` on this page, take the likely change output (heuristic lead, amber/dotted) and list the other outputs as peeled
    payments. Returns [(edge, follow?)] or None when no spend from `a` has a confident change output (the normal ranking is used then)."""
    import peel
    spends = [h["tx"] for h in (d.get("txs") or []) if (h.get("delta") or 0) < 0][:4]
    out = []; J.setdefault("peel", [])
    for h in spends:
        tx = await peel.get_tx(h)
        if not any((v.get("prevout") or {}).get("scriptpubkey_address") == a for v in tx["vin"]): continue
        sp = await peel._spends(tx); A = await peel.analyse(tx, sp, with_pattern=True); c_ = peel.pick(A, min_conf)
        if not c_ or c_["address"] == a: continue
        t = tx["status"].get("block_time")
        J["peel"].append({"from": a, "tx": h, "change": c_["address"], "value": c_["value"], "confidence": c_["confidence"], "reasons": c_["reasons"]})
        out.append(({"source": a, "target": c_["address"], "amount": c_["value"], "unit": "BTC", "tx": h, "time": t, "count": 1, "usd": chains.usd_of(c_["value"], "BTC"), "heur": True,
                     "peel": {"id": "auto", "step": None, "is_peel": False}, "change": {"confidence": c_["confidence"], "level": c_["level"], "reasons": c_["reasons"], "against": c_["against"], "vout": c_["n"]}}, True))
        for o in A["outputs"]:
            if o["n"] == c_["n"] or o["address"] == a: continue
            out.append(({"source": a, "target": o["address"], "amount": o["value"], "unit": "BTC", "tx": h, "time": t, "count": 1, "usd": chains.usd_of(o["value"], "BTC"), "peeled": {"id": "auto"}}, False))
    return out or None
def start(q, direction="forward", max_hops=6, max_nodes=150, max_secs=120, min_usd=100.0, topk=3, skip_unpriced=True, follow_bridges=False, follow_change=False):
    trace._prune(); job = uuid.uuid4().hex[:10]
    trace.JOBS[job] = {"id": job, "q": q, "type": "autotrace", "hops": max_hops, "direction": direction, "status": "queued", "progress": "",
                       "nodes": [], "edges": [], "paths": [], "endpoints": [], "errors": [], "started": time.time(), "capped": False,
                       "params": {"max_hops": max_hops, "max_nodes": max_nodes, "max_secs": max_secs, "min_usd": min_usd, "topk": topk, "skip_unpriced": skip_unpriced, "follow_bridges": follow_bridges, "follow_change": follow_change}}
    async def _go():
        try: await asyncio.wait_for(run(job, q, direction, max_hops, max_nodes, max_secs, min_usd, topk, skip_unpriced, follow_bridges, follow_change), max_secs + 60)
        except asyncio.CancelledError: trace.JOBS[job].update(status="cancelled", progress="cancelled by user")
        except Exception as ex: trace.JOBS[job].update(status="error", progress=f"{type(ex).__name__}: {ex}")
        finally: trace.TASKS.pop(job, None)
    trace.TASKS[job] = asyncio.create_task(_go()); return job
