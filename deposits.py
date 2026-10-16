"""Exchange deposit-address inference (ETH + SOL). Transparent features -> logistic model -> confidence 0-1.
A deposit address typically: receives from several unrelated senders, then forwards (sweeps) near-full balances,
incl. tokens, to ONE exchange hot/collection wallet; often gets a tiny gas top-up from the exchange; few other outflows.
Inferred labels are always 'suggested' and never carry more risk than the exchange level."""
import json, math, os, re
import labels
D = os.path.join(os.path.dirname(__file__), "data")
NATIVE = {"eth": "ETH", "sol": "SOL"}
GAS = {"eth": 0.03, "sol": 0.05}            # tiny native top-up threshold
FEATS = ["f_out_hub", "log_sweeps", "single_out", "log_in_senders", "gas_from_ex", "sweep_ratio", "low_balance", "in_gt_out"]
# heuristic prior used if no trained model is present (hand-set, documented)
PRIOR = {"bias": -4.0, "w": [3.0, 1.2, 1.5, 0.6, 1.0, 1.2, 0.8, 0.3]}
def _load(f, dflt):
    try: return json.load(open(os.path.join(D, f)))
    except Exception: return dflt
MODEL = _load("deposit_model.json", None)
INF = _load("inferred_deposits.json", {"hubs": {}, "deposits": {}})
def reload():
    global MODEL, INF
    MODEL = _load("deposit_model.json", None); INF = _load("inferred_deposits.json", {"hubs": {}, "deposits": {}})
def ent_of(rows):
    """normalised exchange entity from label-db rows"""
    for r in rows:
        e = (r.get("entity") or "").strip() or (r.get("name") or "").split(":")[0].split(" ")[0]
        if e:
            k = re.sub(r"[-_]", ".", re.split(r"[\s:]", e.strip())[0].lower()).replace(".com", "")
            return {"crypto": "Crypto.com", "mexc": "MEXC", "okx": "OKX", "kucoin": "KuCoin", "gate.io": "Gate.io", "gate": "Gate.io", "htx": "HTX",
                    "bybit": "Bybit", "ftx.us": "FTX.US"}.get(k, k.title())
    return None
def is_deposit_row(r):
    n = (r.get("name") or "").lower()
    return "deposit_wallet" in n or n.startswith("bitget dep:") or re.search(r"\bdeposit \d|: deposit\b|deposit address$", n) is not None
def hub(chain, a, extra_hubs=None):
    """Return exchange entity if `a` is a (verified or learned) exchange hot/collection wallet, not a deposit address."""
    k = labels.norm(chain, a)
    if extra_hubs and k in extra_hubs: return extra_hubs[k]
    ex = labels.EXCH.get(chain, {}).get(k)
    if ex: return ex.split(" ")[0]
    rows = [r for r in labels.db_labels(chain, a) if r["category"] == "exchange"]
    if rows and not any(is_deposit_row(r) for r in rows) and max(r["confidence"] for r in rows) >= 0.6: return ent_of(rows)
    h = INF.get("hubs", {}).get(chain, {}).get(k)
    return h
def exchange_any(chain, a):
    k = labels.norm(chain, a)
    if labels.EXCH.get(chain, {}).get(k): return True
    return any(r["category"] == "exchange" for r in labels.db_labels(chain, a))
