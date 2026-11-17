"""Litecoin, Dogecoin and Bitcoin Cash: address validation / normalisation and keyless data sources.
Graph ids are chain-prefixed like the EVM L2s: "ltc:L…", "doge:D…", "bch:q…" (Bitcoin Cash in CashAddr form without the
"bitcoincash:" prefix; legacy 1…/3… BCH addresses are converted). Transactions are "tx:<hash>" with the chain on the node.
Sources (public, no key), tried in order, results normalised to one shape:
  LTC  : Blockbook (blockbook.ltc.zelcore.io, litecoin.atomicwallet.io) -> litecoinspace.org (Esplora)
  DOGE : Blockbook (blockbook.doge.zelcore.io) -> BlockCypher (keyless: ~3 req/s, ~100 req/h per IP)
  BCH  : Blockbook (blockbook.bch.zelcore.io) -> Blockchain.com Haskoin store
All three are UTXO chains with 8 decimals; the Bitcoin common-input-ownership heuristic applies (it is a lead, not proof)."""
import asyncio, hashlib, re, time
from datetime import datetime
import addrutil

CHAINS = ("ltc", "doge", "bch")
UNIT = {"ltc": "LTC", "doge": "DOGE", "bch": "BCH"}
NAME = {"ltc": "Litecoin", "doge": "Dogecoin", "bch": "Bitcoin Cash"}
EXPLORER = {"ltc": ("https://litecoinspace.org/tx/", "https://litecoinspace.org/address/"),
            "doge": ("https://blockchair.com/dogecoin/transaction/", "https://blockchair.com/dogecoin/address/"),
            "bch": ("https://blockchair.com/bitcoin-cash/transaction/", "https://blockchair.com/bitcoin-cash/address/")}
BLOCKBOOK = {"ltc": ["https://blockbook.ltc.zelcore.io/api/v2", "https://litecoin.atomicwallet.io/api/v2"],
             "doge": ["https://blockbook.doge.zelcore.io/api/v2"], "bch": ["https://blockbook.bch.zelcore.io/api/v2"]}
LTC_ESPLORA = "https://litecoinspace.org/api"
BCY = "https://api.blockcypher.com/v1/doge/main"
HASKOIN = "https://api.blockchain.info/haskoin-store/bch"
PAGE = 25

# ---------------- address formats ----------------
B32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
def _b58ver(a):
    try:
        raw = addrutil.b58decode(a)
        return raw[0] if len(raw) == 25 and addrutil._chk(raw[:21]) == raw[21:] else None
    except Exception: return None
def _bech32_ok(a, hrp):
    a = a.lower()
    if not a.startswith(hrp + "1") or len(a) > 90: return False
    try: data = [B32.index(c) for c in a[len(hrp) + 1:]]
    except ValueError: return False
    gen = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]; chk = 1
    for v in [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp] + data:
        b = chk >> 25; chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5): chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk in (1, 0x2bc830a3)
def _cash_polymod(v):
    c = 1
    for d in v:
        c0 = c >> 35; c = ((c & 0x07ffffffff) << 5) ^ d
        for i, g in enumerate((0x98f2bc8e61, 0x79b76d99e2, 0xf33e5fb3c4, 0xae2eabe2a8, 0x1e4f43e470)):
            if (c0 >> i) & 1: c ^= g
    return c ^ 1
_PFX = [ord(x) & 31 for x in "bitcoincash"] + [0]
def _bits(data, f, t, pad):
    acc = bits = 0; out = []; mx = (1 << t) - 1
    for v in data:
        acc = (acc << f) | v; bits += f
        while bits >= t: bits -= t; out.append((acc >> bits) & mx)
    if pad and bits: out.append((acc << (t - bits)) & mx)
    elif not pad and (bits >= f or ((acc << (t - bits)) & mx)): return None
    return out
