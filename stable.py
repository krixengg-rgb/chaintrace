"""ChainTrace stablecoins (v27): USDT / USDC across ETH, TRON, BSC, Arbitrum, Base, Polygon, Optimism and Solana.
- official token contracts (issuer pages cited) so look-alike 'USDT' tokens are not counted;
- issuer blacklist / freeze status read on-chain: Tether USDT isBlackListed + getBlackListStatus (Ethereum, TRON), Circle USDC isBlacklisted (EVM);
- Circle CCTP burn -> mint matching: deterministic, from Circle's attestation service (iris-api.circle.com) which links the burn to the
  destination mint transaction; ChainTrace re-checks the mint on the destination chain (Transfer from 0x0 to the mint recipient);
- stablecoin flow summary per chain / token for an address; issuer mint / burn transfers flagged."""
import asyncio, time
from collections import defaultdict
import httpx, chains, addrutil, keccak

# official contracts (lower-case EVM). source: issuer / token-operator pages, checked 2026-11-20
CIRCLE = "https://developers.circle.com/stablecoins/usdc-contract-addresses"
TETHER = "https://tether.to/en/supported-protocols/"
USDT0 = "https://docs.usdt0.to/technical-documentation/deployments"
OFFICIAL = {
 ("eth", "0xdac17f958d2ee523a2206206994597c13d831ec7"): ("USDT", 6, "Tether", TETHER),
 ("eth", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"): ("USDC", 6, "Circle", CIRCLE),
 ("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"): ("USDT", 6, "Tether", TETHER),
 ("sol", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"): ("USDT", 6, "Tether", TETHER),
 ("sol", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"): ("USDC", 6, "Circle", CIRCLE),
 ("arb", "0xaf88d065e77c8cc2239327c5edb3a432268e5831"): ("USDC", 6, "Circle", CIRCLE),
 ("arb", "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"): ("USDT0", 6, "USDT0 (Tether-backed OFT)", USDT0),
 ("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"): ("USDC", 6, "Circle", CIRCLE),
 ("op", "0x0b2c639c533813f4aa9d7837caf62653d097ff85"): ("USDC", 6, "Circle", CIRCLE),
 ("op", "0x01bff41798a0bcf287b996046ca68b395dbc1071"): ("USDT0", 6, "USDT0 (Tether-backed OFT)", USDT0),
 ("polygon", "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"): ("USDC", 6, "Circle", CIRCLE),
 ("polygon", "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"): ("USDT0", 6, "USDT0 (Tether-backed OFT)", USDT0),
 ("bsc", "0x55d398326f99059ff775485246999027b3197955"): ("USDT", 18, "Binance-Peg (issued by Binance, not Tether)", "https://bscscan.com/token/0x55d398326f99059ff775485246999027b3197955"),
 ("bsc", "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"): ("USDC", 18, "Binance-Peg (issued by Binance, not Circle)", "https://bscscan.com/token/0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"),
}
UNITS = {"USDT", "USDC", "USDT0", "USD₮0", "USDC.E", "USDBC", "BSC-USD"}
def is_stable_unit(u): return (u or "").upper() in UNITS
def norm(c, a): return a if c in ("tron", "sol") else (a or "").lower()
def official(c, token): return OFFICIAL.get((c, norm(c, token))) if token else None

# ---------------- blacklist / freeze status ----------------
BL = {  # chain -> [(token contract, symbol, issuer, [selectors])]
 "eth": [("0xdac17f958d2ee523a2206206994597c13d831ec7", "USDT", "Tether", ["isBlackListed(address)", "getBlackListStatus(address)"]),
         ("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "USDC", "Circle", ["isBlacklisted(address)"])],
 "tron": [("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "USDT", "Tether", ["isBlackListed(address)", "getBlackListStatus(address)"])],
 **{c: [(t, "USDC", "Circle", ["isBlacklisted(address)"])] for (c, t), v in OFFICIAL.items() if v[0] == "USDC" and c in ("arb", "base", "op", "polygon")},
}
def _sel(sig): h = keccak.keccak256(sig.encode()); return "0x" + (h.hex() if isinstance(h, bytes) else h)[:8]
async def _evm_call(c, to, sig, a):
    data = _sel(sig) + a.lower().removeprefix("0x").rjust(64, "0")
    r = await chains.eth_rpc_any("eth_call", [{"to": to, "data": data}, "latest"], 8, chain=c)
    if r is None: raise Exception("RPC unavailable")
    return int(r, 16) != 0 if r not in ("0x", "") else None
async def _tron_call(token, sig, a):
    par = addrutil.tron_b58_to_hex(a)[2:].rjust(64, "0")
    body = {"owner_address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb", "contract_address": token, "function_selector": sig, "parameter": par, "visible": True}
    last = None
    for base in chains.TRON_API:
        try:
            r = await chains.client.post(base + "/wallet/triggerconstantcontract", json=body, timeout=10); r.raise_for_status(); j = r.json()
            res = (j.get("constant_result") or [None])[0]
            if res is None: raise Exception((j.get("result") or {}).get("message") or "no result")
            return int(res, 16) != 0
        except Exception as e: last = e
    raise Exception(f"TronGrid: {last}")
async def balance_of(c, token, a, dec):
    try:
        if c == "tron":
            body = {"owner_address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb", "contract_address": token, "function_selector": "balanceOf(address)", "parameter": addrutil.tron_b58_to_hex(a)[2:].rjust(64, "0"), "visible": True}
            res = None
            for i in range(2):
                for base in chains.TRON_API:
                    try:
                        r = await chains.client.post(base + "/wallet/triggerconstantcontract", json=body, timeout=10); r.raise_for_status(); res = r.json()["constant_result"][0]; break
                    except Exception: continue
                if res is not None: break
                await asyncio.sleep(1.5)
            if res is None: return None
        else:
            res = await chains.eth_rpc_any("eth_call", [{"to": token, "data": "0x70a08231" + a.lower().removeprefix("0x").rjust(64, "0")}, "latest"], 8, chain=c)
        return int(res, 16) / 10 ** dec
    except Exception: return None
async def blacklist(c, a):
    """-> list of {token, symbol, issuer, chain, blacklisted, calls{sig: bool}, balance, source}"""
    a = a.split(":", 1)[1] if c not in ("eth", "tron") and ":" in a else a
    out = []
    async def one(token, sym, iss, sigs):
        calls, err = {}, None
        for s in sigs:
            try: calls[s.split("(")[0]] = await (_tron_call(token, s, a) if c == "tron" else _evm_call(c, token, s, a))
            except Exception as e: err = f"{type(e).__name__}: {str(e)[:80]}"
        vals = [v for v in calls.values() if v is not None]
        bl = any(vals) if vals else None
        dec = 6 if (c, norm(c, token)) not in OFFICIAL else OFFICIAL[(c, norm(c, token))][1]
        bal = await balance_of(c, token, a, dec) if bl else None
        return {"chain": c, "token": token, "symbol": sym, "issuer": iss, "blacklisted": bl, "calls": calls, "error": err if not vals else None,
                "frozen_balance": bal, "method": " / ".join(s.split("(")[0] for s in sigs) + " read on-chain (eth_call / TronGrid triggerconstantcontract)"}
    return list(await asyncio.gather(*[one(*x) for x in BL.get(c, [])]))

# ---------------- flows ----------------
ZERO = {"0x0000000000000000000000000000000000000000", "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb", "0x0"}
def summary(d):
    """stablecoin flows of a looked-up address (api/lookup result) per token: in/out, counterparties, mint/burn, official-contract check"""
    c = d.get("chain"); me = d.get("address")
    T = defaultdict(lambda: {"in": 0.0, "out": 0.0, "n_in": 0, "n_out": 0, "cps": defaultdict(float), "issuer_events": [], "tokens": set(), "official": None})
    for e in d.get("edges") or []:
        if not is_stable_unit(e.get("unit")) or set(e.get("flags") or []) & {"spam", "zero"}: continue
        ec = (e.get("source") or "").split(":")[0] if ":" in str(e.get("source")) and not str(e["source"]).startswith("0x") else c
        u = e["unit"].upper().replace("USD₮0", "USDT0")
        x = T[(c, u)]; amt = e.get("amount") or 0
        tok = e.get("token")
        if tok:
            x["tokens"].add(tok); o = official(c, tok)
            x["official"] = (x["official"] is not False) and bool(o)
        if e["target"] == me: x["in"] += amt; x["n_in"] += e.get("count", 1); x["cps"][e["source"]] += amt
        elif e["source"] == me: x["out"] += amt; x["n_out"] += e.get("count", 1); x["cps"][e["target"]] += amt
        for z, kind in ((e["source"], "issuer mint (from zero address)"), (e["target"], "burn (to zero address)")):
            if z.split(":")[-1] in ZERO: x["issuer_events"].append({"kind": kind, "tx": e.get("tx"), "amount": amt, "time": e.get("time")})
    out = []
    for (cc, u), x in T.items():
        top = sorted(x["cps"].items(), key=lambda kv: -kv[1])[:5]
        out.append({"chain": cc, "unit": u, "in": round(x["in"], 2), "out": round(x["out"], 2), "n_in": x["n_in"], "n_out": x["n_out"],
                    "top": [{"id": k, "amount": round(v, 2)} for k, v in top], "issuer_events": x["issuer_events"][:10],
                    "contracts": sorted(x["tokens"]), "official": x["official"],
                    "official_note": None if x["official"] is None else ("official contract" if x["official"] else "⚠ token contract is not the issuer's official contract: possible look-alike")})
    return sorted(out, key=lambda r: -(r["in"] + r["out"]))

# ---------------- Circle CCTP (burn -> mint), deterministic via Circle's attestation service ----------------
IRIS = "https://iris-api.circle.com/v2/messages/{d}"
CCTP_DOCS = "https://developers.circle.com/cctp/references/contract-addresses"
DOMAIN = {0: "eth", 1: "avax", 2: "op", 3: "arb", 5: "sol", 6: "base", 7: "polygon", 10: "unichain", 11: "linea", 13: "sonic", 14: "worldchain", 16: "sei", 19: "hyperevm", 21: "ink"}
DOM_OF = {v: k for k, v in DOMAIN.items()}
TRANSMITTERS = {"0x81d40f21f12a8f0e3252bccb954d722d4c464b64",   # MessageTransmitterV2 (all EVM domains)
                "0x0a992d191deec32afe36203ad87d7d289a738f81", "0x8186359af5f57fbb40c6b14a588d2a59c0c29880", "0x4d41f22c5a0e5c74090899e5a8fb597a8842b3e8",
                "0xc30362313fbba5cf9163f0bb16a0e01f01a896ca", "0xad09780d193884d503182ad4588450c416d6f9d4", "0xf3be9355363857f3e001be68856a2f96b4c39ba9",
                "0x353be9e2e38ab1d19104534e4edc21c643df86f4"}   # MessageTransmitter V1 (eth, avax, op, arb, base, polygon, unichain)
RECV_V1 = "0x58200b4c34ae05ee816d710053fff3fb75af4395915d3d2a771b24aa10e3cc5d"   # MessageReceived(address,uint32,uint64,bytes32,bytes)
RECV_V2 = "0xff48c13eda96b1cceacc6b9edeedc9e9db9d6226afbc30146b720c19d3addb1c"   # MessageReceived(address,uint32,bytes32,bytes32,uint32,bytes)
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
USDC_OF = {c: t for (c, t), v in OFFICIAL.items() if v[0] == "USDC" and v[2] == "Circle"}
def _b32_addr(c, b):
    b = (b or "").lower().removeprefix("0x")
    if c == "sol":
        try: return addrutil.b58encode(bytes.fromhex(b.rjust(64, "0")))
        except Exception: return "0x" + b
    return "0x" + b[-40:]
async def _iris(d, **q):
    try:
        r = await chains.client.get(IRIS.format(d=d), params=q, timeout=10)
        if r.status_code == 404: return []
        r.raise_for_status(); return r.json().get("messages") or []
    except httpx.HTTPStatusError: return []
async def _verify_mint(c, tx, recipient, amount_units):
    """re-check on the destination chain: USDC Transfer from 0x0 to the mint recipient in the mint tx"""
    if c not in chains.EVM or c not in USDC_OF: return None, "destination chain not re-checked (no ChainTrace RPC for it)"
    r = await chains.eth_rpc_any("eth_getTransactionReceipt", [tx], 8, chain=c)
    if not r: return None, "destination receipt not available from public RPCs"
    rec = recipient.lower()[-40:]
    for l in r.get("logs") or []:
        t = l.get("topics") or []
        if l["address"].lower() == USDC_OF[c] and t and t[0] == TRANSFER and len(t) == 3 and int(t[1], 16) == 0 and t[2][-40:].lower() == rec:
            v = int(l["data"], 16)
            ok = v <= amount_units and v >= amount_units * 0.98   # v2 fast transfers can deduct a small fee
            return ok, f"mint of {v / 1e6:,.2f} USDC to the recipient confirmed in the destination receipt" + ("" if ok else " (amount differs)")
    return False, "no USDC mint to the recipient found in the destination receipt"
def _match(m, src_dom, src_tx, verified=None, vnote=None, src_time=None, dst_time=None):
    dm = m.get("decodedMessage") or {}; body = dm.get("decodedMessageBody") or {}
    sc, dc = DOMAIN.get(int(dm.get("sourceDomain", src_dom)), f"cctp-domain:{src_dom}"), DOMAIN.get(int(dm.get("destinationDomain", -1)), f"cctp-domain:{dm.get('destinationDomain')}")
    tok = (body.get("burnToken") or "")
    sym = "USDC" if norm(sc, tok) == norm(sc, USDC_OF.get(sc, "-")) or sc == "sol" else ("token " + tok[:10])
    amt = int(body.get("amount") or 0) / 1e6 if body.get("amount") else None
    import bridges as B
    src = B.side(sc, src_tx, _b32_addr(sc, body.get("messageSender")) if body.get("messageSender") else None, amt, sym, src_time, amt if sym == "USDC" else None)
    mint = m.get("destinationMintTxHash")
    st = "completed" if mint else (m.get("status") or "pending")
    dst = B.side(dc, mint, _b32_addr(dc, body.get("mintRecipient")) if body.get("mintRecipient") else None, amt, sym, dst_time, status=st)
    notes = []
    if m.get("cctpVersion") == 2 and not mint: notes.append("CCTP V2: Circle's API does not always return the destination mint tx; the recipient and amount are attested by Circle")
    if vnote: notes.append(vnote)
    conf = 0.99 if (mint and verified) else 0.95 if mint or dm else 0.6
    return B.M("Circle CCTP", "iris.circle.com", "deterministic", conf, st, src, dst,
               f"Circle CCTP V{m.get('cctpVersion')} burn (domain {dm.get('sourceDomain')} → {dm.get('destinationDomain')}, nonce {str(dm.get('nonce') or m.get('eventNonce'))[:20]}) attested by Circle (iris-api.circle.com)"
               + ("; destination mint re-checked on-chain" if verified else ""), amt if sym == "USDC" else None, CCTP_DOCS, notes)
async def cctp_tx(h):
    """burn tx (any CCTP source domain) or mint tx (EVM destination) -> CCTP matches"""
    import bridges as B
    h = h.strip()
    if B._sol_ok(h): doms = [5]
    elif B._hex_ok(h): doms = [d for d in DOMAIN if d != 5]
    else: return []
    res = await asyncio.gather(*[_iris(d, transactionHash=h) for d in doms], return_exceptions=True)
    out = []
    for d, ms in zip(doms, res):
        if isinstance(ms, Exception): continue
        for m in ms:
            dm = m.get("decodedMessage") or {}; body = dm.get("decodedMessageBody") or {}
            dc = DOMAIN.get(int(dm["destinationDomain"])) if dm.get("destinationDomain") is not None else None
            ok = vn = None
            if m.get("destinationMintTxHash") and dc and body.get("mintRecipient"):
                try: ok, vn = await asyncio.wait_for(_verify_mint(dc, m["destinationMintTxHash"], _b32_addr(dc, body["mintRecipient"]), int(body.get("amount") or 0)), 8)
                except Exception as e: vn = f"destination re-check failed: {type(e).__name__}"
            out.append(_match(m, d, h, ok, vn))
    if out or not B._hex_ok(h): return out
    # maybe a mint tx: find MessageReceived on an EVM destination, then ask Circle by source domain + nonce
    async def rec(c):
        try: return c, await chains.eth_rpc_any("eth_getTransactionReceipt", [h], 6, chain=c)
        except Exception: return c, None
    for c, r in await asyncio.gather(*[rec(c) for c in ("eth", "arb", "base", "op", "polygon") if c in chains.EVM]):
        for l in (r or {}).get("logs") or []:
            t = l.get("topics") or []
            if l["address"].lower() in TRANSMITTERS and t and t[0] in (RECV_V1, RECV_V2) and len(t) >= 3:
                sd = int(l["data"][2:66], 16); nonce = str(int(t[2], 16)) if t[0] == RECV_V1 else t[2]
                for m in await _iris(sd, nonce=nonce):
                    if (m.get("destinationMintTxHash") or "").lower() == h.lower() or not m.get("destinationMintTxHash"):
                        m.setdefault("destinationMintTxHash", h)
                        src_tx = None
                        try:
                            r2 = await chains.client.get(IRIS.format(d=sd), params={"nonce": nonce}, timeout=10); src_tx = r2.json().get("sourceTxHash")
                        except Exception: pass
                        out.append(_match(m, sd, src_tx, True, "found from the destination: MessageReceived log (source domain + nonce) matched to Circle's attested message"))
    return out
