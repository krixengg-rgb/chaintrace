"""ChainTrace scam-pattern flags (v31): heuristic detectors for fake-recovery and pig-butchering ("sha zhu pan") money flows,
plus public scam reports with their sources. HEURISTIC LEADS, NOT EVIDENCE: a pattern match is a reason to look closer,
never proof that an address belongs to a scammer or that a payment was a fee demanded by one.

Detectors (fetched history of one address, values in USD at the time of each transfer):
  fee_deposits   collector view: many small deposits ($10-$5,000), several senders paying repeatedly within 30 days,
                 often round amounts: the shape of 'tax', 'withdrawal fee' or 'verification' payments demanded from victims.
  fan_in         collector view: value from many distinct senders, then most of it moved on within 72 h to 1-2 counterparties,
                 strongest when the onward counterparty is a labelled or suggested exchange deposit (cash-out).
  fee_after_loss same-payer view (collector): a sender's first payment is large, then 7+ days later the same sender pays smaller
                 amounts again (escalating 'fees' after the main loss).
  recovery_fee   victim view (outgoing): a large payment (the original loss), then 7-365 days later two or more smaller payments
                 to a different, unlabelled address: the shape of a fake 'recovery' service charging upfront fees.
Public reports: dataset scam / phishing labels (with source URLs) and Chainabuse reports (cached, or live when
CHAINABUSE_API_KEY is set and the caller asks), on the address itself and on direct counterparties.
"""
import time
from collections import defaultdict

LEAD = "Heuristic lead, not evidence: these flags describe the shape of the money flows only. Many legitimate services (exchanges, payment processors, payroll) produce similar shapes. Corroborate with the victim's account, communications and exchange records before relying on any flag."
DAY = 86400
SMALL = (10, 5000)
REPORT_KINDS = {"scam", "phishing", "hack", "ransomware", "darknet"}
NAMES = {"fee_deposits": "Repeated fee-like deposits from many payers", "fan_in": "Fan-in then consolidation",
         "fee_after_loss": "Smaller repeat payments after a large first payment", "recovery_fee": "Recovery-fee pattern after a prior loss"}

def _v(e): return e.get("usd") or 0.0
def _round(e):
    u = _v(e); a = e.get("amount") or 0
    if u >= 50 and min(u % 50, 50 - u % 50) <= 0.02 * u: return True   # within 2% of a multiple of $50
    if a and abs(a - round(a, 2 if a >= 1 else 3)) < 1e-9 and len(f"{a:g}".replace('.', '').strip('0')) <= 2: return True   # e.g. 0.05 ETH, 1.5 ETH, 300 USDT
    return False
def _tx(e): return e.get("tx") or e.get("txid")
def _kind(nodes, a):
    n = nodes.get(a) or {}
    if n.get("kind"): return n["kind"]
    if (n.get("suggested") or {}).get("category") == "exchange-deposit": return "exchange-deposit?"
    return None
def _name(nodes, a):
    n = nodes.get(a) or {}; return n.get("name") or (str(a)[:10] + "…")

def fee_deposits(focus, ins):
    sm = [e for e in ins if SMALL[0] <= _v(e) <= SMALL[1] and e.get("time")]
    if len(sm) < 4: return None
    by = defaultdict(list)
    for e in sm: by[e["source"]].append(e)
    rep = [s for s, es in by.items() if len(es) >= 2 and max(x["time"] for x in es) - min(x["time"] for x in es) <= 30 * DAY]
    rnd = sum(1 for e in sm if _round(e)) / len(sm)
    if len(rep) < 2 and len(by) < 8: return None
    s = min(1.0, 0.2 * len(rep) + 0.03 * len(by) + 0.3 * rnd)
    ev = [f"{len(sm)} small deposits (${SMALL[0]:,}-${SMALL[1]:,}) from {len(by)} distinct sender(s)",
          f"{len(rep)} sender(s) paid 2+ times within 30 days (repeat 'fee'-like payments)", f"{rnd:.0%} of them round amounts"]
    return {"strength": round(s, 2), "evidence": ev, "txs": [_tx(e) for e in sorted(sm, key=lambda e: -_v(e))[:6] if _tx(e)]}

