from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio, chains, labels, os, trace, autotrace, deposits, bridges, watch, screen
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
    if c in ("btc", "eth", "sol", "tron", "xrp"):
        for n in d["nodes"]:
            if not n.get("kind") and not str(n["id"]).startswith("tx:"): bridges.decorate_vault(n, c)   # live THORChain/Maya vaults = bridge
    for n in d["nodes"]: n["flag"] = n.get("kind") in labels.EXPO
    if d.get("cp"): _cp_sugg(c, d["cp"].get("counterparties") or [])
    if d.get("balance") is not None: d["balance_usd"] = chains.usd_of(d["balance"], d.get("unit"))
    d["price_usd"] = chains.PRICE.get((d.get("unit") or "").upper())
    return d
_WARM = {}
_BOOT = _t.time()
@app.on_event("startup")
async def _warm_up():
    """off the request path: build the inferred-label store and touch the label DB in worker threads, fetch prices"""
    _WARM["dep"] = asyncio.create_task(asyncio.to_thread(deposits.ensure_store))
    _WARM["lbl"] = asyncio.create_task(asyncio.to_thread(lambda: labels.label("eth", "0x28C6c06298d514Db089934071355E5743bf21d60")))
    asyncio.create_task(chains.ensure_prices())
    async def _sanc_refresh():   # stale (>24h) sanctions list: rebuild from the official files in a nice'd subprocess, after the warm-up settles
        await asyncio.sleep(int(os.environ.get("CHAINTRACE_SANCTIONS_DELAY", "90")))
        await screen.refresh_if_stale()
    if os.environ.get("CHAINTRACE_SANCTIONS_REFRESH", "1") != "0": asyncio.create_task(_sanc_refresh())
async def _warm_wait(cap=1.0):
    """give a cold-start warm-up at most ~1s; never hold a lookup hostage to the store build (soft deadline is 4s)"""
    pend = [t for t in _WARM.values() if not t.done()]
    if pend:
        try: await asyncio.wait(pend, timeout=cap)
        except Exception: pass
    return not (_WARM.get("dep") and not _WARM["dep"].done())
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=2000)   # 50-75 KB lookup JSON -> ~8-12 KB (local/tunnel; Render's edge also compresses)
@app.get("/api/lookup")
async def lookup(q: str, chain: str | None = None, cursor: str | None = None, date_from: int | None = None, date_to: int | None = None):
    if _t.time() - bridges._vts[0] > 3600: asyncio.create_task(bridges.refresh_vaults())
    if screen.stale() and not screen.S["refreshing"] and os.environ.get("CHAINTRACE_SANCTIONS_REFRESH", "1") != "0" and _t.time() - _BOOT > 120: asyncio.create_task(screen.refresh_if_stale())
    c, kind = chains.detect(q)
    if chain and chain in chains.ADDR:
        if kind == "tx" or (not c):
            c = chain; kind = kind or "address"
        elif kind == "address" and chain != c:
            c = chain
    if not c: raise HTTPException(400, "Unrecognised address / tx hash")
    try:
        if kind == "address":
            tok = chains.FAST.set(True)   # interactive: soft deadline, slow Blockscout streams finish in the background
            try: d = await asyncio.wait_for(chains.ADDR[c](q.strip(), cursor=cursor, f=date_from, to=date_to, pages=6 if (date_from or date_to) else 1), LOOKUP_TIMEOUT)
            finally: chains.FAST.reset(tok)
        else:
            await chains.ensure_prices(); d = await asyncio.wait_for(chains.TX[c](q.strip()), LOOKUP_TIMEOUT)
            for e in d["edges"]: e.setdefault("usd", chains.usd_of(e.get("amount"), e.get("unit") or d.get("unit")))
    except asyncio.TimeoutError: raise HTTPException(504, f"{c} data sources too slow right now (>{LOOKUP_TIMEOUT:.0f}s); please retry")
    except Exception as e: raise HTTPException(502, f"{c} upstream error: {e}")
    d["kind"] = kind; t1 = _t.time(); warm = await _warm_wait(); d = finish(d)
    if not warm and d.get("chain") in deposits.NATIVE:   # inferred-label store still building after a cold start: client auto-refreshes
        d["pending"] = (d.get("pending") or []) + ["suggested labels"]; d["partial"] = True
        d["warnings"] = (d.get("warnings") or []) + ["Suggested deposit labels still loading after a restart; this view refreshes automatically"]
    if isinstance(d.get("timing"), dict): d["timing"]["finish"] = round(_t.time() - t1, 3)
    return d
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
@app.post("/api/loss")
async def victim_loss(request: Request):
    """victim-loss calculator / fund-flow summary over the graph the browser holds.
    Body: {nodes[], edges[], case{labels}, loss:{victims[], victim_txs[], suspect, method: proportional|fifo|lifo}}"""
    if int(request.headers.get("content-length") or 0) > 8 * 1024 * 1024: raise HTTPException(413, "payload too large (max 8 MB)")
    try: p = await request.json()
    except Exception: raise HTTPException(400, "body must be JSON")
    if not isinstance(p, dict) or not isinstance(p.get("nodes"), list) or not isinstance(p.get("edges"), list) or not isinstance(p.get("loss"), dict): raise HTTPException(400, "expected {nodes[], edges[], loss{...}}")
    if len(p["nodes"]) > 3000 or len(p["edges"]) > 6000: raise HTTPException(413, "graph too large (max 3000 nodes / 6000 edges)")
    import loss
    try: return await asyncio.wait_for(loss.compute(p, p["loss"]), LOOKUP_TIMEOUT + 10)
    except ValueError as ex: raise HTTPException(400, str(ex))
    except asyncio.TimeoutError: raise HTTPException(504, "loss calculation timed out")