def cash_decode(a):
    """'bitcoincash:q…' or 'q…' -> (type 0=P2PKH/1=P2SH, hash20) or None"""
    s = a.strip(); s = s.split(":", 1)[1] if s.lower().startswith("bitcoincash:") else s
    if s != s.lower() and s != s.upper(): return None
    s = s.lower()
    if not re.fullmatch(r"[qp][02-9ac-hj-np-z]{41}", s): return None
    try: data = [B32.index(c) for c in s]
    except ValueError: return None
    if _cash_polymod(_PFX + data) != 0: return None
    raw = _bits(data[:-8], 5, 8, False)
    if not raw or len(raw) != 21: return None
    return raw[0] >> 3, bytes(raw[1:])
def cash_encode(typ, h20):
    data = _bits([typ << 3] + list(h20), 8, 5, True)
    pm = _cash_polymod(_PFX + data + [0] * 8)
    return "".join(B32[d] for d in data + [(pm >> 5 * (7 - i)) & 31 for i in range(8)])
def legacy_to_cash(a):
    raw = addrutil.b58decode(a)
    if len(raw) != 25 or addrutil._chk(raw[:21]) != raw[21:] or raw[0] not in (0, 5): return None
    return cash_encode(0 if raw[0] == 0 else 1, raw[1:21])
def cash_to_legacy(a):
    d = cash_decode(a)
    if not d: return None
    p = bytes([0 if d[0] == 0 else 5]) + d[1]; return addrutil.b58encode(p + addrutil._chk(p))

def detect_addr(a, hint=None):
    """-> chain or None for a bare LTC / DOGE / BCH address (legacy 1…/3… only with hint)"""
    a = (a or "").strip()
    if a.lower().startswith("ltc1"): return "ltc" if _bech32_ok(a, "ltc") else None
    if a.lower().startswith("bitcoincash:") or re.fullmatch(r"[qpQP][02-9ac-hj-np-zAC-HJ-NP-Z]{41}", a): return "bch" if cash_decode(a) else None
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{26,35}", a): return None
    v = _b58ver(a)
    if v in (0x30, 0x32): return "ltc"
    if v in (0x1e, 0x16): return "doge"
    if v == 0x05 and hint == "ltc": return "ltc"           # old-style LTC P2SH (same version byte as BTC)
    if v in (0x00, 0x05) and hint == "bch": return "bch"   # legacy-format BCH
    return None
def validate(chain, a):
    """-> error string or None"""
    b = bare(chain, a)
    if chain == "bch":
        return None if (cash_decode(b) or (_b58ver(b) in (0, 5))) else "invalid Bitcoin Cash address (CashAddr or legacy checksum)"
    return None if detect_addr(b, chain) == chain else f"invalid {NAME[chain]} address checksum"
def bare(chain, a):
    a = (a or "").strip()
    if a.startswith(chain + ":"): a = a[len(chain) + 1:]
    if chain == "bch":
        if a.lower().startswith("bitcoincash:"): a = a.split(":", 1)[1]
        if re.fullmatch(r"[13][1-9A-HJ-NP-Za-km-z]{25,34}", a): a = legacy_to_cash(a) or a
        return a.lower() if cash_decode(a) else a
    if chain == "ltc" and a.lower().startswith("ltc1"): return a.lower()
    return a
def nid(chain, a): return f"{chain}:{bare(chain, a)}"
def api_addr(chain, a):
    b = bare(chain, a); return "bitcoincash:" + b if chain == "bch" and cash_decode(b) else b

# ---------------- sources -> normalised tx {txid, ins{addr:sat}, outs{addr:sat}, time, fee, confirmed} ----------------
def _add(m, a, v):
    if a: m[a] = m.get(a, 0) + int(v or 0)
def _norm_bb(t, chain):
    ins, outs = {}, {}
    for v in t.get("vin") or []:
        ad = (v.get("addresses") or [None])[0] if v.get("isAddress", True) else None
        if not ad and (v.get("coinbase") or not v.get("txid")): ad = "coinbase"
        if ad: _add(ins, ad if ad == "coinbase" else nid(chain, ad), v.get("value"))
    for o in t.get("vout") or []:
        ad = (o.get("addresses") or [None])[0] if o.get("isAddress", True) else None
        if ad and not ad.startswith("OP_RETURN"): _add(outs, nid(chain, ad), o.get("value"))
    return {"txid": t["txid"], "ins": ins, "outs": outs, "time": t.get("blockTime") if (t.get("blockHeight") or 0) > 0 else None,
            "fee": int(t.get("fees") or 0), "confirmed": (t.get("confirmations") or 0) > 0}
