"""Bulk import of addresses / transaction hashes from CSV or a pasted list (validated server-side, nothing stored).
Input: CSV with a header (value|address|tx|hash|id, optional chain, label, role, notes) or a plain list (one per line; an optional
second/third/fourth field after a comma / tab / semicolon is read as label, role, notes). Chain is detected from the format and
checksums are verified where the format has one (Bitcoin Base58/Bech32, TRON, XRP, EIP-55 mixed-case EVM, Solana length).
0x values are EVM-ambiguous: a chain column (or 'base:0x…' prefix) picks the chain, otherwise Ethereum is assumed (flagged)."""
import csv, io, re
import chains, evmcfg

MAX_ROWS = 500
MAX_BYTES = 256 * 1024
ROLES = {"victim": "victim", "v": "victim", "suspect": "suspect", "s": "suspect", "exchange": "exchange", "vasp": "exchange", "x": "exchange",
         "other": "other", "": ""}
VCOLS = ("value", "address", "addr", "wallet", "tx", "txid", "hash", "tx_hash", "transaction", "id")
CHAIN_ALIASES = {"bitcoin": "btc", "btc": "btc", "xbt": "btc", "ethereum": "eth", "eth": "eth", "erc20": "eth", "solana": "sol", "sol": "sol",
                 "tron": "tron", "trx": "tron", "trc20": "tron", "xrp": "xrp", "ripple": "xrp", "bsc": "bsc", "bnb": "bsc", "bep20": "bsc",
                 "arbitrum": "arb", "arb": "arb", "base": "base", "polygon": "polygon", "matic": "polygon", "pol": "polygon", "optimism": "op", "op": "op",
                 "litecoin": "ltc", "ltc": "ltc", "dogecoin": "doge", "doge": "doge", "bitcoin cash": "bch", "bitcoincash": "bch", "bch": "bch"}

def _checksum_ok(chain, kind, v):
    """-> error string or None"""
    import update_sanctions as us
    if kind != "address": return None
    if chain in chains.EVM:
        b = evmcfg.bare(v)
        if b != b.lower() and b != b.upper():
            from keccak import to_checksum
            if to_checksum(b) != b: return "EIP-55 checksum mismatch (mixed-case address with a typo?)"
        return None
    if chain == "btc": return None if us.is_btc(v) else "invalid Bitcoin address checksum"
    if chain == "sol": return None if us.is_sol(v) else "not a valid Solana address (must decode to 32 bytes)"
    v_ = getattr(chains, "validate_address", None)   # chains that ship their own validator (e.g. LTC / DOGE / BCH)
    if v_:
        e = v_(chain, v)
        if e: return e
    return None

def canon_id(chain, kind, v):
    if kind == "tx":
        h = evmcfg.bare(v).removeprefix("tx:")
        if chain in chains.EVM: h = (h if h.startswith("0x") else "0x" + h).lower()
        return "tx:" + h
    if chain in chains.EVM:
        from keccak import to_checksum
        b = to_checksum(evmcfg.bare(v)); return evmcfg.nid(chain, b)
    norm = getattr(chains, "norm_address", None)
    return norm(chain, v) if norm else v

def _rows(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    lines = [l for l in text.split("\n") if l.strip() and not l.lstrip().startswith("#")]
    if not lines: return [], None
    first = lines[0]
    delim = "\t" if "\t" in first else ";" if first.count(";") > first.count(",") else ","
    rd = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim, skipinitialspace=True))
    head = [h.strip().lower().replace(" ", "_") for h in rd[0]]
    if any(h in VCOLS for h in head):
        vi = next(i for i, h in enumerate(head) if h in VCOLS)
        col = lambda names: next((i for i, h in enumerate(head) if h in names), None)
        ci, li, ri, ni = col(("chain", "network", "blockchain", "asset")), col(("label", "name", "entity")), col(("role", "type", "category")), col(("notes", "note", "comment", "comments", "description"))
        g = lambda r, i: (r[i].strip() if i is not None and i < len(r) else "")
        return [(n + 2, g(r, vi), g(r, ci), g(r, li), g(r, ri), g(r, ni)) for n, r in enumerate(rd[1:])], "csv"
    out = []
    for n, l in enumerate(lines):   # plain list: value[, label[, role[, notes]]] - each line split on its own tab / comma / semicolon
        r = [x.strip().strip('"') for x in re.split(r"\t|;|,", l, maxsplit=3)] + ["", "", ""]
        out.append((n + 1, r[0], "", r[1], r[2], ",".join(x for x in r[3:] if x)))
    return out, "list"