def features(chain, a, d, extra_hubs=None):
    """d = chains.ADDR result. Returns (feature dict, hub entity, evidence) or None if no exchange hub in outflows."""
    a_ = labels.norm(chain, a); E = d.get("edges") or []
    out = [e for e in E if labels.norm(chain, e["source"]) == a_ and labels.norm(chain, e["target"]) != a_]
    inc = [e for e in E if labels.norm(chain, e["target"]) == a_ and labels.norm(chain, e["source"]) != a_]
    if not out: return None
    tgt = {}
    for e in out: tgt.setdefault(e["target"], []).append(e)
    hubs = {t: hub(chain, t, extra_hubs) for t in tgt}
    hubs = {t: h for t, h in hubs.items() if h}
    if not hubs: return None
    ht = max(hubs, key=lambda t: sum(e.get("count", 1) for e in tgt[t]))
    hs = tgt[ht]; n_sw = sum(e.get("count", 1) for e in hs); n_out = sum(e.get("count", 1) for e in out)
    senders = {e["source"] for e in inc}
    gas = any(e.get("unit") == NATIVE[chain] and (e.get("amount") or 0) <= GAS[chain] and exchange_any(chain, e["source"]) for e in inc)
    u_in = sum(e.get("usd") or 0 for e in inc); u_hub = sum(e.get("usd") or 0 for e in hs)
    bal = d.get("balance_usd")
    if bal is None:
        try: import chains; bal = chains.usd_of(d.get("balance"), d.get("unit"))
        except Exception: bal = None
    f = {"f_out_hub": n_sw / max(1, n_out), "log_sweeps": math.log1p(n_sw), "single_out": 1.0 if len(tgt) <= 2 else 1 / (len(tgt) - 1),
         "log_in_senders": math.log1p(len(senders)), "gas_from_ex": 1.0 if gas else 0.0,
         "sweep_ratio": min(1.0, u_hub / u_in) if u_in > 0 else (0.5 if u_hub > 0 else 0.0),
         "low_balance": 1.0 if (bal is not None and bal < 50) else 0.0, "in_gt_out": 1.0 if len(inc) >= len(out) else 0.0}
    ev = {"hub": ht, "exchange": hubs[ht], "sweeps": n_sw, "outflows": n_out, "out_counterparties": len(tgt), "in_senders": len(senders),
          "gas_topup_from_exchange": gas, "usd_swept": round(u_hub, 2), "usd_in": round(u_in, 2), "balance_usd": round(bal, 2) if bal is not None else None,
          "window": "recent page of activity"}
    return f, hubs[ht], ev
def gate(ev):
    """hard sanity rules added after the manual spot-check: drop dust/address-poisoning sweeps, busy wallets
    (many outgoing counterparties = user/market-maker, not a deposit address) and wallets keeping most funds."""
    if (ev.get("usd_swept") or 0) < 5: return "dust-only sweep"
    if ev.get("out_counterparties", 0) > 6: return "too many outgoing counterparties"
    b = ev.get("balance_usd")
    if b is not None and b > max(1000, ev.get("usd_swept") or 0): return "keeps a large balance"
    return None
def prob(f, model=None, chain=None):
    m = model or ((MODEL or {}).get("per_chain") or {}).get(chain) or MODEL or PRIOR
    z = m["bias"] + sum(w * f[k] for w, k in zip(m["w"], FEATS))
    return 1 / (1 + math.exp(-z))
def suggest(chain, a, d):
    """On-the-fly suggestion for an UNLABELLED address. Returns dict or None."""
    if chain not in NATIVE: return None
    k = labels.norm(chain, a)
    pre = INF.get("deposits", {}).get(chain, {}).get(k)
    if pre: return {"entity": pre[0], "confidence": pre[1], "evidence": pre[2], "method": "inferred (batch)"}
    r = features(chain, a, d)
    if not r: return None
    f, ent, ev = r
    if gate(ev): return None
    p = prob(f, chain=chain)
    if p < 0.5: return None
    return {"entity": ent, "confidence": round(p, 3), "evidence": {**ev, "features": {k2: round(v, 3) for k2, v in f.items()}}, "method": "on-the-fly"}
def decorate(node, s, endpoint_at=0.85):
    """attach a suggestion to a graph node without touching verified labels; risk stays at exchange level max."""
    if not s or node.get("kind"): return node
    node["suggested"] = {"label": f"{s['entity']} deposit", "category": "exchange-deposit", **s}
    node["name"] = node.get("name") or f"{s['entity']} deposit? ({int(s["confidence"] * 100)}%)"
    if s["confidence"] >= endpoint_at:
        node["kind"] = "exchange"; node["risk"] = min(node.get("risk") or 0, labels.RISK["exchange"]) or labels.RISK["exchange"]
    return node
def lookup_batch(chain, a):
    pre = INF.get("deposits", {}).get(chain, {}).get(labels.norm(chain, a))
    return {"entity": pre[0], "confidence": pre[1], "evidence": pre[2], "method": "inferred (batch)"} if pre else None
