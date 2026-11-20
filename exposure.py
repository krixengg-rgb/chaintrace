"""ChainTrace exposure flags (v25): direct and indirect (n-hop) exposure of an address to mixers, privacy pools, no-KYC instant swaps and gambling.
Labels: data/exposure_labels.json.gz (built by build_exposure.py from documented public sources; each entry carries its source and URL).
Indirect exposure uses proportional ("haircut") propagation over the fetched graph: value leaving an address is split across its
counterparties in proportion to the value sent to each. The search is bounded (top counterparties per hop, time budget), so figures are
lower bounds for what was fetched. Exposure is an indicative lead, not evidence of wrongdoing."""
import asyncio, gzip, json, os, time
from collections import defaultdict
import chains, labels

CATS = {"mixer": "Mixer", "privacy": "Privacy pool / CoinJoin", "nokyc_swap": "No-KYC swap", "gambling": "Gambling"}
LEAD = "Indicative lead, not evidence: exposure means value moved to or from a labelled service within the hops shown; it says nothing about intent."
METHOD = ("Direct exposure: counterparties of the address that carry a mixer / privacy / no-KYC swap / gambling label. Indirect exposure: the same labels "
          "reached within N hops, with value propagated proportionally (each address's outgoing value is split across its counterparties in proportion "
          "to what it sent them; incoming the same way backwards). Percentages are of the address's total sent (outgoing) or received (incoming) value in the "
          "fetched history, valued in USD where a price is known (otherwise in coin units). Bounded search: only the top counterparties per hop are expanded, "
          "so indirect figures are lower bounds. Labels come only from documented public sources (OFAC SDN, Etherscan public labels via open datasets, GraphSense "
          "TagPacks, project documentation); each hit cites its source.")
_IDX = None
def _load():
    global _IDX
    if _IDX is None:
        try:
            d = json.load(gzip.open(os.path.join(os.path.dirname(__file__), "data", "exposure_labels.json.gz"), "rt"))
            _IDX = {(e["c"], e["a"]): e for e in d["entries"]}
        except Exception as ex: print("exposure labels:", ex); _IDX = {}
    return _IDX
def _key(c, i):
    a = str(i).split(":", 1)[1] if ":" in str(i) and str(i).split(":", 1)[0] in chains.EVM_NEW + ("ltc", "doge", "bch") else str(i)
    return (c, a.lower() if c in chains.EVM else a)
def flag(c, i):
    return _load().get(_key(c, i))
def val(e): return e.get("usd") if e.get("usd") else 0.0

async def _fetch(c, q, budget):
    return await asyncio.wait_for(chains.ADDR[c](q), budget)

def collapse(E):
    """UTXO: a -> tx:h -> b becomes a -> b, the output split across inputs in proportion to what each input contributed (change back to an input dropped)"""
    ins, outs, F = defaultdict(list), defaultdict(list), []
    for e in E:
        if e.get("xchain") or e.get("meta") or e.get("tmp"): continue
        s, t = str(e["source"]), str(e["target"])
        if t.startswith("tx:") and not s.startswith("tx:"): ins[t].append(e)
        elif s.startswith("tx:") and not t.startswith("tx:"): outs[s].append(e)
        elif not s.startswith("tx:") and not t.startswith("tx:"): F.append(e)
    seen = set()
    for h in set(ins) | set(outs):
        if not ins[h]:
            continue
        ii = {}
        for e in ins[h]: ii[e["source"]] = ii.get(e["source"], 0) + (e.get("amount") or 0)
        tin = sum(ii.values()) or 1
        for o in outs[h]:
            if o["target"] in ii or (h, o["target"]) in seen: continue
            seen.add((h, o["target"]))
            for a, v in ii.items():
                f = v / tin
                F.append({"source": a, "target": o["target"], "amount": (o.get("amount") or 0) * f, "usd": (o.get("usd") or 0) * f, "tx": h[3:]})
    return F

