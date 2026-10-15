import os
D = os.path.join(os.path.dirname(__file__), "data")
def _load(f):
    try: return {l.strip() for l in open(os.path.join(D, f)) if l.strip()}
    except FileNotFoundError: return set()
OFAC = {"btc": _load("ofac_XBT.txt"), "eth": {a.lower() for a in _load("ofac_ETH.txt")}, "sol": _load("ofac_SOL.txt")}
MIXERS_ETH = {  # Tornado Cash contracts (public)
 "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc":"Tornado Cash 0.1 ETH","0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936":"Tornado Cash 1 ETH",
 "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf":"Tornado Cash 10 ETH","0xa160cdab225685da1d56aa342ad8841c3b53f291":"Tornado Cash 100 ETH",
 "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b":"Tornado Cash Router","0xd96f2b1c14db8458374d9aca76e26c3d18364307":"Tornado Cash 100 DAI",
 "0x4736dcf1b7a3d580672cce6e7c65cd5cc9cfba9d":"Tornado Cash 10 DAI","0x722122df12d4e14e13ac3b6895a86e84145b6967":"Tornado Cash Proxy",
 "0x169ad27a470d064dede56a2d3ff727986b15d52b":"Tornado Cash 100 USDT","0x0836222f2b2b24a3f36f98668ed8f0b38d1a872f":"Tornado Cash 1000 USDT"}
EXCH = {"eth": {
 "0x28c6c06298d514db089934071355e5743bf21d60":"Binance 14","0x21a31ee1afc51d94c2efccaa2092ad1028285549":"Binance 15",
 "0xdfd5293d8e347dfe59e90efd55b2956a1343963d":"Binance 16","0x56eddb7aa87536c09ccc2793473599fd21a8b17f":"Binance 17",
 "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8":"Binance 7 (cold)","0xf977814e90da44bfa03b6295a0616a897441acec":"Binance 8",
 "0x71660c4005ba85c37ccec55d0c4493e66fe775d3":"Coinbase 1","0x503828976d22510aad0201ac7ec88293211d23da":"Coinbase 2",
 "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43":"Coinbase 10","0x2910543af39aba0cd09dbb2d50200b3e800a63d2":"Kraken 1",
 "0x267be1c1d684f78cb4f6a176c4911b741e4ffdc0":"Kraken 4","0x6cc5f688a315f3dc28a7781717a9a798a59fda7b":"OKX 1"},
 "btc": {"34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo":"Binance cold","bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h":"Binance",
 "3M219KR5vEneNb47ewrPfWyb5jQ2DjxRP6":"Binance","bc1qgdjqv0av3q56jvd82tkdjpy7gdp9ut8tlqmgrpmv24sq90ecnvqqjwvw97":"Bitfinex cold",
 "3LYJfcfHPXYJreMsASk2jkn69LWEYKzexb":"Binance"},
 "sol": {"5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9":"Binance 2","9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM":"Binance 1",
 "H8sMJSCQxfKiFTCfDR3DUMLPwcRbM61LGFJ8N4dK3WjS":"Coinbase 1","2AQdpHJ2JpcEgPiATUXjQxA8QmafFegfQwSLWSprPicm":"Coinbase 2",
 "FWznbcNXWQuHTawe9RxvQ2LdCENssh12dsznf4RiouN5":"Kraken"}}
def norm(chain, a): return a.lower() if chain == "eth" else a
import sqlite3, threading
LDB = os.path.join(D, "labels.sqlite")
RISK = {"sanctioned": 100, "terrorism": 95, "darknet": 85, "ransomware": 85, "hack": 80, "scam": 75, "mixer": 75, "blocklisted": 50,
        "gambling": 35, "exchange": 10, "bridge": 5, "defi": 3, "miner": 0, "other": 0}
EXPO = {"sanctioned": 60, "terrorism": 60, "darknet": 55, "ransomware": 55, "hack": 50, "scam": 50, "mixer": 45, "blocklisted": 30, "gambling": 20}
_tl = threading.local()
def _db():
    if not hasattr(_tl, "db") or _tl.db is None:
        # read-only, queried on disk via index; small page cache, no mmap -> low RAM
        _tl.db = sqlite3.connect(f"file:{LDB}?mode=ro", uri=True) if os.path.exists(LDB) else None
        if _tl.db: _tl.db.execute("PRAGMA cache_size=-2000"); _tl.db.execute("PRAGMA mmap_size=0")
    return _tl.db
