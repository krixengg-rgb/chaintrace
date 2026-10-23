"""ChainTrace PDF investigation report (fpdf2, pure Python: no headless browser, low RAM).
Input: the case JSON the browser sends (graph nodes/edges, case notes/labels, trace summary, API query log, graph PNG).
Output: an A4 PDF with cover, summary, graph, chronological trail, bridge hops, attributions, methodology and appendices.
The canonical case data is embedded in the PDF (case_data.json) so its SHA-256 can be recomputed independently."""
import ast, asyncio, base64, hashlib, io, json, os, re, subprocess, time
from collections import defaultdict, deque
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from fpdf import FPDF, FontFace
from fpdf.enums import XPos, YPos
import chains, labels, bridges

VERSION = "0.8.0"
H = os.path.dirname(os.path.abspath(__file__))
UK = ZoneInfo("Europe/London")
def _commit():
    c = os.environ.get("RENDER_GIT_COMMIT")
    if c: return c[:12]
    try: return subprocess.run(["git", "-C", H, "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=3).stdout.strip() or "unknown"
    except Exception: return "unknown"
COMMIT = _commit()
LEAD = "Intelligence lead – not evidence; corroborate (e.g. production order to the VASP)"
STABLE = {"USDT", "USDC", "DAI", "USDS", "PYUSD", "FDUSD", "TUSD", "USDE", "USDC.E", "BUSD"}
PXSYM = {"BTC": "BTC", "WBTC": "BTC", "CBBTC": "BTC", "ETH": "ETH", "WETH": "ETH", "STETH": "ETH", "SOL": "SOL", "WSOL": "SOL"}
ENDPOINT_KINDS = {"exchange", "sanctioned", "terrorism", "darknet", "ransomware", "hack", "scam", "mixer", "blocklisted", "gambling", "bridge"}
MAX_PNG = 12 * 1024 * 1024
NAVY, TEAL, AMBER, RED, GREY, LINE, HEAD, ZEBRA = (22, 38, 74), (0, 110, 130), (165, 90, 0), (170, 20, 40), (92, 100, 116), (205, 210, 220), (229, 234, 242), (247, 248, 251)

# ---------------- small helpers ----------------
def t_uk(ts):
    d = datetime.fromtimestamp(ts, UK); return d.strftime("%d/%m/%Y %H:%M:%S ") + (d.tzname() or "")
def t_utc(ts): return datetime.fromtimestamp(ts, timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
def t_both(ts):
    if not ts: return "–"
    a, b = datetime.fromtimestamp(ts, UK), datetime.fromtimestamp(ts, timezone.utc)
    return f"{t_uk(ts)}\n" + (b.strftime("%H:%M:%S UTC") if a.date() == b.date() else t_utc(ts))
def t_line(ts): return f"{t_uk(ts)} ({datetime.fromtimestamp(ts, timezone.utc).strftime('%H:%M:%S UTC')})" if ts else "–"
def code(c): return (c or "?").upper() if c in ("btc", "eth", "sol") else chain_name(c)
def num(x, d=8):
    if x is None: return "–"
    try: x = float(x)
    except Exception: return str(x)
    if abs(x) >= 1000: return f"{x:,.2f}"
    s = f"{x:,.{d}f}".rstrip("0").rstrip("."); return s or "0"
def usd(x): return "–" if x is None else f"${x:,.2f}"
def unit_of(e): return (e.get("unit") or "").replace("⇄", "").strip()
def cid(i):   # node id -> (chain, bare address)
    s = str(i)
    if s.startswith("tx:"): s = s[3:]
    if ":" in s and s.split(":", 1)[0] in bridges.CH: c, a = s.split(":", 1); return c, a
    return None, s
def is_tx(i): return str(i).startswith("tx:")
def chain_name(c): return bridges.CH.get(c, (c or "?").upper(),)[0] if c in bridges.CH else (c or "?").upper()
def tx_url(c, h): return (bridges.CH[c][1] + h) if c in bridges.CH and h else None
def addr_url(c, a): return (bridges.CH[c][2] + a) if c in bridges.CH and a else None
def dom(u):
    try: return urlparse(u).netloc.replace("www.", "")
    except Exception: return ""
REDACT = re.compile(r"((?:api[-_]?key|apikey|token|secret|auth)=)[^&'\s]+", re.I)
def redact(u): return REDACT.sub(r"\1[redacted]", u)
def canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")

# ---------------- historical prices (Coinbase Exchange daily candles; free, keyless) ----------------
async def hist_prices(need, errs):
    out = {}; now = time.time()
    async def one(sym, days):
        days = sorted(days); i = 0
        while i < len(days):
            start = days[i]; chunk = [d for d in days[i:] if d <= start + 299 * 86400]; i += len(chunk)
            iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
            url = f"https://api.exchange.coinbase.com/products/{sym}-USD/candles?granularity=86400&start={iso(start)}&end={iso(chunk[-1] + 86400)}"
            try:
                rows = await chains.get(url, ttl=chains.LONG if chunk[-1] < now - 2 * 86400 else 3600)
                for r in rows or []: out[(sym, int(r[0]))] = float(r[4])
            except Exception as ex: errs.append(f"historical price {sym}: {type(ex).__name__}")
    try: await asyncio.wait_for(asyncio.gather(*[one(s, d) for s, d in need.items() if d]), 9)
    except asyncio.TimeoutError: errs.append("historical prices: timed out (partial)")
    return out

# ---------------- upstream query log from ChainTrace's HTTP cache ----------------
def cache_sources(ids, limit=500):
    pats = sorted({str(i).lower().removeprefix("tx:").split(":")[-1] for i in ids if len(str(i)) >= 26}, key=len, reverse=True)
    if not pats: return []
    rx = re.compile("|".join(re.escape(p) for p in pats[:600])); out = []
    try: rows = chains.DB.execute("SELECT k, ts FROM cache ORDER BY ts DESC LIMIT 40000").fetchall()
    except Exception: rows = []
    for k, ts in rows:
        if not rx.search(k.lower()): continue
        try: t = ast.literal_eval(k)
        except Exception: continue
        if t and t[0] == "GET": desc = t[1]
        elif len(t) >= 3: desc = f"{t[0]}  JSON-RPC {t[1]} {str(t[2])[:160]}"
        else: continue
        out.append((ts, redact(desc)))
        if len(out) >= limit: break
    try:
        for k, ts in chains.DB.execute("SELECT k, ts FROM bridge ORDER BY ts DESC LIMIT 5000").fetchall():
            if rx.search(k.lower()): out.append((ts, f"bridge-indexer match ({k}) via Wormholescan / DLN / Mayan / Across / Midgard / LayerZero Scan / Relay"))
    except Exception: pass
    return sorted(set(out))

# ---------------- analysis of the case graph ----------------
def analyse(p):
    nodes = {n["id"]: n for n in (p.get("nodes") or []) if isinstance(n, dict) and n.get("id")}
    edges = [e for e in (p.get("edges") or []) if isinstance(e, dict) and e.get("source") and e.get("target")]
    case = p.get("case") or {}; trace = p.get("trace") or {}
    subj = trace.get("root") or case.get("query") or ""
    subj_ids = [i for i in nodes if subj and (i == subj or i == "tx:" + subj or i.lower() == subj.lower())] or ([subj] if subj else [])
    def chain_of(i):
        c, _ = cid(i)
        return c or (nodes.get(i) or {}).get("chain") or chains.detect(cid(i)[1])[0]
    adj = defaultdict(set)
    for e in edges: adj[e["source"]].add(e["target"]); adj[e["target"]].add(e["source"])
    dist = {}; dq = deque()
    for s in subj_ids: dist[s] = 0; dq.append(s)
    while dq:
        x = dq.popleft()
        for y in adj[x]:
            if y not in dist: dist[y] = dist[x] + 1; dq.append(y)
    hops = lambda i: dist.get(i)
    inflow = defaultdict(float)
    for e in edges: inflow[e["target"]] += e.get("usd") or 0
    txs = set()
    for e in edges:
        for h in (e.get("tx"), e.get("dst_tx")):
            if h: txs.add(h)
    for i in nodes:
        if is_tx(i): txs.add(i[3:])
    times = [t for e in edges for t in (e.get("first"), e.get("time"), e.get("last")) if t]
    S = set(subj_ids)
    return dict(nodes=nodes, edges=edges, case=case, trace=trace, subj=subj, subj_ids=subj_ids, chain_of=chain_of, hops=hops, inflow=inflow, txs=txs,
                chains=sorted({chain_of(i) or "?" for i in nodes if not is_tx(i)}),
                t0=min(times) if times else None, t1=max(times) if times else None,
                out_usd=sum(e.get("usd") or 0 for e in edges if e["source"] in S and not e.get("xchain")),
                in_usd=sum(e.get("usd") or 0 for e in edges if e["target"] in S and not e.get("xchain")),
                gross=sum(e.get("usd") or 0 for e in edges if not e.get("xchain")))

def bridge_rows(A):
    seen = {}; out = []
    for e in A["edges"]:
        b = e.get("bridge") if isinstance(e.get("bridge"), dict) else None
        if not (e.get("xchain") and b): continue
        k = ((b.get("src") or {}).get("tx"), (b.get("dst") or {}).get("tx"))
        if k in seen: continue
        seen[k] = 1; out.append(dict(b, heur=bool(e.get("heur")) or b.get("method") != "deterministic"))
    for b in (A["trace"].get("bridges") or []):
        k = ((b.get("src") or {}).get("tx"), (b.get("dst") or {}).get("tx"))
        if k not in seen: seen[k] = 1; out.append(dict(b, heur=b.get("method") != "deterministic"))
    return out

def entity_rows(A, case_labels):
    rows = []
    for i, n in A["nodes"].items():
        if is_tx(i) or n.get("grp") or n.get("meta"): continue
        ul = case_labels.get(i) if isinstance(case_labels, dict) else None
        if not (n.get("kind") or n.get("name") or n.get("suggested") or ul or n.get("sources")): continue
        rows.append((labels.RISK.get(n.get("kind") or "", 0) + (200 if ul else 0), i, n, ul))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return rows

# ---------------- PDF ----------------
class PDF(FPDF):
    def __init__(s, meta, gen_ts):
        super().__init__("P", "mm", "A4")
        s.meta, s.gen_ts = meta, gen_ts
        f = os.path.join(H, "fonts")
        for st in ("", "I"): s.add_font("dv", st, os.path.join(f, "DejaVuSans.ttf"))
        for st in ("B", "BI"): s.add_font("dv", st, os.path.join(f, "DejaVuSans-Bold.ttf"))
        for st in ("", "B", "I", "BI"): s.add_font("mono", st, os.path.join(f, "DejaVuSansMono.ttf"))
        s.set_margins(14, 17, 14); s.set_auto_page_break(True, 16); s.alias_nb_pages()
        s.set_title(f"ChainTrace report – {meta.get('case_name') or ''}"); s.set_author(meta.get("investigator") or ""); s.set_creator(f"ChainTrace {VERSION} ({COMMIT})")
        s.set_subject("Cryptoasset tracing report"); s.set_lang("en-GB")
    def header(s):
        mk = (s.meta.get("marking") or "").strip()
        if mk:
            s.set_xy(s.l_margin, 6); s.set_font("dv", "B", 8); s.set_text_color(*RED); s.cell(s.epw, 4, mk.upper(), align="C")
        if s.page_no() == 1: s.set_y(17); return
        s.set_xy(s.l_margin, 10); s.set_font("dv", "", 7.5); s.set_text_color(*GREY)
        ref = s.meta.get("ref") or "no reference"
        s.cell(s.epw / 2, 4, f"ChainTrace investigation report · {s.meta.get('case_name') or ''}"[:95]); s.cell(s.epw / 2, 4, f"Ref: {ref}"[:60], align="R")
        s.set_draw_color(*LINE); s.line(s.l_margin, 14.6, s.w - s.r_margin, 14.6); s.set_y(17); s.set_text_color(0)
    def footer(s):
        s.set_y(-11); s.set_draw_color(*LINE); s.line(s.l_margin, s.get_y() - 1.5, s.w - s.r_margin, s.get_y() - 1.5)
        s.set_font("dv", "", 7); s.set_text_color(*GREY)
        s.cell(s.epw * 0.72, 4, f"Generated by ChainTrace v{VERSION} (commit {COMMIT}) · {t_utc(s.gen_ts)} · public blockchain data via third-party APIs")
        s.cell(s.epw * 0.28, 4, f"Page {s.page_no()} of {{nb}}", align="R")
        mk = (s.meta.get("marking") or "").strip()
        if mk: s.set_xy(s.l_margin, -7); s.set_font("dv", "B", 7.5); s.set_text_color(*RED); s.cell(s.epw, 4, mk.upper(), align="C")
        s.set_text_color(0)
    # text primitives
    def h1(s, t, landscape=False):
        s.add_page(orientation="L" if landscape else "P"); s.start_section(t)
        s.set_font("dv", "B", 15); s.set_text_color(*NAVY); s.cell(0, 9, t, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        s.set_draw_color(*TEAL); s.set_line_width(0.6); s.line(s.l_margin, s.get_y(), s.l_margin + 22, s.get_y()); s.set_line_width(0.2); s.ln(4); s.set_text_color(0)
    def h2(s, t):
        if s.get_y() > s.h - 40: s.add_page(orientation=s.cur_orientation)
        s.ln(2); s.set_font("dv", "B", 10.5); s.set_text_color(*NAVY); s.cell(0, 6, t, new_x=XPos.LMARGIN, new_y=YPos.NEXT); s.set_text_color(0); s.ln(0.5)
    def para(s, t, size=9, color=(30, 34, 44), style="", h=4.6):
        s.set_font("dv", style, size); s.set_text_color(*color); s.multi_cell(0, h, t, new_x=XPos.LMARGIN, new_y=YPos.NEXT); s.set_text_color(0); s.ln(1)
    def bullets(s, items, size=9):
        s.set_font("dv", "", size)
        for it in items:
            lh = round(size * 0.52, 2); s.set_x(s.l_margin); s.cell(5, lh, "•"); s.multi_cell(s.epw - 5, lh, it, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        s.ln(1)
    def box(s, t, color=AMBER, size=8.5, title=None):
        s.set_draw_color(*color); s.set_fill_color(255, 249, 236) if color == AMBER else s.set_fill_color(240, 246, 250)
        s.set_font("dv", "", size); s.set_text_color(60, 40, 0) if color == AMBER else s.set_text_color(20, 40, 60)
        txt = (title + "\n" if title else "") + t
        s.multi_cell(0, 4.4, txt, border=1, fill=True, padding=2.2, new_x=XPos.LMARGIN, new_y=YPos.NEXT); s.set_text_color(0); s.set_draw_color(*LINE); s.ln(2)
    def tbl(s, widths, size=7.5, lh=3.7, head=True):
        s.set_font("dv", "", size); s.set_draw_color(*LINE); s.set_fill_color(255, 255, 255); s.set_text_color(0)
        return s.table(col_widths=widths, first_row_as_headings=head, width=sum(widths), align="LEFT", text_align="LEFT", line_height=lh, borders_layout="HORIZONTAL_LINES",
                       headings_style=FontFace(emphasis="B", fill_color=HEAD, size_pt=size, color=NAVY), cell_fill_color=ZEBRA, cell_fill_mode="ROWS",
                       padding=(1.1, 1.3, 1.1, 1.3), wrapmode="CHAR" if False else "WORD")

MONO = FontFace(family="mono", size_pt=6.6)
MONOS = FontFace(family="mono", size_pt=6.2)
BOLD = FontFace(emphasis="B")
LEADF = FontFace(emphasis="B", color=AMBER, size_pt=6.8)
DETF = FontFace(emphasis="B", color=TEAL)
def wrap_hex(s, n=34):   # allow long hashes/addresses to break cleanly inside narrow cells
    s = str(s or ""); return "\n".join(s[i:i + n] for i in range(0, len(s), n)) if s else "–"

def kv(pdf, rows, w=(46, None)):
    w2 = w[1] or pdf.epw - w[0]
    with pdf.tbl((w[0], w2), size=8.5, lh=4.4, head=False) as t:
        for k, v, *st in rows:
            r = t.row(); r.cell(k, style=FontFace(emphasis="B", color=NAVY)); r.cell(v if v not in (None, "") else "–", style=st[0] if st else None)

async def build(p):
    """p: case payload from the browser. Returns (pdf_bytes, info)."""
    gen = time.time(); errs = []
    case = p.get("case") or {}; meta_in = p.get("meta") or {}
    meta = {"ref": (meta_in.get("ref") or "").strip()[:80], "investigator": (meta_in.get("investigator") or "").strip()[:120],
            "marking": (meta_in.get("marking") or "").strip()[:60], "notes": (meta_in.get("notes") or "").strip()[:4000],
            "case_name": (case.get("name") or "Untitled case")[:120]}
    data = {k: p.get(k) for k in ("case", "nodes", "edges", "trace", "meta", "log")}
    data_bytes = canon(data); data_sha = hashlib.sha256(data_bytes).hexdigest()
    png = None; png_sha = None
    if isinstance(p.get("png"), str) and p["png"].startswith("data:image/png;base64,"):
        try:
            png = base64.b64decode(p["png"].split(",", 1)[1], validate=True)
            if len(png) > MAX_PNG or not png.startswith(b"\x89PNG"): png = None; errs.append("graph image rejected (too large or not PNG)")
            else: png_sha = hashlib.sha256(png).hexdigest()
        except Exception: png = None; errs.append("graph image could not be decoded")
    A = analyse(p); nodes, edges = A["nodes"], A["edges"]; case_labels = case.get("labels") or {}
    # historical USD for native assets
    need = defaultdict(set)
    for e in edges:
        sym = PXSYM.get(unit_of(e).upper()); t = e.get("time") or e.get("last")
        if sym and t: need[sym].add(int(t // 86400 * 86400))
    hp = await hist_prices(need, errs) if need else {}
    def val(e):
        u = unit_of(e).upper(); t = e.get("time") or e.get("last"); a = e.get("amount")
        if a is None: return None, "–"
        if u in STABLE: return float(a), "P"
        sym = PXSYM.get(u)
        if sym and t and (sym, int(t // 86400 * 86400)) in hp: return float(a) * hp[(sym, int(t // 86400 * 86400))], "D"
        if e.get("usd") is not None: return float(e["usd"]), "T"
        return None, "–"
    pdf = PDF(meta, gen)
    nm = lambda i: (case_labels.get(i) or {}).get("name") if isinstance(case_labels.get(i), dict) else None
    def who(i):
        n = nodes.get(i) or {}; c, a = cid(i)
        lab = nm(i) or n.get("name")
        return lab, a, A["chain_of"](i)
    B = bridge_rows(A); ents = entity_rows(A, case_labels)
    sugg = [r for r in ents if r[2].get("suggested")]; heur = [b for b in B if b["heur"]]
    trace = A["trace"]; params = case.get("params") or {}
    mode = case.get("mode") or ("auto" if trace.get("type") == "autotrace" else "lookup")
    # ---------- cover ----------
    pdf.add_page(); pdf.start_section("Cover")
    pdf.set_fill_color(*NAVY); pdf.rect(0, 0, pdf.w, 46, style="F")
    pdf.set_xy(14, 13); pdf.set_font("dv", "B", 9); pdf.set_text_color(150, 220, 235); pdf.cell(0, 5, "CHAINTRACE", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(14); pdf.set_font("dv", "B", 21); pdf.set_text_color(255); pdf.cell(0, 11, "Cryptoasset Investigation Report", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(14); pdf.set_font("dv", "", 9.5); pdf.set_text_color(200, 210, 230); pdf.cell(0, 5, "Blockchain tracing summary generated from public ledger data", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_y(54); pdf.set_text_color(*NAVY); pdf.set_font("dv", "B", 15); pdf.multi_cell(0, 7, meta["case_name"], new_x=XPos.LMARGIN, new_y=YPos.NEXT); pdf.ln(3); pdf.set_text_color(0)
    subj_disp = A["subj"] or "–"
    kv(pdf, [
        ("Case reference", meta["ref"] or "(not entered)"),
        ("Investigator", meta["investigator"] or "(not entered)"),
        ("Handling marking", meta["marking"] or "(none entered)"),
        ("Subject", subj_disp, MONO),
        ("Scope", f"{ {'auto': 'AutoTrace', 'trace': 'Multi-hop trace', 'lookup': 'Lookup / manual expansion'}.get(mode, mode)}"
                  + (f" · {trace.get('direction') or params.get('dir') or ''} · max {trace.get('hops') or params.get('amax') or params.get('hops')} hops" if mode != "lookup" else "")
                  + (f" · min ${(trace.get('params') or {}).get('min_usd')}" if (trace.get('params') or {}).get('min_usd') is not None else "")
                  + (" · bridge hops followed" if (trace.get("params") or {}).get("follow_bridges") else "")),
        ("Chains in graph", ", ".join(chain_name(c) for c in A["chains"]) or "–"),
        ("Report generated (UK)", t_uk(gen)), ("Report generated (UTC)", t_utc(gen)),
        ("Case created / updated", (f"{t_uk(case['created'] / 1000)} / {t_uk(case['updated'] / 1000)}" if case.get("created") and case.get("updated") else "–")),
        ("ChainTrace version", f"v{VERSION} · commit {COMMIT}"),
        ("Case data SHA-256", data_sha, MONO),
        ("Graph image SHA-256", png_sha or "(no image)", MONO),
    ])
    pdf.ln(2)
    if meta["notes"]: pdf.h2("Investigator notes"); pdf.para(meta["notes"], size=8.8)
    pdf.box("The case data SHA-256 is computed over the canonical JSON of the case data exactly as received by ChainTrace "
            "(UTF-8, keys sorted, no whitespace). That JSON is embedded in this PDF as the attachment case_data.json. "
            "Extract it and run sha256sum to confirm the data is unchanged since this report was generated. "
            "The graph image hash covers the embedded PNG.", color=TEAL, title="Integrity")
    pdf.box("This document was generated automatically by ChainTrace, an analysis tool that reads public blockchain records via third-party APIs. "
            "It is not an official form or template of any police force, agency or court. Attributions are only as reliable as their sources (see Sections 5 and 7). "
            "Items marked “Intelligence lead” are not evidence and need independent corroboration.", color=AMBER, title="About this document")
    # ---------- 1 executive summary ----------
    pdf.h1("1. Executive summary")
    n_addr = sum(1 for i in nodes if not is_tx(i))
    kv(pdf, [("Subject", subj_disp, MONO), ("Addresses in graph", f"{n_addr} across {len(A['chains'])} chain(s): " + ", ".join(chain_name(c) for c in A["chains"])),
             ("Transactions referenced", f"{len(A['txs'])} unique transaction hashes · {len(edges)} flow edges"),
             ("Activity period", f"{t_uk(A['t0'])} – {t_uk(A['t1'])}" if A["t0"] else "–"),
             ("Subject outflows (graph)", usd(A["out_usd"]) + "  (valued at trace time)"), ("Subject inflows (graph)", usd(A["in_usd"]) + "  (valued at trace time)"),
             ("Gross value of all edges", usd(A["gross"]) + "  (sum over every hop: the same funds may be counted more than once)"),
             ("Cross-chain hops", f"{len(B)} ({len(B) - len(heur)} deterministic, {len(heur)} heuristic lead)"),
             ("Risk score", f"{(case.get('risk') or trace.get('risk') or {}).get('score', '–')} / 100 ({(case.get('risk') or trace.get('risk') or {}).get('level', '–')})  · ChainTrace exposure heuristic, not a legal finding")], w=(50, None))
    # key endpoints
    eps = []
    if trace.get("endpoints"):
        for x in trace["endpoints"]:
            eps.append((x.get("name") or "", x.get("category") or "", x.get("id"), x.get("usd"), x.get("hops"), bool(x.get("suggested")), ", ".join(x.get("sources") or []) if isinstance(x.get("sources"), list) else (x.get("sources") or "")))
    else:
        for _, i, n, ul in ents:
            k = (ul or {}).get("kind") if isinstance(ul, dict) else None
            k = k or n.get("kind")
            if k in ENDPOINT_KINDS or n.get("suggested"):
                eps.append((nm(i) or n.get("name") or "", k or "exchange-deposit (suggested)", i, A["inflow"].get(i) or None, A["hops"](i), bool(n.get("suggested")), ", ".join(sorted({s.get("source") for s in n.get("sources") or [] if isinstance(s, dict)}))))
    for b in B:
        eps.append((b.get("bridge") or "bridge", "bridge hop → " + chain_name((b.get("dst") or {}).get("chain")), (b.get("dst") or {}).get("address"), b.get("usd"), None, b["heur"], b.get("provider") or ""))
    pdf.h2("Key endpoints reached")
    if eps:
        with pdf.tbl((45, 25, 52, 21, 10, 29), size=7.3) as t:
            r = t.row(); [r.cell(x) for x in ("Entity", "Category", "Address", "Flow in (USD)", "Hops", "Basis")]
            for name, cat, i, u, hp_, lead, src in eps[:40]:
                r = t.row(); r.cell(name or "(unnamed)", style=BOLD); r.cell(cat); r.cell(wrap_hex(cid(i)[1] if i else "", 30), style=MONOS); r.cell(usd(u)); r.cell("–" if hp_ is None else str(hp_))
                r.cell("Intelligence lead" if lead else ("Dataset label" + (f" ({src})" if src else "")), style=LEADF if lead else FontFace(size_pt=6.6))
        pdf.para("Flow-in is the value on graph edges into the endpoint, at trace-time prices. For AutoTrace runs it is the total flow the endpoint received from traced branches, "
                 "which is an upper bound on the subject's funds (see Section 7).", size=7.3, color=GREY)
    else: pdf.para("No labelled endpoints (exchange, sanctioned, mixer, bridge, etc.) were reached in this graph.", size=8.5)
    # highest risk exposures
    pdf.h2("Highest risk exposures")
    risk = [r for r in ents if labels.RISK.get(r[2].get("kind") or "", 0) >= 35]
    reasons = list((case.get("risk") or trace.get("risk") or {}).get("reasons") or [])
    if risk:
        with pdf.tbl((54, 24, 62, 14, 28), size=7.3) as t:
            r = t.row(); [r.cell(x) for x in ("Entity", "Category", "Address", "Hops", "Label sources")]
            for _, i, n, ul in risk[:15]:
                r = t.row(); r.cell(n.get("name") or "", style=BOLD); r.cell(n.get("kind") or "", style=FontFace(emphasis="B", color=RED)); r.cell(wrap_hex(cid(i)[1], 34), style=MONOS)
                r.cell("–" if A["hops"](i) is None else str(A["hops"](i))); r.cell(", ".join(sorted({s.get("source") for s in n.get("sources") or [] if isinstance(s, dict)}))[:80])
    else: pdf.para("No high-risk categories (sanctioned, mixer, darknet, hack, scam, ransomware, gambling, blocklisted) appear in the graph.", size=8.5)
    findings = []
    exch = [e for e in eps if e[1] == "exchange" and not e[5]]
    if exch: findings.append(f"Funds reached {len(exch)} attributed exchange/VASP endpoint(s): " + "; ".join(sorted({e[0] for e in exch if e[0]}))[:300] + ". A production order to the VASP can confirm account ownership.")
    hr = sorted({(r[2].get('kind'), r[2].get('name') or '') for r in risk})
    if hr: findings.append("High-risk counterparties in graph: " + "; ".join(f"{k}: {n}" for k, n in hr)[:400] + ".")
    if B: findings.append(f"{len(B)} cross-chain bridge hop(s) identified; {len(B) - len(heur)} linked deterministically by the bridge’s own indexer" + (f", {len(heur)} heuristic (lead only)" if heur else "") + " (Section 4).")
    if sugg: findings.append(f"{len(sugg)} address(es) carry ChainTrace-inferred (AI/model-suggested) exchange-deposit labels. These are intelligence leads only (Section 5).")
    findings += [f"ChainTrace risk note: {x}" for x in reasons[:6]]
    if findings: pdf.h2("Key findings (automatically generated, verify before reliance)"); pdf.bullets(findings, size=8.3)
    # ---------- 2 graph ----------
    pdf.h1("2. Transaction graph")
    if png:
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(png)); w, h = im.size
            if max(w, h) > 3200:
                im.thumbnail((3200, 3200)); b = io.BytesIO(); im.save(b, "PNG", optimize=True); png2 = b.getvalue()
            else: png2 = png
            maxw, maxh = pdf.epw, pdf.h - pdf.get_y() - 40
            sc = min(maxw / w, maxh / h); iw, ih = w * sc, h * sc
            x = pdf.l_margin + (pdf.epw - iw) / 2; y = pdf.get_y()
            pdf.set_fill_color(7, 10, 18); pdf.rect(pdf.l_margin, y, pdf.epw, ih + 4, style="F")
            pdf.image(io.BytesIO(png2), x=x, y=y + 2, w=iw, h=ih); pdf.set_y(y + ih + 7)
        except Exception as ex: errs.append(f"graph image: {type(ex).__name__}"); pdf.para("(Graph image could not be embedded.)")
    else: pdf.para("(No graph image was supplied.)")
    pdf.para("The PNG is exported from the ChainTrace graph view. Nodes are addresses (icons show category), and arrows show the direction of value. "
             "Solid edges are on-chain transfers; dashed cyan edges are cross-chain bridge hops linked by a bridge indexer; dotted amber edges are heuristic bridge leads. "
             f"Image SHA-256: {png_sha or '–'}", size=7.6, color=GREY)
    # ---------- 3 trail ----------
    pdf.h1("3. Chronological transaction trail", landscape=True)
    rows = sorted(edges, key=lambda e: (e.get("time") or e.get("last") or e.get("first") or 0))
    pdf.para(f"{len(rows)} flow edge(s), oldest first. Each edge is a transfer between two addresses in one asset. Where ChainTrace aggregated repeated transfers between the same pair, "
             "the row shows the total, the count and the latest transaction hash. Hashes and addresses are given in full; the link column opens the public explorer record.", size=7.6, color=GREY)
    pdf.para("USD basis: D = daily close on the transaction date (UTC day; Coinbase Exchange USD candles). P = stablecoin at par ($1.00). "
             "T = valued at the trace-time price, not historical. – = no reliable price. Valuations are indicative only; obtain an expert valuation for charging or confiscation purposes.", size=7.2, color=GREY)
    with pdf.tbl((7, 35, 13, 47, 44, 44, 14, 23, 20, 20), size=6.8, lh=3.2) as t:
        r = t.row(); [r.cell(x) for x in ("#", "Time (UK / UTC)", "Chain", "Transaction hash", "From", "To", "Asset", "Amount", "USD", "Source")]
        for k, e in enumerate(rows, 1):
            r = t.row(); tm = e.get("time") or e.get("last")
            fl, fa, fc = who(e["source"]); tl, ta, tc = who(e["target"])
            v, basis = val(e)
            if e.get("xchain") and isinstance(e.get("bridge"), dict):
                b = e["bridge"]; sc, dc = (b.get("src") or {}).get("chain"), (b.get("dst") or {}).get("chain")
                ch = f"{code(sc)} → {code(dc)}"
                txt = f"src {wrap_hex((b.get('src') or {}).get('tx'), 32)}\ndst {wrap_hex((b.get('dst') or {}).get('tx'), 32)}"
                link = (b.get("src") or {}).get("tx_url") or tx_url(sc, (b.get("src") or {}).get("tx"))
                amt = f"{num((b.get('src') or {}).get('amount'))} {(b.get('src') or {}).get('unit') or ''}\n→ {num((b.get('dst') or {}).get('amount'))} {(b.get('dst') or {}).get('unit') or ''}"
                asset = "bridge"
            else:
                c = fc if fc else tc; h = e.get("tx") or (e["target"][3:] if is_tx(e["target"]) else e["source"][3:] if is_tx(e["source"]) else None)
                ch = code(c) if c else "?"; txt = wrap_hex(h, 33) + (f"\n(+{e['count'] - 1} more, first {t_utc(e['first'])[:10]})" if (e.get("count") or 1) > 1 and e.get("first") else "")
                link = tx_url(c, h); amt = num(e.get("amount")) + (f"\n×{e['count']}" if (e.get("count") or 1) > 1 else ""); asset = unit_of(e) or "?"
            r.cell(str(k)); r.cell(t_both(tm) if tm else "–")
            r.cell(ch); r.cell(txt, style=MONOS)
            r.cell(((fl + "\n") if fl else "") + (wrap_hex(fa, 30) if not is_tx(e["source"]) else "(transaction)"), style=MONOS)
            r.cell(((tl + "\n") if tl else "") + (wrap_hex(ta, 30) if not is_tx(e["target"]) else "(transaction)"), style=MONOS)
            r.cell(asset); r.cell(amt); r.cell((usd(v) + f" {basis}") if v is not None else "–")
            r.cell(dom(link) if link else "–", link=link, style=FontFace(color=(0, 80, 170), size_pt=6.6))
    # ---------- 4 bridges ----------
    pdf.h1("4. Cross-chain bridge hops")
    if B:
        pdf.para("A deterministic match means the bridge's own indexer (message, order or VAA identifier) links the source transaction to the destination transaction, and ChainTrace "
                 "checked that the record contains the queried hash. A heuristic match is inferred only from the same asset, a similar amount (within 5% fee tolerance), "
                 "the same recipient address and a time window, and is a lead, not evidence.", size=8, color=GREY)
        for k, b in enumerate(B, 1):
            s_, d_ = b.get("src") or {}, b.get("dst") or {}
            pdf.h2(f"4.{k}  {b.get('bridge') or 'Bridge'}: {chain_name(s_.get('chain'))} → {chain_name(d_.get('chain'))}")
            kv(pdf, [("Method", "HEURISTIC – " + LEAD if b["heur"] else "DETERMINISTIC – bridge indexer link", LEADF if b["heur"] else DETF),
                     ("Confidence", f"{int(round((b.get('confidence') or 0) * 100))}% · status {b.get('status') or '–'} · provider {b.get('provider') or '–'}"),
                     ("Source tx", f"{s_.get('tx') or '–'}\n{s_.get('tx_url') or tx_url(s_.get('chain'), s_.get('tx')) or ''}", MONOS),
                     ("Source address", s_.get("address") or "–", MONOS),
                     ("Sent", f"{num(s_.get('amount'))} {s_.get('unit') or ''} · {t_uk(s_['time']) + ' / ' + t_utc(s_['time']) if s_.get('time') else '–'}"),
                     ("Destination tx", f"{d_.get('tx') or '–'}\n{d_.get('tx_url') or tx_url(d_.get('chain'), d_.get('tx')) or ''}", MONOS),
                     ("Destination address", d_.get("address") or "–", MONOS),
                     ("Received", f"{num(d_.get('amount'))} {d_.get('unit') or ''} · {t_uk(d_['time']) + ' / ' + t_utc(d_['time']) if d_.get('time') else '–'}"),
                     ("Value (indicative)", usd(b.get("usd"))),
                     ("Evidence / basis", str(b.get("evidence") or "–")[:600] + ("\nBridge explorer: " + b["ref"] if isinstance(b.get("ref"), str) and b["ref"].startswith("http") else "")),
                     ("Times", "As reported by the bridge indexer (may differ by seconds from block times in Section 3)."),
                     ] + ([("Notes", "; ".join(map(str, b.get("notes")))[:400])] if b.get("notes") else []), w=(38, None))
    else: pdf.para("No cross-chain bridge hops are recorded in this case.", size=8.5)
    # ---------- 5 entities ----------
    pdf.h1("5. Entities and attributions", landscape=True)
    pdf.para("Attributions come from the open label datasets listed in Section 7, the explorer's public tags, bridge vault lists, and labels the investigator added to the case. "
             "A dataset label is a third-party assertion. Confirm it with the VASP or another primary source before relying on it in evidence.", size=7.6, color=GREY)
    if ents:
        with pdf.tbl((52, 52, 26, 64, 46, 28), size=6.9, lh=3.3) as t:
            r = t.row(); [r.cell(x) for x in ("Address (chain)", "Label", "Category", "Source dataset", "Licence", "Confidence")]
            for _, i, n, ul in ents:
                c = A["chain_of"](i); r = t.row()
                r.cell(f"{chain_name(c)}\n{wrap_hex(cid(i)[1], 30)}", style=MONOS)
                srcs = [s for s in (n.get("sources") or []) if isinstance(s, dict)][:6]
                if ul and isinstance(ul, dict):
                    r.cell(f"{ul.get('name')}\n(investigator label)" + (f"\ndataset: {n.get('name')}" if n.get("name") and n.get("name") != ul.get("name") else ""), style=BOLD)
                    r.cell(ul.get("kind") or n.get("kind") or "–")
                    r.cell("\n".join(["Investigator (case label)"] + [f"{s.get('source')}: {str(s.get('name') or '')[:40]}" for s in srcs]))
                    r.cell("\n".join(["–"] + [str(s.get("licence") or "–")[:40] for s in srcs])); r.cell("\n".join(["–"] + [f"{s.get('confidence', '–')}" for s in srcs]))
                elif n.get("suggested"):
                    sg = n["suggested"]
                    r.cell(f"{sg.get('label') or n.get('name')}\n{LEAD}", style=LEADF); r.cell("exchange-deposit (suggested)")
                    ev = sg.get("evidence") or {}
                    evs = ", ".join(f"{k}={v}" for k, v in list(ev.items())[:5]) if isinstance(ev, dict) else str(ev)[:120]
                    r.cell(f"ChainTrace deposit-address inference ({sg.get('method') or 'model'})\n{evs}"[:300]); r.cell("own work (inferred, behavioural model)")
                    r.cell(f"{int((sg.get('confidence') or 0) * 100)}% (model)", style=LEADF)
                else:
                    r.cell(n.get("name") or "–", style=BOLD); r.cell(n.get("kind") or "–", style=FontFace(emphasis="B", color=RED) if labels.RISK.get(n.get("kind") or "", 0) >= 35 else None)
                    r.cell("\n".join(f"{s.get('source')}: {str(s.get('name') or '')[:44]}" for s in srcs) or "–")
                    r.cell("\n".join(str(s.get("licence") or "–")[:44] for s in srcs) or "–"); r.cell("\n".join(f"{s.get('confidence', '–')}" for s in srcs) or (str(n.get("confidence")) if n.get("confidence") else "–"))
    else: pdf.para("No labelled entities in this graph.", size=8.5)
    if heur or sugg: pdf.box(f"{len(sugg)} inferred deposit label(s) and {len(heur)} heuristic bridge match(es) are marked “{LEAD}”.", title="Intelligence leads")
    # ---------- 6 notes ----------
    cn = case.get("notes") or {}
    if (cn.get("case") or cn.get("nodes") or cn.get("edges")):
        pdf.h1("6. Case notes")
        if cn.get("case"): pdf.h2("Case summary note"); pdf.para(str(cn["case"])[:6000], size=8.6)
        if cn.get("nodes"):
            pdf.h2("Address notes")
            with pdf.tbl((70, pdf.epw - 70), size=7.4) as t:
                r = t.row(); r.cell("Address"); r.cell("Note")
                for i, v in list(cn["nodes"].items())[:200]: r = t.row(); r.cell(wrap_hex(cid(i)[1], 40), style=MONOS); r.cell(str(v)[:1500])
        if cn.get("edges"):
            pdf.h2("Flow notes")
            with pdf.tbl((70, pdf.epw - 70), size=7.4) as t:
                r = t.row(); r.cell("Flow"); r.cell("Note")
                for i, v in list(cn["edges"].items())[:200]: r = t.row(); r.cell(wrap_hex(i, 40), style=MONOS); r.cell(str(v)[:1500])
    # ---------- 7 methodology ----------
    pdf.h1(("7" if (cn.get("case") or cn.get("nodes") or cn.get("edges")) else "6") + ". Methodology and limitations")
    pdf.h2("Data sources")
    pdf.bullets([
        "All transaction data comes from public blockchain records, retrieved through third-party APIs. ChainTrace does not run its own nodes, so results depend on those services being available and accurate.",
        "Bitcoin: mempool.space REST API (address and transaction history, inputs and outputs, block times).",
        "Ethereum: Blockscout public API (eth.blockscout.com) for transfers, token transfers and public tags. Public JSON-RPC endpoints (e.g. publicnode, drpc, Cloudflare) for balances. Ethplorer as a fallback.",
        "Solana: the public Solana JSON-RPC (getSignaturesForAddress / getTransaction), parsing native SOL and SPL token balance changes.",
        "Cross-chain: bridge indexers, all public and keyless: Wormholescan, deBridge DLN stats API, Mayan explorer API, Across API, THORChain/Maya Midgard, LayerZero Scan and Relay. THORChain/Maya inbound vault lists come from THORNode/MayaNode. EVM L2 public RPCs (Arbitrum, Optimism, Base, Polygon) are used for heuristic matching.",
        "Attribution datasets: OFAC SDN digital-currency addresses, GraphSense TagPacks, dawsbot/eth-labels, etherscan-labels, Forta labelled datasets, openlabels and Solana label aggregates, plus a ChainTrace curated seed list and allowlist. Each label records its dataset, licence and confidence (Section 5 and Appendix A).",
        "Prices: CoinGecko (with Coinbase as fallback) for trace-time valuation, and Coinbase Exchange daily candles for historical USD in this report. Stablecoins are valued at par.",
    ], size=7.8)
    pdf.h2("How flows are derived")
    pdf.bullets([
        "Account chains (Ethereum, Solana): each edge is a native or token transfer from one address to another, with the transaction hash, time, asset and amount as decoded from the chain.",
        "Bitcoin (UTXO): Bitcoin does not record which input paid which output. When the subject spends, ChainTrace draws edges from the subject to every output. When the subject receives, each input address is drawn as a sender. Per-edge amounts are therefore an attribution model, not a ledger fact. ChainTrace also applies the common-input-ownership heuristic (addresses co-spending in one transaction are probably controlled by the same entity), which can be wrong, e.g. for CoinJoin and PayJoin transactions.",
        "Aggregation: repeated transfers between the same pair of addresses in the same asset are merged into one edge (count, first/last time). The trail table gives the latest hash, and the full set can be listed from the explorer.",
        "AutoTrace follows the largest outflows hop by hop (top-K per address, minimum USD value) until it reaches labelled endpoints, dead ends or its limits. It filters noise (dust, spam tokens, approvals). Endpoint “flow in” is an upper bound, because tracing does not apply FIFO/LIFO or proportional taint allocation.",
        "Bridge hops: deterministic matches come from the bridge's own indexer. Heuristic matches (ETH mainnet ERC-20 → Arbitrum, Optimism, Base or Polygon only) use asset, amount within 5%, a 3-hour window and the same recipient. Confidence is capped at 60%.",
        "Inferred exchange-deposit labels: a transparent behavioural model (several unrelated senders, sweeps of near-full balances to one exchange hot wallet, gas top-ups from the exchange). It outputs a confidence score and never raises risk above exchange level. These are intelligence leads only.",
        "The risk score is ChainTrace's exposure heuristic based on the categories of nearby counterparties. It is not a legal or regulatory finding.",
    ], size=7.8)
    pdf.h2("Known gaps and limitations")
    pdf.bullets([
        "Coverage: only Bitcoin, Ethereum and Solana are traced natively. EVM L2s and other chains appear only as bridge destinations, for context. Privacy coins, Lightning, custodial (off-chain) transfers inside exchanges, and OTC desks are not visible.",
        "Labels can be incomplete, out of date or wrong. The absence of a label does not mean an address is unattributed in commercial datasets. Historical rotated THORChain vaults may be unlabelled.",
        "Bridges not covered: Circle CCTP direct, native L2 canonical bridges, and other bridges without a free public indexer. The Relay public API is rate-limited. deBridge and Across cannot be looked up from the destination transaction.",
        "APIs can rate-limit, time out or return partial pages. ChainTrace caps queries per request, so graphs may be partial; see the errors noted in Appendix A.",
        "USD values are indicative. Times are block times from the chain, shown in UK local time (Europe/London, BST/GMT) and UTC.",
        "All findings should be reproduced independently (e.g. on a second explorer) and attributions confirmed with the relevant VASP before evidential use.",
    ], size=7.8)
    # ---------- appendix A ----------
    pdf.h1("Appendix A. Data sources and queries", landscape=True)
    log = [x for x in (p.get("log") or []) if isinstance(x, dict) and x.get("url")][-400:]
    pdf.h2(f"A.1 ChainTrace queries made while building this case ({len(log)})")
    if log:
        with pdf.tbl((58, pdf.epw - 58), size=6.6, lh=3.0) as t:
            r = t.row(); r.cell("Query time (UK / UTC)"); r.cell("ChainTrace API request")
            for x in log:
                ts = (x.get("t") or 0) / 1000; r = t.row(); r.cell(t_line(ts)); r.cell(redact(str(x["url"]))[:400], style=MONOS)
    else: pdf.para("No query log was recorded for this case. Cases saved before v0.8 do not include one.", size=8)
    ids = [i for i in nodes] + list(A["txs"])
    up = cache_sources(ids)
    pdf.h2(f"A.2 Upstream API requests on record for these addresses and transactions ({len(up)})")
    pdf.para("These come from ChainTrace's server-side HTTP cache, and the time shown is when the data was last fetched. On hosted deployments the cache is temporary, so this list may be incomplete.", size=7.3, color=GREY)
    if up:
        with pdf.tbl((58, pdf.epw - 58), size=6.4, lh=2.9) as t:
            r = t.row(); r.cell("Retrieved (UK / UTC)"); r.cell("URL / RPC call")
            for ts, d in up: r = t.row(); r.cell(t_line(ts)); r.cell(d[:420], style=MONOS)
    pdf.h2("A.3 Public explorer records (for independent verification)")
    ex = []
    for i in nodes:
        if is_tx(i): continue
        c = A["chain_of"](i); u = addr_url(c, cid(i)[1])
        if u: ex.append(("address", u))
    for e in edges:
        for c, h in ((A["chain_of"](e["source"]) or A["chain_of"](e["target"]), e.get("tx")),):
            if h and not e.get("xchain"): u = tx_url(c, h); ex.append(("tx", u)) if u else None
    for b in B:
        for s_ in (b.get("src") or {}, b.get("dst") or {}):
            u = s_.get("tx_url") or tx_url(s_.get("chain"), s_.get("tx"))
            if u: ex.append(("tx (bridge)", u))
        if isinstance(b.get("ref"), str) and b["ref"].startswith("http"): ex.append(("bridge explorer", b["ref"]))
    ex = list(dict.fromkeys(ex))
    with pdf.tbl((26, pdf.epw - 26), size=6.4, lh=2.9) as t:
        r = t.row(); r.cell("Type"); r.cell("URL")
        for k, u in ex[:600]: r = t.row(); r.cell(k); r.cell(u, style=MONOS, link=u)
    pdf.h2("A.4 Label datasets")
    try:
        import update_labels
        used = {s.get("source") for n in nodes.values() for s in (n.get("sources") or []) if isinstance(s, dict)}
        with pdf.tbl((30, 90, pdf.epw - 30 - 90 - 50, 50), size=6.6, lh=3.0) as t:
            r = t.row(); [r.cell(x) for x in ("Dataset", "Description", "URL", "Licence")]
            for k, (d, u, l, _, _) in update_labels.SOURCES.items():
                r = t.row(); r.cell(k + (" (used)" if k in used else ""), style=BOLD if k in used else None); r.cell(d); r.cell(u, style=MONOS, link=u if u.startswith("http") else None); r.cell(l)
    except Exception as ex2: errs.append(f"label dataset list: {type(ex2).__name__}")
    if errs: pdf.h2("A.5 Report generation notes"); pdf.bullets(errs, size=7.6)
    # ---------- appendix B ----------
    pdf.h1("Appendix B. Integrity and reproducibility")
    kv(pdf, [("Case data SHA-256", data_sha, MONO), ("Case data size", f"{len(data_bytes):,} bytes (canonical JSON, UTF-8)"),
             ("Embedded attachment", "case_data.json (the exact bytes hashed above)"), ("Graph image SHA-256", png_sha or "–", MONO),
             ("Generated", f"{t_uk(gen)}  /  {t_utc(gen)}"), ("Software", f"ChainTrace v{VERSION}, commit {COMMIT} (fpdf2 {__import__('fpdf').__version__})"),
             ("Trace parameters", json.dumps(trace.get("params") or params or {}, sort_keys=True)[:500], MONOS)], w=(42, None))
    pdf.para("To verify: open the PDF's attachments panel (or use a tool such as pdfdetach), save case_data.json, then run “sha256sum case_data.json”. The result should equal the value above. "
             "Changing any address, amount, label or note in the case data gives a different hash. The SHA-256 of the PDF file itself is reported separately when the report is generated, "
             "because a file cannot contain its own hash.", size=8.2)
    pdf.embed_file(bytes=data_bytes, basename="case_data.json", desc="ChainTrace canonical case data (hashed on the cover)", modification_date=datetime.fromtimestamp(gen, timezone.utc))
    out = bytes(pdf.output())
    return out, {"case_sha256": data_sha, "png_sha256": png_sha, "pdf_sha256": hashlib.sha256(out).hexdigest(), "pages": pdf.page_no(), "notes": errs}
