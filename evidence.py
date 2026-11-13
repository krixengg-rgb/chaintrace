"""ChainTrace UK law-enforcement evidence pack.
- Investigator-entered Report Fraud (formerly Action Fraud) / NFIB, officer and case fields (never invented, all optional).
- VASP schedule built from the case graph: every exchange / VASP / deposit address with chain, address, XRP destination tags, memos,
  amounts, tx hashes and first/last seen (UK + UTC). Labels are re-checked server-side against the label DB.
- One DRAFT request per VASP (DOCX + TXT) for the officer to complete and serve through the proper legal route.
  These are NOT court orders and are deliberately not styled like one (no crest, no court case number, no order wording).
Legal references below were taken from public sources (legislation.gov.uk, GOV.UK, ICO, Report Fraud) in November 2026; the officer must take their own legal advice."""
import csv, hashlib, io, json, re, time, zipfile
from collections import defaultdict
import labels, deposits, screen
import report as R

PACK_VERSION = "1.0"
DRAFT_BANNER = "DRAFT – NOT A COURT ORDER – FOR OFFICER REVIEW AND COMPLETION"
NOT_OFFICIAL = ("Prepared with ChainTrace, an independent blockchain analysis tool. It is not an official form or template of the Home Office, NCA, "
                "City of London Police / Report Fraud, the courts or any police force, and has no legal effect on its own.")
