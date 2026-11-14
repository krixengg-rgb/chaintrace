"""Deep (full) address history for EVM chains whose public explorer API is not reachable from the server
(Arbitrum One, Base and Polygon Blockscout sit behind a bot challenge; BSC has no public Blockscout).

Sources, best first (each paginated with its own cursor; every one optional):
  1. Etherscan API V2   env ETHERSCAN_API_KEY  (free key; free tier covers Ethereum, Arbitrum One, Polygon - not Base/OP/BSC)
  2. Alchemy Transfers  env ALCHEMY_API_KEY    (free key; Ethereum, Arbitrum, Base, Polygon, OP, BSC)
  3. 3xpl public sandbox (keyless, no signup; rate-limited ~30 req/min per server IP, uptime not guaranteed):
     native, internal and ERC-20 balance movements for the full history; counterparties and token amounts are then
     read from each transaction's receipt over the chain's public RPC (cached forever: confirmed txs are immutable).
  4. (caller) recent-window public RPC log scan - last resort.
Everything returned is public blockchain data; counterparties of internal transfers are the contract that executed
them (lead-grade)."""
import os, json, base64, asyncio, time
import chains, evmcfg

def env(k): return (os.environ.get(k) or "").strip() or None
ES_FREE = {"eth": 1, "arb": 42161, "polygon": 137}
AL_NET = {"eth": "eth-mainnet", "arb": "arb-mainnet", "base": "base-mainnet", "polygon": "polygon-mainnet", "op": "opt-mainnet", "bsc": "bnb-mainnet"}
X3 = {"arb": "arbitrum-one", "base": "base", "polygon": "polygon", "op": "optimism", "bsc": "bnb", "eth": "ethereum"}
X3_URL = os.environ.get("CHAINTRACE_3XPL", "https://sandbox-api.3xpl.com")
X3_DEAD = {}   # chain -> time the sandbox refused / failed (back off 5 min)
LAST = {}      # (chain, address lower) -> {t, src, note, next} of the last deep page served (read by chains.evm_address)
DECODE_CAP = int(os.environ.get("CHAINTRACE_DEEP_DECODE", "60"))   # txs per page whose receipts are decoded for counterparties

def enc(c): return base64.urlsafe_b64encode(json.dumps(c, separators=(",", ":")).encode()).decode().rstrip("=") if c else None
def dec(c):
    if not c: return None
    try: return json.loads(base64.urlsafe_b64decode(c + "=" * (-len(c) % 4)))
    except Exception: return None

def sources(chain):
    s = []
    if env("ETHERSCAN_API_KEY") and chain in ES_FREE: s.append("etherscan")
    if env("ALCHEMY_API_KEY") and chain in AL_NET: s.append("alchemy")
    if chain in X3 and os.environ.get("CHAINTRACE_3XPL_OFF") != "1": s.append("3xpl")
    return s
def unlock_note(chain):
    if chain in ES_FREE and not env("ETHERSCAN_API_KEY"): return "Set ETHERSCAN_API_KEY (free Etherscan key) or ALCHEMY_API_KEY (free) on the server for faster, unthrottled full history."
    if chain in AL_NET and not env("ALCHEMY_API_KEY"): return "Set ALCHEMY_API_KEY (free Alchemy key) on the server for faster, unthrottled full history (Etherscan's free tier does not cover this chain)."
    return ""
NAMES = {"etherscan": "Etherscan API V2 (your key)", "alchemy": "Alchemy Transfers API (your key)", "3xpl": "3xpl public sandbox (keyless, rate-limited) + public RPC receipts"}

async def page(chain, a, cursor=None, f=None, to=None):
    """-> {edges, hist, ok, src, next, note}; tries the cursor's source, else each available source in order"""
    c = dec(cursor) or {}; order = [c["s"]] if c.get("s") else sources(chain); err = []
    for s in order:
        if s == "3xpl" and time.time() - X3_DEAD.get(chain, 0) < 300 and not c: err.append("3xpl: backing off"); continue
        try:
            fn = {"etherscan": _etherscan, "alchemy": _alchemy, "3xpl": _x3}[s]
            edges, hist, nxt = await asyncio.wait_for(fn(chain, a, c if c.get("s") == s else {}, f, to), 28)
            nx = enc(dict(nxt, s=s)) if nxt else None
            return {"edges": edges, "hist": hist, "ok": True, "src": NAMES[s], "next": nx, "note": unlock_note(chain) if s == "3xpl" else ""}
        except Exception as e:
            if s == "3xpl": X3_DEAD[chain] = time.time()
            err.append(f"{s}: {type(e).__name__} {str(e)[:80]}")
    return {"edges": [], "hist": [], "ok": False, "src": None, "next": None, "note": "; ".join(err)}