@app.post("/api/eth/swaps")
async def eth_swaps(request: Request):
    """decode likely DEX swaps into readable steps. Body {txs:[hash,...<=12], trader:"0x.."}. Free data: public RPC receipts + eth_call."""
    try: p = await request.json()
    except Exception: raise HTTPException(400, "body must be JSON")
    import re as _re, swaps
    txs = [h for h in (p.get("txs") or []) if isinstance(h, str) and _re.fullmatch(r"0x[0-9a-fA-F]{64}", h)][:12]
    tr = p.get("trader") if isinstance(p.get("trader"), str) and _re.fullmatch(r"0x[0-9a-fA-F]{40}", p.get("trader") or "") else None
    if not txs: return {"swaps": [], "nodes": [], "edges": []}
    await chains.ensure_prices()
    res = await swaps.decode_many(txs, tr, budget=min(22, LOOKUP_TIMEOUT - 3))
    nodes, edges = {}, []
    canon = {tr.lower(): tr} if tr else {}
    for sw in res:
        n_, e_ = swaps.graph(sw, canon)
        for x in n_: nodes.setdefault(x["id"], x)
        edges += e_
    return {"swaps": res, "nodes": list(nodes.values()), "edges": edges, "asked": len(txs)}
@app.post("/api/evidence-pack")
async def evidence_pack(request: Request):
    """UK law-enforcement evidence pack: PDF report with investigator-entered Report Fraud/NFIB/officer fields + per-VASP DRAFT records requests (DOCX/TXT),
    VASP schedule CSV, how-to and SHA256SUMS, as one zip. Drafts are not court orders."""
    if int(request.headers.get("content-length") or 0) > 20 * 1024 * 1024: raise HTTPException(413, "case payload too large (max 20 MB)")
    try: p = await request.json()
    except Exception: raise HTTPException(400, "body must be JSON")
    if not isinstance(p, dict) or not isinstance(p.get("nodes"), list) or not isinstance(p.get("edges"), list): raise HTTPException(400, "expected {case, nodes[], edges[], ...}")
    if len(p["nodes"]) > 3000 or len(p["edges"]) > 6000: raise HTTPException(413, "graph too large for a report (max 3000 nodes / 6000 edges)")
    import evidence
    async with _REPORT_SEM:
        try: z, info = await asyncio.wait_for(evidence.build_pack(p), LOOKUP_TIMEOUT + 30)
        except asyncio.TimeoutError: raise HTTPException(504, "evidence pack generation timed out")
    import json as _json
    return Response(z, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="ChainTrace-evidence-pack-{info["ref"]}.zip"',
        "X-Pack-SHA256": info["zip_sha256"], "X-Report-SHA256": info["pdf_sha256"], "X-Case-SHA256": info["case_sha256"], "X-Report-Pages": str(info["pages"]),
        "X-Pack-VASPs": _json.dumps(info["vasps"], ensure_ascii=True)[:1800],
        "Access-Control-Expose-Headers": "X-Pack-SHA256, X-Report-SHA256, X-Case-SHA256, X-Report-Pages, X-Pack-VASPs"})
