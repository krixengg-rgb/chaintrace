import httpx, time, asyncio, re, json, sqlite3, os, base64
from datetime import datetime
from labels import label
# HTTP cache: disposable. On an ephemeral disk (Render free) it is simply rebuilt after restarts.
CACHE_PATH = os.environ.get("CHAINTRACE_CACHE", os.path.join(os.path.dirname(__file__), "cache.sqlite"))
CACHE_MAX_ROWS = int(os.environ.get("CHAINTRACE_CACHE_MAX_ROWS", "20000"))
def _open_cache():
    try:
        os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
        db = sqlite3.connect(CACHE_PATH, check_same_thread=False)
        db.execute("PRAGMA journal_mode=WAL"); db.execute("CREATE TABLE IF NOT EXISTS cache(k TEXT PRIMARY KEY, ts REAL, v TEXT)")
        return db
    except Exception as e:   # corrupt/unwritable -> fall back to in-memory cache
        print("cache.sqlite unavailable, using memory:", e)
        db = sqlite3.connect(":memory:", check_same_thread=False); db.execute("CREATE TABLE cache(k TEXT PRIMARY KEY, ts REAL, v TEXT)"); return db
DB = _open_cache(); DB.execute("PRAGMA cache_size=-4000")
_writes = [0]
WARN = []
CP_LAST = [None]   # counterparties of the most recent page (read synchronously right after ADDR returns)
NEG = {}
STATS = {"hit": 0, "miss": 0}
class _C:
    def __contains__(self, k):
        r = DB.execute("SELECT ts FROM cache WHERE k=?", (repr(k),)).fetchone(); return bool(r)
    def __getitem__(self, k):
        ts, v = DB.execute("SELECT ts, v FROM cache WHERE k=?", (repr(k),)).fetchone(); return (ts, json.loads(v))
    def __setitem__(self, k, tv):
        DB.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (repr(k), tv[0], json.dumps(tv[1]))); DB.commit()
        _writes[0] += 1
        if _writes[0] % 500 == 0:   # keep disk bounded: drop oldest rows beyond cap
            DB.execute("DELETE FROM cache WHERE k IN (SELECT k FROM cache ORDER BY ts DESC LIMIT -1 OFFSET ?)", (CACHE_MAX_ROWS,)); DB.commit()
_cache = _C()
TTL = 300
LONG = 30 * 86400   # immutable data (old pages, confirmed txs)
SEM = {"mempool.space": asyncio.Semaphore(3), "blockscout": asyncio.Semaphore(4), "solana": asyncio.Semaphore(1), "other": asyncio.Semaphore(4)}
def _sem(u):
    if u.startswith(os.environ.get("CHAINTRACE_BS", "https://eth.blockscout.com")): return SEM["blockscout"]   # stalled Blockscout never starves RPC
    return next((v for k, v in SEM.items() if k in u), SEM["other"])
def ts_of(t):
    if t is None: return None
    if isinstance(t, (int, float)): return int(t)
    try: return int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())
    except Exception: return None
def enc(c): return base64.urlsafe_b64encode(json.dumps(c).encode()).decode() if c else None
def dec(c): return json.loads(base64.urlsafe_b64decode(c.encode())) if c else None
client = httpx.AsyncClient(timeout=httpx.Timeout(15, connect=6), headers={"User-Agent": "chaintrace-mvp"},
                           limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))
