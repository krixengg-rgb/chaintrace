"""ChainTrace shareable read-only case links (v28).
A share link carries the whole snapshot as an encrypted, authenticated token in the URL fragment (#t=...): nothing is stored on the server,
and the fragment is never sent to the server by the browser. The viewer page posts the token to /api/share/open, which decrypts it
(AES-256-GCM, so any change is rejected), checks the expiry and returns the read-only snapshot with its SHA-256 audit hash.
Key: env SHARE_KEY, else derived from CHAINTRACE_PASSWORD with HKDF-SHA256 (changing either key revokes every link).
Case notes and private labels are excluded unless the user opts in."""
import base64, hashlib, json, os, time, zlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

VER = "v1"; AAD = b"chaintrace-share-v1"
TTLS = {"1h": 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
MAX_NODES, MAX_EDGES, MAX_TOKEN = 600, 2500, 900_000
NODE_KEYS = ("id", "chain", "name", "kind", "tags", "risk", "flag", "balance", "unit", "is_contract", "cluster")
EDGE_KEYS = ("source", "target", "amount", "unit", "tx", "time", "first", "last", "count", "usd", "flags", "xchain", "heur", "token", "bridge")
def canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
class ShareError(Exception):
    def __init__(self, msg, code=400): super().__init__(msg); self.code = code

def _key():
    k = (os.environ.get("SHARE_KEY") or "").strip()
    if k:
        try:
            raw = base64.urlsafe_b64decode(k + "=" * (-len(k) % 4))
            if len(raw) == 32: return raw
        except Exception: pass
        return hashlib.sha256(k.encode()).digest()
    pw = os.environ.get("CHAINTRACE_PASSWORD") or ""
    if not pw: raise ShareError("sharing is not configured (set SHARE_KEY or CHAINTRACE_PASSWORD)", 503)
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"chaintrace-share-key-v1", info=b"share-links").derive(pw.encode())
def key_source(): return "SHARE_KEY" if (os.environ.get("SHARE_KEY") or "").strip() else "derived from CHAINTRACE_PASSWORD"

def _node(n):
    o = {k: n[k] for k in NODE_KEYS if k in n and n[k] not in (None, "", [])}
    if n.get("sources"): o["sources"] = [{k: s.get(k) for k in ("source", "name", "category", "source_url") if s.get(k)} for s in n["sources"][:4] if isinstance(s, dict)]
    if n.get("sanctions"): o["sanctions"] = [{k: s.get(k) for k in ("short", "entry", "uid", "url", "wording") if s.get(k)} for s in n["sanctions"][:3] if isinstance(s, dict)]
    if isinstance(n.get("suggested"), dict): o["suggested"] = {k: n["suggested"].get(k) for k in ("label", "entity", "confidence") if n["suggested"].get(k) is not None}
    return o
def sanitize(p, include_notes=False, include_labels=False):
    """case payload (as built for the PDF) -> the snapshot that goes into the link. Returns (snapshot, excluded list)."""
    if not isinstance(p, dict): raise ShareError("body must be a JSON object")
    nodes = [n for n in (p.get("nodes") or []) if isinstance(n, dict) and n.get("id")]
    edges = [e for e in (p.get("edges") or []) if isinstance(e, dict) and e.get("source") and e.get("target")]
    if not nodes: raise ShareError("nothing to share: the graph is empty")
    if len(nodes) > MAX_NODES or len(edges) > MAX_EDGES: raise ShareError(f"graph too large to share as a link (max {MAX_NODES} nodes / {MAX_EDGES} edges); hide noise or split the case", 413)
    case = p.get("case") or {}; excl = []
    snap = {"case": {"name": str(case.get("name") or "Untitled case")[:120], "query": case.get("query"), "mode": case.get("mode")},
            "nodes": [_node(n) for n in nodes], "edges": [{k: e[k] for k in EDGE_KEYS if k in e and e[k] not in (None, "", [])} for e in edges]}
    notes = case.get("notes") or {}
    has_notes = bool((notes.get("case") if isinstance(notes, dict) else notes) or any((notes.get(k) or {}) for k in ("nodes", "edges")) if isinstance(notes, dict) else notes)
    if include_notes and has_notes: snap["notes"] = notes
    elif has_notes: excl.append("case notes")
    labs = case.get("labels") or {}
    if include_labels and labs: snap["labels"] = {k: {kk: v.get(kk) for kk in ("name", "kind", "note") if isinstance(v, dict) and v.get(kk)} for k, v in labs.items() if isinstance(v, dict)}
    elif labs: excl.append(f"{len(labs)} private label(s)")
    for k, nm in (("meta", "report details (reference, investigator, notes)"), ("log", "activity / audit log"), ("png", "graph image"), ("loss", "victim-loss details")):
        if p.get(k): excl.append(nm)
    return snap, excl

def make(p, ttl="7d", include_notes=False, include_labels=False, preview=False, now=None):
    secs = TTLS.get(str(ttl)) or (int(ttl) if str(ttl).isdigit() and 300 <= int(ttl) <= TTLS["30d"] else None)
    if not secs: raise ShareError("expiry must be one of " + ", ".join(TTLS))
    snap, excl = sanitize(p, include_notes, include_labels)
    h = hashlib.sha256(canon(snap)).hexdigest(); iat = int(now or time.time()); exp = iat + secs
    info = {"audit_sha256": h, "issued": iat, "expires": exp, "nodes": len(snap["nodes"]), "edges": len(snap["edges"]), "excluded": excl,
            "included": ["graph (addresses, transactions, amounts, public labels)"] + (["case notes"] if "notes" in snap else []) + (["private labels"] if "labels" in snap else []),
            "key": key_source(), "read_only": True}
    body = zlib.compress(canon({"v": VER, "iat": iat, "exp": exp, "sha256": h, "snap": snap}), 9)
    info["bytes"] = len(body)
    if preview: return info
    nonce = os.urandom(12)
    tok = VER + "." + base64.urlsafe_b64encode(nonce + AESGCM(_key()).encrypt(nonce, body, AAD)).decode().rstrip("=")
    if len(tok) > MAX_TOKEN: raise ShareError("snapshot too large for a link; hide noise or split the case", 413)
    return {**info, "token": tok}

def open_token(tok, now=None):
    tok = (tok or "").strip()
    if not tok.startswith(VER + ".") or len(tok) > MAX_TOKEN + 100: raise ShareError("not a ChainTrace share link")
    try:
        raw = base64.urlsafe_b64decode(tok[3:] + "=" * (-len(tok[3:]) % 4))
        body = AESGCM(_key()).decrypt(raw[:12], raw[12:], AAD)
        d = json.loads(zlib.decompress(body))
    except ShareError: raise
    except Exception: raise ShareError("link is invalid, was altered, or was made with a different key (links are revoked when the key changes)", 400)
    if (now or time.time()) > d["exp"]: raise ShareError(f"this shared snapshot expired on {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(d['exp']))}", 410)
    ok = hashlib.sha256(canon(d["snap"])).hexdigest() == d["sha256"]
    return {"snapshot": d["snap"], "issued": d["iat"], "expires": d["exp"], "audit_sha256": d["sha256"], "hash_ok": ok, "read_only": True}