def propagate(focus, E, chain, hops, direction):
    """-> (hits{id: {...share, usd, hop, path}}, total value)"""
    nxt = (lambda e: e["target"]) if direction == "out" else (lambda e: e["source"])
    me = (lambda e: e["source"]) if direction == "out" else (lambda e: e["target"])
    by = defaultdict(list)
    for e in E:
        if e["source"] != e["target"]: by[me(e)].append(e)
    usd_mode = any(val(e) for e in by.get(focus, []))
    w = (lambda e: val(e)) if usd_mode else (lambda e: e.get("amount") or 0)
    tot0 = sum(w(e) for e in by.get(focus, [])) or 0.0
    S = {focus: (1.0, [focus])}; hits = {}; seen = {focus}
    for h in range(1, hops + 1):
        N = {}
        for x, (s, path) in S.items():
            es = [e for e in by.get(x, []) if nxt(e) != focus]
            tot = sum(w(e) for e in es)
            if not tot: continue
            agg = defaultdict(float)
            for e in es: agg[nxt(e)] += w(e)
            for t, v in agg.items():
                f = s * v / tot
                fl = flag(chain, t)
                if fl:
                    hh = hits.setdefault(t, {"id": t, **fl, "hop": h, "share": 0.0, "path": path + [t]}); hh["share"] += f; hh["hop"] = min(hh["hop"], h)
                elif t not in seen:
                    if t in N: N[t] = (N[t][0] + f, N[t][1])
                    else: N[t] = (f, path + [t])
        seen |= set(N); S = N
    for hh in hits.values(): hh["value"] = round(hh["share"] * tot0, 2); hh["share"] = round(hh["share"], 6)
    return hits, tot0, ("USD" if usd_mode else "coin")

async def compute(q, chain=None, hops=2, k=6, budget=20.0):
    t0 = time.time(); hops = max(1, min(4, int(hops)))
    c, kind = chains.detect(q, chain)
    if kind != "address" or c not in chains.ADDR: raise ValueError("give an address")
    if c in chains.EVM_NEW: q = chains.evmcfg.nid(c, q.strip())
    d0 = await _fetch(c, q.strip(), budget); focus = d0.get("address") or q.strip()
    E = list(d0.get("edges") or []); fetched = [focus]; notes = []
    front = {focus}
    for h in range(2, hops + 1):
        if time.time() - t0 > budget - 3: notes.append(f"time budget reached before hop {h}"); break
        cand = defaultdict(float)
        for e in E:
            for a, b in ((e["source"], e["target"]), (e["target"], e["source"])):
                if a in front and b not in fetched and not flag(c, b) and not str(b).startswith("tx:"): cand[b] += val(e) or (e.get("amount") or 0) * 1e-9
        pick = [b for b, _ in sorted(cand.items(), key=lambda x: -x[1])[:k]]
        sem = asyncio.Semaphore(3)
        async def one(b):
            async with sem:
                try: return b, await _fetch(c, b, max(2.0, budget - (time.time() - t0) - 1))
                except Exception as ex: return b, ex
        res = await asyncio.gather(*[one(b) for b in pick])
        nf = 0
        for b, d in res:
            if isinstance(d, Exception): nf += 1; continue
            E += d.get("edges") or []; fetched.append(b)
        if nf: notes.append(f"{nf} counterparty lookup(s) failed or timed out at hop {h}")
        front = set(pick)
    E = collapse(E)
    out = {}
    for dr in ("out", "in"):
        hits, tot, basis = propagate(focus, E, c, hops, dr)
        cats = {}
        for hh in hits.values():
            for scope in ("direct", "indirect"):
                if (scope == "direct") != (hh["hop"] == 1): continue
                x = cats.setdefault(hh["cat"], {"direct": 0.0, "indirect": 0.0, "value_direct": 0.0, "value_indirect": 0.0, "names": set()})
                x[scope] += hh["share"]; x["value_" + scope] += hh["value"]; x["names"].add(hh["name"].split(":")[0].split(" (")[0])
        for x in cats.values():
            x["names"] = sorted(x["names"])[:6]
            for s in ("direct", "indirect"): x[s + "_pct"] = round(min(1.0, x.pop(s)) * 100, 2); x["value_" + s] = round(x["value_" + s], 2)
        out[dr] = {"total": round(tot, 2), "basis": basis, "categories": cats, "hits": sorted(hits.values(), key=lambda h: -h["share"])[:40]}
    self_flag = flag(c, focus)
    return {"address": focus, "chain": c, "hops": hops, "top_k": k, "self": self_flag, "outgoing": out["out"], "incoming": out["in"], "fetched": len(fetched),
            "edges": len(E), "notes": notes, "secs": round(time.time() - t0, 1), "labels": {k_: CATS[k_] for k_ in CATS}, "lead": LEAD, "method": METHOD}