def fan_in(focus, ins, outs, nodes):
    snd = {e["source"] for e in ins}
    vi = sum(map(_v, ins))
    if len(snd) < 5 or vi <= 0: return None
    t_in = [e["time"] for e in ins if e.get("time")]
    if not t_in: return None
    w0, w1 = min(t_in), max(t_in) + 72 * 3600
    later = [e for e in outs if e.get("time") and w0 <= e["time"] <= w1]
    rec = defaultdict(float)
    for e in later: rec[e["target"]] += _v(e)
    top = sorted(rec.items(), key=lambda x: -x[1])[:2]
    share = sum(v for _, v in top) / vi if top else 0
    if share < 0.7: return None
    ex = [a for a, _ in top if _kind(nodes, a) in ("exchange", "exchange-deposit?")]
    s = 1.0 if ex else 0.5
    ev = [f"{len(snd)} distinct senders paid in ${vi:,.0f}", f"{share:.0%} of it moved on within 72 h of the last deposit to {len(top)} counterparty(ies): " +
          ", ".join(f"{_name(nodes, a)} (${v:,.0f})" for a, v in top)]
    if ex: ev.append("onward counterparty is an exchange (labelled or suggested deposit): likely cash-out point, ask the exchange for KYC")
    return {"strength": s, "evidence": ev, "txs": [_tx(e) for e in sorted(later, key=lambda e: -_v(e))[:4] if _tx(e)], "consolidated_to": [a for a, _ in top]}

def fee_after_loss(focus, ins):
    by = defaultdict(list)
    for e in ins:
        if e.get("time") and _v(e) > 0: by[e["source"]].append(e)
    hits = []
    for s_, es in by.items():
        es.sort(key=lambda e: e["time"]); big = es[0]
        if _v(big) < 1000: continue
        fol = [e for e in es[1:] if e["time"] - big["time"] >= 7 * DAY and _v(e) <= 0.5 * _v(big)]
        if len(fol) >= 2: hits.append((s_, big, fol))
    if not hits: return None
    s = min(1.0, 0.45 + 0.15 * (len(hits) - 1) + 0.05 * sum(len(f) for _, _, f in hits))
    ev = [f"sender {s_[:10]}…: first ${_v(b):,.0f}, then {len(f)} smaller payment(s) {int((f[0]['time'] - b['time']) / DAY)}+ days later (${sum(map(_v, f)):,.0f})" for s_, b, f in hits[:4]]
    return {"strength": round(s, 2), "evidence": ev, "txs": [_tx(x) for _, b, f in hits[:3] for x in [b] + f[:2] if _tx(x)]}

def recovery_fee(focus, outs, nodes):
    o = sorted([e for e in outs if e.get("time") and _v(e) > 0], key=lambda e: e["time"])
    best = None
    for i, big in enumerate(o):
        if _v(big) < 1000 or _kind(nodes, big["target"]) in ("exchange", "exchange-deposit?"): continue
        by = defaultdict(list)
        for e in o[i + 1:]:
            if e["target"] != big["target"] and 7 * DAY <= e["time"] - big["time"] <= 365 * DAY and _v(e) <= 0.3 * _v(big) and _kind(nodes, e["target"]) not in ("exchange", "exchange-deposit?", "defi", "bridge"):
                by[e["target"]].append(e)
        for t, es in by.items():
            if len(es) >= 2 and (best is None or len(es) > len(best[2])): best = (big, t, es)
    if not best: return None
    big, t, es = best
    lk = (nodes.get(big["target"]) or {}).get("kind")
    s = min(1.0, 0.5 + 0.1 * (len(es) - 2) + (0.25 if lk in REPORT_KINDS else 0))
    ev = [f"large payment ${_v(big):,.0f} to {_name(nodes, big['target'])}" + (f" (labelled {lk})" if lk else "") + " = possible original loss",
          f"then {len(es)} smaller payment(s) totalling ${sum(map(_v, es)):,.0f} to a different unlabelled address {str(t)[:10]}… starting {int((es[0]['time'] - big['time']) / DAY)} days later",
          "fake 'recovery' services typically ask victims of an earlier scam for upfront fees: check how the victim found the 'recovery' contact"]
    return {"strength": round(s, 2), "evidence": ev, "txs": [_tx(x) for x in [big] + es[:4] if _tx(x)], "fee_recipient": t}

