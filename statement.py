"""ChainTrace v33: DRAFT investigator witness statement (generic layout in the style of a criminal-justice witness statement).
It is NOT the official MG11 form and does not reproduce it: there is no crest, form number or official wording. The statement of
truth / declaration is left as a placeholder for the officer's force-approved text. Every page says DRAFT, CHECK AND AMEND BEFORE SIGNING.

Content is built only from the case payload the browser sends (the same payload as the report / evidence pack) and from
investigator-entered fields; nothing is invented: unknown fields are left as [square-bracket placeholders].
- methodology, tools and data sources with versions / list dates;
- findings: transfers with tx hashes, UTC and UK local time, amount in the coin, indicative USD and GBP (ECB rate for the day);
- heuristic results (suggested exchange deposits, heuristic bridge / swap leads, peel / change leads, clusters) stated as OPINION / LEAD;
- exhibits list = the files of the evidence pack generated in the same request, each with its SHA-256, plus the pack's own SHA-256;
- audit-log anchor: entry count, hash-chain verification, head hash and the latest anchor receipt.
Outputs: DOCX (editable), PDF, or a zip with both + the evidence pack they reference + SHA256SUMS."""
import asyncio, hashlib, io, os, re, time, zipfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import report as R

BANNER = "DRAFT – CHECK AND AMEND BEFORE SIGNING"
NOT_FORM = ("Generic draft layout produced by ChainTrace. This is not the official MG11 form and must not be presented as one: "
            "transfer the checked wording onto your force's approved witness statement form.")
DECL_PH = "[PLACEHOLDER – insert your force-approved statement of truth / declaration wording here. ChainTrace does not supply this text.]"
UK = ZoneInfo("Europe/London")
MAXF = 80

def _s(x, n=200): return re.sub(r"\s+", " ", str(x or "")).strip()[:n]
def ph(v, label): return _s(v) or f"[{label}]"
def _uk_utc(ts):
    if not ts: return "time unknown"
    a = datetime.fromtimestamp(ts, UK); b = datetime.fromtimestamp(ts, timezone.utc)
    return f"{b.strftime('%d/%m/%Y %H:%M:%S')} UTC ({a.strftime('%d/%m/%Y %H:%M:%S')} UK {a.tzname()})"