# ---- USD prices (CoinGecko free simple-price, cached 10 min) ----
PRICE = {"USDT": 1.0, "USDC": 1.0, "DAI": 1.0, "USDS": 1.0, "PYUSD": 1.0, "FDUSD": 1.0, "TUSD": 1.0, "USDE": 1.0}
_price_ts = [0.0]
async def ensure_prices():
    if time.time() - _price_ts[0] < 600: return PRICE
    _price_ts[0] = time.time()
    try:
        d = await asyncio.wait_for(get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd", ttl=600), 4)
        b, e, s = d["bitcoin"]["usd"], d["ethereum"]["usd"], d["solana"]["usd"]
        PRICE.update({"BTC": b, "WBTC": b, "ETH": e, "WETH": e, "STETH": e, "SOL": s, "WSOL": s})
    except Exception as ex:
        try:   # fallback: Coinbase spot (CoinGecko often 429s shared cloud IPs such as Render)
            r = await asyncio.wait_for(asyncio.gather(*[get(f"https://api.coinbase.com/v2/prices/{c}-USD/spot", ttl=600) for c in ("BTC", "ETH", "SOL")]), 5)
            b, e, s = (float(x["data"]["amount"]) for x in r)
            PRICE.update({"BTC": b, "WBTC": b, "ETH": e, "WETH": e, "STETH": e, "SOL": s, "WSOL": s})
        except Exception as ex2:
            print("price fetch failed:", ex, "| fallback:", ex2); _price_ts[0] = time.time() - 540   # retry in ~1 min
    return PRICE
def usd_of(amount, unit, rate=None):
    p = rate or PRICE.get((unit or "").upper())
    try: return round(float(amount) * float(p), 2) if p and amount is not None else None
    except Exception: return None
async def get(url, ttl=TTL, **kw):
    k = ("GET", url, str(kw))
    if k in _cache and time.time() - _cache[k][0] < ttl: STATS["hit"] += 1; return _cache[k][1]
    STATS["miss"] += 1
    async with _sem(url):
      for i in range(4):
        r = await client.get(url, **kw)
        if r.status_code == 429: await asyncio.sleep(1.5 * (i + 1)); continue
        r.raise_for_status(); break
      if "solana" not in url: await asyncio.sleep(0.15)
    if r.status_code == 429: raise Exception("rate limited")
    d = r.json(); _cache[k] = (time.time(), d); return d
async def rpc(url, method, params, ttl=None):
    k = (url, method, str(params))
    ttl = ttl or (LONG if method == "getTransaction" else TTL)
    if k in _cache and time.time() - _cache[k][0] < ttl: STATS["hit"] += 1; return _cache[k][1]
    STATS["miss"] += 1
    async with _sem(url):
      for i in range(5):
        r = await client.post(url, json={"jsonrpc":"2.0","id":1,"method":method,"params":params})
        if r.status_code == 429: await asyncio.sleep(2 * (i + 1)); continue
        r.raise_for_status(); break
      if "solana" in url: await asyncio.sleep(0.12)
    if r.status_code == 429: raise Exception("rate limited")
    j = r.json()
    if "error" in j: raise Exception(j["error"])
    _cache[k] = (time.time(), j["result"]); return j["result"]

def detect(q):
    q = q.strip()
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", q): return "eth", "address"
    if re.fullmatch(r"0x[0-9a-fA-F]{64}", q): return "eth", "tx"
    if re.fullmatch(r"[0-9a-fA-F]{64}", q): return "btc", "tx"
    if re.fullmatch(r"(bc1[02-9ac-hj-np-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})", q): return "btc", "address"
    if re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{80,90}", q): return "sol", "tx"
    if re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", q): return "sol", "address"
    return None, None

def node(chain, a, tags=None):
    l = label(chain, a, tags); return {"id": a, "chain": chain, **l}

# ---------------- BTC (mempool.space) ----------------
MP = "https://mempool.space/api"
def btc_edges(tx):
    ins = {}; outs = {}
    for v in tx["vin"]:
        a = (v.get("prevout") or {}).get("scriptpubkey_address") or ("coinbase" if v.get("is_coinbase") else None)
        if a: ins[a] = ins.get(a, 0) + (v.get("prevout") or {}).get("value", 0)
    for o in tx["vout"]:
        a = o.get("scriptpubkey_address")
        if a: outs[a] = outs.get(a, 0) + o["value"]
    return ins, outs
async def btc_address(a, limit=25):
    info = await get(f"{MP}/address/{a}"); txs = (await get(f"{MP}/address/{a}/txs"))[:limit]
    cs, ms = info["chain_stats"], info["mempool_stats"]
    bal = (cs["funded_txo_sum"] - cs["spent_txo_sum"] + ms["funded_txo_sum"] - ms["spent_txo_sum"]) / 1e8
    nodes = {a: node("btc", a)}; edges = []; hist = []; cluster = {a}
    for tx in txs:
        ins, outs = btc_edges(tx)
        sent = ins.get(a, 0); recv = outs.get(a, 0)
        if a in ins:  # common-input-ownership heuristic
            cluster |= {x for x in ins if x != "coinbase"}
            for o, v in outs.items():
                if o != a: edges.append({"source": a, "target": o, "amount": v/1e8, "unit": "BTC", "tx": tx["txid"]})
        else:
            for i, v in ins.items():
                edges.append({"source": i, "target": a, "amount": recv/1e8 if len(ins)==1 else v/1e8, "unit": "BTC", "tx": tx["txid"]})
        hist.append({"tx": tx["txid"], "time": tx["status"].get("block_time"), "delta": (recv - sent)/1e8, "unit": "BTC",
                     "fee": tx.get("fee",0)/1e8, "confirmed": tx["status"]["confirmed"]})
    edges = _agg(edges, 40)
    for e in edges:
        for k in ("source","target"): nodes.setdefault(e[k], node("btc", e[k]))
    return {"chain":"btc","address":a,"balance":bal,"unit":"BTC","tx_count":cs["tx_count"]+ms["tx_count"],
            "txs":hist,"nodes":list(nodes.values()),"edges":edges,"cluster":sorted(cluster)}
async def btc_tx(h):
    tx = await get(f"{MP}/tx/{h}"); ins, outs = btc_edges(tx); nodes = {}; edges = []
    tid = "tx:" + h
    nodes[tid] = {"id": tid, "chain":"btc","kind":"tx","name":"tx "+h[:10],"tags":[],"risk":0}
    for i, v in ins.items(): edges.append({"source": i, "target": tid, "amount": v/1e8, "unit": "BTC", "tx": h})
    for o, v in outs.items(): edges.append({"source": tid, "target": o, "amount": v/1e8, "unit": "BTC", "tx": h})
    for e in edges:
        for k in ("source","target"): nodes.setdefault(e[k], node("btc", e[k]))
    return {"chain":"btc","tx":h,"fee":tx.get("fee",0)/1e8,"time":tx["status"].get("block_time"),"unit":"BTC",
            "cluster":sorted(x for x in ins if x!="coinbase"),"nodes":list(nodes.values()),"edges":edges,
            "inputs":[{"address":k,"value":v/1e8} for k,v in ins.items()],"outputs":[{"address":k,"value":v/1e8} for k,v in outs.items()]}

def _agg(edges, cap):
    m = {}
    for e in edges:
        k = (e["source"], e["target"])
        t = e.get("time") if isinstance(e.get("time"), (int, float)) else ts_of(e.get("time"))
        if k in m:
            x = m[k]; x["amount"] += e["amount"]; x["count"] += 1
            if t: x["first"] = min(x.get("first") or t, t); x["last"] = max(x.get("last") or t, t)
            if e.get("flags"): x["flags"] = sorted(set(x.get("flags") or []) & set(e["flags"]))   # flagged only if every transfer is
            else: x["flags"] = []
        else: m[k] = {**e, "count": 1, "first": t, "last": t, "flags": list(e.get("flags") or [])}
    return sorted(m.values(), key=lambda e: -e["amount"])[:cap]

# ---------------- ETH (Blockscout + public RPC) ----------------
BS = os.environ.get("CHAINTRACE_BS", "https://eth.blockscout.com/api/v2"); ETH_RPC = "https://ethereum-rpc.publicnode.com"
def _tags(x):
    if not x: return []
    t = [g["name"] for g in ((x.get("metadata") or {}).get("tags") or [])]
    t += [g.get("display_name") or g.get("label") for g in (x.get("public_tags") or [])]
    if x.get("name") and not t: t.append(x["name"])
    return [s for s in t if s]
async def eth_address(a, limit=40):
    info, txs, tts = await asyncio.gather(get(f"{BS}/addresses/{a}"), get(f"{BS}/addresses/{a}/transactions"),
                                          get(f"{BS}/addresses/{a}/token-transfers"), return_exceptions=False)
    try: bal = int(await rpc(ETH_RPC, "eth_getBalance", [a, "latest"]), 16) / 1e18; src = "rpc"
    except Exception: bal = int(info.get("coin_balance") or 0) / 1e18; src = "blockscout"
    al = a.lower(); seen = {}; edges = []; hist = []
    def reg(x):
        if x and x.get("hash"): seen.setdefault(x["hash"], _tags(x))
    reg({**info, "hash": info["hash"]})
    for t in txs.get("items", [])[:limit]:
        f, to = t.get("from"), t.get("to"); reg(f); reg(to)
        v = int(t.get("value") or 0) / 1e18
        if f and to: edges.append({"source": f["hash"], "target": to["hash"], "amount": v, "tx": t["hash"], "unit":"ETH"})
        hist.append({"tx": t["hash"], "time": t.get("timestamp"), "delta": v if (to and to["hash"].lower()==al) else -v,
                     "unit":"ETH", "method": t.get("method"), "status": t.get("status")})
    for t in tts.get("items", [])[:limit]:
        f, to = t.get("from"), t.get("to"); reg(f); reg(to)
        tok = t.get("token") or {}; tot = t.get("total") or {}
        try: v = int(tot.get("value") or 0) / 10 ** int(tot.get("decimals") or tok.get("decimals") or 0)
        except Exception: v = 0
        sym = tok.get("symbol") or "TOKEN"
        if f and to: edges.append({"source": f["hash"], "target": to["hash"], "amount": v, "tx": t.get("transaction_hash"), "unit": sym})
        hist.append({"tx": t.get("transaction_hash"), "time": t.get("timestamp"), "delta": v if (to and to["hash"].lower()==al) else -v, "unit": sym, "method":"token transfer"})
    edges = _agg_unit(edges, 50)
    nodes = {k: node("eth", k, v) for k, v in seen.items() if any(k in (e["source"], e["target"]) for e in edges) or k == info["hash"]}
    tc = info.get("transactions_count")
    try:
        c = await get(f"{BS}/addresses/{a}/counters"); tc = c.get("transactions_count")
    except Exception: pass
    hist.sort(key=lambda h: h.get("time") or "", reverse=True)
    return {"chain":"eth","address":info["hash"],"balance":bal,"balance_source":src,"unit":"ETH","tx_count":tc,
            "is_contract":info.get("is_contract"),"txs":hist[:60],"nodes":list(nodes.values()),"edges":edges}
# ---- noise flags: 'zero' value, 'approval' calls, 'spam' tokens (Blockscout reputation / URL-like names), 'unpriced' tokens
APPROVE = re.compile(r"approv|allowance|setApprovalForAll|permit", re.I)
SPAMNAME = re.compile(r"https?:|www\.|\.(com|io|org|net|xyz|app|site|top|finance|gift)\b|t\.me|claim|reward|visit|airdrop|voucher|\$ ?\d|✅|🎁", re.I)
def token_flags(tok, rate, v):
    fl = []
    if not v: fl.append("zero")
    rep = (tok.get("reputation") or "ok").lower()
    if rep not in ("ok", "") or SPAMNAME.search(f"{tok.get('name') or ''} {tok.get('symbol') or ''}"): fl.append("spam")
    if rate is None and (tok.get("symbol") or "").upper() not in PRICE:
        fl.append("unpriced")
        try: many = int(tok.get("holders_count") or tok.get("holders") or 0) >= 20000
        except Exception: many = False
        if many and "spam" not in fl: fl.append("spam")   # airdrop heuristic: no market price but very widely distributed
    return fl
def _agg_unit(edges, cap):
    m = {}
    for e in edges:
        k = (e["source"], e["target"], e["unit"])
        t = e.get("time") if isinstance(e.get("time"), (int, float)) else ts_of(e.get("time"))
        if k in m:
            x = m[k]; x["amount"] += e["amount"]; x["count"] += 1
            if t: x["first"] = min(x.get("first") or t, t); x["last"] = max(x.get("last") or t, t)
            if e.get("flags"): x["flags"] = sorted(set(x.get("flags") or []) & set(e["flags"]))   # flagged only if every transfer is
            else: x["flags"] = []
        else: m[k] = {**e, "count": 1, "first": t, "last": t, "flags": list(e.get("flags") or [])}
    for e in m.values(): e["usd"] = usd_of(e["amount"], e["unit"], e.pop("rate", None))
    # keep the biggest flows by USD where known, then by frequency
    return sorted(m.values(), key=lambda e: (-(e["usd"] or 0), -e["count"]))[:cap]
def counterparties(chain, focus, agg, raw=None, limit=150):
    """per (counterparty, direction) summary of flows touching `focus`: USD, per-token amounts, tx count, first/last seen, flags"""
    fl = focus.lower() if chain == "eth" else focus; cps = {}
    for e in agg:
        s_, t_ = (e["source"].lower(), e["target"].lower()) if chain == "eth" else (e["source"], e["target"])
        if s_ == fl and t_ != fl: cp, d = e["target"], "out"
        elif t_ == fl and s_ != fl: cp, d = e["source"], "in"
        else: continue
        if cp.startswith("tx:") or cp == "coinbase": continue
        x = cps.setdefault((cp, d), {"id": cp, "dir": d, "usd": 0.0, "count": 0, "units": {}, "uusd": {}, "ucount": {}, "first": None, "last": None, "flags": None})
        x["usd"] += e.get("usd") or 0; x["count"] += e.get("count", 1)
        x["units"][e["unit"]] = x["units"].get(e["unit"], 0) + (e.get("amount") or 0)
        x["uusd"][e["unit"]] = round(x["uusd"].get(e["unit"], 0) + (e.get("usd") or 0), 2); x["ucount"][e["unit"]] = x["ucount"].get(e["unit"], 0) + e.get("count", 1)
        for k_, fn in (("first", min), ("last", max)):
            if e.get(k_): x[k_] = fn(x[k_] or e[k_], e[k_])
        x["flags"] = sorted(set(e.get("flags") or [])) if x["flags"] is None else sorted(set(x["flags"]) & set(e.get("flags") or []))
    out = sorted(cps.values(), key=lambda x: (-x["usd"], -x["count"]))[:limit]
    for x in out:
        x["usd"] = round(x["usd"], 2); n = node(chain, x["id"])
        x.update(name=n.get("name"), kind=n.get("kind"), risk=n.get("risk"))
    series = []
    for e in (raw or []):
        s_, t_ = (e["source"].lower(), e["target"].lower()) if chain == "eth" else (e["source"], e["target"])
        if fl not in (s_, t_) or s_ == t_: continue
        t = e.get("time") if isinstance(e.get("time"), (int, float)) else ts_of(e.get("time"))
        if t: series.append([t, round(usd_of(e.get("amount"), e.get("unit"), e.get("rate")) or 0, 2), "out" if s_ == fl else "in", e["unit"], 1 if e.get("flags") else 0])
    series.sort(); return {"counterparties": out, "series": series[-800:]}
async def eth_tx(h):
    (t, err), (tt_, _) = await asyncio.gather(_cap(get(f"{BS}/transactions/{h}"), BS_TIMEOUT + 3), _cap(get(f"{BS}/transactions/{h}/token-transfers"), BS_TIMEOUT))
    if t is None: raise Exception(f"Blockscout transaction endpoint unavailable ({err}); try again shortly")
    tts = (tt_ or {}).get("items", [])
    tid = "tx:" + h; nodes = {tid: {"id": tid,"chain":"eth","kind":"tx","name":"tx "+h[:10],"tags":[],"risk":0}}; edges = []
    f, to = t.get("from"), t.get("to")
    for x in (f, to):
        if x: nodes[x["hash"]] = node("eth", x["hash"], _tags(x))
    v = int(t.get("value") or 0) / 1e18
    if f: edges.append({"source": f["hash"], "target": tid, "amount": v, "unit":"ETH", "tx": h})
    if to: edges.append({"source": tid, "target": to["hash"], "amount": v, "unit":"ETH", "tx": h})
    for tt in tts:
        a, b = tt.get("from"), tt.get("to"); tok = tt.get("token") or {}; tot = tt.get("total") or {}
        try: val = int(tot.get("value") or 0) / 10 ** int(tot.get("decimals") or tok.get("decimals") or 0)
        except Exception: val = 0
        for x in (a, b):
            if x: nodes.setdefault(x["hash"], node("eth", x["hash"], _tags(x)))
        if a and b: edges.append({"source": a["hash"], "target": b["hash"], "amount": val, "unit": tok.get("symbol") or "TOKEN", "tx": h})
    return {"chain":"eth","tx":h,"time":t.get("timestamp"),"status":t.get("status"),"method":t.get("method"),
            "fee":int((t.get("fee") or {}).get("value") or 0)/1e18,"unit":"ETH","nodes":list(nodes.values()),"edges":edges}

# ---------------- SOL (public RPC) ----------------
SOL = "https://api.mainnet-beta.solana.com"
SYS = {"11111111111111111111111111111111","ComputeBudget111111111111111111111111111111"}
def sol_transfers(tx):
    """Extract (from, to, amount, unit) from parsed SOL + SPL transfers; token accounts resolved to owners."""
    if not tx: return []
    m = tx["transaction"]["message"]; meta = tx.get("meta") or {}
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in m["accountKeys"]]
    owner = {}; mint = {}
    for b in (meta.get("preTokenBalances") or []) + (meta.get("postTokenBalances") or []):
        owner[keys[b["accountIndex"]]] = b.get("owner"); mint[keys[b["accountIndex"]]] = b.get("mint")
    ins = list(m.get("instructions", []))
    for ii in meta.get("innerInstructions") or []: ins += ii.get("instructions", [])
    out = []
    for i in ins:
        p = i.get("parsed")
        if not isinstance(p, dict) or p.get("type") not in ("transfer", "transferChecked"): continue
        info = p.get("info", {})
        if i.get("program") == "system":
            out.append((info.get("source"), info.get("destination"), int(info.get("lamports", 0))/1e9, "SOL"))
        elif i.get("program") in ("spl-token", "spl-token-2022"):
            s, d = info.get("source"), info.get("destination")
            amt = (info.get("tokenAmount") or {}).get("uiAmount")
            mt = info.get("mint") or mint.get(s) or mint.get(d)
            if amt is None:
                dec = next((b["uiTokenAmount"]["decimals"] for b in (meta.get("postTokenBalances") or []) if b.get("mint")==mt), 0)
                amt = int(info.get("amount", 0)) / 10 ** dec
            unit = SOL_TOKENS.get(mt, (mt or "SPL")[:6] + "…")
            out.append((owner.get(s) or info.get("authority") or s, owner.get(d) or d, amt, unit))
    return [o for o in out if o[0] and o[1]]
