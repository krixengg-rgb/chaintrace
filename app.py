from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio, chains, labels, os, trace, autotrace, deposits, bridges, watch
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
    if c in ("btc", "eth", "sol"):
        for n in d["nodes"]:
            if not n.get("kind") and not str(n["id"]).startswith("tx:"): bridges.decorate_vault(n, c)   # live THORChain/Maya vaults = bridge
    for n in d["nodes"]: n["flag"] = n.get("kind") in labels.EXPO
    if d.get("cp"): _cp_sugg(c, d["cp"].get("counterparties") or [])
    if d.get("balance") is not None: d["balance_usd"] = chains.usd_of(d["balance"], d.get("unit"))
    d["price_usd"] = chains.PRICE.get((d.get("unit") or "").upper())
    return d
@app.get("/api/lookup")
async def lookup(q: str, chain: str | None = None, cursor: str | None = None, date_from: int | None = None, date_to: int | None = None):
    if _t.time() - bridges._vts[0] > 3600: asyncio.create_task(bridges.refresh_vaults())
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
def _cp_sugg(c, cps):
    if c not in deposits.NATIVE: return
    for x in cps:
        if not x.get("kind") and not x.get("suggested"):
            s = deposits.lookup_batch(c, x["id"])
            if s: x["suggested"] = {"label": f"{s['entity']} deposit", "entity": s["entity"], "category": "exchange-deposit", "confidence": s["confidence"], "method": s["method"]}
@app.get("/api/counterparties")
async def counterparties(q: str, pages: int = 1, cursor: str | None = None, date_from: int | None = None, date_to: int | None = None):
    """top inflow/outflow counterparties of an address over 1-5 history pages (bounded by a 20s budget)"""
    c, kind = chains.detect(q)
    if not c or kind != "address": raise HTTPException(400, "counterparties need an address")
    pages = max(1, min(5, pages)); t0 = _t.time(); res = {"counterparties": [], "series": []}; nxt = cursor; n = 0; partial = []
    while n < pages and _t.time() - t0 < 18:
        try: d = await asyncio.wait_for(chains.ADDR[c](q.strip(), cursor=nxt, f=date_from, to=date_to), max(3, 22 - (_t.time() - t0)))
        except Exception as e:
            if n == 0: raise HTTPException(502, f"{c} upstream error: {e}")
            partial.append(f"stopped after {n} page(s): {type(e).__name__}"); break
        res = chains.merge_cp(res, d.get("cp") or {}); n += 1; nxt = d.get("next"); partial += d.get("warnings") or []
        if not nxt: break
    _cp_sugg(c, res["counterparties"])
    return {"chain": c, "address": q.strip(), "pages": n, "next": nxt, "warnings": partial, **res}
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
                          min_usd: float = 100, topk: int = 3, skip_unpriced: bool = True, follow_bridges: bool = False):
    c, kind = chains.detect(q)
    if not c: raise HTTPException(400, "Unrecognised address / tx hash")
    if direction not in ("forward", "backward"): raise HTTPException(400, "direction must be forward or backward")
    max_hops = max(1, min(8, max_hops)); max_nodes = max(10, min(250, max_nodes)); max_secs = max(15, min(240, max_secs))
    topk = max(1, min(6, topk)); min_usd = max(0.0, min_usd)
    if sum(1 for j in trace.JOBS.values() if j["status"] in ("queued", "running")) >= MAX_RUNNING_TRACES:
        raise HTTPException(429, "too many traces running, try again shortly")
    return {"job": autotrace.start(q.strip(), direction, max_hops, max_nodes, max_secs, min_usd, topk, skip_unpriced, follow_bridges)}
@app.get("/api/trace/{job}")
def trace_get(job: str):
    j = trace.JOBS.get(job)
    if not j: raise HTTPException(404, "no such job")
    return j
@app.delete("/api/trace/{job}")
def trace_cancel(job: str):
    if job not in trace.JOBS: raise HTTPException(404, "no such job")
    return {"cancelled": trace.cancel(job)}
