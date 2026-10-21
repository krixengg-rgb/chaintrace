from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio, chains, labels, os, trace, autotrace, deposits
app = FastAPI(title="ChainTrace")
# ---- auth + rate limiting (public exposure) ----
import secrets, base64, time as _t, collections
from fastapi import Request
from fastapi.responses import JSONResponse, Response
_env = {}
_envf = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_envf):   # local dev fallback; on Render use env vars
    for _l in open(_envf):
        if "=" in _l: k, v = _l.strip().split("=", 1); _env[k] = v
USER = os.environ.get("CHAINTRACE_USER") or _env.get("CHAINTRACE_USER") or _env.get("CT_USER")
PASS = os.environ.get("CHAINTRACE_PASSWORD") or _env.get("CHAINTRACE_PASSWORD") or _env.get("CT_PASS")
if not USER or not PASS or len(PASS) < 12:
    raise SystemExit("Set CHAINTRACE_USER and CHAINTRACE_PASSWORD (>=12 chars); refusing to start without auth")
RL = collections.defaultdict(collections.deque)   # ip -> request timestamps
LIMITS = {"api": (60, 60), "trace": (6, 60)}         # (requests, seconds)
def _ip(r):
    xff = r.headers.get("x-forwarded-for")   # Render's proxy appends the client IP; first entry is the client
    return (xff.split(",")[0].strip() if xff else None) or r.headers.get("cf-connecting-ip") or (r.client.host if r.client else "?")
@app.middleware("http")
async def guard(request: Request, call_next):
    h = request.headers.get("authorization", "")
    ok = False
    if h.startswith("Basic "):
        try:
            u, _, p = base64.b64decode(h[6:]).decode().partition(":")
            ok = secrets.compare_digest(u, USER) & secrets.compare_digest(p, PASS)
        except Exception: ok = False
    if request.url.path == "/healthz": return await call_next(request)
    if not ok:
        return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="ChainTrace"'})
    path = request.url.path
    if path.startswith("/api/"):
        kind = "trace" if (path in ("/api/trace", "/api/autotrace") and request.method == "POST") else "api"
        n, win = LIMITS[kind]; q = RL[(_ip(request), kind)]; now = _t.time()
        while q and q[0] < now - win: q.popleft()
        if len(q) >= n: return JSONResponse({"detail": f"rate limit: max {n} {kind} requests per {win}s"}, 429, {"Retry-After": str(win)})
        q.append(now)
    return await call_next(request)
MAX_RUNNING_TRACES = 2
LOOKUP_TIMEOUT = float(os.environ.get("CHAINTRACE_LOOKUP_TIMEOUT", "25"))   # stay under proxy timeouts
H = os.path.dirname(__file__)
def finish(d):
    by = {n["id"]: n for n in d["nodes"]}
    focus = d.get("address")
    if focus and focus in by:
        nb = [by[x] for e in d["edges"] for x in (e["source"], e["target"]) if x != focus and x in by]
        d["risk"] = labels.score(by[focus], nb); d["label"] = by[focus]
    else:
        nb = [n for n in d["nodes"] if n.get("kind") != "tx"]
        worst = max(nb, key=lambda n: n["risk"], default=None)
        d["risk"] = labels.score({"risk":0,"kind":None}, nb) if worst else {"score":0,"level":"low","reasons":[]}
    c = d.get("chain")
    if c in deposits.NATIVE:   # suggested (inferred) exchange-deposit labels: display only, never raise risk
        for n in d["nodes"]:
            if not n.get("kind") and not str(n["id"]).startswith("tx:"): deposits.decorate(n, deposits.lookup_batch(c, n["id"]), endpoint_at=9)
        if focus and focus in by and not by[focus].get("kind") and not by[focus].get("suggested") and not d.get("_paged"):
            try: deposits.decorate(by[focus], deposits.suggest(c, focus, d), endpoint_at=9)
            except Exception as ex: print("suggest failed", ex)
        if focus and focus in by and by[focus].get("suggested"): d["suggestion"] = by[focus]["suggested"]
    for n in d["nodes"]: n["flag"] = n.get("kind") in labels.EXPO
    if d.get("balance") is not None: d["balance_usd"] = chains.usd_of(d["balance"], d.get("unit"))
    d["price_usd"] = chains.PRICE.get((d.get("unit") or "").upper())
    return d
