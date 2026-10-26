"""ChainTrace watchlist checks (stateless): watch items + last-seen cursors in, new alert events + new cursors out.
Used by POST /api/watch/check (browser keeps the list in IndexedDB) and by the box-side CLI watch_check.py."""
import asyncio, time, hashlib
import chains, labels, deposits, bridges
SANCT = {"sanctioned", "terrorism"}
RISKY = {"darknet", "ransomware", "hack", "scam", "blocklisted", "gambling"}
CATS = ("sanctioned", "mixer", "risky", "exchange", "exchange-deposit", "bridge", "labelled")
DEFAULT_RULES = {"any_tx": True, "out_usd": None, "cats": ["sanctioned", "mixer", "risky", "exchange", "exchange-deposit", "bridge"], "bal_pct": None}
NOISE = {"spam", "zero", "approval"}
FRESH_TTL = 45          # seconds: first history pages / balances are re-fetched at most this often while watching
MAX_EVENTS = 40         # per address per check (busy hot wallets are summarised beyond this)
SEV = {"high": 3, "medium": 2, "low": 1}

def cat_of(n):
    """watch category of a labelled counterparty node (None = unlabelled)"""
    k = n.get("kind")
    if k in SANCT: return "sanctioned"
    if k == "mixer": return "mixer"
    if k in RISKY: return "risky"
    if n.get("suggested") and (not k or k == "exchange") and n["suggested"].get("category") == "exchange-deposit": return "exchange-deposit"
    if k in ("exchange", "bridge"): return k
    return "labelled" if (k or n.get("name")) else None
def enrich(chain, a, cache):
    if a in cache: return cache[a]
    n = chains.node(chain, a)
    if chain in deposits.NATIVE and not n.get("kind"): deposits.decorate(n, deposits.lookup_batch(chain, a), endpoint_at=9)
    if not n.get("kind"): bridges.decorate_vault(n, chain)
    src = next((s.get("source") for s in (n.get("sources") or [])), None)
    cache[a] = {"id": a, "name": n.get("name"), "kind": n.get("kind"), "risk": n.get("risk") or 0, "source": src,
                "suggested": ({k: n["suggested"].get(k) for k in ("label", "entity", "confidence", "method")} if n.get("suggested") else None)}
    cache[a]["cat"] = cat_of({**n, "suggested": n.get("suggested")})
    return cache[a]
def norm_rules(r):
    r = {**DEFAULT_RULES, **(r or {})}
    try: r["out_usd"] = float(r["out_usd"]) if r.get("out_usd") not in (None, "", 0, "0") else None
    except Exception: r["out_usd"] = None
    try: r["bal_pct"] = float(r["bal_pct"]) if r.get("bal_pct") not in (None, "", 0, "0") else None
    except Exception: r["bal_pct"] = None
    r["cats"] = [c for c in (r.get("cats") or []) if c in CATS]; r["any_tx"] = bool(r.get("any_tx"))
    return r
def _eid(*xs): return hashlib.sha1("|".join(map(str, xs)).encode()).hexdigest()[:16]

