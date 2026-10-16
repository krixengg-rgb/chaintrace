"""Offline batch: train + evaluate the deposit-address model and crawl exchange hubs for new inferred deposit labels.
Usage: python3 infer_deposits.py collect|train|crawl|all [--n 160]
Outputs (committed, compact): data/deposit_model.json, data/inferred_deposits.json, data/deposit_eval.json
Only free public APIs are used, through chains.py's rate-limited/cached client."""
import asyncio, json, os, random, sys, time, math, collections, sqlite3
import numpy as np
import chains, labels, deposits as dep
W = os.path.join(os.path.dirname(__file__), "data", "depwork"); os.makedirs(W, exist_ok=True)
DB = sqlite3.connect(labels.LDB)
N = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 160
CONC = {"eth": 4, "sol": 1}
def raw_path(c): return os.path.join(W, f"raw_{c}.json")
def load_raw(c):
    try: return json.load(open(raw_path(c)))
    except Exception: return {}
def mini(d):
    return {"balance": d.get("balance"), "unit": d.get("unit"), "balance_usd": chains.usd_of(d.get("balance"), d.get("unit")),
            "edges": [{k: e.get(k) for k in ("source", "target", "amount", "unit", "usd", "count")} for e in d.get("edges", [])]}
async def fetch_all(c, addrs, raw, tag, budget_s):
    sem = asyncio.Semaphore(CONC[c]); t0 = time.time(); done = [0]
    async def one(a):
        if a in raw or time.time() - t0 > budget_s: return
        async with sem:
            if time.time() - t0 > budget_s: return
            try: d = await asyncio.wait_for(chains.ADDR[c](a), 60); raw[a] = {"tag": tag, **mini(d)}
            except Exception as ex: raw[a] = {"tag": tag, "error": str(ex)[:100], "edges": []}
            done[0] += 1
            if done[0] % 20 == 0:
                json.dump(raw, open(raw_path(c), "w")); print(c, tag, done[0], f"{int(time.time()-t0)}s", flush=True)
    await asyncio.gather(*[one(a) for a in addrs]); json.dump(raw, open(raw_path(c), "w"))
def positives(c):
    if c == "eth":
        q = "select address,entity,name from labels where chain='eth' and category='exchange' and (name like 'Bitget Dep:%' or name like '%: Deposit %' or name like '% Deposit %')"
        rows = [r for r in DB.execute(q) if "funder" not in r[2].lower() and "eth2" not in r[2].lower()]
    else:
        rows = list(DB.execute("select address,entity,name from labels where chain='sol' and name like '%deposit_wallet'"))
    random.Random(7).shuffle(rows); return rows
async def collect():
    for c in ("eth", "sol"):
        raw = load_raw(c); pos = positives(c)
        # stratify ETH so not only Bitget: take all non-Bitget first
        if c == "eth": pos = [r for r in pos if not r[2].startswith("Bitget")] + [r for r in pos if r[2].startswith("Bitget")]
        await fetch_all(c, [r[0] for r in pos[:N]], raw, "pos", 1500 if c == "eth" else 2400)
        # hard negatives: unlabelled senders INTO positives (mostly user wallets) + unlabelled counterparties of a DeFi router
        posset = {labels.norm(c, r[0]) for r in pos}; cand = []
        for a, v in raw.items():
            if v["tag"] != "pos": continue
            for e in v["edges"]:
                s = e["source"]
                if labels.norm(c, e["target"]) == labels.norm(c, a) and labels.norm(c, s) not in posset and not labels.db_labels(c, s) and not labels.EXCH.get(c, {}).get(labels.norm(c, s)):
                    cand.append(s)
        random.Random(11).shuffle(cand); cand = list(dict.fromkeys(cand))[:N]
        await fetch_all(c, cand, raw, "neg", 1500 if c == "eth" else 2400)
        print(c, "raw:", collections.Counter(v["tag"] for v in raw.values()), flush=True)
def learn_hubs(c, raw, train_pos):
    """collection wallets = targets receiving sweeps from >=2 distinct TRAIN positives, not themselves deposit-labelled."""
    rec = collections.defaultdict(set); ents = collections.defaultdict(collections.Counter)
    for a in train_pos:
        er = labels.db_labels(c, a); en = dep.ent_of(er)
        for e in raw[a]["edges"]:
            if labels.norm(c, e["source"]) == labels.norm(c, a) and labels.norm(c, e["target"]) != labels.norm(c, a):
                t = labels.norm(c, e["target"]); rec[t].add(a); ents[t][en] += 1
    hubs = {}
    for t, s in rec.items():
        if len(s) < 2: continue
        rows = labels.db_labels(c, t)
        if any(dep.is_deposit_row(r) for r in rows) or any(r["category"] not in ("exchange", "other") for r in rows): continue
        hubs[t] = ents[t].most_common(1)[0][0]
    return hubs