def db_labels(chain, a):
    db = _db()
    if not db: return []
    return [dict(zip(("category","entity","name","source","source_url","licence","confidence"), r)) for r in
            db.execute("SELECT category,entity,name,source,source_url,licence,confidence FROM labels WHERE chain=? AND address=?", (chain, norm(chain, a)))]
def label(chain, a, extra_tags=None):
    k = norm(chain, a)
    if k in ("0x0000000000000000000000000000000000000000", "11111111111111111111111111111111"): return {"name": "null/system", "kind": None, "tags": [], "risk": 0, "sources": []}
    rows = db_labels(chain, a)
    old = _label_v1(chain, a, extra_tags)
    if not rows: return {**old, "sources": [{"source": "blockscout", "name": t, "licence": "Blockscout public API tags", "confidence": 0.6} for t in (extra_tags or [])][:4]}
    best = max(rows, key=lambda r: (RISK.get(r["category"], 0), r["confidence"]))
    kind = best["category"] if best["category"] != "other" else (old["kind"] or None)
    if old["kind"] and RISK.get(old["kind"], 0) > RISK.get(kind or "other", 0): kind = old["kind"]
    named = max(rows, key=lambda r: (r["category"] == best["category"], r["confidence"]))
    name = old["name"] if (old["name"] and best["category"] == "other") else (named["name"] or named["entity"] or old["name"])
    if name == "OFAC SDN listed":
        alt = [r["name"] or r["entity"] for r in rows if r["source"] != "ofac" and (r["name"] or r["entity"])]
        if alt: name = alt[0] + " (OFAC SDN)"
    tags = sorted({r["category"] for r in rows} | set(old["tags"]))
    return {"name": name, "kind": kind, "tags": tags, "risk": RISK.get(kind or "other", 0), "confidence": best["confidence"],
            "sources": [{k2: r[k2] for k2 in ("source","name","category","licence","source_url","confidence")} for r in rows][:8]}
def _label_v1(chain, a, extra_tags=None):
    k = norm(chain, a); tags = []; kind = None; name = None
    if k in ("0x0000000000000000000000000000000000000000", "11111111111111111111111111111111"): return {"name": "null/system", "kind": None, "tags": [], "risk": 0}
    if k in OFAC[chain]: tags.append("OFAC sanctioned"); kind = "sanctioned"
    if chain == "eth" and k in MIXERS_ETH: name = MIXERS_ETH[k]; tags.append("mixer"); kind = kind or "mixer"
    ex = EXCH.get(chain, {}).get(k)
    if ex: name = name or ex; tags.append("exchange"); kind = kind or "exchange"
    for t in (extra_tags or []):
        tl = t.lower()
        if "tornado" in tl or "mixer" in tl: kind = kind or "mixer"; tags.append("mixer")
        if tl in ("exchange", "hot wallet") or "binance" in tl or "coinbase" in tl: kind = kind or "exchange"
        if not name and t not in ("exchange","HOT WALLET","Exchange","Token Contract"): name = t
    base = {"sanctioned":100,"mixer":75,"exchange":10}.get(kind, 0)
    return {"name": name, "kind": kind, "tags": sorted(set(tags + (extra_tags or []))), "risk": base}
def score(own, neighbors):
    """own risk + exposure from direct counterparties."""
    exp = 0; reasons = []
    for n in neighbors:
        if n.get("kind") in EXPO:
            exp = max(exp, EXPO[n["kind"]]); reasons.append(f"direct exposure to {n['kind']} {n.get('name') or n['id'][:12]}")
    s = min(100, max(own["risk"], exp + (10 if own["kind"] == "exchange" else 0)))
    if own.get("kind") in EXPO or own.get("kind") in ("exchange","bridge","defi"):
        src = ", ".join(sorted({x["source"] for x in own.get("sources", [])})) or "label db"
        reasons.insert(0, f"address labelled {own['kind']} ({own.get('name') or ''}; source: {src})")
    lvl = "severe" if s >= 75 else "high" if s >= 45 else "medium" if s >= 20 else "low"
    return {"score": s, "level": lvl, "reasons": list(dict.fromkeys(reasons))[:8]}
