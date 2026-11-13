"""Sanctions screening (official lists) + community scam reports (unverified leads).

Sanctions: data/sanctions.json (built by update_sanctions.py from the US Treasury OFAC SDN Advanced XML and the UK Sanctions List).
The repo ships a baseline; the app refreshes it in a separate low-priority process when it is more than a day old.
Community reports: scam / hack / phishing labels already in labels.sqlite (GraphSense, Forta, dawsbot, etherscan-labels, ScamSniffer),
plus Chainabuse reports when CHAINABUSE_API_KEY is set (cached; free keys allow only ~10 calls a month, so calls are explicit only)."""
import asyncio, json, os, sqlite3, subprocess, sys, threading, time
H = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(H, "data", "sanctions.json")
RUNTIME = os.environ.get("CHAINTRACE_SANCTIONS") or os.path.join(os.path.dirname(os.environ.get("CHAINTRACE_CACHE") or os.path.join(H, "cache.sqlite")), "chaintrace-sanctions.json")
STALE_SECS = 86400
S = {"idx": {}, "raw": {}, "lists": {}, "counts": {}, "generated": 0, "sha256": None, "path": None, "refreshing": False, "last_refresh": None, "refresh_error": None}
REPORT_CATS = {"scam", "hack", "ransomware", "darknet", "blocklisted", "terrorism"}
NOT_REPORTS = {"ofac", "builtin", "allowlist"}   # official list / own seed data are not "community reports"
SUPPORTED = ("btc", "eth", "sol", "tron", "xrp", "bsc", "arb", "base", "polygon", "op")

EVM_ALIAS = ("bsc", "arb", "base", "polygon", "op")   # EVM chains screened against the 0x (ETH/EVM) listings
def key(chain, a):
    a = (a or "").strip()
    if chain in EVM_ALIAS or chain == "eth": a = a.split(":", 1)[1] if ":" in a and a.split(":", 1)[0] in EVM_ALIAS else a
    if chain == "eth" or a.startswith("0x"): return a.lower()
    if a.lower().startswith("bc1"): return a.lower()
    return a

def _load_file(p):
    with open(p) as f: d = json.load(f)
    idx, raw = {}, {}
    for e in d.get("entries") or []:
        idx.setdefault((e["c"], e["a"]), []).append(e)
        raw.setdefault(e["a"].lower(), []).append(e)
    return d, idx, raw

def load():
    """pick the newest of the shipped baseline and the runtime refresh"""
    best = None
    for p in (RUNTIME, BASE):
        try:
            g = json.load(open(p)).get("generated", 0) if os.path.exists(p) else -1
            if g >= 0 and (best is None or g > best[0]): best = (g, p)
        except Exception as ex: print("sanctions: cannot read", p, ex)
    if not best: print("sanctions: no list file; screening disabled"); return False
    d, idx, raw = _load_file(best[1])
    S.update(idx=idx, raw=raw, lists=d.get("lists") or {}, counts=d.get("counts") or {}, generated=d.get("generated") or 0, sha256=d.get("sha256"), path=best[1])
    return True
try: load()
except Exception as _ex: print("sanctions: load failed", _ex)

def loaded(): return bool(S["idx"])
def stale(): return time.time() - (S["generated"] or 0) > STALE_SECS

def _brief(e):
    L = S["lists"].get(e["l"]) or {}
    return {"list": e["l"], "list_name": L.get("name") or e["l"], "short": L.get("short") or e["l"].upper(), "as_of": L.get("as_of"),
            "entry": e.get("name"), "uid": e.get("uid"), "type": e.get("type"), "programs": e.get("programs") or [], "designated": e.get("listed"),
            "asset": e.get("asset"), "address": e.get("raw") or e["a"], "url": e.get("url"), "list_url": L.get("url"), "licence": L.get("licence"),
            "wording": wording(e, L)}

def wording(e, L=None):
    L = L or S["lists"].get(e["l"]) or {}
    nm = e.get("name") or "?"; sh = L.get("short") or e["l"].upper()
    ref = f", ID {e['uid']}" if e.get("uid") and e["l"] == "ofac" else (f", ref {e['uid']}" if e.get("uid") else "")
    return f"matches {sh}{'' if sh.endswith('List') else ' list'} entry {nm}{ref} (as of {L.get('as_of') or '?'}): confirm before action"