def Xy(c, raw, addrs, y, hubs):
    X, Y, miss = [], [], 0
    for a in addrs:
        r = dep.features(c, a, raw[a], hubs)
        if r is None: X.append(None); miss += 1
        else: X.append(([r[0][k] for k in dep.FEATS], r[2]))
        Y.append(y)
    return X, Y, miss
def fit(X, y, l2=0.5, it=4000, lr=0.1):
    X = np.array(X, float); y = np.array(y, float); w = np.zeros(X.shape[1]); b = 0.0
    for _ in range(it):
        p = 1 / (1 + np.exp(-(X @ w + b))); g = p - y
        w -= lr * (X.T @ g / len(y) + l2 * w / len(y)); b -= lr * g.mean()
    return {"bias": float(b), "w": [float(v) for v in w]}
def evaluate(X, y, m, th):
    tp = fp = fn = tn = 0
    for x, t in zip(X, y):
        p = 0.0 if x is None else dep.prob(dict(zip(dep.FEATS, x[0])), m) * (0 if dep.gate(x[1]) else 1)
        pr = p >= th
        tp += pr and t; fp += pr and not t; fn += (not pr) and t; tn += (not pr) and not t
    P = tp / (tp + fp) if tp + fp else None; R = tp / (tp + fn) if tp + fn else None
    return {"threshold": th, "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(P, 3) if P is not None else None, "recall": round(R, 3) if R is not None else None}
def train():
    out_m, out_e, out_h = {}, {}, {}
    for c in ("eth", "sol"):
        raw = {a: v for a, v in load_raw(c).items() if not v.get("error")}
        pos = [a for a, v in raw.items() if v["tag"] == "pos"]; neg = [a for a, v in raw.items() if v["tag"] == "neg"]
        rnd = random.Random(3); rnd.shuffle(pos); rnd.shuffle(neg)
        k1, k2 = int(len(pos) * .7), int(len(neg) * .7)
        trp, tep, trn, ten = pos[:k1], pos[k1:], neg[:k2], neg[k2:]
        hubs = learn_hubs(c, raw, trp)                          # learned from TRAIN positives only (no leakage)
        Xp, yp, mp = Xy(c, raw, trp, 1, hubs); Xn, yn, mn = Xy(c, raw, trn, 0, hubs)
        Xtr = [x[0] for x in Xp + Xn if x is not None]; ytr = [t for x, t in zip(Xp + Xn, yp + yn) if x is not None]
        m = fit(Xtr, ytr) if len(set(ytr)) == 2 else dict(dep.PRIOR)
        Tp, typ, tmp = Xy(c, raw, tep, 1, hubs); Tn, tyn, tmn = Xy(c, raw, ten, 0, hubs)
        ev = {"n_train_pos": len(trp), "n_train_neg": len(trn), "n_test_pos": len(tep), "n_test_neg": len(ten),
              "test_pos_without_hub": tmp, "test_neg_without_hub": tmn, "learned_hubs": len(hubs),
              "model": [evaluate(Tp + Tn, typ + tyn, m, th) for th in (0.5, 0.7, 0.85)],
              "heuristic_prior": [evaluate(Tp + Tn, typ + tyn, dep.PRIOR, th) for th in (0.5, 0.85)],
              "weights": dict(zip(dep.FEATS, [round(v, 2) for v in m["w"]])), "bias": round(m["bias"], 2),
              "negatives": "unlabelled wallets that sent funds into known deposit addresses (hard negatives; mostly users)"}
        # final model + hubs on ALL positives for production
        hubs_all = learn_hubs(c, raw, pos)
        Xa, ya, _ = Xy(c, raw, pos, 1, hubs_all); Xb, yb, _ = Xy(c, raw, neg, 0, hubs_all)
        XA = [x[0] for x in Xa + Xb if x is not None]; yA = [t for x, t in zip(Xa + Xb, ya + yb) if x is not None]
        hard = sum(1 for x, t in zip(Xa + Xb, ya + yb) if x is not None and t == 0)
        ev["hub_present_negatives_total"] = hard
        if hard < 20:   # too few hub-present negatives -> fitted model would just learn "has hub" => use documented prior
            out_m[c] = dict(dep.PRIOR); ev["model_used"] = f"heuristic prior (only {hard} hub-present negatives; fitted LR not trusted)"
        else: out_m[c] = fit(XA, yA); ev["model_used"] = "logistic regression"
        out_e[c] = ev; out_h[c] = hubs_all
        print(c, json.dumps(ev, indent=1), flush=True)
    # one model shared at runtime per chain
    json.dump({"bias": out_m["eth"]["bias"], "w": out_m["eth"]["w"], "per_chain": out_m, "trained": time.strftime("%Y-%m-%d")}, open("data/deposit_model.json", "w"), indent=1)
    json.dump(out_e, open("data/deposit_eval.json", "w"), indent=1)
    inf = dep._load("inferred_deposits.json", {"hubs": {}, "deposits": {}}); inf["hubs"] = out_h
    json.dump(inf, open("data/inferred_deposits.json", "w"), separators=(",", ":"))
def hubs_for_crawl(c):
    hs = dict((labels.norm(c, k), v.split(" ")[0]) for k, v in labels.EXCH.get(c, {}).items())
    if c == "eth":
        for a, n in DB.execute("select address,name from labels where chain='eth' and category='exchange' and source='dawsbot' and name glob '[A-Z]*[0-9]' and name not like '%Dep%' and name not like '%Funder%'"):
            if n.split(" ")[0] in ("Binance", "Coinbase", "Kraken", "OKX", "Bitget", "KuCoin", "Bybit", "Gate.io", "MEXC", "HTX", "Bitfinex", "Upbit"): hs[a] = n.split(" ")[0]
    learned = dep._load("inferred_deposits.json", {}).get("hubs", {}).get(c, {})
    top = collections.Counter(learned.values())
    for a, e in learned.items(): hs.setdefault(a, e)
    return hs
async def crawl(per_hub=15, budget={"eth": 700, "sol": 900}):
    dep.reload(); model = dep._load("deposit_model.json", {})
    inf = dep._load("inferred_deposits.json", {"hubs": {}, "deposits": {}}); inf.setdefault("deposits", {})
    for c in ("eth", "sol"):
        m = (model.get("per_chain") or {}).get(c) or dep.PRIOR; hs = hubs_for_crawl(c); raw = load_raw(c)
        hl = list(hs.items()); random.Random(5).shuffle(hl); hl = hl[:20 if c == "eth" else 10]
        print(c, "crawling", len(hl), "hubs", flush=True); hraw = {}
        await fetch_all(c, [a for a, _ in hl], hraw, "hub", budget[c] * 0.3)
        cand = []
        for h, v in hraw.items():
            snd = [e["source"] for e in v.get("edges", []) if labels.norm(c, e["target"]) == labels.norm(c, h)]
            snd = [s for s in dict.fromkeys(snd) if not labels.db_labels(c, s) and not labels.EXCH.get(c, {}).get(labels.norm(c, s)) and labels.norm(c, s) not in hs]
            cand += snd[:per_hub]
        cand = list(dict.fromkeys(cand)); print(c, "candidates", len(cand), flush=True)
        await fetch_all(c, cand, raw, "cand", budget[c] * 0.7)
        got = inf["deposits"].setdefault(c, {})
        for a in cand:
            v = raw.get(a)
            if not v or v.get("error"): continue
            r = dep.features(c, a, v, {labels.norm(c, k): e for k, e in hs.items()})
            if not r: continue
            f, ent, ev = r; p = dep.prob(f, m)
            if p >= 0.6 and not dep.gate(ev): got[labels.norm(c, a)] = [ent, round(p, 3), {k2: ev[k2] for k2 in ("hub", "sweeps", "outflows", "out_counterparties", "in_senders", "gas_topup_from_exchange", "usd_swept")}]
        print(c, "inferred", len(got), collections.Counter(x[0] for x in got.values()).most_common(10), flush=True)
    inf["generated"] = time.strftime("%Y-%m-%d"); json.dump(inf, open("data/inferred_deposits.json", "w"), separators=(",", ":"))
if __name__ == "__main__":
    st = sys.argv[1] if len(sys.argv) > 1 else "all"
    if st in ("collect", "all"): asyncio.run(collect())
    if st in ("train", "all"): train()
    if st in ("crawl", "all"): asyncio.run(crawl())
def rescore():
    """re-score already-fetched crawl candidates with the current model + gate (no network)."""
    dep.reload(); model = dep._load("deposit_model.json", {}); inf = dep._load("inferred_deposits.json", {"hubs": {}, "deposits": {}})
    inf["deposits"] = {}
    for c in ("eth", "sol"):
        m = (model.get("per_chain") or {}).get(c) or dep.PRIOR; hs = {labels.norm(c, k): e for k, e in hubs_for_crawl(c).items()}
        got = inf["deposits"].setdefault(c, {})
        for a, v in load_raw(c).items():
            if v.get("tag") != "cand" or v.get("error"): continue
            r = dep.features(c, a, v, hs)
            if not r: continue
            f, ent, ev = r; p = dep.prob(f, m)
            if p >= 0.6 and not dep.gate(ev): got[labels.norm(c, a)] = [ent, round(p, 3), {k2: ev[k2] for k2 in ("hub", "sweeps", "outflows", "out_counterparties", "in_senders", "gas_topup_from_exchange", "usd_swept")}]
        print(c, "inferred", len(got), collections.Counter(x[0] for x in got.values()).most_common(12))
    inf["generated"] = time.strftime("%Y-%m-%d"); json.dump(inf, open("data/inferred_deposits.json", "w"), separators=(",", ":"))
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "rescore": rescore()