# investigator-entered fields: key -> (label, max length)
LE_FIELDS = {
    "rf_ref": ("Report Fraud / Action Fraud reference (e.g. NFRC…)", 60),
    "crime_ref": ("Force crime / occurrence reference", 60),
    "nfib_code": ("NFIB fraud classification code (if known)", 60),
    "victim_ref": ("Victim or case reference", 80),
    "offence": ("Offence(s) under investigation", 300),
    "period_from": ("Period of interest – from", 20),
    "period_to": ("Period of interest – to", 20),
    "facts": ("Facts of the case (short)", 2500),
    "officer_name": ("Officer name", 80),
    "officer_rank": ("Rank / role", 60),
    "officer_number": ("Collar / warrant number", 30),
    "force": ("Force / unit", 120),
    "officer_email": ("Email", 120),
    "officer_phone": ("Phone", 40),
}
SOURCES = [
    ("Proceeds of Crime Act 2002, s.345 (production orders; includes cryptoasset investigations since ECCTA 2023)", "https://www.legislation.gov.uk/ukpga/2002/29/section/345"),
    ("Proceeds of Crime Act 2002, s.363 (customer information orders) and s.370 (account monitoring orders)", "https://www.legislation.gov.uk/ukpga/2002/29/part/8"),
    ("ECCTA 2023, Sch 10 para 7: cryptoasset exchange providers and custodian wallet providers added to 'financial institution' in POCA Sch 6", "https://www.legislation.gov.uk/ukpga/2023/56/schedule/10"),
    ("POCA 2002 s.342 (offences of prejudicing an investigation)", "https://www.legislation.gov.uk/ukpga/2002/29/section/342"),
    ("Home Office: Investigations code of practice under POCA s.377", "https://www.gov.uk/government/publications/investigations-code-of-practice-issued-under-section-377"),
    ("Police and Criminal Evidence Act 1984, Schedule 1 (special procedure material) – official application form on GOV.UK", "https://www.gov.uk/government/publications/application-for-a-production-order-under-pace"),
    ("Data Protection Act 2018, Sch 2 Pt 1 para 2 (crime and taxation exemption) – ICO guidance on sharing with law enforcement", "https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-sharing/sharing-personal-data-with-law-enforcement-authorities/"),
    ("Crime (International Co-operation) Act 2003, s.7 (requests for assistance in obtaining evidence abroad)", "https://www.legislation.gov.uk/ukpga/2003/32/section/7"),
    ("Home Office: Mutual legal assistance (UK Central Authority)", "https://www.gov.uk/guidance/mutual-legal-assistance-mla-requests"),
    ("FCA Financial Services Register (check whether a cryptoasset firm is registered in the UK)", "https://register.fca.org.uk/"),
    ("Report Fraud (replaced Action Fraud on 4 December 2025; NFRC references remain valid)", "https://www.reportfraud.police.uk/news/report-fraud-service-goes-live/"),
    ("Home Office Counting Rules: Fraud (NFIB classification codes), April 2026", "https://assets.publishing.service.gov.uk/media/69d4d4e4826d774e7b263e43/nfib-fraud-april-2026.pdf"),
]
ROUTES = [
    ("POCA 2002 s.345 production order",
     "Use this draft's schedules as the description of material in an application by an appropriate officer (s.378) to a judge, in a confiscation, civil recovery, "
     "money laundering, detained cash/property, frozen funds or cryptoasset investigation. The judge decides whether to make the order; the period is normally "
     "seven days (s.345(5)). Follow the s.377 Code of Practice."),
    ("PACE 1984 s.9 / Schedule 1 production order",
     "For special procedure material (e.g. confidential financial records) in an indictable-offence investigation. Use the official application form on GOV.UK; "
     "the schedules below can be adapted as the description of material."),
    ("POCA 2002 s.363 customer information order / s.370 account monitoring order",
     "Since the Economic Crime and Corporate Transparency Act 2023, cryptoasset exchange providers and custodian wallet providers are 'financial institutions' for these orders "
     "(POCA Sch 6 para 6(1)(j)-(k)). Seek advice from your financial investigation unit on whether these are the better route."),
    ("Voluntary disclosure request (DPA 2018 Sch 2 Pt 1 para 2)",
     "The firm may choose to disclose personal data for the prevention or detection of crime. This places no compulsion on the firm. Many exchanges run a law-enforcement "
     "request portal and will only accept requests through it."),
    ("Overseas firm: mutual legal assistance",
     "If the firm is outside the UK and will not disclose voluntarily, evidence for use in UK proceedings will generally need a Letter of Request issued by a judicial "
     "authority or designated prosecuting authority (Crime (International Co-operation) Act 2003 s.7), sent through the Home Office UK Central Authority. Speak to the CPS / your force's international unit."),
]
REQUEST_ITEMS = [
    ("KYC / customer due diligence", "Full name(s), date of birth, nationality, residential address, email and phone on file; identity documents, selfie / liveness images and proof of address supplied; any enhanced due diligence records and source-of-funds / source-of-wealth declarations."),
    ("Account opening", "Account / user ID, date and time of registration, IP address and device details at registration, referral or introducer details, account status and any restrictions, freezes or closures (with dates and reasons where they can be given)."),
    ("Transaction history", "All crypto deposits and withdrawals (asset, amount, date/time with time zone, on-chain transaction hash, sending / destination address, destination tag or memo), trades and conversions, and internal transfers to or from other customers."),
    ("Deposit / withdrawal addresses", "Every deposit address assigned to the account on every network (including the addresses and destination tags / memos in Schedule A), and any withdrawal address book / whitelist entries."),
    ("Fiat on / off-ramp", "Linked bank accounts, cards, e-money or payment-provider accounts used to fund or withdraw, with transaction records."),
    ("Access logs", "Login history with IP addresses, timestamps (with time zone), device identifiers, user agents, and any changes to email, phone, password or 2FA settings."),
    ("Linked accounts", "Other accounts the firm has linked to this customer (e.g. shared device, IP address, KYC details, payment instrument, referral)."),
    ("Current position", "Current balances by asset and confirmation of whether funds remain on the account."),
]

def clean_le(d):
    d = d if isinstance(d, dict) else {}
    out = {}
    for k, (_, mx) in LE_FIELDS.items():
        v = d.get(k)
        if isinstance(v, (str, int, float)) and str(v).strip(): out[k] = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(v)).strip()[:mx]
    return out
def le_rows(le):
    return [(lab, le.get(k)) for k, (lab, _) in LE_FIELDS.items()]
def period_text(le):
    a, b = le.get("period_from"), le.get("period_to")
    if a or b: return f"{a or '[start date]'} to {b or '[end date]'}"
    return "[officer to specify the period of interest]"

# ---------------- VASP schedule from the case graph ----------------
_KNOWN = []
def known_entities():
    """lower-case exchange names from the built-in exchange label list (used to group investigator labels like 'Binance 14 (victim)')"""
    if not _KNOWN:
        for m in labels.EXCH.values():
            for v in m.values():
                e = deposits.ent_of([{"name": v}])
                if e: _KNOWN.append(e.lower())
        _KNOWN.extend(["coinbase", "kraken", "binance", "okx", "bybit", "kucoin", "bitfinex", "bitstamp", "gemini", "crypto.com", "htx", "gate.io", "mexc", "bitget", "uphold", "revolut"])
    return set(_KNOWN)