def sanctions(chain, a):
    """official sanctions-list hits for (chain, address). EVM addresses match any 0x listing (ETH, USDT/USDC on ETH, ARB, BSC, ETC)."""
    if not a or not S["idx"]: return []
    hits = S["idx"].get(("eth" if chain in EVM_ALIAS else chain, key(chain, a))) or []
    seen, out = set(), []
    for e in hits:
        k = (e["l"], e.get("uid"))
        if k in seen: continue
        seen.add(k); out.append(_brief(e))
    out.sort(key=lambda h: (h["list"] != "ofac", h["entry"] or ""))
    return out

def sanctions_any(a):
    """chain-agnostic exact match (batch screening of chains ChainTrace does not trace, e.g. LTC, XMR, BCH)"""
    seen, out = set(), []
    for e in S["raw"].get((a or "").strip().lower()) or []:
        if e["a"].lower() != (a or "").strip().lower() and e.get("raw", "").lower() != (a or "").strip().lower(): continue
        k = (e["l"], e.get("uid"), e["c"])
        if k in seen: continue
        seen.add(k); out.append({**_brief(e), "chain": e["c"]})
    return out

def community(chain, a, rows):
    """community / dataset scam-report leads from label-DB rows (labels.db_labels output) + cached Chainabuse result"""
    reps = [r for r in rows or [] if r.get("category") in REPORT_CATS and r.get("source") not in NOT_REPORTS]
    ca = ca_cached(chain, a)
    n = len(reps) + ((ca or {}).get("count") or 0)
    if not n: return None
    cats = sorted({r["category"] for r in reps} | {x.get("category") for x in (ca or {}).get("reports") or [] if x.get("category")})
    return {"count": n, "categories": cats, "status": "community reports: unverified leads",
            "datasets": [{"source": r["source"], "name": r.get("name"), "category": r["category"], "url": r.get("source_url"), "licence": r.get("licence")} for r in reps][:8],
            "chainabuse": _ca_public(ca) if ca else None, "search_url": ca_search_url(a)}

# ---------------- Chainabuse ----------------
CA_API = "https://api.chainabuse.com/v0/reports"
CA_CHAIN = {"btc": "BTC", "eth": "ETH", "sol": "SOL", "tron": "TRON"}   # XRP is not a Chainabuse chain filter: searched unfiltered
CA_TTL = 7 * 86400
CA_LIMIT = int(os.environ.get("CHAINABUSE_MONTHLY_LIMIT") or 10)
def ca_key(): return (os.environ.get("CHAINABUSE_API_KEY") or "").strip() or None
def ca_search_url(a): return f"https://chainabuse.com/address/{(a or '').strip()}"
_cdb = threading.local()
def _ca_db():
    if getattr(_cdb, "db", None) is None:
        p = os.path.join(os.path.dirname(RUNTIME), "chaintrace-chainabuse.sqlite")
        _cdb.db = sqlite3.connect(p, check_same_thread=False)
        _cdb.db.execute("CREATE TABLE IF NOT EXISTS ca(k TEXT PRIMARY KEY, t REAL, v TEXT)")
        _cdb.db.execute("CREATE TABLE IF NOT EXISTS budget(month TEXT PRIMARY KEY, used INTEGER)")
    return _cdb.db
def _month(): return time.strftime("%Y-%m", time.gmtime())
def ca_budget():
    try: r = _ca_db().execute("SELECT used FROM budget WHERE month=?", (_month(),)).fetchone(); used = r[0] if r else 0
    except Exception: used = 0
    return {"configured": bool(ca_key()), "month": _month(), "used": used, "limit": CA_LIMIT, "left": max(0, CA_LIMIT - used)}
def ca_cached(chain, a):
    try:
        r = _ca_db().execute("SELECT t, v FROM ca WHERE k=?", (f"{chain}:{key(chain, a)}",)).fetchone()
        if r and time.time() - r[0] < CA_TTL: d = json.loads(r[1]); d["cached_at"] = int(r[0]); return d
    except Exception: pass
    return None
