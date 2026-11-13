"""Canonical L1<->L2 bridges (OP Mainnet, Base, Arbitrum One): deterministic matching from on-chain data only (public RPCs, no indexer).
OP Stack deposits: the L2 deposit tx hash is computed from the L1 TransactionDeposited log (sourceHash = keccak(0 || keccak(l1BlockHash || logIndex)),
type-0x7E tx), then confirmed on the L2 RPC. Reverse (L2 deposit tx -> L1 origin) via the L1Block predeploy's origin block number.
OP Stack withdrawals: MessagePassed.withdrawalHash -> OptimismPortal WithdrawalProven/WithdrawalFinalized logs on L1.
Arbitrum ETH deposits (Inbox.depositEth): ArbitrumDepositTx (type 0x64) hash computed from the MessageDelivered log, confirmed on L2.
Arbitrum withdrawals: ArbSys L2ToL1Tx(position) -> Outbox OutBoxTransactionExecuted(transactionIndex) on L1."""
import asyncio, time
import chains, evmcfg
from keccak import keccak256, to_checksum
K = lambda s: "0x" + keccak256(s.encode()).hex()
OPS = {"op": {"portal": "0xbeb5fc579115071764c7423a4f12edde41f106ed", "name": "OP Mainnet"},
       "base": {"portal": "0x49048044d57e1c92a77f79988d21fa8faf74e97e", "name": "Base"}}
T_DEPOSITED = K("TransactionDeposited(address,address,uint256,bytes)")
T_MSGPASSED = K("MessagePassed(uint256,address,address,uint256,uint256,bytes,bytes32)")
T_W_PROVEN = K("WithdrawalProven(bytes32,address,address)"); T_W_PROVEN2 = K("WithdrawalProvenExtension1(bytes32,address)")
T_W_FINAL = K("WithdrawalFinalized(bytes32,bool)")
T_ETH_FIN = K("ETHBridgeFinalized(address,address,uint256,bytes)"); T_ERC_FIN = K("ERC20BridgeFinalized(address,address,address,address,uint256,bytes)")
T_ETH_INIT = K("ETHBridgeInitiated(address,address,uint256,bytes)"); T_ERC_INIT = K("ERC20BridgeInitiated(address,address,address,address,uint256,bytes)")
T_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
L2_TO_L1 = "0x4200000000000000000000000000000000000016"; L1BLOCK = "0x4200000000000000000000000000000000000015"
ARB_BRIDGE = "0x8315177ab297ba92a06054ce80a67ed4dbd7ed3a"; ARB_INBOX = "0x4dbd4fc535ac27206064b68ffcf827b0a60bab3f"
ARB_OUTBOX = "0x0b9857ae2d4a3dbe74ffe1d7df045bb7f96e4840"; ARBSYS = "0x0000000000000000000000000000000000000064"
T_MSG_DELIVERED = K("MessageDelivered(uint256,bytes32,address,uint8,address,bytes32,uint256,uint64)")
T_INBOX_MSG = K("InboxMessageDelivered(uint256,bytes)")
T_L2TOL1 = K("L2ToL1Tx(address,address,uint256,uint256,uint256,uint256,uint256,uint256,bytes)")
T_ARB_WINIT = K("WithdrawalInitiated(address,address,address,uint256,uint256,uint256)")
T_OUTBOX_EXEC = K("OutBoxTransactionExecuted(address,address,uint256,uint256)")

def _b(h): h = (h or "0x")[2:]; return bytes.fromhex(h if len(h) % 2 == 0 else "0" + h)
def _int_b(n): return n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
def rlp(x):
    if isinstance(x, list):
        p = b"".join(rlp(i) for i in x); return (bytes([0xc0 + len(p)]) if len(p) < 56 else bytes([0xf7 + len(_int_b(len(p)))]) + _int_b(len(p))) + p
    if isinstance(x, int): x = _int_b(x)
    if len(x) == 1 and x[0] < 0x80: return x
    return (bytes([0x80 + len(x)]) if len(x) < 56 else bytes([0xb7 + len(_int_b(len(x)))]) + _int_b(len(x))) + x
