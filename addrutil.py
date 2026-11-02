"""Base58check helpers for TRON and XRP Ledger address detection / conversion."""
import hashlib, re

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
R58 = "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"

def b58decode(s, alphabet=B58):
    n = 0
    for c in s:
        i = alphabet.find(c)
        if i < 0: raise ValueError("bad base58 char")
        n = n * 58 + i
    h = n.to_bytes((n.bit_length() + 7) // 8 or 1, "big")
    pad = len(s) - len(s.lstrip(alphabet[0]))
    return b"\0" * pad + h

def b58encode(b, alphabet=B58):
    n = int.from_bytes(b, "big"); out = []
    while n:
        n, r = divmod(n, 58); out.append(alphabet[r])
    pad = len(b) - len(b.lstrip(b"\0"))
    return alphabet[0] * pad + "".join(reversed(out) or alphabet[0])

def _chk(payload):
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]

def tron_hex_to_b58(h):
    """41… hex (21 bytes) -> T… base58check"""
    h = h[2:] if h.startswith("0x") else h
    raw = bytes.fromhex(h)
    if len(raw) != 21 or raw[0] != 0x41: raise ValueError("not a TRON address hex")
    return b58encode(raw + _chk(raw))

def tron_b58_to_hex(a):
    raw = b58decode(a)
    if len(raw) != 25 or raw[0] != 0x41 or _chk(raw[:21]) != raw[21:]: raise ValueError("bad TRON address")
    return raw[:21].hex()

def is_tron_address(a):
    a = (a or "").strip()
    if re.fullmatch(r"41[0-9a-fA-F]{40}", a):
        try: tron_hex_to_b58(a); return True
        except Exception: return False
    if not (a.startswith("T") and len(a) == 34): return False
    try:
        raw = b58decode(a)
        return len(raw) == 25 and raw[0] == 0x41 and _chk(raw[:21]) == raw[21:]
    except Exception: return False

def norm_tron(a):
    a = (a or "").strip()
    if re.fullmatch(r"41[0-9a-fA-F]{40}", a): return tron_hex_to_b58(a)
    if is_tron_address(a): return a
    raise ValueError("not a TRON address")

def is_xrp_address(a):
    """Classic r… address (X-address optional later). Ripple alphabet + checksum."""
    a = (a or "").strip()
    if not a.startswith("r") or not (25 <= len(a) <= 35): return False
    if any(c not in R58 for c in a): return False
    try:
        raw = b58decode(a, R58)
        return len(raw) >= 5 and _chk(raw[:-4]) == raw[-4:]
    except Exception: return False