SOL_DEADLINE = float(os.environ.get("CHAINTRACE_SOL_DEADLINE", "17"))
SOL_TOKENS = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":"USDC","Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB":"USDT",
              "So11111111111111111111111111111111111111112":"wSOL"}
async def sol_address(a, limit=15):
    bal = (await rpc(SOL, "getBalance", [a]))["value"] / 1e9
    sigs = await rpc(SOL, "getSignaturesForAddress", [a, {"limit": limit}])
    edges = []; hist = []
    for s in sigs:
        try: tx = await rpc(SOL, "getTransaction", [s["signature"], {"encoding":"jsonParsed","maxSupportedTransactionVersion":0}])
        except Exception: tx = None
        tr = sol_transfers(tx); d = {}
        for f, t, v, u in tr:
            edges.append({"source": f, "target": t, "amount": v, "unit": u, "tx": s["signature"]})
            if t == a: d[u] = d.get(u, 0) + v
            if f == a: d[u] = d.get(u, 0) - v
        hist.append({"tx": s["signature"], "time": s.get("blockTime"), "delta": round(next(iter(d.values()), 0), 9),
                     "unit": next(iter(d), "SOL"), "status": "error" if s.get("err") else "ok", "method": f"{len(tr)} transfer(s)"})
    edges = _agg_unit(edges, 50); nodes = {a: node("sol", a)}
    for e in edges:
        for k in ("source","target"): nodes.setdefault(e[k], node("sol", e[k]))
    try: tokens = await rpc(SOL, "getTokenAccountsByOwner", [a, {"programId":"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding":"jsonParsed"}])
    except Exception: tokens = {"value": []}
    tb = []
    for t in tokens.get("value", [])[:50]:
        inf = t["account"]["data"]["parsed"]["info"]; amt = inf["tokenAmount"].get("uiAmount") or 0
        if amt: tb.append({"mint": inf["mint"], "symbol": SOL_TOKENS.get(inf["mint"]), "amount": amt})
    return {"chain":"sol","address":a,"balance":bal,"unit":"SOL","tx_count":f"{len(sigs)} (recent)","tokens":tb[:20],
            "txs":hist,"nodes":list(nodes.values()),"edges":edges}