def _keep(t, f, to): return chains._inrange(t, f, to)

# ---------------- Etherscan V2 ----------------
async def _etherscan(chain, a, c, f, to):
    U = evmcfg.EVM[chain]["unit"]; p = int(c.get("p") or 1); al = a.lower(); edges, hist = [], []
    base = "https://api.etherscan.io/v2/api"
    async def act(action):
        r = await chains.get(base, ttl=chains.LONG if p > 1 else 300, params={"chainid": ES_FREE[chain], "module": "account", "action": action, "address": a,
                                                                              "page": p, "offset": 50, "sort": "desc", "apikey": env("ETHERSCAN_API_KEY")})
        if str(r.get("status")) != "1" and "No transactions" not in str(r.get("message")): raise Exception(str(r.get("result"))[:120])
        return r.get("result") if isinstance(r.get("result"), list) else []
    txs, toks, ints = await asyncio.gather(act("txlist"), act("tokentx"), act("txlistinternal"))
    for t, kind in [(x, "tx") for x in txs] + [(x, "tok") for x in toks] + [(x, "int") for x in ints]:
        ts = int(t.get("timeStamp") or 0) or None
        if not _keep(ts, f, to) or t.get("isError") == "1": continue
        if kind == "tok":
            try: v = int(t.get("value") or 0) / 10 ** int(t.get("tokenDecimal") or 0)
            except Exception: v = 0
            unit = t.get("tokenSymbol") or "TOKEN"
        else: v = int(t.get("value") or 0) / 1e18; unit = U
        fr, too = t.get("from") or "", t.get("to") or t.get("contractAddress") or ""
        if not v or not fr or not too: continue
        e = {"source": fr, "target": too, "amount": v, "unit": unit, "tx": t.get("hash"), "time": ts}
        if kind == "int": e["internal"] = True
        edges.append(e)
        hist.append({"tx": t.get("hash"), "time": ts, "delta": v if too.lower() == al else -v, "unit": unit,
                     "method": {"tx": "transfer", "tok": "token transfer", "int": "internal"}[kind] + " (etherscan)"})
    more = any(len(x) >= 50 for x in (txs, toks, ints))
    return edges, hist, ({"p": p + 1} if more else None)

# ---------------- Alchemy ----------------
async def _alchemy(chain, a, c, f, to):
    U = evmcfg.EVM[chain]["unit"]; al = a.lower(); edges, hist = [], []
    url = f"https://{AL_NET[chain]}.g.alchemy.com/v2/{env('ALCHEMY_API_KEY')}"
    cats = ["external", "erc20"] + (["internal"] if chain in ("eth", "polygon") else [])
    async def q(side, key):
        if key == "done": return [], "done"
        prm = {"category": cats, "order": "desc", "maxCount": "0x32", "withMetadata": True, "excludeZeroValue": True, side: a}
        if key: prm["pageKey"] = key
        r = await chains.rpc(url, "alchemy_getAssetTransfers", [prm], ttl=chains.LONG if key else 300)
        return r.get("transfers") or [], r.get("pageKey") or "done"
    (tf, kf), (tt, kt) = await asyncio.gather(q("fromAddress", c.get("f")), q("toAddress", c.get("t")))
    for t in tf + tt:
        ts = chains.ts_of((t.get("metadata") or {}).get("blockTimestamp"))
        if not _keep(ts, f, to): continue
        v = float(t.get("value") or 0); fr, too = t.get("from") or "", t.get("to") or ""
        unit = t.get("asset") or (U if t.get("category") in ("external", "internal") else "TOKEN")
        if not v or not fr or not too: continue
        e = {"source": fr, "target": too, "amount": v, "unit": unit, "tx": t.get("hash"), "time": ts}
        if t.get("category") == "internal": e["internal"] = True
        edges.append(e)
        hist.append({"tx": t.get("hash"), "time": ts, "delta": v if too.lower() == al else -v, "unit": unit, "method": f"{t.get('category')} (alchemy)"})
    return edges, hist, ({"f": kf, "t": kt} if (kf != "done" or kt != "done") else None)

# ---------------- 3xpl sandbox + public RPC receipts ----------------
MODS = ("main", "trace", "erc-20")
async def _x3get(path, params):
    r = await chains.get(f"{X3_URL}/{path}", ttl=300, params=params)
    if not isinstance(r, dict) or not isinstance(r.get("data"), dict): raise Exception(f"3xpl: {str((r or {}).get('data'))[:100]}")
    return r["data"]