@app.get("/api/lookup")
async def lookup(q: str, chain: str | None = None, cursor: str | None = None, date_from: int | None = None, date_to: int | None = None):
    c, kind = chains.detect(q)
    if chain and c and chain != c and kind == "address": c = chain
    if not c: raise HTTPException(400, "Unrecognised address / tx hash")
    try:
        if kind == "address":
            d = await asyncio.wait_for(chains.ADDR[c](q.strip(), cursor=cursor, f=date_from, to=date_to, pages=6 if (date_from or date_to) else 1), LOOKUP_TIMEOUT)
        else:
            await chains.ensure_prices(); d = await asyncio.wait_for(chains.TX[c](q.strip()), LOOKUP_TIMEOUT)
            for e in d["edges"]: e.setdefault("usd", chains.usd_of(e.get("amount"), e.get("unit") or d.get("unit")))
    except asyncio.TimeoutError: raise HTTPException(504, f"{c} data sources too slow right now (>{LOOKUP_TIMEOUT:.0f}s); please retry")
    except Exception as e: raise HTTPException(502, f"{c} upstream error: {e}")
    d["kind"] = kind; return finish(d)
@app.post("/api/trace")
async def trace_start(q: str, hops: int = 2, direction: str = "forward", topk: int = 3, max_nodes: int = 120):
    c, kind = chains.detect(q)
    if not c: raise HTTPException(400, "Unrecognised address / tx hash")
    hops = max(1, min(5, hops)); topk = max(1, min(10, topk)); max_nodes = max(10, min(400, max_nodes))
    if direction not in ("forward", "backward", "both"): raise HTTPException(400, "bad direction")
    if sum(1 for j in trace.JOBS.values() if j["status"] in ("queued", "running")) >= MAX_RUNNING_TRACES:
        raise HTTPException(429, "too many traces running, try again shortly")
    return {"job": trace.start(q.strip(), hops, direction, topk, max_nodes)}
@app.post("/api/autotrace")
async def autotrace_start(q: str, direction: str = "forward", max_hops: int = 6, max_nodes: int = 150, max_secs: int = 120,
                          min_usd: float = 100, topk: int = 3, skip_unpriced: bool = True):
    c, kind = chains.detect(q)
    if not c: raise HTTPException(400, "Unrecognised address / tx hash")
    if direction not in ("forward", "backward"): raise HTTPException(400, "direction must be forward or backward")
    max_hops = max(1, min(8, max_hops)); max_nodes = max(10, min(250, max_nodes)); max_secs = max(15, min(240, max_secs))
    topk = max(1, min(6, topk)); min_usd = max(0.0, min_usd)
    if sum(1 for j in trace.JOBS.values() if j["status"] in ("queued", "running")) >= MAX_RUNNING_TRACES:
        raise HTTPException(429, "too many traces running, try again shortly")
    return {"job": autotrace.start(q.strip(), direction, max_hops, max_nodes, max_secs, min_usd, topk, skip_unpriced)}
@app.get("/api/trace/{job}")
def trace_get(job: str):
    j = trace.JOBS.get(job)
    if not j: raise HTTPException(404, "no such job")
    return j
@app.delete("/api/trace/{job}")
def trace_cancel(job: str):
    if job not in trace.JOBS: raise HTTPException(404, "no such job")
    return {"cancelled": trace.cancel(job)}
@app.get("/api/prices")
async def prices(): return await chains.ensure_prices()
@app.get("/healthz")
def healthz(): return {"ok": True, "labels_db": os.path.exists(labels.LDB)}
@app.get("/api/cache")
def cache_stats(): return {**chains.STATS, "rows": chains.DB.execute("select count(*) from cache").fetchone()[0]}
@app.get("/api/labels")
def lbl():
    if not os.path.exists(labels.LDB): return {"by_chain_category": [], "sources": [], "warning": "labels.sqlite missing - run update_labels.py"}
    import sqlite3; db = sqlite3.connect(f"file:{labels.LDB}?mode=ro", uri=True)
    return {"by_chain_category": [dict(zip(("chain","category","addresses"), r)) for r in db.execute("select chain,category,count(distinct address) from labels group by 1,2 order by 1,3 desc")],
            "sources": [dict(zip(("id","description","url","licence","included","rows"), r)) for r in db.execute("select * from sources")]}
def _old_lbl(): return {"ofac_counts": {k: len(v) for k, v in labels.OFAC.items()}, "mixers": len(labels.MIXERS_ETH),
                   "exchanges": {k: len(v) for k, v in labels.EXCH.items()}}
app.mount("/static", StaticFiles(directory=os.path.join(H, "static")), name="static")
@app.get("/")
def index(): return FileResponse(os.path.join(H, "static", "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0" if os.environ.get("PORT") else "127.0.0.1", port=int(os.environ.get("PORT", 8090)))