async def sol_tx(sig):
    tx = await rpc(SOL, "getTransaction", [sig, {"encoding":"jsonParsed","maxSupportedTransactionVersion":0}])
    if not tx: raise Exception("transaction not found")
    tid = "tx:" + sig; nodes = {tid: {"id": tid,"chain":"sol","kind":"tx","name":"tx "+sig[:10],"tags":[],"risk":0}}; edges = []
    for f, t, v, u in sol_transfers(tx):
        edges.append({"source": f, "target": t, "amount": v, "unit": u, "tx": sig})
        for x in (f, t): nodes.setdefault(x, node("sol", x))
    return {"chain":"sol","tx":sig,"time":tx.get("blockTime"),"fee":(tx.get("meta") or {}).get("fee",0)/1e9,"unit":"SOL",
            "status":"error" if (tx.get("meta") or {}).get("err") else "ok","nodes":list(nodes.values()),"edges":edges}

ADDR = {"btc": btc_address, "eth": eth_address, "sol": sol_address}
TX = {"btc": btc_tx, "eth": eth_tx, "sol": sol_tx}

# ======== v2: paginated history (overrides v1 address fetchers) ========
def _inrange(t, f, to):
    return t is None or ((f is None or t >= f) and (to is None or t <= to))
def _finish_page(chain, focus, edges, hist, ntags=None, cap=60):
    raw = edges; agg = _agg_unit([dict(e) for e in edges], 10 ** 9); edges = agg[:cap]; ntags = ntags or {}
    try: CP_LAST[0] = counterparties(chain, focus, agg, raw)
    except Exception as ex: CP_LAST[0] = {"counterparties": [], "series": [], "error": str(ex)}
    nodes = {focus: node(chain, focus, ntags.get(focus))}
    for e in edges:
        for k in ("source", "target"): nodes.setdefault(e[k], node(chain, e[k], ntags.get(e[k])))
    hist.sort(key=lambda h: h.get("time") or 0, reverse=True)
    for h in hist: h["usd"] = usd_of(abs(h.get("delta") or 0), h.get("unit"), h.pop("rate", None))
    return list(nodes.values()), edges, hist