def _norm_es(t, chain):
    ins, outs = {}, {}
    for v in t.get("vin") or []:
        ad = (v.get("prevout") or {}).get("scriptpubkey_address") or ("coinbase" if v.get("is_coinbase") else None)
        if ad: _add(ins, ad if ad == "coinbase" else nid(chain, ad), (v.get("prevout") or {}).get("value"))
    for o in t.get("vout") or []:
        if o.get("scriptpubkey_address"): _add(outs, nid(chain, o["scriptpubkey_address"]), o.get("value"))
    st = t.get("status") or {}
    return {"txid": t["txid"], "ins": ins, "outs": outs, "time": st.get("block_time"), "fee": int(t.get("fee") or 0), "confirmed": bool(st.get("confirmed"))}
def _iso(s):
    try: return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()) if s else None
    except Exception: return None
def _norm_bcy(t, chain):
    ins, outs = {}, {}
    for v in t.get("inputs") or []:
        ad = (v.get("addresses") or [None])[0] or ("coinbase" if not v.get("prev_hash") else None)
        if ad: _add(ins, ad if ad == "coinbase" else nid(chain, ad), v.get("output_value"))
    for o in t.get("outputs") or []:
        ad = (o.get("addresses") or [None])[0]
        if ad: _add(outs, nid(chain, ad), o.get("value"))
    return {"txid": t["hash"], "ins": ins, "outs": outs, "time": _iso(t.get("confirmed")), "fee": int(t.get("fees") or 0), "confirmed": (t.get("block_height") or -1) > 0,
            "height": t.get("block_height")}
def _norm_hk(t, chain):
    ins, outs = {}, {}
    for v in t.get("inputs") or []:
        ad = "coinbase" if v.get("coinbase") else v.get("address")
        if ad: _add(ins, ad if ad == "coinbase" else nid(chain, ad), v.get("value"))
    for o in t.get("outputs") or []:
        if o.get("address"): _add(outs, nid(chain, o["address"]), o.get("value"))
    conf = bool((t.get("block") or {}).get("height"))
    return {"txid": t["txid"], "ins": ins, "outs": outs, "time": t.get("time") if conf else None, "fee": int(t.get("fee") or 0), "confirmed": conf}

async def _first(chain, tries):
    """run source coroutines in order; return (source, result) of the first that works"""
    import chains
    errs = []
    for name, fn in tries:
        try: return name, await fn()
        except Exception as e: errs.append(f"{name}: {type(e).__name__}{(' ' + str(e)[:60]) if str(e) else ''}")
    chains._warn(f"{chain}: all sources failed ({'; '.join(errs)})")
    raise Exception(f"{NAME[chain]} data sources unavailable ({'; '.join(errs)[:200]})")

