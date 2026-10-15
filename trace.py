"""Async multi-hop fund tracing (BFS with top-K per hop and node caps)."""
import asyncio, uuid, time, chains
JOBS = {}
from labels import EXPO, RISK
TERMINAL = set(RISK) - {"other"}
ORDER = sorted(RISK, key=lambda k: -RISK[k])
def _rank(cands):
    # unit-agnostic: normalise amounts per unit, add a small bonus for repeated flows
    mx = {}
    for e in cands: mx[e["unit"]] = max(mx.get(e["unit"], 0), e["amount"] or 0)
    return sorted(cands, key=lambda e: -((e["amount"] or 0) / (mx[e["unit"]] or 1) + 0.05 * e.get("count", 1)))
async def run(job, q, hops, direction, topk, max_nodes):
    c, kind = chains.detect(q)
    J = JOBS[job]; J.update(chain=c, status="running")
    nodes, edges, parent = {}, {}, {}
    def add(d):
        for n in d["nodes"]:
            if n["id"] not in nodes: nodes[n["id"]] = n
            elif n.get("kind") and not nodes[n["id"]].get("kind"): nodes[n["id"]] = n
    try:
        if kind == "address":
            root = q.strip() if c != "eth" else (await chains.ADDR[c](q.strip()))["address"]; frontier = [(root, 0)]
        else:
            d = await chains.TX[c](q.strip()); add(d); root = "tx:" + q.strip(); frontier = []
            for e in d["edges"]:
                edges[(e["source"], e["target"], e.get("unit"))] = e
                if direction in ("forward", "both") and e["source"] == root and e["target"] not in parent:
                    parent[e["target"]] = (root, e); frontier.append((e["target"], 1))
                if direction in ("backward", "both") and e["target"] == root and e["source"] not in parent:
                    parent[e["source"]] = (root, e); frontier.append((e["source"], 1))
            # a tx with many legs: keep top-K
            frontier = frontier[:max(topk * 2, 6)]
        parent.setdefault(root, None); seen = set(); J["root"] = root
        while frontier:
            depth = frontier[0][1]
            layer = [a for a, dd in frontier if dd == depth]; frontier = [x for x in frontier if x[1] != depth]
            J["progress"] = f"hop {depth}/{hops}: expanding {len(layer)} address(es)"
            nxt = []
            for a in layer:
                if a in seen or a.startswith("tx:") or a == "coinbase": continue
                seen.add(a)
                n = nodes.get(a) or chains.node(c, a)
                if a != root and n.get("kind") in TERMINAL: continue  # stop at labelled entities
                if depth >= hops or len(nodes) >= max_nodes: continue
                try: d = await chains.ADDR[c](a)
                except Exception as ex: J["errors"].append(f"{a[:12]}: {ex}"); continue
                if a == root: J["summary"] = {k: d.get(k) for k in ("balance", "unit", "tx_count", "address")}
                fw = [e for e in d["edges"] if e["source"] == a and e["target"] != a]
                bw = [e for e in d["edges"] if e["target"] == a and e["source"] != a]
                pick = (_rank(fw)[:topk] if direction in ("forward", "both") else []) + (_rank(bw)[:topk] if direction in ("backward", "both") else [])
                lab = {n["id"]: n for n in d["nodes"]}
                for e in pick:
                    other = e["target"] if e["source"] == a else e["source"]
                    if len(nodes) >= max_nodes and other not in nodes: J["capped"] = True; continue
                    if other not in nodes: nodes[other] = lab.get(other) or chains.node(c, other)
                    nodes.setdefault(a, lab.get(a) or chains.node(c, a))
                    edges[(e["source"], e["target"], e.get("unit"))] = e
                    if other not in parent: parent[other] = (a, e); nxt.append((other, depth + 1))
                J["nodes"], J["edges"] = list(nodes.values()), list(edges.values())
            frontier += nxt
        # ---- paths to labelled entities
        paths = []
        for nid, n in nodes.items():
            if n.get("kind") in TERMINAL and nid != root and nid in parent:
                chain_n, chain_e, cur = [nid], [], nid
                while parent.get(cur):
                    p, e = parent[cur]; chain_e.append([e["source"], e["target"], e.get("unit")]); chain_n.append(p); cur = p
                chain_n.reverse(); chain_e.reverse()
                paths.append({"target": nid, "kind": n["kind"], "name": n.get("name"), "hops": len(chain_e), "nodes": chain_n, "edges": chain_e,
                              "dir": "forward" if chain_e and chain_e[0][0] == root else "backward"})
        paths.sort(key=lambda p: (ORDER.index(p["kind"]), p["hops"]))
        own = nodes.get(root) or {"risk": 0, "kind": None}
        score = own.get("risk", 0); reasons = []
        if own.get("kind") in EXPO: reasons.append(f"root labelled {own['kind']} ({own.get('name')}; source: {', '.join(sorted({x['source'] for x in own.get('sources', [])}))})")
        for p in paths:
            sh = lambda x: x if x.startswith("tx:") else x[:8] + "…"
            srcs = ", ".join(sorted({x["source"] for x in nodes[p["target"]].get("sources", [])}))
            p["sources"] = srcs
            desc = f"{p['dir']} {p['hops']} hop(s) to {p['kind']} {p.get('name') or p['target'][:12]} [{srcs}]: " + " → ".join(sh(x) for x in p["nodes"])
            if p["kind"] in EXPO:
                score = max(score, int(EXPO[p["kind"]] * 0.75 ** (p["hops"] - 1)))
            reasons.append(desc)
        lvl = "severe" if score >= 75 else "high" if score >= 45 else "medium" if score >= 20 else "low"
        J.update(nodes=list(nodes.values()), edges=list(edges.values()), paths=paths[:30],
                 risk={"score": score, "level": lvl, "reasons": reasons[:12]}, status="done", progress="done",
                 elapsed=round(time.time() - J["started"], 1))
    except Exception as ex:
        J.update(status="error", progress=str(ex))
def _prune():
    """Jobs live in memory only (lost on restart/sleep); keep at most 50, drop finished ones after 1h."""
    now = time.time()
    for k in [k for k, j in JOBS.items() if j["status"] in ("done", "error") and now - j["started"] > 3600]: JOBS.pop(k, None)
    while len(JOBS) > 50: JOBS.pop(next(iter(JOBS)))
def start(q, hops=2, direction="forward", topk=3, max_nodes=120):
    _prune(); job = uuid.uuid4().hex[:10]
    JOBS[job] = {"id": job, "q": q, "hops": hops, "direction": direction, "status": "queued", "progress": "", "nodes": [], "edges": [],
                 "paths": [], "errors": [], "started": time.time(), "capped": False}
    asyncio.create_task(run(job, q, hops, direction, topk, max_nodes)); return job