async def btc_page(a, cursor=None):
    if cursor == "__chain__": url = f"{MP}/address/{a}/txs/chain"   # first confirmed page (first page was all mempool)
    else: url = f"{MP}/address/{a}/txs" + (f"/chain/{cursor}" if cursor else "")
    txs = await get(url, ttl=LONG if cursor and cursor != "__chain__" else 900)
    conf = [t for t in txs if t["status"]["confirmed"]]
    nxt = conf[-1]["txid"] if len(conf) >= 25 else None
    if not cursor and len(txs) >= 25 and len(conf) < 25: nxt = conf[-1]["txid"] if conf else "__chain__"   # mempool-heavy first page
    return txs, nxt
async def btc_address(a, cursor=None, f=None, to=None, pages=1):
    out = {"chain": "btc", "address": a, "unit": "BTC"}; await ensure_prices()
    if not cursor:
        info = await get(f"{MP}/address/{a}"); cs, ms = info["chain_stats"], info["mempool_stats"]
        out["balance"] = (cs["funded_txo_sum"] - cs["spent_txo_sum"] + ms["funded_txo_sum"] - ms["spent_txo_sum"]) / 1e8
        out["tx_count"] = cs["tx_count"] + ms["tx_count"]
    edges, hist, cluster = [], [], {a}
    for _ in range(max(1, pages)):
        txs, cursor_n = await btc_page(a, cursor)
        for tx in txs:
            t = tx["status"].get("block_time")
            if not _inrange(t, f, to): continue
            ins, outs = btc_edges(tx); sent = ins.get(a, 0); recv = outs.get(a, 0)
            if a in ins:
                cluster |= {x for x in ins if x != "coinbase"}
                for o, v in outs.items():
                    if o != a: edges.append({"source": a, "target": o, "amount": v/1e8, "unit": "BTC", "tx": tx["txid"], "time": t})
            else:
                for i, v in ins.items():
                    edges.append({"source": i, "target": a, "amount": recv/1e8 if len(ins)==1 else v/1e8, "unit": "BTC", "tx": tx["txid"], "time": t})
            hist.append({"tx": tx["txid"], "time": t, "delta": (recv - sent)/1e8, "unit": "BTC", "fee": tx.get("fee",0)/1e8, "confirmed": tx["status"]["confirmed"]})
        cursor = cursor_n
        oldest = min((x["status"].get("block_time") or 9e12 for x in txs), default=None)
        if not cursor or (f and oldest and oldest < f): cursor = None if (f and oldest and oldest < f) else cursor; break
        if hist: break  # got something in range; let user click "load more"
    out["nodes"], out["edges"], out["txs"] = _finish_page("btc", a, edges, hist); out["cp"] = CP_LAST[0]
    out["cluster"] = sorted(cluster); out["next"] = cursor
    return out