def _a(word): return "0x" + word[-40:].lower()
def cs(a):
    try: return to_checksum(a)
    except Exception: return a
async def rpc(c, m, p, t=10): return await chains.eth_rpc_any(m, p, t, chain=c)
def side(c, tx, addr, amt, unit, t=None, status=None):
    import bridges
    return bridges.side(c, tx, cs(addr) if addr else None, amt, unit, t, status=status)
async def _ts(c, blk):
    try: b = await rpc(c, "eth_getBlockByNumber", [blk, False]); return int(b["timestamp"], 16)
    except Exception: return None

# ---------- OP Stack deposits ----------
def op_deposit_hash(log):
    """L2 deposit tx hash from an L1 TransactionDeposited log (OP Stack spec: deposits.md)"""
    src = keccak256(b"\x00" * 32 + keccak256(_b(log["blockHash"]) + int(log["logIndex"], 16).to_bytes(32, "big")))
    frm, to = _b("0x" + log["topics"][1][-40:]), _b("0x" + log["topics"][2][-40:])
    d = _b(log["data"]); ln = int.from_bytes(d[32:64], "big"); op = d[64:64 + ln]
    mint, value, gas, creation, data = int.from_bytes(op[0:32], "big"), int.from_bytes(op[32:64], "big"), int.from_bytes(op[64:72], "big"), op[72] == 1, op[73:]
    raw = b"\x7e" + rlp([src, frm, b"" if creation else to, mint, value, gas, 0, data])
    return "0x" + keccak256(raw).hex(), {"source_hash": "0x" + src.hex(), "from": "0x" + frm.hex(), "to": "0x" + to.hex(), "mint": mint, "value": value, "data": data}

async def _l2_effect(c, h2):
    """what the L2 deposit tx did: bridge-finalized recipient/amount/token, else plain ETH mint to `to`"""
    rc = await rpc(c, "eth_getTransactionReceipt", [h2])
    if not rc: return None
    out = {"status": "completed" if rc.get("status") == "0x1" else "failed on L2", "block": rc.get("blockNumber")}
    for l in rc.get("logs") or []:
        tp = l.get("topics") or []; w = (l.get("data") or "0x")[2:]
        if tp and tp[0] == T_ETH_FIN and len(tp) >= 3:
            out.update(recipient=_a(tp[2]), sender=_a(tp[1]), amount=int(w[:64], 16) / 1e18, unit="ETH", token=None); break
        if tp and tp[0] == T_ERC_FIN and len(tp) >= 4:
            tok = _a(tp[1]); amt = int(w[64:128], 16)
            import swaps
            sym, dec = await swaps.token(tok, c)
            out.update(recipient=_a(w[:64]), sender=_a(tp[3]), amount=amt / 10 ** dec, unit=sym, token=tok); break
    return out

async def op_deposits_from_l1(h, rc=None):
    rc = rc or await rpc("eth", "eth_getTransactionReceipt", [h])
    res = []
    for l in (rc or {}).get("logs") or []:
        tp = l.get("topics") or []
        c = next((k for k, v in OPS.items() if v["portal"] == l["address"].lower()), None)
        if not c or not tp or tp[0] != T_DEPOSITED: continue
        h2, info = op_deposit_hash(l)
        if not info["mint"] and not info["value"] and info["to"] != "0x4200000000000000000000000000000000000007": continue
        eff = None
        try: eff = await _l2_effect(c, h2)
        except Exception: pass
        t1 = await _ts("eth", rc.get("blockNumber"))
        if eff is not None and not eff.get("recipient") and not info["mint"]: continue   # cross-domain message without a value transfer
        rcp = (eff or {}).get("recipient") or info["to"]; amt = (eff or {}).get("amount", info["mint"] / 1e18); unit = (eff or {}).get("unit", "ETH")
        verified = eff is not None
        t2 = await _ts(c, eff["block"]) if eff else None
        import bridges
        res.append(bridges.M(f"{OPS[c]['name']} canonical bridge (OptimismPortal)", "canonical (on-chain)", "deterministic" if verified else "computed (unconfirmed)",
                             0.99 if verified else 0.7, (eff or {}).get("status", "pending / not found on L2"),
                             side("eth", h, (eff or {}).get("sender") or info["from"], amt, unit, t1),
                             side(c, h2 if verified else None, rcp, amt, unit, t2, (eff or {}).get("status")),
                             f"L1 TransactionDeposited log #{int(l['logIndex'], 16)} → L2 deposit tx hash computed (sourceHash {info['source_hash'][:12]}…)"
                             + (" and confirmed on the L2 RPC" if verified else "; not (yet) found on the L2 RPC"),
                             ref=evmcfg.EVM[c]["ex"] + "/tx/" + h2,
                             notes=[] if verified else ["Computed hash not found on L2: deposit may still be pending (≈1–3 min) or the L2 RPC was unavailable"]))
    return res

