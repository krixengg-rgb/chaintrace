"""ChainTrace production-order draft list (v24): likely exchange deposit addresses in a case graph, grouped per exchange.

Sources of a candidate (strongest first):
  1. a public / dataset label or an investigator label that says the address belongs to an exchange (deposit address if the label says so);
  2. ChainTrace's deposit inference (the existing deposit model: receives from several senders, sweeps to ONE exchange hot wallet);
  3. a deposit -> sweep pattern visible in this graph: an unlabelled address forwards the funds to a labelled exchange hot / collection wallet;
  4. optional live check (bounded): unlabelled end-points of the graph are looked up and scored with the same deposit features.
For each candidate the incoming transfers in the graph are listed (txid, date UTC + UK time, amount in coin, value in GBP on the day).

This is a DRAFT LEAD LIST to support a production order / disclosure request. It is not evidence and not legal advice."""
import asyncio, json, os, time, csv, io
from collections import defaultdict
import chains, labels, deposits
import report as R

WORDING = ("Draft lead list to support a production order / disclosure request to the exchange(s) named. It is not evidence: addresses are "
           "attributed from public labels, ChainTrace's deposit inference or a deposit-to-sweep pattern, and must be confirmed by the exchange's own records. "
           "Not legal advice: choose the legal route and wording with your force's legal / financial investigation advisers.")
METHOD = ("Candidates: (1) public, dataset or investigator labels naming an exchange (deposit address where the label says so); (2) ChainTrace deposit "
          "inference (several senders, near-full sweeps to one exchange hot wallet, gas top-ups from the exchange, low balance); (3) a deposit-to-sweep pattern "
          "in the graph (an unlabelled address forwarding to a labelled exchange wallet; via the transaction node on UTXO chains); (4) optional bounded live check "
          "of unlabelled end-points with the same deposit features. Amounts: incoming transfers in the graph; GBP on the day from Coinbase daily closes x ECB GBP/USD "
          "(stablecoins at par); transfers worth under £1 on the day and spam / zero-value transfers are left out. Contacts: only law-enforcement routes the exchange publishes itself, checked on the date shown; otherwise blank.")
_C = None
def contacts():
    global _C
    if _C is None:
        try: _C = json.load(open(os.path.join(os.path.dirname(__file__), "data", "exchange_contacts.json"))).get("entries") or {}
        except Exception: _C = {}
    return _C
def contact_for(ent):
    k = (ent or "").lower().replace(".com", "").split(" ")[0]
    return contacts().get(k)
def level(p): return "high" if p >= 0.85 else "medium" if p >= 0.65 else "low"

def _flows(A):
    """address -> address flows, collapsing UTXO tx nodes (a -> tx:h -> b becomes a -> b with tx h)"""
    nodes, edges = A["nodes"], A["edges"]
    ins, outs, F = defaultdict(list), defaultdict(list), []
    for e in edges:
        if e.get("xchain") or e.get("meta") or e.get("tmp"): continue
        s, t = e["source"], e["target"]
        if R.is_tx(t) and not R.is_tx(s): ins[t].append(e)
        elif R.is_tx(s) and not R.is_tx(t): outs[s].append(e)
        elif not R.is_tx(s) and not R.is_tx(t): F.append({**e, "tx": e.get("tx")})
    for h in set(ins) | set(outs):
        srcs = {e["source"] for e in ins[h]}
        for o in outs[h]:
            if o["target"] in srcs: continue    # change back to an input
            F.append({**o, "source": sorted(srcs)[0] if len(srcs) == 1 else (sorted(srcs)[0] if srcs else h), "senders": sorted(srcs), "tx": o.get("tx") or h[3:]})
    return F

async def _value(rows, errs):
    import loss as LS
    need = defaultdict(set)
    for r in rows:
        sym = LS.PXSYM.get((r["asset"] or "").upper())
        if sym and r["time"]: need[sym].add(LS.day(r["time"]))
    try: hp = await LS._candles(need, errs) if need else {}
    except Exception as ex: hp = {}; errs.append(f"prices: {type(ex).__name__}")
    try: gh, gt = await LS._gbp({LS.day(r["time"]) for r in rows if r["time"]}, errs)
    except Exception as ex: gh, gt = {}, None; errs.append(f"GBP rates: {type(ex).__name__}")
    for r in rows:
        a, u, t = r["amount"], (r["asset"] or "").upper(), r["time"]
        usd = None
        if isinstance(a, (int, float)) and t:
            if u in LS.STABLE: usd = a
            else:
                sym = LS.PXSYM.get(u)
                if sym and (sym, LS.day(t)) in hp: usd = a * hp[(sym, LS.day(t))]
        g = gh.get(LS.day(t)) if t else None
        r["usd_then"] = round(usd, 2) if usd is not None else None
        r["gbp_then"] = round(usd * g[0], 2) if usd is not None and g else None

