"""Quality gate for a new inferred-deposit scan. Exit 0 = publish (candidate copied to data/), 1 = refuse.
Checks: (1) no drastic shrink vs published, (2) spot-check statistics look sane, (3) held-out precision not below baseline."""
import gzip, json, os, random, shutil, statistics, sys, time, collections
import deposits as dep, infer_deposits as I
H = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(H, "data"); W = os.path.join(D, "depwork")
CAND = os.path.join(W, "candidate.jsonl.gz"); PUB = os.path.join(D, "inferred_deposits.jsonl.gz"); LEGACY = os.path.join(D, "inferred_deposits.json")
MIN_KEEP = 0.8          # new count per chain must be >= 80% of published
def read(path):
    out = collections.defaultdict(dict)
    if path.endswith(".gz") and os.path.exists(path):
        with gzip.open(path, "rt") as f:
            for l in f:
                r = json.loads(l)
                if r["t"] == "dep": out[r["c"]][r["a"]] = r
    elif os.path.exists(path):
        for c, m in json.load(open(path)).get("deposits", {}).items():
            for a, (e, p, ev) in m.items(): out[c][a] = {"e": e, "p": p, "ev": ev}
    return out
def main(dry=False):
    fails, rep = [], {"time": time.strftime("%Y-%m-%d %H:%M")}
    if not os.path.exists(CAND): print("GATE FAIL: no candidate file"); return 1
    new = read(CAND); old = read(PUB if os.path.exists(PUB) else LEGACY)
    for c in ("eth", "sol"):
        n, o = len(new.get(c, {})), len(old.get(c, {})); rep[f"{c}_count"] = {"new": n, "published": o}
        if o and n < MIN_KEEP * o: fails.append(f"{c}: shrinks {o} -> {n}")
        rows = list(new.get(c, {}).values())
        if not rows: continue
        bad = [r for r in rows if dep.gate(r["ev"])]
        cps = statistics.median(r["ev"].get("out_counterparties", 0) for r in rows); mp = statistics.mean(r["p"] for r in rows)
        top = collections.Counter(r["e"] for r in rows).most_common(1)[0]
        st = {"gate_violations": len(bad), "median_out_counterparties": cps, "mean_confidence": round(mp, 3),
              "top_exchange_share": round(top[1] / len(rows), 3), "top_exchange": top[0],
              "single_sweep_share": round(sum(1 for r in rows if r["ev"].get("sweeps", 0) <= 1) / len(rows), 3)}
        rep[f"{c}_spotcheck"] = st
        if bad: fails.append(f"{c}: {len(bad)} rows violate sanity rules")
        if cps > 4: fails.append(f"{c}: median outgoing counterparties {cps} > 4")
        if mp < 0.8: fails.append(f"{c}: mean confidence {mp:.2f} < 0.80")
        if len(rows) >= 50 and top[1] / len(rows) > 0.9: fails.append(f"{c}: {top[0]} is {top[1]/len(rows):.0%} of output (suspicious)")
        if len(rows) >= 50 and st["single_sweep_share"] > 0.6: fails.append(f"{c}: {st['single_sweep_share']:.0%} single-sweep labels (weak evidence)")
        sample = random.Random(int(time.time())).sample(rows, min(20, len(rows)))
        json.dump(sample, open(os.path.join(W, f"spotcheck_{c}_{time.strftime('%Y%m%d')}.json"), "w"), indent=1)   # for human review
    base = json.load(open(os.path.join(D, "deposit_eval.json")))
    cur = I.eval_only(); rep["heldout_at_0.85"] = cur
    for c, r in cur.items():
        bm = base[c]["model"] if "logistic" in base[c].get("model_used", "") else base[c]["heuristic_prior"]
        bp = next(x["precision"] for x in bm if x["threshold"] == 0.85)
        rep[f"{c}_baseline_precision"] = bp
        if r["precision"] is None or r["precision"] < bp: fails.append(f"{c}: held-out precision {r['precision']} < baseline {bp}")
    rep["fails"] = fails; rep["passed"] = not fails
    print(json.dumps(rep, indent=1))
    if fails: print("GATE FAIL:", "; ".join(fails)); return 1
    if not dry:
        shutil.copy(CAND, PUB)
        if os.path.exists(LEGACY): os.remove(LEGACY)
        json.dump(rep, open(os.path.join(D, "deposit_scan_report.json"), "w"), indent=1)
    print("GATE PASS" + (" (dry run)" if dry else ": published " + PUB)); return 0
if __name__ == "__main__": sys.exit(main("--dry" in sys.argv))
