"""ChainTrace per-address risk score 0-100 (v26): a transparent, additive breakdown. Indicative lead, not evidence.
Each factor has a fixed maximum (its weight); the score is the sum of the points awarded, capped at 100.
An address that is itself on an official sanctions list is pinned to 100 (shown as such)."""
import asyncio, statistics, time
from collections import defaultdict

LEAD = "Indicative lead, not evidence: a transparent heuristic over public labels and the fetched transaction history. It is not a legal or regulatory finding and must not be used on its own to make decisions about a person."
FACTORS = [  # key, label, weight (max points), what it measures
    ("sanctions", "Sanctions", 30, "Address on the OFAC SDN / UK Sanctions List (pins the score to 100), or share of value exchanged directly with listed addresses."),
    ("scam", "Scam / abuse reports", 15, "Dataset scam / hack / darknet / ransomware labels and community reports (Chainabuse cache) on the address itself."),
    ("mixer_gambling", "Mixer / privacy / gambling exposure", 20, "Share of value to or from mixers, privacy pools and gambling services, direct counts in full, indirect (n hops) at half."),
    ("nokyc", "No-KYC swap / exchange exposure", 10, "Share of value to or from no-KYC instant swap services, direct in full, indirect at half."),
    ("patterns", "Peel / structuring patterns", 5, "Bursts of similar-sized transfers, amounts just under round reporting thresholds, many fresh one-off recipients (peel-like spending)."),
    ("age", "Address age", 5, "Newly active addresses score higher (first activity in the fetched history)."),
    ("velocity", "Volume velocity", 5, "Pass-through behaviour: most incoming value leaves again quickly, and high value per active day."),
    ("scam_pattern", "Scam-pattern flags (pig-butchering / fake recovery)", 10, "Heuristic detectors: repeated fee-like deposits from many payers, fan-in then consolidation to an exchange, smaller repeat payments after a large first payment, recovery-fee pattern after a prior loss."),
]
W = {k: w for k, _, w, _ in FACTORS}
LEVELS = [(75, "severe"), (50, "high"), (25, "medium"), (10, "low"), (0, "minimal")]
def level(s): return next(n for t, n in LEVELS if s >= t)
REPORT_KINDS = {"scam", "hack", "darknet", "ransomware", "terrorism", "phishing"}
THRESH = [1000, 3000, 5000, 9000, 10000, 15000]   # common reporting / travel-rule thresholds (USD / GBP / EUR are close enough for a lead)

def _v(e): return e.get("usd") or 0.0

def patterns(focus, edges):
    """-> (points 0..1, evidence list)"""
    out = sorted([e for e in edges if e["source"] == focus and e["target"] != focus and e.get("time")], key=lambda e: e["time"])
    ev, s = [], 0.0
    # bursts of near-equal amounts (±5%) within 72 h, same asset
    best = 0
    for i, e in enumerate(out):
        a = e.get("amount") or 0
        if not a: continue
        grp = [x for x in out[i:] if x["time"] - e["time"] <= 72 * 3600 and x.get("unit") == e.get("unit") and abs((x.get("amount") or 0) - a) <= 0.05 * a]
        n = sum(x.get("count", 1) for x in grp)
        best = max(best, n)
    if best >= 3: s += min(0.5, 0.15 * (best - 2)); ev.append(f"{best} near-equal outgoing transfers (±5%) within 72 h")
    # just under round thresholds (90-99.9% of a threshold, USD value)
    under = [e for e in out if any(0.9 * t <= _v(e) < t for t in THRESH)]
    if len(under) >= 2: s += min(0.3, 0.1 * len(under)); ev.append(f"{len(under)} outgoing transfer(s) valued just under a round threshold ({', '.join('$' + format(t, ',') for t in THRESH)})")
    # peel-like: many distinct one-off recipients each getting a small share
    rec = defaultdict(float)
    for e in out: rec[e["target"]] += _v(e)
    tot = sum(rec.values())
    small = [r for r, v in rec.items() if tot and v / tot < 0.1]
    if len(out) >= 6 and len(small) >= 5 and len(small) / max(1, len(rec)) > 0.7: s += 0.3; ev.append(f"{len(small)} of {len(rec)} recipients each received <10% of the outgoing value (peel-like / dispersal)")
    return min(1.0, s), ev