async def _values(edges, errs):
    """USD (report's basis: stablecoins at par, Coinbase daily close, else trace-time USD) and GBP (ECB USD->GBP for the day)"""
    from collections import defaultdict
    import loss as LS
    need = defaultdict(set)
    for e in edges:
        sym = R.PXSYM.get(R.unit_of(e).upper()); t = e.get("time") or e.get("last")
        if sym and t: need[sym].add(int(t // 86400 * 86400))
    hp = await R.hist_prices(need, errs) if need else {}
    days = {int((e.get("time") or e.get("last")) // 86400 * 86400) for e in edges if e.get("time") or e.get("last")}
    try: hist, today = await LS._gbp(days, errs)
    except Exception as ex: hist, today = {}, None; errs.append(f"GBP rates: {type(ex).__name__}")
    out = {}
    for k, e in enumerate(edges):
        u = R.unit_of(e).upper(); t = e.get("time") or e.get("last"); a = e.get("amount"); v = None
        if a is not None:
            if u in R.STABLE: v = float(a)
            elif R.PXSYM.get(u) and t and (R.PXSYM[u], int(t // 86400 * 86400)) in hp: v = float(a) * hp[(R.PXSYM[u], int(t // 86400 * 86400))]
            elif e.get("usd") is not None: v = float(e["usd"])
        g = None
        if v is not None:
            rt = (hist.get(int(t // 86400 * 86400)) or (None,))[0] if t else None
            rt = rt or (today[0] if today else None)
            if rt: g = v * rt
        out[k] = (v, g)
    return out, today

def _heuristics(A, case_labels):
    H = []
    for sc, i, n, ul in R.entity_rows(A, case_labels):
        sg = n.get("suggested")
        if sg: H.append(f"Address {i} is, in my opinion, likely to be a deposit address at {sg.get('entity')} (ChainTrace behavioural inference, confidence {int(100 * (sg.get('confidence') or 0))}%). This is a lead to be confirmed with the exchange, not a fact.")
        cl = n.get("cluster") if isinstance(n.get("cluster"), dict) else None
        if cl: H.append(f"Address {i} is, in my opinion, likely controlled by the same wallet as {cl.get('root')} (common-input heuristic). This can be wrong (e.g. CoinJoin) and is a lead only.")
    for b in R.bridge_rows(A):
        if b.get("heur"):
            s_, d_ = b.get("src") or {}, b.get("dst") or {}
            H.append(f"Cross-chain lead ({b.get('provider') or 'heuristic'}): {R.num(s_.get('amount'))} {s_.get('unit') or ''} in tx {s_.get('tx')} may correspond to {R.num(d_.get('amount'))} {d_.get('unit') or ''} in tx {d_.get('tx')} on {R.chain_name(d_.get('chain'))} (amount/time coincidence, confidence {b.get('confidence')}). This is my opinion and a lead only.")
    for e in A["edges"]:
        if e.get("heur") and not e.get("xchain"):
            H.append(f"The link {e['source']} → {e['target']}" + (f" (tx {e.get('tx')})" if e.get("tx") else "") + " is a heuristic lead (e.g. change / peel-chain detection), not a recorded fact.")
    return list(dict.fromkeys(H))[:60]

def blocks(p, pack_files, pack_sha, gen, vals, today, errs):
    case = p.get("case") or {}; meta = p.get("meta") or {}; S = meta.get("statement") if isinstance(meta.get("statement"), dict) else {}
    le = meta.get("le") if isinstance(meta.get("le"), dict) else {}
    A = R.analyse(p); case_labels = case.get("labels") or {}
    pre = _s(S.get("exhibit_prefix"), 12) or "[INITIALS]"
    S = {**S, "name": S.get("name") or le.get("officer_name"), "role": S.get("role") or " ".join(x for x in (le.get("officer_rank"), le.get("officer_number")) if x), "force": S.get("force") or le.get("force")}
    nm = ph(S.get("name") or meta.get("investigator"), "full name")
    B = [("banner", BANNER), ("h1", "Witness statement – DRAFT"), ("box", NOT_FORM),
         ("kv", [("Statement of", nm), ("Age if under 18", ph(S.get("age"), "'Over 18' or age")), ("Occupation / rank / role", ph(S.get("role"), "rank / role")),
                 ("Force / organisation", ph(S.get("force"), "force or organisation")), ("Case reference", ph(meta.get("ref") or le.get("crime_ref"), "case / crime reference")),
                 ("Report Fraud / NFIB reference", ph(le.get("rf_ref"), "Report Fraud / NFIB reference if any")),
                 ("Statement date", ph(S.get("date"), "date of signing")), ("Pages", "[number of pages]")]),
         ("h2", "Declaration"), ("box", DECL_PH)]
    n = [0]
    def para(t): n[0] += 1; B.append(("p", f"{n[0]}. {t}"))
    B.append(("h2", "Introduction"))
    para(f"I am {nm}, {ph(S.get('role'), 'rank / role')} with {ph(S.get('force'), 'force or organisation')}. {ph(S.get('experience'), 'describe your training and experience in blockchain analysis')}.")
    para(f"This statement concerns case “{_s(case.get('name') or 'Untitled case', 120)}”. It describes how I analysed public blockchain records relating to the case and what I found. "
         f"Where I give an opinion, or rely on a heuristic, I say so expressly; those passages are intelligence leads, not statements of fact.")
    B.append(("h2", "Methodology, tools and data sources"))
    para(f"I used ChainTrace version {R.VERSION} (build {R.COMMIT}), a web-based blockchain tracing tool, at {ph(S.get('tool_url'), 'URL of the ChainTrace instance')}. "
         f"This draft was generated on {_uk_utc(gen)}. ChainTrace reads public ledger data through third-party public APIs; it does not run its own blockchain nodes.")
    try:
        import screen
        lists = "; ".join(f"{x.get('short')} list as of {x.get('as_of')}" for x in screen.S["lists"].values())
    except Exception: lists = "[sanctions list dates]"
    para("Data sources: Bitcoin – mempool.space / Blockstream Esplora APIs; Ethereum and EVM chains – Blockscout public APIs and public JSON-RPC endpoints; TRON – TronGrid; "
         "Solana – public Solana JSON-RPC; XRP Ledger – public rippled servers; cross-chain – the bridges' and swap protocols' own public indexers (e.g. THORChain Midgard, Chainflip). "
         f"Address labels come from public datasets cited per label in the exhibited report (Appendix A). Sanctions screening: {lists}. "
         "USD values use Coinbase Exchange daily closing prices (stablecoins at par) or the value recorded at trace time; GBP values apply the European Central Bank USD→GBP reference rate for the day (Frankfurter API).")
    para("Times are block times recorded on each blockchain. I give them in UTC and in UK local time (Europe/London, GMT or BST as applicable).")
    para("Every action taken in the case was recorded in ChainTrace's hash-chained case audit log (see the audit-log paragraph below).")
    B.append(("h2", "Findings"))
    E = sorted([e for e in A["edges"] if e.get("tx") and not e.get("meta")], key=lambda e: e.get("time") or e.get("last") or 0)
    para(f"The case graph contains {len(A['nodes'])} nodes and {len(A['edges'])} flows across {', '.join(R.chain_name(c) for c in A['chains'] if c and c != '?') or 'the chains shown'}. "
         f"I set out below the {min(len(E), MAXF)} recorded transfer(s) with transaction hashes, oldest first" + (f" (the first {MAXF} of {len(E)}; the remainder are in the exhibited report)" if len(E) > MAXF else "") + ".")
    idx = {id(e): k for k, e in enumerate(A["edges"])}
    rows = []
    for k, e in enumerate(E[:MAXF], 1):
        v, g = vals.get(idx[id(e)], (None, None)); t = e.get("time") or e.get("last")
        fl = (case_labels.get(e["source"]) or {}).get("name") if isinstance(case_labels.get(e["source"]), dict) else None
        tl = (case_labels.get(e["target"]) or {}).get("name") if isinstance(case_labels.get(e["target"]), dict) else None
        rows.append([str(k), _uk_utc(t), R.chain_name(A["chain_of"](e["source"]) if not R.is_tx(e["source"]) else A["chain_of"](e["target"])), str(e.get("tx")),
                     (f"{fl}: " if fl else "") + R.cid(e["source"])[1], (f"{tl}: " if tl else "") + R.cid(e["target"])[1],
                     f"{R.num(e.get('amount'))} {R.unit_of(e)}" + (f" (×{e['count']} merged)" if (e.get("count") or 1) > 1 else ""),
                     R.gbp(g), R.usd(v), "OPINION / LEAD (heuristic link)" if e.get("heur") else "recorded on-chain"])
    B.append(("tbl", (["#", "Time (UTC and UK)", "Chain", "Transaction hash", "From", "To", "Amount (coin)", "GBP (indicative)", "USD (indicative)", "Basis"], rows)))
    tg = sum(r for r in (vals.get(idx[id(e)], (None, None))[1] for e in E[:MAXF]) if r)
    para(f"The GBP figures above total {R.gbp(tg)} across the listed rows. They are indicative values on the day of each transfer and add flows at every hop, so the same funds can be counted more than once."
         + (f" Where no daily rate was available the rate of {today[1]} was used." if today else ""))
    if isinstance(p.get("loss"), dict) and p["loss"].get("payments"):
        para(f"The investigator marked {len(p['loss'].get('payments') or [])} victim payment(s) in the case; the loss calculation is exhibited in the evidence pack (victim_loss_summary.csv) and the report.")
    B.append(("h2", "Opinion and heuristic leads"))
    H = _heuristics(A, case_labels)
    if H:
        para("The following are opinions based on heuristic analysis. Each is an intelligence lead, not evidence of fact, and should be corroborated (for example by production orders to the exchanges named):")
        B.append(("bul", H))
    else: para("No heuristic attributions or links are relied on in this statement.")
    B.append(("h2", "Exhibits"))
    para(f"I produce the following exhibits. They are the files of the ChainTrace evidence pack generated together with this draft on {_uk_utc(gen)}. "
         f"The SHA-256 hash of each file is given so that its integrity can be checked; the pack file as a whole has SHA-256 {pack_sha}.")
    ex = [[f"{pre}/{k}", d, f, h] for k, (f, h, d) in enumerate(pack_files, 1)]
    B.append(("tbl", (["Exhibit", "Description", "File", "SHA-256"], ex)))
    B.append(("h2", "Case audit log"))
    au = [e for e in (case.get("audit") or []) if isinstance(e, dict)]
    if au:
        import auditlog
        v = auditlog.verify(au); anc = [a for a in (case.get("anchors") or []) if isinstance(a, dict)]
        para(f"The case audit log holds {len(au)} hash-chained entries. Verification when this draft was generated: {'intact' if v.get('ok') else 'NOT intact (' + str(v.get('why')) + ' at entry ' + str(v.get('at')) + ')'}; head hash {v.get('head') or '–'}.")
        if anc:
            a = anc[-1]; ok = auditlog.check_receipt(a)
            para(f"The most recent anchor receipt covers entries 1–{a.get('seq')} with head hash {a.get('head')}, issued {_uk_utc(a.get('t'))}; receipt {'verified by this server' if ok else 'could not be verified by this server'}.")
        else: para("No anchor receipt had been issued for this case when the draft was generated. [Anchor the audit log and regenerate if required.]")
    else: para("No audit-log entries were included with the case. [Explain how the analysis was recorded.]")
    B.append(("h2", "Signature"))
    B.append(("kv", [("Signature", "[NOT SIGNED – DRAFT]"), ("Date", ph(S.get("date"), "date")), ("Witness (if applicable)", "[name / signature]")]))
    if errs: B.append(("box", "Generation notes: " + "; ".join(errs[:8])))
    return B

def to_docx(B):
    from docx import Document
    from docx.shared import Pt, RGBColor, Mm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_ORIENT
    d = Document(); s = d.sections[0]; s.page_width, s.page_height = Mm(210), Mm(297)
    for m in ("left_margin", "right_margin"): setattr(s, m, Mm(15))
    st = d.styles["Normal"]; st.font.name = "Arial"; st.font.size = Pt(10)
    for part in (s.header, s.footer):
        p = part.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER; r = p.add_run(BANNER); r.bold = True; r.font.size = Pt(11); r.font.color.rgb = RGBColor(0xC0, 0x10, 0x20)
    for t, x in B:
        if t == "banner":
            p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; r = p.add_run(x); r.bold = True; r.font.size = Pt(16); r.font.color.rgb = RGBColor(0xC0, 0x10, 0x20)
        elif t == "h1": d.add_heading(x, level=1)
        elif t == "h2": d.add_heading(x, level=2)
        elif t == "p": d.add_paragraph(x)
        elif t == "box":
            tb = d.add_table(rows=1, cols=1); tb.style = "Table Grid"; c = tb.cell(0, 0); r = c.paragraphs[0].add_run(x); r.font.size = Pt(9); r.font.color.rgb = RGBColor(0x6B, 0x3C, 0x00); d.add_paragraph()
        elif t == "bul":
            for i in x: d.add_paragraph(i, style="List Bullet")
        elif t == "kv":
            tb = d.add_table(rows=0, cols=2); tb.style = "Table Grid"
            for k, v in x:
                row = tb.add_row().cells; row[0].text = k; row[1].text = str(v)
                for r in row[0].paragraphs[0].runs: r.bold = True
            d.add_paragraph()
        elif t == "tbl":
            hd, rows = x; tb = d.add_table(rows=1, cols=len(hd)); tb.style = "Table Grid"
            for j, h in enumerate(hd):
                tb.rows[0].cells[j].text = h
                for r in tb.rows[0].cells[j].paragraphs[0].runs: r.bold = True; r.font.size = Pt(7.5)
            for row in rows:
                cells = tb.add_row().cells
                for j, cval in enumerate(row):
                    cells[j].text = str(cval)
                    for p in cells[j].paragraphs:
                        for r in p.runs: r.font.size = Pt(7)
            d.add_paragraph()
    d.core_properties.title = "DRAFT witness statement – check and amend before signing"; d.core_properties.author = "ChainTrace (draft for officer completion)"
    b = io.BytesIO(); d.save(b); return b.getvalue()

def to_pdf(B, gen):
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    class P(FPDF):
        def header(s):
            s.set_xy(s.l_margin, 6); s.set_font("dv", "B", 10); s.set_text_color(192, 16, 32); s.cell(s.epw, 5, BANNER, align="C"); s.set_y(15); s.set_text_color(0)
        def footer(s):
            s.set_y(-11); s.set_font("dv", "", 7); s.set_text_color(110)
            s.cell(s.epw, 4, f"Page {s.page_no()} of {{nb}} · ChainTrace {R.VERSION} · generic draft layout, not an official MG11 form · {BANNER}", align="C")
    f = os.path.join(R.H, "fonts"); pdf = P("P", "mm", "A4")
    pdf.add_font("dv", "", os.path.join(f, "DejaVuSans.ttf")); pdf.add_font("dv", "B", os.path.join(f, "DejaVuSans-Bold.ttf")); pdf.add_font("mono", "", os.path.join(f, "DejaVuSansMono.ttf"))
    pdf.set_margins(14, 15, 14); pdf.set_auto_page_break(True, 15); pdf.alias_nb_pages(); pdf.set_title("DRAFT witness statement"); pdf.set_creator(f"ChainTrace {R.VERSION} ({R.COMMIT})"); pdf.set_lang("en-GB")
    pdf.add_page()
    NL = dict(new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for t, x in B:
        if t == "banner":
            pdf.set_fill_color(253, 232, 235); pdf.set_draw_color(192, 16, 32); pdf.set_text_color(192, 16, 32); pdf.set_font("dv", "B", 15)
            pdf.multi_cell(0, 11, x, border=1, align="C", fill=True, **NL); pdf.set_text_color(0); pdf.ln(2)
        elif t == "h1": pdf.set_font("dv", "B", 14); pdf.multi_cell(0, 7, x, **NL); pdf.ln(1)
        elif t == "h2": pdf.ln(2); pdf.set_font("dv", "B", 11); pdf.set_text_color(22, 38, 74); pdf.multi_cell(0, 6, x, **NL); pdf.set_text_color(0)
        elif t == "p": pdf.set_font("dv", "", 9.2); pdf.multi_cell(0, 4.6, x, **NL); pdf.ln(1.2)
        elif t == "box":
            pdf.set_font("dv", "", 8.6); pdf.set_fill_color(255, 246, 225); pdf.set_draw_color(200, 150, 60); pdf.set_text_color(107, 60, 0)
            pdf.multi_cell(0, 4.4, x, border=1, fill=True, **NL); pdf.set_text_color(0); pdf.ln(1.5)
        elif t == "bul":
            pdf.set_font("dv", "", 8.6)
            for i in x: pdf.multi_cell(0, 4.3, "• " + i, **NL); pdf.ln(0.6)
        elif t == "kv":
            pdf.set_font("dv", "", 8.8)
            with pdf.table(col_widths=(55, 127), text_align="LEFT", line_height=5, first_row_as_headings=False) as tb:
                for k, v in x: r = tb.row(); r.cell(k); r.cell(str(v))
            pdf.ln(2)
        elif t == "tbl":
            hd, rows = x
            w = {10: (6, 24, 14, 30, 24, 24, 17, 14, 13, 16), 4: (16, 46, 50, 70)}.get(len(hd))
            pdf.set_font("dv", "", 6.2 if len(hd) > 4 else 7)
            with pdf.table(col_widths=w, text_align="LEFT", line_height=2.9 if len(hd) > 4 else 3.4) as tb:
                r = tb.row(); [r.cell(h) for h in hd]
                for row in rows:
                    r = tb.row(); [r.cell(re.sub(r"(.{22})", r"\1 ", str(c)) if len(str(c)) > 40 and " " not in str(c) else str(c)) for c in row]
            pdf.ln(2)
    return bytes(pdf.output())

async def build(p, fmt="zip"):
    import evidence
    gen = time.time(); errs = []
    zb, info = await evidence.build_pack(p)
    pack_sha = hashlib.sha256(zb).hexdigest(); ref = info.get("ref") or "case"
    zf = zipfile.ZipFile(io.BytesIO(zb)); files = []
    DESC = {"pdf": "ChainTrace investigation report (PDF)", "vasp_schedule.csv": "Schedule of exchange / VASP addresses (CSV)", "cross_chain_hops.csv": "Cross-chain bridge and swap hops (CSV)",
            "victim_loss_summary.csv": "Victim loss summary (CSV)", "production_order_draft.csv": "Draft production-order address list (CSV, leads)", "case_audit_log.csv": "Case audit log (CSV)",
            "case_audit_log.json": "Case audit log with verification (JSON)", "case_notes.csv": "Case notes journal (CSV)", "HOW_TO_USE.txt": "How to use the pack", "SHA256SUMS.txt": "SHA-256 checksums of the pack files"}
    for zi in zf.infolist():
        nm = zi.filename.split("/", 1)[-1]; b = zf.read(zi)
        d = DESC.get(nm) or ("ChainTrace investigation report (PDF)" if nm.endswith(".pdf") and "/" not in nm else ("DRAFT records request to a VASP" if nm.startswith("vasp_drafts/") else nm))
        files.append((nm, hashlib.sha256(b).hexdigest(), d))
    A = R.analyse(p); E = [e for e in A["edges"]]
    vals, today = await _values(E, errs)
    B = blocks(p, files, pack_sha, gen, vals, today, errs)
    docx_b = to_docx(B) if fmt in ("zip", "docx") else None
    pdf_b = to_pdf(B, gen) if fmt in ("zip", "pdf") else None
    base = f"DRAFT_witness_statement_{evidence.safe(ref)}"
    meta = {"ref": ref, "pack_sha256": pack_sha, "exhibits": len(files), "generated": int(gen)}
    if fmt == "docx": return docx_b, base + ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", meta
    if fmt == "pdf": return pdf_b, base + ".pdf", "application/pdf", meta
    out = [(base + ".docx", docx_b), (base + ".pdf", pdf_b), (f"ChainTrace-evidence-pack-{ref}.zip", zb)]
    out.append(("SHA256SUMS.txt", "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in out).encode()))
    o = io.BytesIO(); dt = time.localtime(gen)[:6]
    with zipfile.ZipFile(o, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in out:
            zi = zipfile.ZipInfo(f"ChainTrace-statement-{ref}/{n}", date_time=dt); zi.compress_type = zipfile.ZIP_DEFLATED; z.writestr(zi, b)
    return o.getvalue(), f"ChainTrace-statement-{ref}.zip", "application/zip", meta