async def op_deposit_origin(c, h2, tx):
    """L2 deposit tx (type 0x7e) -> the L1 tx that created it: L1Block.number() at that L2 block gives the L1 origin; recompute hashes of its portal logs"""
    blk = tx.get("blockNumber")
    n = await rpc(c, "eth_call", [{"to": L1BLOCK, "data": "0x8381f58a"}, blk])   # number()
    l1 = int(n, 16)
    for b in (l1, l1 - 1, l1 + 1):
        logs = await rpc("eth", "eth_getLogs", [{"address": OPS[c]["portal"], "fromBlock": hex(b), "toBlock": hex(b), "topics": [T_DEPOSITED]}], 15)
        for l in logs or []:
            hh, info = op_deposit_hash(l)
            if hh == h2.lower(): return l, info
    return None, None

# ---------- OP Stack withdrawals ----------
async def _l1_logs_by_topic(addr, topics, from_blk, span_blocks, chunk=10000):
    """L1 logs for (address, topic0, topic1) over a wide block range: Ethereum Blockscout logs API in one call, else 10k-block RPC chunks"""
    head = int(await rpc("eth", "eth_blockNumber", []), 16); out = []
    try:
        q = {"module": "logs", "action": "getLogs", "address": addr, "fromBlock": from_blk, "toBlock": min(from_blk + span_blocks, head), "topic0": topics[0]}
        if len(topics) > 1: q.update(topic1=topics[1], topic0_1_opr="and")
        d = await chains.get("https://eth.blockscout.com/api", params=q, ttl=300)
        if isinstance(d, dict) and isinstance(d.get("result"), list):
            return [{"transactionHash": x["transactionHash"], "blockNumber": x["blockNumber"] if str(x["blockNumber"]).startswith("0x") else hex(int(x["blockNumber"])),
                     "data": x.get("data"), "topics": [t for t in x.get("topics") or [] if t]} for x in d["result"]]
    except Exception as e: print("blockscout logs failed", type(e).__name__, e)
    rngs = [(b, min(b + chunk - 1, head)) for b in range(from_blk, min(from_blk + span_blocks, head + 1), chunk)]
    async def one(a, z):
        try: return await rpc("eth", "eth_getLogs", [{"address": addr, "fromBlock": hex(a), "toBlock": hex(z), "topics": topics}], 20) or []
        except Exception: return None
    for i in range(0, min(len(rngs), 40), 8):
        rs = await asyncio.gather(*[one(a, z) for a, z in rngs[i:i + 8]])
        for r in rs: out += r or []
        if out: break
    return out
async def _l1_block_near(ts):
    head = int(await rpc("eth", "eth_blockNumber", []), 16)
    return max(0, head - int((time.time() - ts) / 12) - 300)