def _entity_for(i, n, ul, c, a):
    """(entity, role, basis, sources, lead) or None. Server-side re-check against the label DB; investigator label wins."""
    rows = []
    try: rows = [r for r in labels.db_labels(c, a) if r.get("category") == "exchange"]
    except Exception: pass
    if isinstance(ul, dict) and (ul.get("kind") == "exchange") and ul.get("name"):
        nm = ul["name"].strip()[:80]; first = deposits.ent_of([{"name": nm}]) or nm
        ent = deposits.ent_of(rows) if rows else None
        if not (ent and nm.lower().startswith(ent.lower())): ent = first if first.lower() in known_entities() else nm
        return ent, f"investigator-labelled exchange / VASP address ({nm})", "Investigator label (case)", sorted({r.get("source") for r in rows if r.get("source")}), False
    if rows:
        ent = deposits.ent_of(rows) or (rows[0].get("name") or "Exchange")
        dep = any(deposits.is_deposit_row(r) for r in rows)
        return ent, ("deposit address (dataset label)" if dep else "exchange hot / collection wallet (dataset label)"), \
            "Dataset label", sorted({r.get("source") for r in rows if r.get("source")}), False
    if n.get("kind") == "exchange" and n.get("name"):
        ent = deposits.ent_of([{"name": n["name"]}]) or n["name"]
        return ent, "exchange wallet (explorer / built-in label)", "Explorer / built-in label", sorted({s.get("source") for s in n.get("sources") or [] if isinstance(s, dict) and s.get("source")}), False
    sg = n.get("suggested")
    if isinstance(sg, dict) and sg.get("entity") and "exchange" in (sg.get("category") or "exchange"):
        return str(sg["entity"])[:80], f"suspected deposit address (ChainTrace inference, {int((sg.get('confidence') or 0) * 100)}% model score)", \
            "INFERRED – " + R.LEAD, [sg.get("method") or "deposit inference"], True
    return None

def vasp_schedule(p):
    A = R.analyse(p); nodes, edges = A["nodes"], A["edges"]; case_labels = (p.get("case") or {}).get("labels") or {}
    out = {}
    for i, n in nodes.items():
        if R.is_tx(i) or n.get("grp") or n.get("meta"): continue
        c, a = A["chain_of"](i), R.cid(i)[1]
        if not a or c not in ("btc", "eth", "sol", "tron", "xrp", "bsc", "arb", "base", "polygon", "op"): continue
        ul = case_labels.get(i) if isinstance(case_labels, dict) else None
        r = _entity_for(i, n, ul, c, a)
        if not r: continue
        ent, role, basis, srcs, lead = r
        row = {"id": i, "chain": c, "address": a, "label": (ul or {}).get("name") if isinstance(ul, dict) else n.get("name"), "role": role, "basis": basis,
               "sources": srcs, "lead": lead, "in": defaultdict(float), "out": defaultdict(float), "in_usd": 0.0, "out_usd": 0.0,
               "dtags": set(), "memos": set(), "txs": [], "first": None, "last": None, "n_in": 0, "n_out": 0,
               "sanctioned": [h.get("short", "") + " " + h.get("entry", "") for h in screen.sanctions(c, a)] if c in screen.SUPPORTED else []}
        for e in edges:
            if e.get("xchain"): continue
            if e["target"] == i: d = "in"
            elif e["source"] == i: d = "out"
            else: continue
            amt = e.get("amount"); u = R.unit_of(e) or "?"
            if isinstance(amt, (int, float)): row[d][u] += amt
            row[d + "_usd"] += e.get("usd") or 0; row["n_" + d] += e.get("count") or 1
            for k in ("destination_tag",):
                if e.get(k) is not None: row["dtags"].add(str(e[k]))
            for t in e.get("destination_tags") or []: row["dtags"].add(str(t))
            for k in ("memo", "memos"):
                v = e.get(k)
                for m in (v if isinstance(v, list) else [v] if v else []): row["memos"].add(str(m)[:120])
            cp = e["source"] if d == "in" else e["target"]
            for h in (e.get("tx"),):
                if h: row["txs"].append({"tx": h, "dir": d, "amount": amt, "unit": u, "usd": e.get("usd"), "count": e.get("count") or 1,
                                         "time": e.get("time") or e.get("last"), "first": e.get("first"), "cp": R.cid(cp)[1],
                                         "dtag": e.get("destination_tag"), "url": R.tx_url(c, h)})
            for t in (e.get("first"), e.get("time"), e.get("last")):
                if t: row["first"] = min(row["first"] or t, t); row["last"] = max(row["last"] or t, t)
        row["txs"].sort(key=lambda x: x.get("time") or 0)
        v = out.setdefault(ent.lower(), {"entity": ent, "addresses": [], "lead_only": True})
        v["addresses"].append(row); v["lead_only"] = v["lead_only"] and lead
    res = []
    for v in out.values():
        for r_ in v["addresses"]:
            r_["in"] = dict(r_["in"]); r_["out"] = dict(r_["out"]); r_["dtags"] = sorted(r_["dtags"]); r_["memos"] = sorted(r_["memos"])
        v["addresses"].sort(key=lambda r_: (r_["lead"], -(r_["in_usd"] + r_["out_usd"])))
        v["in_usd"] = sum(r_["in_usd"] for r_ in v["addresses"]); v["out_usd"] = sum(r_["out_usd"] for r_ in v["addresses"])
        v["first"] = min([r_["first"] for r_ in v["addresses"] if r_["first"]] or [None], key=lambda x: x or 0) if any(r_["first"] for r_ in v["addresses"]) else None
        v["last"] = max([r_["last"] for r_ in v["addresses"] if r_["last"]] or [0]) or None
        res.append(v)
    res.sort(key=lambda v: (v["lead_only"], -(v["in_usd"] + v["out_usd"]), v["entity"].lower()))
    return res