async def _rpc_seq(chain, method, params):
    """one RPC at a time (no racing: many calls per page), first good answer; cached forever for mined txs"""
    for u in evmcfg.EVM[chain]["rpcs"]:
        try:
            r = await asyncio.wait_for(chains.rpc(u, method, params, ttl=chains.LONG), 8)
            if r is not None: return r
        except Exception: continue
    return None
async def _x3(chain, a, c, f, to):
    import swaps
    slug = X3[chain]; U = evmcfg.EVM[chain]["unit"]; al = a.lower(); p = int(c.get("p") or 0)
    mods = c.get("m") or list(MODS)
    evs = {}   # module -> events
    if p == 0:
        d = await _x3get(f"{slug}/address/{a}", {"data": "events", "from": "all", "limit": 100})
        for m in MODS: evs[m] = (d.get("events") or {}).get(f"{slug}-{m}") or []
    else:
        res = await asyncio.gather(*[_x3get(f"{slug}/address/{a}", {"data": "events", "from": f"{slug}-{m}", "limit": 100, "page": f"-{p}"}) for m in mods], return_exceptions=True)   # negative pages = newest first
        for m, r in zip(mods, res):
            if isinstance(r, Exception): raise r
            evs[m] = (r.get("events") or {}).get(f"{slug}-{m}") or []
    more = [m for m in mods if len(evs.get(m) or []) >= 100]
    # per-tx movements of the watched address
    by = {}
    for m in mods:
        for e in evs.get(m) or []:
            if e.get("failed"): continue
            if m == "main" and e.get("extra"): continue   # gas fee components (burnt / to the sequencer)
            try: eff = int(e.get("effect") or "0")
            except Exception: continue
            if not eff: continue
            t = by.setdefault(e["transaction"], {"time": chains.ts_of(e.get("time")), "mov": []})
            t["mov"].append((m, e.get("currency") or "", eff))
    txs = sorted(by.items(), key=lambda kv: -(kv[1]["time"] or 0))
    txs = [kv for kv in txs if _keep(kv[1]["time"], f, to)]
    sem = asyncio.Semaphore(6)
    async def decode(h):
        async with sem:
            tx, rc = await asyncio.gather(_rpc_seq(chain, "eth_getTransactionByHash", [h]), _rpc_seq(chain, "eth_getTransactionReceipt", [h]))
            return tx, rc
    dec_ = await asyncio.gather(*[decode(h) for h, _ in txs[:DECODE_CAP]], return_exceptions=True)
    rcpt = {h: r for (h, _), r in zip(txs, dec_) if not isinstance(r, Exception)}
    edges, hist = [], []
    for h, t in txs:
        ts = t["time"]; tx, rc = rcpt.get(h) or (None, None)
        fr = (tx or {}).get("from") or ""; too = (tx or {}).get("to") or (rc or {}).get("contractAddress") or ""
        for m, cur, eff in t["mov"]:
            if m == "erc-20":
                tok = cur.split("/", 1)[-1].lower()
                sym, dcm = await swaps.token(tok, chain)
                v = abs(eff) / 10 ** dcm; unit = sym
                hist.append({"tx": h, "time": ts, "delta": v if eff > 0 else -v, "unit": unit, "method": "token transfer (3xpl)"})
                if rc:   # counterparties from the receipt's Transfer logs of this token touching the address
                    for l in rc.get("logs") or []:
                        tp = l.get("topics") or []
                        if len(tp) == 3 and tp[0] == chains.T_TRANSFER and (l.get("address") or "").lower() == tok:
                            s_, d_ = chains._a32(tp[1]), chains._a32(tp[2])
                            if al not in (s_, d_): continue
                            amt = int(l.get("data") or "0x0", 16) / 10 ** dcm
                            if amt: edges.append({"source": s_, "target": d_, "amount": amt, "unit": unit, "tx": h, "time": ts})
            else:
                v = abs(eff) / 1e18
                hist.append({"tx": h, "time": ts, "delta": v if eff > 0 else -v, "unit": U, "method": ("transfer" if m == "main" else "internal") + " (3xpl)"})
                if not tx: continue
                if m == "main":
                    if eff < 0 and too: edges.append({"source": a, "target": too, "amount": v, "unit": U, "tx": h, "time": ts})
                    elif eff > 0 and fr: edges.append({"source": fr, "target": a, "amount": v, "unit": U, "tx": h, "time": ts})
                else:   # internal transfer: the executing contract is the visible counterparty (lead-grade)
                    cp = too if too.lower() != al else fr
                    if cp: edges.append({"source": cp if eff > 0 else a, "target": a if eff > 0 else cp, "amount": v, "unit": U, "tx": h, "time": ts, "internal": True})
    return edges, hist, ({"p": p + 1, "m": more} if more else None)