BS_TIMEOUT = float(os.environ.get("CHAINTRACE_BS_TIMEOUT", "9"))      # hard per-call cap for Blockscout info/counters/tx
BS_STREAM_TIMEOUT = float(os.environ.get("CHAINTRACE_BS_STREAM_TIMEOUT", "11"))   # history streams (token-transfers is often ~9s)
ETH_RPCS = [ETH_RPC, "https://eth.drpc.org", "https://cloudflare-eth.com"]   # free, keyless public RPCs (raced)
ETHPLORER = "https://api.ethplorer.io"                                 # documented public 'freekey' (no signup), fallback only
async def _cap(coro, t):
    try: return await asyncio.wait_for(coro, t), None
    except Exception as ex: return None, type(ex).__name__ or "error"
async def _bs_stream(a, path, params):
    """one Blockscout history stream; never raises. returns (items, next, failed)"""
    if params == "done": return [], "done", False
    nk = f"{a}/{path}/{params}"
    if time.time() - NEG.get(nk, 0) < 600: return [], params, True
    d, err = await _cap(get(f"{BS}/addresses/{a}/{path}", ttl=LONG if params else 900, params=params or {}), 8 if "internal" in path else BS_STREAM_TIMEOUT)
    if d is None:
        NEG[nk] = time.time(); WARN.append(f"blockscout {path} unavailable for {a[:10]}: {err}"); return [], params, True
    return d.get("items", []), (d.get("next_page_params") or "done"), False
async def eth_rpc_any(method, params, t=7):
    """race the free RPCs; first good answer wins"""
    async def one(u):
        r = await rpc(u, method, params)
        if r is None: raise Exception("empty")
        return r
    tasks = [asyncio.create_task(one(u)) for u in ETH_RPCS]
    try:
        for fut in asyncio.as_completed(tasks, timeout=t):
            try: return await fut
            except Exception: continue
    except Exception: pass
    finally:
        for x in tasks: x.cancel()
    return None
async def _ethplorer_history(a, want_eth=True, want_tok=True):
    """fallback history when Blockscout streams fail (ETH transfers + token transfers, last ~50 each)"""
    al = a.lower(); edges = []; hist = []
    async def none(): return None
    (txs, _), (th, _) = await asyncio.gather(
        _cap(get(f"{ETHPLORER}/getAddressTransactions/{al}", ttl=600, params={"apiKey": "freekey", "limit": 50}) if want_eth else none(), 8),
        _cap(get(f"{ETHPLORER}/getAddressHistory/{al}", ttl=600, params={"apiKey": "freekey", "limit": 50, "type": "transfer"}) if want_tok else none(), 8))
    for t in (txs if isinstance(txs, list) else []):
        fr, too, v = t.get("from"), t.get("to"), float(t.get("value") or 0)
        if fr and too: edges.append({"source": fr, "target": too, "amount": v, "tx": t.get("hash"), "unit": "ETH", "time": t.get("timestamp")})
        hist.append({"tx": t.get("hash"), "time": t.get("timestamp"), "delta": v if (too or "").lower() == al else -v, "unit": "ETH", "status": "ok" if t.get("success", True) else "error", "method": "transfer (ethplorer)"})
    for t in ((th or {}).get("operations") or []):
        ti = t.get("tokenInfo") or {}; sym = ti.get("symbol") or "TOKEN"
        try: v = int(t.get("value") or 0) / 10 ** int(ti.get("decimals") or 0)
        except Exception: v = 0
        try: rate = float((ti.get("price") or {}).get("rate")) if ti.get("price") else None
        except Exception: rate = None
        fr, too = t.get("from"), t.get("to")
        if fr and too: edges.append({"source": fr, "target": too, "amount": v, "tx": t.get("transactionHash"), "unit": sym, "time": t.get("timestamp"), "rate": rate})
        hist.append({"tx": t.get("transactionHash"), "time": t.get("timestamp"), "delta": v if (too or "").lower() == al else -v, "unit": sym, "method": "token transfer (ethplorer)", "rate": rate})
    return edges, hist, (isinstance(txs, list) or th is not None)