def amounts(d): return ", ".join(f"{R.num(v)} {u}" for u, v in sorted(d.items(), key=lambda kv: -kv[1])) or "–"

# ---------------- draft request document (one structure -> TXT and DOCX) ----------------
def draft_blocks(v, le, case, gen):
    """list of (type, payload): h1/h2/p/box/bul/kv/tbl"""
    ent = v["entity"]; ph = lambda k, d: le.get(k) or f"[{d}]"
    B = [("banner", DRAFT_BANNER),
         ("h1", f"DRAFT request for customer and transaction records – {ent}"),
         ("box", "STATUS OF THIS DOCUMENT\nThis is an unsigned draft generated from a blockchain analysis. It is not an order of any court, has no legal effect, and must not be "
                 "served as it stands. The officer must review and complete it, choose the correct legal route, and serve it (or attach it to an application) through that route. "
                 "Take your own legal advice (force legal services / financial investigation unit / CPS) before use. " + NOT_OFFICIAL),
         ("h2", "1. Addressee"),
         ("kv", [("To", f"{ent} – law-enforcement response / compliance team"), ("Address / portal", "[officer to insert: the firm's published law-enforcement request route or registered address]"),
                 ("UK registration", "[officer to check the FCA register and state whether the firm is UK-registered: https://register.fca.org.uk/]")]),
         ("h2", "2. Requesting officer"),
         ("kv", [("Name", ph("officer_name", "officer name")), ("Rank / role", ph("officer_rank", "rank / role")), ("Collar / warrant no.", ph("officer_number", "collar / warrant number")),
                 ("Force / unit", ph("force", "force / unit")), ("Email", ph("officer_email", "official email")), ("Phone", ph("officer_phone", "phone")),
                 ("Date", "[date of service]")]),
         ("h2", "3. References"),
         ("kv", [("Force crime reference", ph("crime_ref", "crime / occurrence reference")), ("Report Fraud / Action Fraud ref", ph("rf_ref", "NFRC… reference if any")),
                 ("NFIB classification", ph("nfib_code", "NFIB code if known")), ("Victim / case reference", ph("victim_ref", "victim / case reference")),
                 ("Offence(s) under investigation", ph("offence", "offence(s) and statutory provision")), ("Period of interest", period_text(le)),
                 ("ChainTrace case", f"{case.get('name') or 'Untitled case'} (analysis generated {R.t_uk(gen)} / {R.t_utc(gen)})")]),
         ("h2", "4. Legal basis (officer to select ONE and delete the others)"),
         ("bul", [f"[ ] {t}: {d}" for t, d in ROUTES]),
         ("p", "Note: this draft is written for England, Wales and Northern Ireland. Procedures in Scotland differ. Legislation changes; check the current text on legislation.gov.uk."),
         ("h2", "5. Background"),
         ("p", le.get("facts") or "[officer to insert a short, factual summary of the case: what happened, when, the victim's loss, and why the firm's records are needed. "
                                   "Do not include more personal data than necessary.]"),
         ("p", f"Blockchain analysis indicates that funds connected with this investigation moved to or from the address(es) in Schedule A, which public label data "
               f"or the officer's own analysis associate with {ent}. "
               "This on-chain information is an intelligence lead from public blockchain records and third-party labels. It is not evidence on its own and must be "
               "corroborated by the firm's own records. If any address in Schedule A is not controlled by the firm, please say so."),
         ("h2", "Schedule A – identifiers held by the firm (from the ChainTrace case graph)"),
    ]
    rows = []
    for k, r in enumerate(v["addresses"], 1):
        rows.append([str(k), R.code(r["chain"]), r["address"], ", ".join(r["dtags"]) or "–", ", ".join(r["memos"]) or "–",
                     f"in: {amounts(r['in'])}\nout: {amounts(r['out'])}", (R.t_line(r["first"]) + "\n" + R.t_line(r["last"])) if r["first"] else "–",
                     r["role"] + ("\nSANCTIONS MATCH: " + "; ".join(r["sanctioned"]) if r["sanctioned"] else "") + ("\n" + R.LEAD if r["lead"] else "")])
    B.append(("tbl", (["#", "Chain", "Address", "Destination tag(s)", "Memo(s)", "Traced amounts", "First / last seen (UK, UTC)", "Basis"], rows)))
    B.append(("p", "Times are block times converted to UK local time (Europe/London) with UTC in brackets. Amounts are the flows visible in the case graph, which may be partial. "
                   "XRP destination tags usually identify the individual customer account at the receiving exchange."))
    txr = []
    for r in v["addresses"]:
        for t in r["txs"][:40]:
            txr.append([R.code(r["chain"]), t["tx"], "deposit to firm" if t["dir"] == "in" else "withdrawal from firm", f"{R.num(t['amount'])} {t['unit']}" + (f" (×{t['count']}, latest hash)" if t["count"] > 1 else ""),
                        R.t_line(t["time"]) if t["time"] else "–", t["cp"], "–" if t.get("dtag") is None else str(t["dtag"])])
    B.append(("h2", "Schedule B – transactions of interest"))
    B.append(("tbl", (["Chain", "Transaction hash", "Direction", "Amount", "Time (UK, UTC)", "Counterparty address", "Dest. tag"], txr or [["–"] * 7])))
    B.append(("h2", "Schedule C – material requested for the period of interest (" + period_text(le) + ")"))
    B.append(("p", "For each account that has held, used or been credited from the identifiers in Schedules A and B, please provide:"))
    B.append(("bul", [f"{t}: {d}" for t, d in REQUEST_ITEMS]))
    B.append(("p", "Please give times with their time zone, export transaction data in a machine-readable format (e.g. CSV) where possible, and include a short statement "
                   "identifying the person producing the records. [Officer: delete any item that is not necessary and proportionate for this investigation.]"))
    B.append(("h2", "6. Confidentiality"))
    B.append(("p", "[Officer to decide] The firm may be asked not to inform the customer of this request where that would prejudice the investigation. "
                   "Under POCA 2002 s.342 it can be an offence to make a disclosure likely to prejudice certain investigations; consider whether that applies and word this section accordingly."))
    B.append(("h2", "7. Signature"))
    B.append(("kv", [("Signed", "[officer signature]"), ("Name / rank / number", f"{ph('officer_name', 'name')} / {ph('officer_rank', 'rank')} / {ph('officer_number', 'number')}"),
                     ("Authorised by (if required)", "[supervising officer / authorising officer]"), ("Date", "[date]")]))
    B.append(("h2", "How to use this draft"))
    B.append(("bul", [
        "Check every address in Schedule A on a public explorer and remove any you cannot stand behind. Items marked as an intelligence lead are model inferences, not attributions.",
        "Pick the legal route in section 4 and delete the others. For a production order or other court order, use the schedules as the description of material in your "
        "application; the court, not this document, makes the order.",
        "For a firm outside the UK, check whether it accepts voluntary law-enforcement requests through its portal; evidence for court generally needs mutual legal assistance.",
        "Complete the placeholders in [square brackets], delete any request item that is not necessary and proportionate, and keep a copy with the PDF report and its SHA-256 hash.",
        "Treat the firm's returned records, not this analysis, as the evidence of account ownership.",
    ]))
    B.append(("h2", "Public sources used for the legal references"))
    B.append(("bul", [f"{t}: {u}" for t, u in SOURCES]))
    return B