# ---------------- screening: sanctions lists (hard flag) + community reports (unverified leads) ----------------
SCREEN_MAX = 500
def _screen_one(raw, chain=None):
    a = (raw or "").strip().strip(",;'\"")
    c, kind = chains.detect(a)
    if chain in chains.ADDR and kind != "tx": c = chain
    row = {"input": raw, "address": a, "chain": c, "valid": bool(c and kind == "address")}
    if not a: return None
    if c and kind == "address":
        lab = labels.label(c, a)
        row.update(name=lab.get("name"), kind=lab.get("kind"), sanctions=lab.get("sanctions") or [], reports=lab.get("reports"),
                   unlisted_note=lab.get("unlisted_note"))
    else:
        row.update(sanctions=screen.sanctions_any(a), reports=None, kind=None, name=None)   # e.g. LTC / XMR / BCH on the lists
        if row["sanctions"]: row["chain"] = row["sanctions"][0].get("chain"); row["valid"] = True
    if not row["sanctions"] and row["valid"]:
        oth = [h for h in screen.sanctions_any(a) if h.get("chain") != c]   # same string listed under another asset (e.g. a BCH/LTC-listed 1… address)
        for h in oth: h["wording"] = h["wording"].replace(": confirm before action", f"; listed as a {h.get('asset') or h.get('chain', '').upper()} address: confirm before action")
        row["sanctions"] = oth
    row["verdict"] = "sanctioned" if row["sanctions"] else "reported" if (row.get("reports") or {}).get("count") else ("no match" if row["valid"] else "not an address")
    row["wording"] = row["sanctions"][0]["wording"] if row["sanctions"] else ("community reports: unverified leads, not evidence" if row["verdict"] == "reported" else None)
    row["chainabuse_url"] = screen.ca_search_url(a) if row["valid"] else None
    return row
def _lists_meta():
    st = screen.status()
    return {"lists": st["lists"], "generated": st["generated"], "stale": st["stale"], "counts": st["counts"], "chainabuse_api": st["chainabuse"]}
@app.get("/api/screen")
async def screen_one(addr: str, chain: str | None = None, chainabuse: bool = False):
    """screen one address against the OFAC SDN + UK Sanctions List digital-currency addresses and community scam reports.
    chainabuse=1 makes one live Chainabuse API call (cached 7 days; needs CHAINABUSE_API_KEY; free keys allow ~10 calls a month)."""
    if len(addr) > 120: raise HTTPException(400, "address too long")
    row = _screen_one(addr, chain)
    if not row: raise HTTPException(400, "give an address")
    if row["valid"] and row["chain"] in chains.ADDR:
        ca = await screen.chainabuse(row["chain"], row["address"], call=chainabuse)
        row["chainabuse"] = ca
        if ca.get("status") in ("ok", "cached") and ca.get("count"):
            row["reports"] = screen.community(row["chain"], row["address"], labels.db_labels(row["chain"], row["address"]))
            if row["verdict"] == "no match": row["verdict"] = "reported"; row["wording"] = "community reports: unverified leads, not evidence"
    return {**row, **_lists_meta()}
@app.post("/api/screen/batch")
async def screen_batch(request: Request):
    """{"addresses": [...]} or {"text": "pasted list"} -> one row per address (local lists only; no Chainabuse calls)"""
    try: p = await request.json()
    except Exception: raise HTTPException(400, "body must be JSON")
    import re as _re
    items = p.get("addresses") if isinstance(p, dict) else None
    if not items and isinstance(p, dict) and isinstance(p.get("text"), str): items = [x for x in _re.split(r"[\s,;]+", p["text"]) if x.strip()]
    if not isinstance(items, list) or not items: raise HTTPException(400, 'expected {"addresses": [...]} or {"text": "..."}')
    items = list(dict.fromkeys(str(x).strip() for x in items if str(x).strip()))
    if len(items) > SCREEN_MAX: raise HTTPException(413, f"max {SCREEN_MAX} addresses per batch")
    rows = await asyncio.to_thread(lambda: [r for r in (_screen_one(x) for x in items) if r])
    summ = {k: sum(1 for r in rows if r["verdict"] == k) for k in ("sanctioned", "reported", "no match", "not an address")}
    return {"rows": rows, "summary": summ, "screened_at": int(_t.time()), **_lists_meta()}
@app.get("/api/screen/status")
def screen_status(): return screen.status()
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