async def eth_address(a, cursor=None, f=None, to=None, pages=1):
    out = {"chain": "eth", "unit": "ETH", "address": a}
    await ensure_prices()
    t0 = time.time(); DEADLINE = float(os.environ.get("CHAINTRACE_ETH_DEADLINE", "18")); miss = []
    async def _hdr():
        # every source capped and concurrent; any of them may fail without failing the lookup
        (info, e1), (cnt, e2), bal, code, nonce = await asyncio.gather(
            _cap(get(f"{BS}/addresses/{a}"), BS_TIMEOUT), _cap(get(f"{BS}/addresses/{a}/counters"), min(6, BS_TIMEOUT)),
            eth_rpc_any("eth_getBalance", [a, "latest"]), eth_rpc_any("eth_getCode", [a, "latest"]), eth_rpc_any("eth_getTransactionCount", [a, "latest"]))
        if info: out["address"] = info.get("hash") or a
        else: miss.append("address info")
        if bal: out["balance"] = int(bal, 16) / 1e18; out["balance_source"] = "rpc"
        elif info: out["balance"] = int(info.get("coin_balance") or 0) / 1e18; out["balance_source"] = "blockscout"
        else: out["balance"] = None; out["balance_source"] = "unavailable"
        out["is_contract"] = info.get("is_contract") if info else (None if code is None else code not in ("0x", "0x0", ""))
        if cnt: out["tx_count"] = cnt.get("transactions_count"); out["token_transfers_count"] = cnt.get("token_transfers_count")
        else: miss.append("counters")
        try: cval = int(out.get("tx_count") or 0)
        except Exception: cval = 0
        if nonce and int(nonce, 16) > cval:   # missing/stale Blockscout counter (total txs can't be below outgoing nonce) -> RPC nonce
            out["tx_count"] = int(nonce, 16); out["tx_count_note"] = "outgoing txs (nonce) from RPC"
    hdr = asyncio.create_task(_hdr()) if not cursor else None   # runs concurrently with the history streams
    cur = dec(cursor) or {"t": None, "k": None, "i": None}
    al = a.lower(); ntags = {}; edges = []; hist = []
    def reg(x):
        if x and x.get("hash"): ntags.setdefault(x["hash"], _tags(x))
    failed = set(); spec = None
    if not cursor and not (f or to):
        async def _spec():   # hedge: if Blockscout hasn't answered within 5s, fetch the fallback in parallel
            await asyncio.sleep(5); return await _ethplorer_history(a, True, True)
        spec = asyncio.create_task(_spec())
    for _ in range(max(1, pages)):
        (tx, ct, f1), (tt, ck, f2), (it, ci, f3) = await asyncio.gather(_bs_stream(a, "transactions", cur["t"]),
            _bs_stream(a, "token-transfers", cur["k"]), _bs_stream(a, "internal-transactions", cur["i"]))
        for n_, fl in (("transactions", f1), ("token transfers", f2), ("internal transactions", f3)):
            if fl: failed.add(n_)
        cur = {"t": ct, "k": ck, "i": ci}; times = []
        for t in tx:
            fr, too = t.get("from"), t.get("to"); reg(fr); reg(too); ts = ts_of(t.get("timestamp")); times.append(ts)
            if not _inrange(ts, f, to): continue
            v = int(t.get("value") or 0) / 1e18
            fl = (["zero"] if not v else []) + (["approval"] if APPROVE.search(t.get("method") or "") else [])
            if fr and too: edges.append({"source": fr["hash"], "target": too["hash"], "amount": v, "tx": t["hash"], "unit": "ETH", "time": ts, "flags": fl})
            hist.append({"tx": t["hash"], "time": ts, "delta": v if (too and too["hash"].lower()==al) else -v, "unit": "ETH", "method": t.get("method"), "status": t.get("status"), "flags": fl})
        for t in tt:
            fr, too = t.get("from"), t.get("to"); reg(fr); reg(too); ts = ts_of(t.get("timestamp")); times.append(ts)
            if not _inrange(ts, f, to): continue
            tok = t.get("token") or {}; tot = t.get("total") or {}
            try: v = int(tot.get("value") or 0) / 10 ** int(tot.get("decimals") or tok.get("decimals") or 0)
            except Exception: v = 0
            sym = tok.get("symbol") or "TOKEN"
            try: rate = float(tok.get("exchange_rate")) if tok.get("exchange_rate") else None
            except Exception: rate = None
            fl = token_flags(tok, rate, v)
            if fr and too: edges.append({"source": fr["hash"], "target": too["hash"], "amount": v, "tx": t.get("transaction_hash"), "unit": sym, "time": ts, "rate": rate, "flags": fl})
            hist.append({"tx": t.get("transaction_hash"), "time": ts, "delta": v if (too and too["hash"].lower()==al) else -v, "unit": sym, "method": "token transfer", "rate": rate, "flags": fl})
        for t in it:
            fr, too = t.get("from"), t.get("to"); reg(fr); reg(too); ts = ts_of(t.get("timestamp")); times.append(ts)
            v = int(t.get("value") or 0) / 1e18
            if not v or not _inrange(ts, f, to): continue
            if fr and too: edges.append({"source": fr["hash"], "target": too["hash"], "amount": v, "tx": t.get("transaction_hash"), "unit": "ETH", "time": ts, "internal": True})
            hist.append({"tx": t.get("transaction_hash"), "time": ts, "delta": v if (too and too["hash"].lower()==al) else -v, "unit": "ETH", "method": "internal"})
        times = [x for x in times if x]
        done = all(v == "done" for v in cur.values())
        if f and times and max(times) < f: done = True
        if done or hist or failed or time.time() - t0 > DEADLINE: break
    if ({"transactions", "token transfers"} & failed) and not cursor and not (f or to):
        we, wt = "transactions" in failed, "token transfers" in failed
        if spec:
            try: e2_, h2_, ok = await asyncio.wait_for(spec, 9)
            except Exception: e2_, h2_, ok = [], [], False
            keep = lambda h_: (we and "token" not in (h_.get("method") or "")) or (wt and "token" in (h_.get("method") or ""))
            e2_ = [e for e in e2_ if (we and e["unit"] == "ETH") or (wt and e["unit"] != "ETH")]; h2_ = [h_ for h_ in h2_ if keep(h_)]
            spec = None
        else: e2_, h2_, ok = await _ethplorer_history(a, we, wt)
        what = " + ".join(x for x, w in (("ETH transfers", we), ("token transfers", wt)) if w)
        cs = {x.lower(): x for e in edges for x in (e["source"], e["target"])}   # reuse checksum forms seen from Blockscout
        for e in e2_: e["source"] = cs.get(e["source"].lower(), e["source"]); e["target"] = cs.get(e["target"].lower(), e["target"])
        if ok: edges += e2_; hist += h2_; out["history_source"] = f"{what} from Ethplorer (fallback, last ~50)"
        else: out["history_source"] = f"{what} unavailable"
    if spec: spec.cancel()
    if hdr:
        try: await asyncio.wait_for(hdr, max(1, 20 - (time.time() - t0)))
        except Exception: miss.append("header")
        out.setdefault("balance", None)
    # canonical address: from Blockscout info, else the checksummed form seen in edges, else as typed
    if not out.get("address") or out["address"] == a:
        seen = next((x for e in edges for x in (e["source"], e["target"]) if x.lower() == al and x != al), None)
        out["address"] = seen or a
    a = out["address"]
    for e in edges:   # unify case of the focus address across sources
        if e["source"].lower() == al: e["source"] = a
        if e["target"].lower() == al: e["target"] = a
    out["nodes"], out["edges"], out["txs"] = _finish_page("eth", a, edges, hist, ntags); out["cp"] = CP_LAST[0]
    out["next"] = None if all(v == "done" for v in cur.values()) or (f and done) else enc(cur)
    if failed or miss:
        out["partial"] = True
        out["warnings"] = [f"Some data unavailable from Blockscout ({', '.join(sorted(failed) + miss)}); showing partial results"
                           + (f" — history from {out['history_source']}" if out.get("history_source") else "")]
    return out