async def op_withdrawal(c, h, rc):
    res = []
    import bridges
    for l in rc.get("logs") or []:
        tp = l.get("topics") or []
        if l["address"].lower() != L2_TO_L1 or not tp or tp[0] != T_MSGPASSED: continue
        w = (l.get("data") or "0x")[2:]; whash = "0x" + w[192:256] if len(w) >= 256 else None
        value = int(w[:64], 16) / 1e18
        # what the user withdrew: L2StandardBridge ...Initiated in the same receipt (amount, token, L1 recipient)
        amt, unit, rcp, snd = value, "ETH", _a(tp[3]), _a(tp[2])
        for l2 in rc.get("logs") or []:
            t2 = l2.get("topics") or []; d2 = (l2.get("data") or "0x")[2:]
            if t2 and t2[0] == T_ETH_INIT and len(t2) >= 3: amt, unit, rcp, snd = int(d2[:64], 16) / 1e18, "ETH", _a(t2[2]), _a(t2[1])
            if t2 and t2[0] == T_ERC_INIT and len(t2) >= 4:
                import swaps
                tok = _a(t2[1]); sym, dec = await swaps.token(tok, c); amt, unit, rcp, snd = int(d2[64:128], 16) / 10 ** dec, sym, _a(d2[:64]), _a(t2[3])
        if not amt: continue   # cross-domain message without a value transfer
        t2s = await _ts(c, rc.get("blockNumber")); start = await _l1_block_near(t2s or time.time())
        fin = await _l1_logs_by_topic(OPS[c]["portal"], [T_W_FINAL, whash], start, 60 * 7200)
        prv = [] if fin else await _l1_logs_by_topic(OPS[c]["portal"], [T_W_PROVEN, whash], start, 30 * 7200)
        st = "completed" if fin else ("proven, not yet finalized" if prv else "initiated (not proven on L1 yet)")
        l1 = (fin or prv or [None])[0]; t1 = await _ts("eth", l1["blockNumber"]) if l1 else None
        res.append(bridges.M(f"{OPS[c]['name']} canonical bridge (withdrawal)", "canonical (on-chain)", "deterministic", 0.99 if fin else 0.9, st,
                             side(c, h, snd, amt, unit, t2s), side("eth", l1["transactionHash"] if l1 else None, rcp, amt, unit, t1, st),
                             f"MessagePassed withdrawalHash {whash[:12]}… → OptimismPortal {'WithdrawalFinalized' if fin else 'WithdrawalProven' if prv else '(no L1 log yet)'}"
                             + (" on L1" if l1 else ""), ref=("https://etherscan.io/tx/" + l1["transactionHash"]) if l1 else None,
                             notes=[] if fin else ["Withdrawals finalize ≥7 days after being proven; the funds stay in the bridge until then"]))
    return res

# ---------- Arbitrum ----------
async def arb_deposits_from_l1(h, rc):
    res = []
    import bridges
    msgs = {}
    for l in rc.get("logs") or []:
        tp = l.get("topics") or []
        if l["address"].lower() == ARB_BRIDGE and tp and tp[0] == T_MSG_DELIVERED:
            w = (l.get("data") or "0x")[2:]
            msgs[int(tp[1], 16)] = {"kind": int(w[64:128], 16), "sender": _a(w[128:192])}
        if l["address"].lower() == ARB_INBOX and tp and tp[0] == T_INBOX_MSG:
            d = _b(l["data"]); ln = int.from_bytes(d[32:64], "big"); msgs.setdefault(int(tp[1], 16), {})["data"] = d[64:64 + ln]
    for num, m in msgs.items():
        if m.get("kind") != 12 or not m.get("data"): continue   # 12 = L1MessageType_ethDeposit (Inbox.depositEth)
        dest, value = "0x" + m["data"][:20].hex(), int.from_bytes(m["data"][20:52], "big")
        raw = b"\x64" + rlp([42161, num.to_bytes(32, "big"), _b(m["sender"]), _b(dest), value])
        h2 = "0x" + keccak256(raw).hex()
        eff = None
        try: eff = await rpc("arb", "eth_getTransactionReceipt", [h2])
        except Exception: pass
        t1 = await _ts("eth", rc.get("blockNumber")); t2 = await _ts("arb", eff["blockNumber"]) if eff else None
        res.append(bridges.M("Arbitrum One canonical bridge (Inbox.depositEth)", "canonical (on-chain)", "deterministic" if eff else "computed (unconfirmed)",
                             0.99 if eff else 0.7, "completed" if eff else "pending / not found on L2",
                             side("eth", h, rc.get("from") or m["sender"], value / 1e18, "ETH", t1), side("arb", h2 if eff else None, dest, value / 1e18, "ETH", t2),
                             f"Bridge MessageDelivered #{num} (ETH deposit) → ArbitrumDepositTx hash computed" + (" and confirmed on the Arbitrum RPC" if eff else "; not found on the Arbitrum RPC"),
                             ref="https://arbiscan.io/tx/" + h2,
                             notes=[] if eff else ["Sender may be an aliased contract address or the deposit is still pending; treat the computed hash as a lead"]))
    if not res and any(m.get("kind") == 9 for m in msgs.values()):   # retryable ticket (token gateway / custom message): recipient from logs only
        pass
    return res