def blocks_to_txt(B):
    out = []
    for t, x in B:
        if t == "banner": out += ["*" * 78, x.center(78), "*" * 78, ""]
        elif t == "h1": out += [x, "=" * min(78, len(x)), ""]
        elif t == "h2": out += ["", x, "-" * min(78, len(x))]
        elif t in ("p", "box"): out += [x, ""]
        elif t == "bul": out += [f"  - {i}" for i in x] + [""]
        elif t == "kv": out += [f"  {k}: {v}" for k, v in x] + [""]
        elif t == "tbl":
            hd, rows = x
            for r in rows:
                out.append("  " + " | ".join(f"{h}: {str(c).replace(chr(10), ' / ')}" for h, c in zip(hd, r) if c not in ("", None)))
            out.append("")
    out += ["", DRAFT_BANNER]
    return "\n".join(out).replace("\r", "") + "\n"

def blocks_to_docx(B):
    from docx import Document
    from docx.shared import Pt, RGBColor, Mm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    d = Document(); s = d.sections[0]; s.page_width, s.page_height = Mm(210), Mm(297)
    for m in ("left_margin", "right_margin"): setattr(s, m, Mm(16))
    st = d.styles["Normal"]; st.font.name = "Arial"; st.font.size = Pt(9.5)
    for part in (s.header, s.footer):
        p = part.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER; r = p.add_run(DRAFT_BANNER); r.bold = True; r.font.size = Pt(9); r.font.color.rgb = RGBColor(0xB0, 0x10, 0x20)
    for t, x in B:
        if t == "banner": continue
        if t == "h1": d.add_heading(x, level=1)
        elif t == "h2": d.add_heading(x, level=2)
        elif t == "p": d.add_paragraph(x)
        elif t == "box":
            tb = d.add_table(rows=1, cols=1); tb.style = "Table Grid"; c = tb.cell(0, 0); c.text = ""
            r = c.paragraphs[0].add_run(x); r.font.size = Pt(9); r.font.color.rgb = RGBColor(0x6B, 0x3C, 0x00); d.add_paragraph()
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
                for r in tb.rows[0].cells[j].paragraphs[0].runs: r.bold = True; r.font.size = Pt(8)
            for row in rows:
                cells = tb.add_row().cells
                for j, cval in enumerate(row):
                    cells[j].text = str(cval)
                    for p in cells[j].paragraphs:
                        for r in p.runs: r.font.size = Pt(7.5)
            d.add_paragraph()
    d.core_properties.title = "DRAFT request (not a court order)"; d.core_properties.author = "ChainTrace (draft for officer completion)"
    b = io.BytesIO(); d.save(b); return b.getvalue()