async def check_one(item, cap=16.0):
    """item: {id, address, chain?, name, ref, rules, cursor?, since?} -> {id, status, cursor, events, summary, warnings}"""
    a = (item.get("address") or "").strip(); wid = item.get("id") or a
    c, kind = chains.detect(a)
    c = item.get("chain") if item.get("chain") in ("btc", "eth", "sol") and c else c
    if not c or kind != "address": return {"id": wid, "status": "error", "error": "not a BTC/ETH/SOL address", "events": []}
    rules = norm_rules(item.get("rules")); cur = dict(item.get("cursor") or {}); base = not cur.get("checked")
    if base and item.get("since"): cur = {"t": int(item["since"]), "seen": []}; base = False
    raw = {}; tf = chains.FRESH.set(FRESH_TTL); tr = chains.RAW.set(raw)
    try: d = await asyncio.wait_for(chains.ADDR[c](a), cap)
    except asyncio.TimeoutError: return {"id": wid, "status": "error", "error": f"{c} data sources too slow (>{cap:.0f}s)", "events": []}
    except Exception as e: return {"id": wid, "status": "error", "error": f"{c} upstream error: {type(e).__name__}: {str(e)[:120]}", "events": []}
    finally: chains.FRESH.reset(tf); chains.RAW.reset(tr)
    focus = d.get("address") or a; fl = focus.lower() if c == "eth" else focus
    same = (lambda x: (x or "").lower() == fl) if c == "eth" else (lambda x: x == fl)
    hist = [h for h in (d.get("txs") or []) if h.get("tx")]
    edges = raw.get("edges") or d.get("edges") or []
    by_tx = {}
    for e in edges: by_tx.setdefault(e.get("tx"), []).append(e)
    # group history entries per transaction (an ETH tx can carry ETH + several token transfers)
    txs = {}
    for h in hist:
        t = txs.setdefault(h["tx"], {"tx": h["tx"], "time": h.get("time"), "parts": [], "noise": True})
        if h.get("time") and (not t["time"] or h["time"] > t["time"]): t["time"] = h["time"]
        if not (set(h.get("flags") or []) & NOISE) and h.get("delta"): t["noise"] = False
        t["parts"].append(h)
    seen = set(cur.get("seen") or []); last_t = cur.get("t") or 0
    new = [t for t in txs.values() if t["tx"] not in seen and (base is False) and ((t["time"] or 9e12) > last_t - 600)]
    new.sort(key=lambda t: t["time"] or 9e12, reverse=True)
    lc = {}; events = []; pri = chains.PRICE
    for t in new:
        if t["noise"]: continue
        parts = [p for p in t["parts"] if not (set(p.get("flags") or []) & NOISE) and p.get("delta")]
        amts = {}
        for p in parts:
            u = p.get("unit") or d.get("unit"); x = amts.setdefault(u, {"unit": u, "amount": 0.0, "usd": 0.0, "priced": False})
            x["amount"] += p["delta"]
            if p.get("usd") is not None: x["usd"] += (p["usd"] if p["delta"] > 0 else -p["usd"]); x["priced"] = True
        amts = sorted(amts.values(), key=lambda x: -abs(x["usd"] or 0))
        net = sum(x["usd"] for x in amts if x["priced"]); priced = any(x["priced"] for x in amts)
        out_usd = -sum(x["usd"] for x in amts if x["priced"] and x["usd"] < 0)
        direction = "out" if (amts and amts[0]["amount"] < 0) else "in"
        cps = {}
        for e in by_tx.get(t["tx"], []):
            if same(e.get("source")) and not same(e.get("target")): k, dd = e.get("target"), "out"
            elif same(e.get("target")) and not same(e.get("source")): k, dd = e.get("source"), "in"
            else: continue
            if not k or k == "coinbase": continue
            v = chains.usd_of(e.get("amount"), e.get("unit"), e.get("rate")) or 0
            y = cps.setdefault(k, {"dir": dd, "usd": 0.0}); y["usd"] += v
        cpl = []
        for k, y in sorted(cps.items(), key=lambda kv: -kv[1]["usd"])[:25]:
            cpl.append({**enrich(c, k, lc), "dir": y["dir"], "usd": round(y["usd"], 2)})
        main = next((x for x in cpl if x["dir"] == direction), cpl[0] if cpl else None)
        flagged = [x for x in cpl if x["cat"] and x["cat"] in rules["cats"]]
        fired = []
        if rules["any_tx"]: fired.append("new transaction")
        if rules["out_usd"] and out_usd >= rules["out_usd"]: fired.append(f"outflow ≥ ${rules['out_usd']:,.0f}")
        for x in flagged[:3]: fired.append(f"{'to' if x['dir'] == 'out' else 'from'} {x['cat']}: {x['name'] or x['id'][:10]}")
        if not fired: continue
        sev = "high" if any(x["cat"] in ("sanctioned", "mixer", "risky") for x in flagged) else \
              "medium" if (flagged or (rules["out_usd"] and out_usd >= rules["out_usd"])) else "low"
        if flagged: main = flagged[0]
        events.append({"id": _eid(wid, t["tx"]), "type": "tx", "watch_id": wid, "address": focus, "chain": c, "name": item.get("name"), "ref": item.get("ref"),
                       "tx": t["tx"], "tx_url": bridges.CH[c][1] + t["tx"], "time": t["time"], "dir": direction,
                       "amounts": [{"unit": x["unit"], "amount": round(x["amount"], 10), "usd": round(x["usd"], 2) if x["priced"] else None} for x in amts[:4]],
                       "usd": round(abs(net), 2) if priced else None, "out_usd": round(out_usd, 2) if priced else None,
                       "counterparty": main, "counterparties": len(cpl), "flagged": flagged[:5], "rules": fired, "severity": sev})
    events.sort(key=lambda e: (-SEV[e["severity"]], -(e["time"] or 9e12)))
    extra = max(0, len(events) - MAX_EVENTS); events = events[:MAX_EVENTS]
    warn = list(d.get("warnings") or [])
    if extra: events.append({"id": _eid(wid, "more", time.time()), "type": "summary", "watch_id": wid, "address": focus, "chain": c, "name": item.get("name"), "ref": item.get("ref"),
                             "time": int(time.time()), "severity": "low", "rules": [f"{extra} more new transaction(s) not shown"], "amounts": []})
    if cur.get("checked") and txs and new and len(new) == len(txs) and d.get("next"):
        warn.append("More than one history page of new activity since the last check: only the most recent page was scanned (check more often for busy wallets).")
    bal = d.get("balance"); ob = cur.get("bal")
    if rules["bal_pct"] and bal is not None and ob is not None and cur.get("checked"):
        pct = (abs(bal - ob) / ob * 100) if ob else (100.0 if bal else 0)
        if pct >= rules["bal_pct"]:
            events.insert(0, {"id": _eid(wid, "bal", ob, bal), "type": "balance", "watch_id": wid, "address": focus, "chain": c, "name": item.get("name"), "ref": item.get("ref"),
                              "time": int(time.time()), "dir": "in" if bal > ob else "out", "severity": "medium",
                              "amounts": [{"unit": d.get("unit"), "amount": round(bal - ob, 10), "usd": chains.usd_of(abs(bal - ob), d.get("unit"))}],
                              "usd": chains.usd_of(abs(bal - ob), d.get("unit")), "balance_from": ob, "balance_to": bal,
                              "rules": [f"balance {'+' if bal > ob else '−'}{pct:.1f}% ({ob:.8g} → {bal:.8g} {d.get('unit')})"]})
    times = [t["time"] for t in txs.values() if t["time"]]
    allseen = list(dict.fromkeys([t["tx"] for t in sorted(txs.values(), key=lambda t: t["time"] or 9e12, reverse=True)] + list(cur.get("seen") or [])))[:150]
    ncur = {"t": max([last_t] + times), "seen": allseen, "bal": bal if bal is not None else ob, "checked": int(time.time()), "n": int(cur.get("n") or 0) + 1}
    me = enrich(c, focus, lc)
    last = max(times) if times else None
    return {"id": wid, "status": "baseline" if base else "ok", "address": focus, "chain": c, "cursor": ncur, "events": events, "warnings": warn[:4],
            "summary": {"balance": bal, "unit": d.get("unit"), "balance_usd": chains.usd_of(bal, d.get("unit")), "tx_count": d.get("tx_count"),
                        "last_activity": last, "label": {k: me.get(k) for k in ("name", "kind", "cat")}, "new_txs": len(new), "events": len(events),
                        "page_txs": len(txs)}}

async def check_many(items, budget=21.0, conc=3, per=16.0, stagger=0.35):
    """bounded batch: at most `conc` addresses in flight, staggered starts; items not started in time come back 'deferred'"""
    t0 = time.time(); sem = asyncio.Semaphore(conc); await chains.ensure_prices()
    try: await asyncio.wait_for(bridges.refresh_vaults(), 4)
    except Exception: pass
    async def run(i, it):
        await asyncio.sleep(i * stagger)
        async with sem:
            left = budget - (time.time() - t0)
            if left < 5: return {"id": it.get("id") or it.get("address"), "status": "deferred", "events": [], "error": "time budget used; checked next round"}
            return await check_one(it, min(per, left - 1))
    return await asyncio.gather(*[run(i, it) for i, it in enumerate(items)])