async def draft(p, opts=None):
    opts = opts or {}; t0 = time.time(); errs = []
    import evidence as EV
    A = R.analyse(p); nodes = A["nodes"]; case_labels = (p.get("case") or {}).get("labels") or {}
    F = _flows(A)
    cand = {}
    def put(i, ent, typ, conf, reason, basis, lead):
        c = A["chain_of"](i); old = cand.get(i)
        if old and old["confidence"] >= conf: return
        cand[i] = {"id": i, "chain": c, "address": R.cid(i)[1], "exchange": ent, "type": typ, "confidence": round(conf, 3), "level": level(conf), "reason": reason, "basis": basis, "lead": lead}
    hubs = {}
    for i, n in nodes.items():
        if R.is_tx(i) or n.get("grp") or n.get("meta"): continue
        c = A["chain_of"](i); a = R.cid(i)[1]
        if not a or not c: continue
        ul = case_labels.get(i) if isinstance(case_labels, dict) else None
        r = EV._entity_for(i, n, ul, c, a)
        if r:
            ent, role, basis, srcs, lead = r
            if lead:   # ChainTrace inference
                sg = n.get("suggested") or {}; ev = sg.get("evidence") or {}
                why = f"ChainTrace deposit inference: {ev.get('sweeps', '?')} sweep(s) to {ent} wallet {labels.short_id(str(ev.get('hub') or '?'))}, {ev.get('in_senders', '?')} sender(s)" + ("; gas top-up from the exchange" if ev.get("gas_topup_from_exchange") else "")
                put(i, ent, "suspected deposit address (inference)", float(sg.get("confidence") or 0.5), why, basis, True)
            else:
                dep = role.startswith("deposit") or "deposit" in (n.get("name") or "").lower()
                put(i, ent, "deposit address (label)" if dep else "exchange wallet (label)", 0.9 if dep else 0.8, f"{role}; sources: {', '.join(srcs) or basis}", basis, False)
                if not dep:
                    try: h = deposits.hub(c, a)
                    except Exception: h = None
                    hubs[i] = h or ent
    # deposit -> sweep pattern in the graph
    out_by = defaultdict(list)
    for f in F: out_by[f["source"]].append(f)
    for i, fs in out_by.items():
        if i in cand or i not in nodes or R.is_tx(i): continue
        to_hub = [f for f in fs if f["target"] in hubs]
        if not to_hub: continue
        ents = {hubs[f["target"]] for f in to_hub}
        if len(ents) != 1: continue
        ent = ents.pop(); share = len(to_hub) / len(fs)
        got_in = any(f["target"] == i for f in F)
        conf = 0.55 + 0.15 * share + (0.05 if got_in else 0)
        tx = to_hub[0].get("tx")
        put(i, ent, "suspected deposit address (sweep pattern)", conf, f"forwards {'all' if share == 1 else f'{len(to_hub)} of {len(fs)}'} outgoing transfer(s) in this graph to a labelled {ent} wallet {labels.short_id(R.cid(to_hub[0]['target'])[1])}" + (f" (tx {tx[:12]}…)" if tx else ""), "Graph pattern – " + R.LEAD, True)
    # optional live check of unlabelled end-points
    checked = []
    if opts.get("check"):
        has_out = {f["source"] for f in F}
        ends = [i for i in nodes if not R.is_tx(i) and i not in cand and i not in has_out and any(f["target"] == i for f in F) and not nodes[i].get("kind")]
        ends = ends[:int(opts.get("max_checks") or 8)]
        budget = float(opts.get("budget") or 20)
        async def one(i):
            c = A["chain_of"](i); a = R.cid(i)[1]
            if c not in chains.ADDR: return
            try:
                q = i if c in chains.EVM_NEW or c in ("ltc", "doge", "bch") else a
                d = await asyncio.wait_for(chains.ADDR[c](q), budget)
                r = deposits.features(c, q if c in chains.EVM_NEW else a, d)
                checked.append({"id": i, "chain": c, "result": "no exchange wallet among its outflows" if not r else None})
                if not r: return
                f, ent, ev = r; g = deposits.gate(ev)
                if g: checked[-1]["result"] = f"rejected: {g}"; return
                pr = deposits.prob(f, chain=c if c in deposits.NATIVE else None)
                checked[-1]["result"] = f"{ent} deposit score {pr:.2f}"
                if pr >= 0.5:
                    put(i, ent, "suspected deposit address (live check)", pr, f"live check: {ev['sweeps']} sweep(s) to {ent} wallet {labels.short_id(str(ev['hub']))}, {ev['in_senders']} sender(s), {ev['out_counterparties']} outgoing counterparty(ies)", "Live deposit features – " + R.LEAD, True)
            except Exception as ex: checked.append({"id": i, "chain": c, "result": f"lookup failed: {type(ex).__name__}"})
        try: await asyncio.wait_for(asyncio.gather(*[one(i) for i in ends]), budget + 5)
        except asyncio.TimeoutError: errs.append("live check: time budget reached")
    # rows: incoming transfers to each candidate
    rows = []
    for i, cd in cand.items():
        inc = [f for f in F if f["target"] == i and f["source"] != i and not set(f.get("flags") or []) & {"spam", "zero", "approval"} and (f.get("amount") or 0) > 0]
        sweep = False
        if not inc:
            inc = [f for f in F if f["source"] == i and f["target"] in hubs and (f.get("amount") or 0) > 0 and not set(f.get("flags") or []) & {"spam", "zero"}]
            sweep = bool(inc)
        if not inc: inc = [None]
        for f in inc:
            t = (f or {}).get("time") or (f or {}).get("last")
            rows.append({**{k: cd[k] for k in ("exchange", "chain", "address", "type", "confidence", "level", "reason", "lead")},
                         "txid": (f or {}).get("tx"), "time": t, "time_utc": R.t_utc(t) if t else "", "time_uk": R.t_uk(t) if t else "",
                         "amount": (f or {}).get("amount"), "asset": R.unit_of(f) if f else "", "from": R.cid(((f or {}).get("target") if sweep else (f or {}).get("source")) or "")[1] if f else "",
                         "count": (f or {}).get("count") or (1 if f else 0), "usd_then": None, "gbp_then": None,
                         "direction": "sweep to exchange" if sweep else "in",
                         "note": ("sweep from this address to the exchange wallet (its incoming deposits are not in the graph – load the address to list them)" if sweep else "aggregated transfers: " + str(f.get("count")) + " transfers, txids not in the graph – load the address history" if f and (f.get("count") or 1) > 1 and not f.get("tx") else
                                  "no incoming transfer to this address in the graph" if not f else "")})
    await _value([r for r in rows if r["amount"] is not None], errs)
    mg = float(opts.get("min_gbp", 1.0)); n0 = len(rows)
    rows = [r for r in rows if r.get("gbp_then") is None or r["gbp_then"] >= mg]; dust = n0 - len(rows)
    pri = lambda r: 0 if r["type"].startswith("deposit") else 1 if r["type"].startswith("suspected") else 2
    G = {}
    for r in sorted(rows, key=lambda r: (r["exchange"].lower(), pri(r), -r["confidence"], r["address"], r["time"] or 0)):
        g = G.setdefault(r["exchange"].lower(), {"exchange": r["exchange"], "contact": contact_for(r["exchange"]), "addresses": set(), "rows": [], "gbp_then": 0.0, "lead_only": True})
        g["rows"].append(r); g["addresses"].add((r["chain"], r["address"])); g["gbp_then"] += r.get("gbp_then") or 0; g["lead_only"] = g["lead_only"] and r["lead"]
    groups = []
    for g in G.values():
        g["addresses"] = len(g["addresses"]); g["gbp_then"] = round(g["gbp_then"], 2); groups.append(g)
    groups.sort(key=lambda g: (g["lead_only"], -g["gbp_then"]))
    return {"groups": groups, "rows": sum((g["rows"] for g in groups), []), "candidates": len(cand), "checked": checked, "errors": errs, "dust_dropped": dust, "min_gbp": mg,
            "wording": WORDING, "method": METHOD, "secs": round(time.time() - t0, 1), "generated": int(time.time())}

COLS = ["exchange", "chain", "deposit_address", "type", "confidence", "level", "reason", "direction", "txid", "time_utc", "time_uk", "amount", "asset", "gbp_on_the_day", "usd_on_the_day", "counterparty", "transfers", "note",
        "le_portal", "le_email", "contact_source", "contact_verified"]
def to_csv(res):
    b = io.StringIO(); w = csv.writer(b); w.writerow(COLS)
    for g in res["groups"]:
        c = g.get("contact") or {}
        for r in g["rows"]:
            w.writerow([r["exchange"], R.code(r["chain"]), r["address"], r["type"], r["confidence"], r["level"], r["reason"], r.get("direction", ""), r["txid"] or "", r["time_utc"], r["time_uk"],
                        "" if r["amount"] is None else r["amount"], r["asset"], "" if r.get("gbp_then") is None else r["gbp_then"], "" if r.get("usd_then") is None else r["usd_then"],
                        r["from"], r["count"], r["note"], c.get("portal", ""), c.get("email", ""), c.get("source_url", ""), c.get("verified", "")])
    w.writerow([]); w.writerow([res["wording"]]); w.writerow([res["method"]])
    return b.getvalue()