def schedule_csv(V):
    b = io.StringIO(); w = csv.writer(b)
    w.writerow(["vasp", "chain", "address", "label", "role", "basis", "intelligence_lead_only", "destination_tags", "memos", "traced_in", "traced_out",
                "traced_in_usd_trace_time", "traced_out_usd_trace_time", "first_seen_uk", "first_seen_utc", "last_seen_uk", "last_seen_utc", "tx_hashes", "sanctions_match"])
    for v in V:
        for r in v["addresses"]:
            w.writerow([v["entity"], r["chain"], r["address"], r.get("label") or "", r["role"], r["basis"], "yes" if r["lead"] else "no", ";".join(r["dtags"]), ";".join(r["memos"]),
                        amounts(r["in"]), amounts(r["out"]), round(r["in_usd"], 2), round(r["out_usd"], 2),
                        R.t_uk(r["first"]) if r["first"] else "", R.t_utc(r["first"]) if r["first"] else "", R.t_uk(r["last"]) if r["last"] else "", R.t_utc(r["last"]) if r["last"] else "",
                        ";".join(t["tx"] for t in r["txs"]), "; ".join(r["sanctioned"])])
    return b.getvalue().encode("utf-8-sig")

def how_to(le, V, info, gen, names):
    L = ["CHAINTRACE UK EVIDENCE PACK – HOW TO USE", "=" * 42, "",
         f"Generated: {R.t_uk(gen)} / {R.t_utc(gen)}   ChainTrace v{R.VERSION} (commit {R.COMMIT}), pack format {PACK_VERSION}", "",
         NOT_OFFICIAL, "",
         "Contents", "--------"] + [f"  {n}" for n in names] + ["",
         "1. The PDF report is the analysis. Its cover carries the SHA-256 of the case data, and case_data.json is embedded in it so the hash can be re-checked.",
         f"   PDF SHA-256: {info.get('pdf_sha256')}", f"   Case data SHA-256: {info.get('case_sha256')}",
         "   Record these hashes in your notes. SHA256SUMS.txt lists the hash of every file in this pack.",
         "2. vasp_drafts/ holds one DRAFT request per exchange / VASP (Word and plain text). Each is marked DRAFT – NOT A COURT ORDER on every page.",
         "   Complete the [square-bracket] placeholders, choose the legal route, delete anything not necessary and proportionate, and serve it through that route.",
         "   A production order is made by a judge on your application. These drafts are only the description of material and the request text.",
         "3. vasp_schedule.csv lists every exchange / VASP address in the graph with tags, memos, amounts, hashes and first/last seen (UK and UTC) for your own records or an application schedule.",
         "4. On-chain data and third-party labels are intelligence leads, not evidence. Items marked 'INFERRED' are ChainTrace model suggestions. Corroborate with the firm's own records.",
         "4a. victim_loss_summary.csv (only when a victim-loss summary was run) gives the total lost per asset (on the day and today, GBP and USD), where the funds went, what is still held and the hop-by-hop table. It states the tracing method used (proportional, FIFO or LIFO): quote that method with any figure.",
         "5. Overseas firms may need mutual legal assistance (Letter of Request via the Home Office UK Central Authority). Take your own legal advice before use.", "",
         f"Exchanges / VASPs found in this case: {len(V)}"]
    for v in V: L.append(f"  - {v['entity']}: {len(v['addresses'])} address(es)" + (" (inferred leads only)" if v["lead_only"] else ""))
    L += ["", "Investigator-entered fields (blank = not entered):"] + [f"  {lab}: {val or '–'}" for lab, val in le_rows(le) if lab != LE_FIELDS["facts"][0]]
    L += ["", "Public sources for the legal references:"] + [f"  - {t}: {u}" for t, u in SOURCES]
    return ("\n".join(L) + "\n").encode("utf-8")