async def page(chain, a, cursor=None):
    """-> {balance?, tx_count?, txs[normalised], next, source}"""
    import chains
    q = api_addr(chain, a)
    src, page_ = (cursor.split(":", 1) if cursor and ":" in cursor else (None, cursor))
    def bb(base):
        async def f():
            p = int(page_ or 1) if src in (None, "bb") else 1
            d = await chains.get(f"{base}/address/{q}?details=txs&pageSize={PAGE}&page={p}", ttl=900 if p == 1 else chains.LONG)
            txs = d.get("transactions") or (d.get("txs") if isinstance(d.get("txs"), list) else None) or []
            return {"balance": (int(d.get("balance") or 0) + int(d.get("unconfirmedBalance") or 0)) / 1e8, "tx_count": d["txs"] if isinstance(d.get("txs"), int) else d.get("txApperances"),
                    "txs": [_norm_bb(t, chain) for t in txs], "next": f"bb:{p + 1}" if p < int(d.get("totalPages") or 1) else None, "pages": d.get("totalPages")}
        return f
    tries = []
    if src in (None, "bb"): tries += [(f"blockbook {b.split('/')[2]}", bb(b)) for b in BLOCKBOOK[chain]]
    if chain == "ltc" and src in (None, "es"):
        async def es():
            info = None
            if not page_ or src is None: info = await chains.get(f"{LTC_ESPLORA}/address/{q}", ttl=900)
            txs = await chains.get(f"{LTC_ESPLORA}/address/{q}/txs" + (f"/chain/{page_}" if src == "es" and page_ else ""), ttl=900)
            conf = [t for t in txs if (t.get("status") or {}).get("confirmed")]
            out = {"txs": [_norm_es(t, chain) for t in txs], "next": f"es:{conf[-1]['txid']}" if len(conf) >= 25 else None}
            if info: cs, ms = info["chain_stats"], info["mempool_stats"]; out.update(balance=(cs["funded_txo_sum"] - cs["spent_txo_sum"] + ms["funded_txo_sum"] - ms["spent_txo_sum"]) / 1e8, tx_count=cs["tx_count"] + ms["tx_count"])
            return out
        tries.append(("litecoinspace", es))
    if chain == "doge" and src in (None, "bc"):
        async def bcy():
            d = await chains.get(f"{BCY}/addrs/{q}/full?limit=25" + (f"&before={page_}" if src == "bc" and page_ else ""), ttl=900)
            txs = [_norm_bcy(t, chain) for t in d.get("txs") or []]
            hs = [t["height"] for t in txs if t.get("height") and t["height"] > 0]
            return {"balance": (d.get("final_balance") or 0) / 1e8, "tx_count": d.get("final_n_tx"), "txs": txs, "next": f"bc:{min(hs)}" if d.get("hasMore") and hs else None}
        tries.append(("blockcypher", bcy))
    if chain == "bch" and src in (None, "hk"):
        async def hk():
            off = int(page_ or 0) if src == "hk" else 0
            bal = await chains.get(f"{HASKOIN}/address/{q}/balance", ttl=900) if not off else {}
            txs = await chains.get(f"{HASKOIN}/address/{q}/transactions/full?limit=25&offset={off}", ttl=900 if not off else chains.LONG)
            out = {"txs": [_norm_hk(t, chain) for t in txs], "next": f"hk:{off + 25}" if len(txs) >= 25 else None}
            if bal: out.update(balance=((bal.get("confirmed") or 0) + (bal.get("unconfirmed") or 0)) / 1e8, tx_count=bal.get("txs"))
            return out
        tries.append(("haskoin", hk))
    name, r = await _first(chain, tries); r["source"] = name; return r

async def tx(chain, h):
    import chains
    h = h.strip().removeprefix("tx:")
    if h.startswith(chain + ":"): h = h[len(chain) + 1:]
    h = h.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", h): raise ValueError("not a transaction hash")
    tries = [(f"blockbook {b.split('/')[2]}", (lambda b=b: _bbtx(b, h, chain))) for b in BLOCKBOOK[chain]]
    if chain == "ltc": tries.append(("litecoinspace", lambda: _wrap(chains.get(f"{LTC_ESPLORA}/tx/{h}", ttl=chains.LONG), _norm_es, chain)))
    if chain == "doge": tries.append(("blockcypher", lambda: _wrap(chains.get(f"{BCY}/txs/{h}?limit=100", ttl=chains.LONG), _norm_bcy, chain)))
    if chain == "bch": tries.append(("haskoin", lambda: _wrap(chains.get(f"{HASKOIN}/transaction/{h}", ttl=chains.LONG), _norm_hk, chain)))
    name, t = await _first(chain, tries); t["source"] = name; return t
async def _bbtx(base, h, chain):
    import chains
    return _norm_bb(await chains.get(f"{base}/tx/{h}", ttl=86400 * 30), chain)
async def _wrap(co, norm, chain): return norm(await co, chain)

async def balance(chain, a):
    try: return (await page(chain, a)).get("balance")
    except Exception: return None