async def arb_withdrawal(h, rc):
    res = []
    import bridges
    for l in rc.get("logs") or []:
        tp = l.get("topics") or []
        if l["address"].lower() != ARBSYS or not tp or tp[0] != T_L2TOL1 or len(tp) < 4: continue
        w = (l.get("data") or "0x")[2:]; dest = _a(tp[1]); pos = int(tp[3], 16)
        caller = _a(w[:64]); ts = int(w[192:256], 16); value = int(w[256:320], 16) / 1e18
        amt, unit, snd, rcp = (value or None), ("ETH" if value else None), caller, dest
        for g in rc.get("logs") or []:   # token withdrawal through an Arbitrum gateway: WithdrawalInitiated(l1Token, from, to, id, exitNum, amount)
            gt = g.get("topics") or []; gd = (g.get("data") or "0x")[2:]
            if gt and gt[0] == T_ARB_WINIT and len(gt) >= 3 and len(gd) >= 192:
                snd, rcp = _a(gt[1]), _a(gt[2]); raw = int(gd[128:192], 16)
                burn = next((b for b in rc.get("logs") or [] if (b.get("topics") or [""])[0] == T_TRANSFER and len(b["topics"]) == 3 and int(b["topics"][2], 16) == 0), None)
                if burn:
                    import swaps
                    sym, dec = await swaps.token(burn["address"], "arb"); amt, unit = raw / 10 ** dec, sym
                break
        start = await _l1_block_near(ts)
        logs = await _l1_logs_by_topic(ARB_OUTBOX, [T_OUTBOX_EXEC, "0x" + dest[2:].rjust(64, "0")], start, 40 * 7200)
        hit = next((x for x in logs if int((x.get("data") or "0x0")[2:66] or "0", 16) == pos), None)
        t1 = await _ts("eth", hit["blockNumber"]) if hit else None
        st = "completed" if hit else "initiated (not executed on L1 yet; ~7-day challenge period)"
        res.append(bridges.M("Arbitrum One canonical bridge (withdrawal)", "canonical (on-chain)", "deterministic", 0.99 if hit else 0.9, st,
                             side("arb", h, snd, amt, unit, ts), side("eth", hit["transactionHash"] if hit else None, rcp, amt, unit, t1, st),
                             f"ArbSys L2ToL1Tx position {pos} → Outbox OutBoxTransactionExecuted" + (" on L1" if hit else " (not found yet)"),
                             ref=("https://etherscan.io/tx/" + hit["transactionHash"]) if hit else None,
                             notes=[] if amt else ["Withdrawal message without a decoded amount (custom gateway or contract call)"]))
    return res

# ---------- entry point (bridges TX_PROVIDERS) ----------
async def canonical_tx(h):
    h = h.lower(); found = await chains.detect_tx_chains(h)
    out = []
    for c in found:
        try:
            rc = await rpc(c, "eth_getTransactionReceipt", [h])
            if not rc: continue
            if c == "eth":
                out += await op_deposits_from_l1(h, rc)
                out += await arb_deposits_from_l1(h, rc)
            elif c in OPS:
                tx = await rpc(c, "eth_getTransactionByHash", [h])
                if tx and tx.get("type") == "0x7e" and (tx.get("from") or "").lower() != "0xdeaddeaddeaddeaddeaddeaddeaddeaddead0001":
                    l, info = await op_deposit_origin(c, h, tx)
                    if l: out += [m for m in await op_deposits_from_l1(l["transactionHash"]) if (m["dst"].get("tx") or "").lower() == h]
                out += await op_withdrawal(c, h, rc)
            elif c == "arb": out += await arb_withdrawal(h, rc)
        except Exception as e: print("canonical", c, h, type(e).__name__, e)
    return out