@app.get("/api/bridge")
async def bridge(q: str | None = None, tx: str | None = None, chain: str | None = None, anchor: str | None = None, heuristic: str = "auto"):
    """Cross-chain match for a bridge transaction (either side) or an address's bridge activity.
    Deterministic = linked by the bridge's own indexer (message/order id). Heuristic = amount/time/same-address lead only."""
    q = (q or tx or "").strip()
    c, kind = chains.detect(q)
    if not c: raise HTTPException(400, "Give a transaction hash (ETH/BTC/SOL) or an address")
    try:
        if kind == "tx": d = await asyncio.wait_for(bridges.match_tx(q, None, "always" if heuristic == "always" else heuristic.lower() not in ("false", "0", "off", "no")), LOOKUP_TIMEOUT - 1)
        else: d = await asyncio.wait_for(bridges.match_address(q, c), LOOKUP_TIMEOUT - 1)
    except asyncio.TimeoutError: raise HTTPException(504, f"bridge indexers too slow right now (>{LOOKUP_TIMEOUT - 1:.0f}s); please retry")
    except ValueError as e: raise HTTPException(400, str(e))
    d = dict(d)
    for m in d.get("matches", []) + d.get("heuristic", []):
        nodes, edges = bridges.fragment(m, anchor, "dst" if m.get("side", "src") == "src" else "src")
        for n in nodes: n["flag"] = n.get("kind") in labels.EXPO
        m["graph"] = {"nodes": nodes, "edges": edges}
    d["caveat"] = "Deterministic = linked by the bridge's own indexer. Heuristic = lead only (amount/time/address coincidence), not evidence."
    return d
WATCH_MAX = 8                        # addresses per /api/watch/check call (client batches + staggers the rest)
_WATCH_SEM = asyncio.Semaphore(2)    # concurrent watch batches across all clients
@app.post("/api/watch/check")
async def watch_check(request: Request):
    """stateless watchlist check: {items:[{id, address, chain?, name, ref, rules, cursor?, since?}]} -> new events + updated cursors.
    Nothing is stored server-side; the watchlist and cursors live with the caller (browser IndexedDB or watch_check.py)."""
    try: p = await request.json()
    except Exception: raise HTTPException(400, "body must be JSON")
    items = p.get("items") if isinstance(p, dict) else None
    if not isinstance(items, list) or not items: raise HTTPException(400, "expected {items:[...]}")
    if len(items) > WATCH_MAX: raise HTTPException(413, f"max {WATCH_MAX} addresses per check; send the rest in later batches")
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("address"), str) or len(it["address"]) > 100: raise HTTPException(400, "each item needs an address")
        cur = it.get("cursor")
        if cur is not None and (not isinstance(cur, dict) or len(cur.get("seen") or []) > 400): raise HTTPException(400, "bad cursor")
    t0 = _t.time()
    async with _WATCH_SEM:
        res = await watch.check_many(items, budget=max(6.0, LOOKUP_TIMEOUT - 4 - (_t.time() - t0)))
    return {"checked_at": int(_t.time()), "elapsed": round(_t.time() - t0, 1), "results": res, "rules_help": {"cats": watch.CATS, "default": watch.DEFAULT_RULES}}
_REPORT_SEM = asyncio.Semaphore(1)   # one PDF at a time (512 MB hosts)
@app.post("/api/report")
async def make_report(request: Request):
    """case JSON (graph, notes, labels, trace summary, query log, PNG) -> PDF investigation report"""
    if int(request.headers.get("content-length") or 0) > 20 * 1024 * 1024: raise HTTPException(413, "case payload too large (max 20 MB)")
    try: p = await request.json()
    except Exception: raise HTTPException(400, "body must be JSON")
    if not isinstance(p, dict) or not isinstance(p.get("nodes"), list) or not isinstance(p.get("edges"), list): raise HTTPException(400, "expected {case, nodes[], edges[], ...}")
    if len(p["nodes"]) > 3000 or len(p["edges"]) > 6000: raise HTTPException(413, "graph too large for a report (max 3000 nodes / 6000 edges)")
    import report   # lazy: fpdf2/Pillow only loaded when a report is requested
    async with _REPORT_SEM:
        try: pdf, info = await asyncio.wait_for(report.build(p), LOOKUP_TIMEOUT + 20)
        except asyncio.TimeoutError: raise HTTPException(504, "report generation timed out")
    import re as _re
    name = _re.sub(r"[^A-Za-z0-9._-]+", "_", ((p.get("meta") or {}).get("ref") or (p.get("case") or {}).get("name") or "case"))[:60]
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="ChainTrace-report-{name}.pdf"',
        "X-Report-SHA256": info["pdf_sha256"], "X-Case-SHA256": info["case_sha256"], "X-Report-Pages": str(info["pages"]),
        "Access-Control-Expose-Headers": "X-Report-SHA256, X-Case-SHA256, X-Report-Pages"})
@app.get("/api/bridges")
def bridges_supported(): return {"supported": bridges.SUPPORTED}
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