def parse(text):
    if len(text.encode("utf-8", "ignore")) > MAX_BYTES: raise ValueError(f"input too large (max {MAX_BYTES // 1024} KB)")
    raw, fmt = _rows(text)
    capped = len(raw) > MAX_ROWS; raw = raw[:MAX_ROWS]
    seen = {}; rows = []
    for line, val, ch, lab, role, notes in raw:
        r = {"row": line, "value": val[:200], "label": lab[:120], "notes": notes[:2000], "role": "", "chain": None, "kind": None, "id": None, "status": "ok", "error": None, "warnings": []}
        rk = role.strip().lower()
        if rk not in ROLES: r["warnings"].append(f"unknown role '{role[:20]}' ignored (use victim, suspect, exchange or other)")
        else: r["role"] = ROLES[rk]
        if not val: r.update(status="error", error="empty value"); rows.append(r); continue
        want = CHAIN_ALIASES.get(ch.strip().lower()) if ch else None
        if ch and not want: r["warnings"].append(f"unknown chain '{ch[:20]}': detected from the format instead")
        v = val.strip().strip('"').strip("'")
        if want and want in chains.EVM and want != "eth" and re.fullmatch(r"(tx:)?0x[0-9a-fA-F]{40}|(tx:)?0x[0-9a-fA-F]{64}", v): v = f"{want}:{v}"
        c, k = chains.detect(v, want if want and want not in chains.EVM else None)
        if want and c and want != c and not (want in chains.EVM and c in chains.EVM):
            c2, k2 = chains.detect(v, want)
            if c2 == want: c, k = c2, k2
            else: r["warnings"].append(f"chain column says {want} but the value looks like {c}: using {c}")
        if not c: r.update(status="error", error="not a recognised address or transaction hash"); rows.append(r); continue
        err = _checksum_ok(c, k, v)
        if err: r.update(status="error", error=err, chain=c, kind=k); rows.append(r); continue
        if c == "eth" and v.lower().startswith("0x") and not want and not evmcfg.split(v)[0]:
            r["warnings"].append("0x value: assumed Ethereum (add a chain column or a 'base:' / 'bsc:' … prefix for another EVM chain)")
        r.update(chain=c, kind=k, id=canon_id(c, k, v))
        key = (c, r["id"].lower() if c in chains.EVM or k == "tx" else r["id"])
        if key in seen: r.update(status="duplicate", error=f"duplicate of row {seen[key]}")
        else: seen[key] = line
        rows.append(r)
    s = {"rows": len(rows), "ok": sum(r["status"] == "ok" for r in rows), "errors": sum(r["status"] == "error" for r in rows),
         "duplicates": sum(r["status"] == "duplicate" for r in rows), "addresses": sum(r["status"] == "ok" and r["kind"] == "address" for r in rows),
         "txs": sum(r["status"] == "ok" and r["kind"] == "tx" for r in rows), "warnings": sum(bool(r["warnings"]) for r in rows),
         "chains": sorted({r["chain"] for r in rows if r["status"] == "ok"}), "format": fmt, "capped": capped, "max_rows": MAX_ROWS}
    return {"summary": s, "rows": rows}

TEMPLATE = ("value,chain,label,role,notes\n"
            "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h,btc,Binance hot wallet (example),exchange,Public exchange wallet - example row\n"
            "0x28C6c06298d514Db089934071355E5743bf21d60,eth,Binance 14 (example),exchange,\n"
            "0x8894E0a0c962CB723c1976a4421c95949bE2D4E3,bsc,,suspect,EVM address on BNB Smart Chain: set the chain column\n"
            "TXFBqBbqJommqZf7BV8NNYzePh97UmJodJ,tron,,victim,TRON address\n"
            "rPVMhWBsfF9iMXYj3aAzJVkPDTFNSyWdKy,xrp,,,XRP address\n"
            "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9,sol,,,Solana address\n"
            "0x2824b1b16d3f9ec8c8315b611dbe05aea73603377ba7e7e2b62d661d71ed14c8,bsc,,,transaction hash on BSC\n")