def safe(s): return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")[:50] or "VASP"

async def build_pack(p):
    gen = time.time()
    meta = p.setdefault("meta", {}) if isinstance(p.get("meta"), dict) else p.setdefault("meta", {})
    le = clean_le(meta.get("le")); meta["le"] = le; meta["evidence_pack"] = True
    pdf, info = await R.build(p)
    V = vasp_schedule(p); case = p.get("case") or {}
    ref = safe(meta.get("ref") or le.get("crime_ref") or case.get("name") or "case")
    files = [(f"ChainTrace-report-{ref}.pdf", pdf)]
    for k, v in enumerate(V, 1):
        B = draft_blocks(v, le, case, gen); base = f"vasp_drafts/{k:02d}_{safe(v['entity'])}_DRAFT_request"
        try: files.append((base + ".docx", blocks_to_docx(B)))
        except Exception as ex: info.setdefault("notes", []).append(f"DOCX unavailable ({type(ex).__name__}); plain text only")
        files.append((base + ".txt", blocks_to_txt(B).encode("utf-8")))
    files.append(("vasp_schedule.csv", schedule_csv(V)))
    if info.get("loss") and info["loss"].get("csv"): files.append(("victim_loss_summary.csv", info["loss"]["csv"].encode("utf-8")))
    names = [n for n, _ in files] + ["HOW_TO_USE.txt", "SHA256SUMS.txt"]
    files.append(("HOW_TO_USE.txt", how_to(le, V, info, gen, names)))
    sums = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in files).encode()
    files.append(("SHA256SUMS.txt", sums))
    zb = io.BytesIO()
    dt = time.localtime(gen)[:6]
    with zipfile.ZipFile(zb, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files:
            zi = zipfile.ZipInfo(f"ChainTrace-evidence-pack-{ref}/{n}", date_time=dt); zi.compress_type = zipfile.ZIP_DEFLATED; z.writestr(zi, b)
    out = zb.getvalue()
    info = {k: v for k, v in info.items() if k != "loss"}
    return out, {**info, "zip_sha256": hashlib.sha256(out).hexdigest(), "vasps": [{"entity": v["entity"], "addresses": len(v["addresses"]), "lead_only": v["lead_only"]} for v in V],
                 "files": names, "ref": ref}