def age(edges, now=None):
    ts = [e.get("first") or e.get("time") for e in edges if e.get("first") or e.get("time")]
    if not ts: return 0.0, ["no dated transactions fetched"], None
    days = ((now or time.time()) - min(ts)) / 86400
    p = 1.0 if days < 30 else 0.6 if days < 90 else 0.3 if days < 365 else 0.0
    return p, [f"first activity {days:.0f} days ago (full history fetched)"], round(days, 1)

def velocity(focus, edges):
    ins = sorted([e for e in edges if e["target"] == focus and e["source"] != focus and e.get("time")], key=lambda e: e["time"])
    outs = sorted([e for e in edges if e["source"] == focus and e["target"] != focus and e.get("time")], key=lambda e: e["time"])
    vi, vo = sum(map(_v, ins)), sum(map(_v, outs))
    ev, s = [], 0.0
    if vi and vo:
        ratio = min(vi, vo) / max(vi, vo)
        # median delay from each incoming transfer to the next outgoing one
        ds = []
        for e in ins:
            nx = next((o["time"] for o in outs if o["time"] >= e["time"]), None)
            if nx is not None: ds.append(nx - e["time"])
        med = statistics.median(ds) / 3600 if ds else None
        if ratio >= 0.8 and med is not None and med <= 24: s += 0.6; ev.append(f"pass-through: {ratio:.0%} of incoming value matched by outgoing, median {med:.1f} h to move on")
        elif ratio >= 0.8: s += 0.25; ev.append(f"{ratio:.0%} of incoming value matched by outgoing" + (f", median {med:.0f} h to move on" if med else ""))
    ts = [e["time"] for e in ins + outs]
    if ts:
        days = max(1.0, len({int(t // 86400) for t in ts}))
        per = (vi + vo) / days
        if per >= 250000: s += 0.4
        elif per >= 50000: s += 0.25
        elif per >= 10000: s += 0.1
        if per >= 10000: ev.append(f"${per:,.0f} moved per active day")
    return min(1.0, s), ev

def score(d, X=None):
    """d: decorated lookup result (api/lookup); X: exposure.compute result or None -> breakdown dict"""
    focus = d.get("address"); lab = d.get("label") or {}; edges = [e for e in d.get("edges") or [] if not e.get("meta")]
    F = {}
    def put(k, frac, ev, extra=None): F[k] = {"points": round(W[k] * max(0.0, min(1.0, frac)), 1), "frac": round(max(0.0, min(1.0, frac)), 3), "evidence": ev, **(extra or {})}
    # sanctions
    sh = lab.get("sanctions") or []
    nodes = {n["id"]: n for n in d.get("nodes") or []}
    tot = sum(_v(e) for e in edges if focus in (e["source"], e["target"])) or 0
    sv = defaultdict(float)
    for e in edges:
        o = e["target"] if e["source"] == focus else e["source"] if e["target"] == focus else None
        if o and (nodes.get(o) or {}).get("kind") == "sanctioned": sv[o] += _v(e)
    if sh: put("sanctions", 1.0, [x["wording"] for x in sh[:3]], {"pinned": True})
    elif sv:
        frac = sum(sv.values()) / tot if tot else 0.5
        put("sanctions", max(0.5, min(1.0, frac * 2)), [f"direct transfers with sanctioned {(nodes.get(o) or {}).get('name') or o} (${v:,.0f})" for o, v in sorted(sv.items(), key=lambda x: -x[1])[:3]])
    else: put("sanctions", 0, ["no match on the current OFAC SDN / UK Sanctions List; no direct sanctioned counterparty in the fetched history"])
    # scam reports
    rep = lab.get("reports") or {}; kind = lab.get("kind")
    if kind in REPORT_KINDS: put("scam", 1.0, [f"labelled {kind}: {lab.get('name') or ''} (" + ", ".join(s.get("source", "") for s in (lab.get("sources") or [])[:3]) + ")"] + ([f"{rep['count']} report(s)"] if rep.get("count") else []))
    elif rep.get("count"): put("scam", 0.5 if rep["count"] == 1 else 0.75 if rep["count"] < 3 else 1.0, [f"{rep['count']} community report(s) ({', '.join(rep.get('categories') or [])}): unverified"])
    else: put("scam", 0, ["no scam / abuse labels or cached community reports"])
    # exposure-based
    def expo(cats):
        best, ev = 0.0, []
        if not X: return 0.0, ["exposure not computed"]
        for dr, nm in (("outgoing", "out"), ("incoming", "in")):
            o = X.get(dr) or {}
            f = 0.0
            for c in cats:
                x = (o.get("categories") or {}).get(c)
                if not x: continue
                f += x["direct_pct"] / 100 + 0.5 * x["indirect_pct"] / 100
                ev.append(f"{nm}: {c.replace('_', ' ')} {x['direct_pct']}% direct, {x['indirect_pct']}% indirect ({', '.join(x['names'][:3])})")
            best = max(best, f)
        s = X.get("self")
        if s and s["cat"] in cats: best = 1.0; ev.insert(0, f"address itself labelled {s['name']} ({s['src']})")
        return min(1.0, best * 2 if best < 0.5 else 1.0), ev or ["none found within %d hop(s)" % X.get("hops", 0)]
    f, ev = expo(("mixer", "privacy", "gambling")); put("mixer_gambling", f, ev)
    f, ev = expo(("nokyc_swap",)); put("nokyc", f, ev)
    f, ev = patterns(focus, edges); put("patterns", f, ev or ["no bursts, threshold-hugging amounts or dispersal found"])
    f, ev, days = age(edges)
    if d.get("next") and f:   # only the most recent page was fetched: the first activity is unknown, so no age points
        f, ev = 0.0, [f"oldest fetched transfer {days:.0f} days ago, but older history exists (not fetched): age not scored"]
    put("age", f, ev, {"days": days})
    f, ev = velocity(focus, edges); put("velocity", f, ev or ["no pass-through or high-velocity pattern"])
    import scampattern
    sp = scampattern.analyse(d)
    put("scam_pattern", sp["frac"], [f"{x['name']} ({x['strength']:.0%}): " + "; ".join(x["evidence"][:2]) for x in sp["flags"]] or ["no fee-deposit, fan-in, fee-after-loss or recovery-fee pattern in the fetched history"])
    raw = round(min(100.0, sum(x["points"] for x in F.values())))
    pinned = bool(sh)
    s = 100 if pinned else raw
    return {"address": focus, "chain": d.get("chain"), "score": s, "raw_score": raw, "level": level(s), "pinned": pinned,
            "factors": [{"key": k, "label": lb, "weight": w, "measures": m, **F[k]} for k, lb, w, m in FACTORS],
            "history": {"edges": len(edges), "complete": not d.get("next")}, "exposure_hops": (X or {}).get("hops"),
            "lead": LEAD, "method": "Additive score: each factor awards up to its weight (sum of weights = 100); the address itself being on an official sanctions list pins the score to 100. "
            "Figures use only the fetched history (the most recent page for busy addresses) and public labels; absent data scores 0, so a low score is not a clean bill of health."}

async def compute(q, chain, lookup, hops=2, budget=20.0):
    import exposure
    async def ex():
        try: return await asyncio.wait_for(exposure.compute(q, chain, hops, 5, budget - 2), budget)
        except Exception as e: return {"error": f"{type(e).__name__}: {e}"}
    d, X = await asyncio.gather(lookup(q, chain), ex())
    if d.get("kind") != "address": raise ValueError("give an address")
    xe = X.get("error") if isinstance(X, dict) else None
    r = score(d, None if xe else X)
    if xe: r["notes"] = [f"exposure check failed ({xe}); mixer / no-KYC factors scored 0"]
    return r