def _ca_public(d): return {k: d.get(k) for k in ("count", "reports", "cached_at", "checked_at", "truncated")}
async def chainabuse(chain, a, call=True):
    """{"status": ok|cached|no_key|budget|error, ...}. Never raises."""
    c = ca_cached(chain, a)
    if c: return {"status": "cached", **_ca_public(c), "search_url": ca_search_url(a)}
    k = ca_key()
    if not k: return {"status": "no_key", "search_url": ca_search_url(a),
                      "note": "Chainabuse needs a free API key (env CHAINABUSE_API_KEY). Use the search link to check manually."}
    if not call: return {"status": "not_checked", "search_url": ca_search_url(a)}
    b = ca_budget()
    if b["left"] <= 0: return {"status": "budget", "search_url": ca_search_url(a), "note": f"Chainabuse monthly API budget used ({b['used']}/{b['limit']})"}
    import httpx
    params = {"address": a.strip(), "perPage": 50, "page": 1}
    if chain in CA_CHAIN: params["chain"] = CA_CHAIN[chain]
    try:
        async with httpx.AsyncClient(timeout=12) as cl:
            r = await cl.get(CA_API, params=params, auth=(k, k), headers={"accept": "application/json"})
        db = _ca_db(); db.execute("INSERT INTO budget VALUES(?,1) ON CONFLICT(month) DO UPDATE SET used=used+1", (_month(),)); db.commit()
        if r.status_code in (401, 403): return {"status": "error", "note": f"Chainabuse rejected the API key (HTTP {r.status_code})", "search_url": ca_search_url(a)}
        r.raise_for_status(); j = r.json()
    except Exception as ex:
        return {"status": "error", "note": f"Chainabuse unavailable: {type(ex).__name__}", "search_url": ca_search_url(a)}
    reps = []
    for x in j.get("reports") or []:
        reps.append({"id": x.get("id"), "category": (x.get("scamCategory") or "OTHER").lower(), "created": x.get("createdAt"),
                     "checked": x.get("checked"), "trusted": x.get("trusted"), "url": f"https://chainabuse.com/report/{x.get('id')}"})
    d = {"count": int(j.get("count") or len(reps)), "reports": reps, "checked_at": int(time.time()), "truncated": (j.get("count") or 0) > len(reps)}
    try: _ca_db().execute("INSERT OR REPLACE INTO ca VALUES(?,?,?)", (f"{chain}:{key(chain, a)}", time.time(), json.dumps(d))); _ca_db().commit()
    except Exception: pass
    return {"status": "ok", **_ca_public(d), "search_url": ca_search_url(a)}

# ---------------- refresh ----------------
_RLOCK = threading.Lock()
def _refresh_blocking():
    if not _RLOCK.acquire(blocking=False): return False
    S["refreshing"] = True
    try:
        cmd = [sys.executable, os.path.join(H, "update_sanctions.py"), "--out", RUNTIME]
        r = subprocess.run(cmd, cwd=H, capture_output=True, text=True, timeout=900, preexec_fn=(lambda: os.nice(15)) if hasattr(os, "nice") else None)
        if r.returncode != 0: S["refresh_error"] = (r.stderr or r.stdout or "")[-300:]; print("sanctions refresh failed:", S["refresh_error"]); return False
        load(); S["refresh_error"] = None; print("sanctions refreshed:", S["counts"]); return True
    except Exception as ex: S["refresh_error"] = f"{type(ex).__name__}: {ex}"; return False
    finally: S["refreshing"] = False; S["last_refresh"] = int(time.time()); _RLOCK.release()
async def refresh_if_stale(force=False):
    """runs update_sanctions.py in a separate nice'd process (no GIL / event-loop contention); at most once an hour on failure"""
    if S["refreshing"]: return False
    if not force and (not stale() or (S["last_refresh"] and time.time() - S["last_refresh"] < 3600)): return False
    return await asyncio.to_thread(_refresh_blocking)

def status():
    return {"loaded": loaded(), "generated": S["generated"], "stale": stale(), "refreshing": S["refreshing"], "refresh_error": S["refresh_error"],
            "file": os.path.basename(S["path"] or ""), "sha256": S["sha256"], "lists": S["lists"], "counts": S["counts"],
            "chainabuse": ca_budget(), "community_sources": "labels.sqlite scam/hack/phishing/ransomware/darknet labels (GraphSense, Forta, dawsbot, etherscan-labels, ScamSniffer)"}