def reports(d, nodes, ca=None):
    """public reports with sources: the address itself, then direct counterparties labelled scam / phishing"""
    focus = d.get("address"); out = []
    def add(a, who, n):
        lab = n or {}
        for s in lab.get("sources") or []:
            if (s.get("category") or lab.get("kind")) in REPORT_KINDS:
                out.append({"address": a, "who": who, "source": s.get("source"), "name": s.get("name") or lab.get("name"), "category": s.get("category") or lab.get("kind"), "url": s.get("source_url") or s.get("url")})
    add(focus, "this address", d.get("label") or nodes.get(focus))
    for a, n in nodes.items():
        if a != focus and n.get("kind") in REPORT_KINDS: add(a, "counterparty", n)
    if ca and ca.get("count"):
        for r in (ca.get("reports") or [])[:10]: out.append({"address": focus, "who": "this address", "source": "chainabuse", "name": f"Chainabuse report ({r.get('category')})", "category": r.get("category"), "url": r.get("url")})
    seen, res = set(), []
    for r in out:
        k = (r["address"], r["source"], r["url"])
        if k not in seen and r.get("url"): seen.add(k); res.append(r)
    return res

def _expand(e):
    """aggregated edges (count > 1, first..last) -> evenly spread pseudo-transfers so per-payment rules still see repeats"""
    n = int(e.get("count") or 1)
    if n <= 1 or not e.get("first") or not e.get("last"): return [e]
    n = min(n, 50); st = (e["last"] - e["first"]) / (n - 1)
    return [{**e, "amount": (e.get("amount") or 0) / n, "usd": _v(e) / n, "time": int(e["first"] + i * st), "count": 1, "aggregated": True} for i in range(n)]
def analyse(d, ca=None):
    focus = d.get("address"); nodes = {n["id"]: n for n in d.get("nodes") or []}
    edges = [e for e in d.get("edges") or [] if not e.get("meta") and not str(e.get("source", "")).startswith("tx:") and not str(e.get("target", "")).startswith("tx:")]
    edges = [x for e in edges for x in _expand(e)]
    ins = [e for e in edges if e["target"] == focus and e["source"] != focus]
    outs = [e for e in edges if e["source"] == focus and e["target"] != focus]
    flags = []
    for k, f in (("fee_deposits", lambda: fee_deposits(focus, ins)), ("fan_in", lambda: fan_in(focus, ins, outs, nodes)),
                 ("fee_after_loss", lambda: fee_after_loss(focus, ins)), ("recovery_fee", lambda: recovery_fee(focus, outs, nodes))):
        if k == "recovery_fee" and ((d.get("label") or nodes.get(focus) or {}).get("kind") in REPORT_KINDS): continue   # victim-view rule: not for an address itself labelled scam
        r = f()
        if r: r["txs"] = list(dict.fromkeys(r.get("txs") or [])); flags.append({"key": k, "name": NAMES[k], **r})
    svc = ((d.get("label") or nodes.get(focus) or {}).get("kind"))
    if svc in ("exchange", "defi", "bridge", "miner", "gambling") and flags:
        for f in flags: f["strength"] = round(f["strength"] * 0.3, 2); f["evidence"].append(f"address is a labelled {svc}: this shape is normal for a service, strength reduced")
    reps = reports(d, nodes, ca)
    comb = 1.0
    for f in flags: comb *= (1 - f["strength"])
    frac = round(1 - comb, 3)
    return {"address": focus, "chain": d.get("chain"), "flags": flags, "reports": reps, "frac": frac,
            "checked": list(NAMES.values()), "history": {"edges": len(edges), "complete": not d.get("next")},
            "chainabuse": {k: ca.get(k) for k in ("status", "count", "search_url", "note") if ca and k in ca} if ca else None,
            "lead": LEAD, "method": __doc__.split("Detectors", 1)[1].strip(), "at": int(time.time())}