async def sol_address(a, cursor=None, f=None, to=None, pages=1, limit=15):
    out = {"chain": "sol", "address": a, "unit": "SOL"}; t0 = time.time(); await ensure_prices()
    if not cursor:
        out["balance"] = (await rpc(SOL, "getBalance", [a]))["value"] / 1e9
        try: tokens = await asyncio.wait_for(rpc(SOL, "getTokenAccountsByOwner", [a, {"programId":"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding":"jsonParsed"}]), 6)
        except Exception: tokens = {"value": []}
        tb = []
        for t in tokens.get("value", [])[:50]:
            inf = t["account"]["data"]["parsed"]["info"]; amt = inf["tokenAmount"].get("uiAmount") or 0
            if amt: tb.append({"mint": inf["mint"], "symbol": SOL_TOKENS.get(inf["mint"]), "amount": amt})
        out["tokens"] = tb[:20]
    edges, hist = [], []; nxt = cursor
    for _ in range(max(1, pages)):
        opts = {"limit": limit}
        if nxt: opts["before"] = nxt
        sigs = await rpc(SOL, "getSignaturesForAddress", [a, opts], ttl=LONG if nxt else 600)
        nxt = sigs[-1]["signature"] if len(sigs) >= limit else None
        stop = False
        for s in sigs:
            if time.time() - t0 > SOL_DEADLINE:   # partial page instead of a proxy timeout; Load more continues from here
                out["partial"] = True; nxt = hist[-1]["tx"] if hist else nxt
                out["warnings"] = [f"Solana RPC is slow right now: showing the {len(hist)} most recent transaction(s) fetched in time; use Load more for the rest"]
                break
            t = s.get("blockTime")
            if to and t and t > to: continue
            if f and t and t < f: stop = True; continue
            try: tx = await rpc(SOL, "getTransaction", [s["signature"], {"encoding":"jsonParsed","maxSupportedTransactionVersion":0}])
            except Exception: tx = None
            tr = sol_transfers(tx); d = {}
            for fr, tt_, v, u in tr:
                edges.append({"source": fr, "target": tt_, "amount": v, "unit": u, "tx": s["signature"], "time": t})
                if tt_ == a: d[u] = d.get(u, 0) + v
                if fr == a: d[u] = d.get(u, 0) - v
            hist.append({"tx": s["signature"], "time": t, "delta": round(next(iter(d.values()), 0), 9), "unit": next(iter(d), "SOL"),
                         "status": "error" if s.get("err") else "ok", "method": f"{len(tr)} transfer(s)"})
        if stop: nxt = None
        if not nxt or hist: break
    out["nodes"], out["edges"], out["txs"] = _finish_page("sol", a, edges, hist); out["cp"] = CP_LAST[0]
    out["tx_count"] = "paged"; out["next"] = nxt
    return out

ADDR = {"btc": btc_address, "eth": eth_address, "sol": sol_address}

def merge_cp(a, b):
    """merge two counterparties() results (pages)"""
    cp_ = lambda x: dict(x, units=dict(x["units"]), uusd=dict(x.get("uusd") or {}), ucount=dict(x.get("ucount") or {}))
    m = {(x["id"], x["dir"]): cp_(x) for x in a.get("counterparties", [])}
    for x in b.get("counterparties", []):
        k = (x["id"], x["dir"])
        if k not in m: m[k] = cp_(x); continue
        y = m[k]; y["usd"] = round(y["usd"] + x["usd"], 2); y["count"] += x["count"]
        for f_ in ("units", "uusd", "ucount"):
            for u, v in (x.get(f_) or {}).items(): y[f_][u] = y[f_].get(u, 0) + v
        for k_, fn in (("first", min), ("last", max)):
            vals = [v for v in (y.get(k_), x.get(k_)) if v]; y[k_] = fn(vals) if vals else None
        y["flags"] = sorted(set(y.get("flags") or []) & set(x.get("flags") or []))
    ser = sorted((a.get("series") or []) + (b.get("series") or []))
    return {"counterparties": sorted(m.values(), key=lambda x: (-x["usd"], -x["count"]))[:300], "series": ser[-1500:]}
