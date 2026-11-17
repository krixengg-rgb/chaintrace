"""Case audit log (static/casenotes.js) server side: hash-chain verification identical to the browser's, signed anchor receipts,
and CSV / table helpers for the PDF report and evidence pack.
Entry hash = sha256(JSON.stringify([seq, t, actor, action, target, detail, prev])) - compact JSON, UTF-8, keys in insertion order.
Receipts: HMAC-SHA256 over "chaintrace-audit-anchor-v1|case_id|seq|head|t" with env AUDIT_KEY (or, if unset, a key derived
from CHAINTRACE_PASSWORD; changing the password then invalidates older receipts). The key is never returned or logged."""
import csv, hashlib, hmac, io, json, os, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
ZERO = "0" * 64
UK = ZoneInfo("Europe/London")

def entry_hash(e):
    s = json.dumps([e.get("seq"), e.get("t"), e.get("actor"), e.get("action"), e.get("target"), e.get("detail"), e.get("prev")], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8", "surrogatepass")).hexdigest()

def verify(entries):
    """-> {ok, n, head, at?, why?}"""
    prev = ZERO; entries = [e for e in (entries or []) if isinstance(e, dict)]
    for i, e in enumerate(entries):
        if e.get("prev") != prev or e.get("seq") != i + 1: return {"ok": False, "n": len(entries), "at": e.get("seq") or i + 1, "why": "sequence/link broken"}
        try: h = entry_hash(e)
        except Exception: return {"ok": False, "n": len(entries), "at": e.get("seq"), "why": "entry not hashable"}
        if h != e.get("h"): return {"ok": False, "n": len(entries), "at": e.get("seq"), "why": "entry altered"}
        prev = h
    return {"ok": True, "n": len(entries), "head": prev if entries else None}

def _key():
    k = os.environ.get("AUDIT_KEY")
    if k and len(k) >= 16: return hashlib.sha256(b"chaintrace-audit-key|" + k.encode()).digest()
    pw = os.environ.get("CHAINTRACE_PASSWORD") or ""
    if not pw: return None
    return hashlib.sha256(b"chaintrace-audit-key-from-password|" + pw.encode()).digest()

def _msg(case_id, seq, head, t): return f"chaintrace-audit-anchor-v1|{case_id}|{int(seq)}|{head}|{int(t)}".encode()

def anchor(case_id, seq, head):
    k = _key()
    if not k: raise RuntimeError("anchoring is not configured on this server (set AUDIT_KEY)")
    if not isinstance(case_id, str) or not case_id or len(case_id) > 80: raise ValueError("case_id required")
    if not isinstance(head, str) or len(head) != 64 or any(c not in "0123456789abcdef" for c in head): raise ValueError("head must be a sha256 hex digest")
    if not isinstance(seq, int) or seq < 1: raise ValueError("seq must be a positive integer")
    t = int(time.time())
    return {"v": 1, "case_id": case_id, "seq": seq, "head": head, "t": t, "sig": hmac.new(k, _msg(case_id, seq, head, t), hashlib.sha256).hexdigest(),
            "alg": "HMAC-SHA256", "server": "ChainTrace"}

def check_receipt(r):
    k = _key()
    if not k or not isinstance(r, dict): return False
    try: m = _msg(r["case_id"], r["seq"], r["head"], r["t"])
    except Exception: return False
    return hmac.compare_digest(hmac.new(k, m, hashlib.sha256).hexdigest(), str(r.get("sig") or ""))

def t_both(ms):
    if not ms: return "–"
    ts = ms / 1000
    return datetime.fromtimestamp(ts, UK).strftime("%d/%m/%Y %H:%M:%S %Z") + " / " + datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S UTC")

def detail_txt(d): return " · ".join(f"{k}: {v}" for k, v in (d or {}).items()) if isinstance(d, dict) else str(d or "")

def audit_csv(entries):
    b = io.StringIO(); w = csv.writer(b)
    w.writerow(["seq", "time_uk_utc", "actor", "action", "target", "detail", "prev_sha256", "sha256"])
    for e in entries or []:
        if isinstance(e, dict): w.writerow([e.get("seq"), t_both(e.get("t")), e.get("actor"), e.get("action"), e.get("target"), json.dumps(e.get("detail"), ensure_ascii=False), e.get("prev"), e.get("h")])
    return ("\ufeff" + b.getvalue()).encode("utf-8")

def notes_csv(journal):
    b = io.StringIO(); w = csv.writer(b)
    w.writerow(["time_uk_utc", "author", "on", "target", "tags", "status", "revisions", "text", "earlier_versions"])
    for e in sorted([x for x in journal or [] if isinstance(x, dict)], key=lambda x: x.get("t") or 0):
        st = ("deleted " + t_both((e.get("deleted") or {}).get("t"))) if e.get("deleted") else ("edited " + t_both(e.get("edited"))) if e.get("edited") else ""
        w.writerow([t_both(e.get("t")), e.get("author"), {"case": "case", "nodes": "address", "edges": "flow"}.get(e.get("kind"), e.get("kind")), e.get("target") or "",
                    "; ".join(map(str, e.get("tags") or [])), st, len(e.get("rev") or []), e.get("text"),
                    " || ".join(f"{t_both(r.get('t'))} {r.get('author')}: {r.get('text')}" for r in (e.get("rev") or []) if isinstance(r, dict))])
    return ("\ufeff" + b.getvalue()).encode("utf-8")
