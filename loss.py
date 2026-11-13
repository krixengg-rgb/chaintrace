"""ChainTrace victim-loss calculator / fund-flow summary (v14).

Input: the graph the browser already holds (nodes + edges, as sent to /api/report) plus a loss spec:
  {"victims": [addr, ...], "victim_txs": [hash, ...], "suspect": addr | None, "method": "proportional" | "fifo" | "lifo"}
Output: totals lost per asset (coin, USD and GBP on the day of each payment and today), where the tainted funds went
(exchanges/VASPs with deposit labels and XRP destination tags, bridges, swaps, mixers, sanctioned addresses, held balances,
untraced), the amount still in identified wallets, a hop-by-hop table, and a CSV.

Nothing here is invented: amounts, times and hashes come from the graph or the chain; prices from Coinbase daily candles;
GBP from the ECB reference rate (Frankfurter API). Where a figure depends on a convention (the tracing method) or a heuristic
(heuristic bridge/peel edges, inferred deposit labels, implied conversions) the output says so."""
import asyncio, csv, io, math, time
from collections import defaultdict, deque
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import chains

UK = ZoneInfo("Europe/London")
LEAD = "Intelligence lead – not evidence; corroborate (e.g. production order to the VASP)"
METHODS = {
    "proportional": ("Proportional (haircut)",
                     "Every outgoing transfer from an address carries the same share of victim funds as that address held at the moment of the transfer "
                     "(victim funds received so far ÷ all funds received so far on the graph, less what had already left). Mixing with other funds dilutes the victim share."),
    "fifo": ("FIFO (first in, first out)",
             "Funds leave an address in the order they arrived: the earliest receipts are spent first. Victim funds are only treated as leaving once the funds "
             "received before them have been spent."),
    "lifo": ("LIFO (last in, first out)",
             "The most recent receipts are spent first. Victim funds are treated as leaving first when they are the latest funds to arrive."),
}
STABLE = {"USDT", "USDC", "DAI", "USDS", "PYUSD", "FDUSD", "TUSD", "USDE", "USDC.E", "BUSD"}
PXSYM = {"BTC": "BTC", "WBTC": "BTC", "CBBTC": "BTC", "ETH": "ETH", "WETH": "ETH", "STETH": "ETH", "SOL": "SOL", "WSOL": "SOL", "XRP": "XRP"}
NATIVE = {"btc": "BTC", "eth": "ETH", "sol": "SOL", "tron": "TRX", "xrp": "XRP"}
CATS = [  # (key, heading, statement wording)
    ("exchange", "Exchanges / VASPs", "received by addresses attributed to an exchange or other virtual asset service provider (VASP)"),
    ("bridge", "Bridges (not followed further)", "sent into a cross-chain bridge with no matched destination on the graph"),
    ("mixer", "Mixers", "sent to an address labelled as a mixer"),
    ("sanctioned", "Sanctioned addresses", "sent to an address on the OFAC SDN or UK Sanctions List"),
    ("held", "Still held in identified wallets", "still held at the last address on the graph (capped at that address's balance as recorded)"),
    ("end", "Last seen at an address (balance not confirmed)", "reached an address with no onward flows on the graph and no recorded balance"),
    ("untraced", "Left the graph (onward flow not traced)", "left an address but the onward transfer is not on the graph"),
    ("returned", "Returned to a victim address", "came back to one of the victim addresses"),
]
CATNAME = {k: h for k, h, _ in CATS}
EPS = 1e-12

def uk(ts):
    if not ts: return ""
    d = datetime.fromtimestamp(ts, UK); return d.strftime("%d/%m/%Y %H:%M:%S ") + (d.tzname() or "")
def utc(ts): return datetime.fromtimestamp(ts, timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC") if ts else ""
def day(ts): return int(ts // 86400 * 86400)
def unit_of(e): return str(e.get("unit") or "").replace("⇄", "").strip().upper()
def tnum(x):
    if x is None: return None
    if isinstance(x, (int, float)): return float(x) if x > 0 else None
    t = chains.ts_of(x); return float(t) if t else None
def etime(e): return tnum(e.get("time")) or tnum(e.get("last")) or tnum(e.get("first"))
def same(a, b): return a == b or (str(a).startswith("0x") and str(a).lower() == str(b).lower())
def r8(x): return round(x, 8) if x is not None else None

# ---------------- prices ----------------
async def _candles(need, errs):
    """{(sym, day): close USD} from Coinbase Exchange daily candles (free, keyless)"""
    out = {}; now = time.time()
    async def one(sym, days):
        days = sorted(days); i = 0
        while i < len(days):
            start = days[i]; chunk = [d for d in days[i:] if d <= start + 299 * 86400]; i += len(chunk)
            iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
            url = f"https://api.exchange.coinbase.com/products/{sym}-USD/candles?granularity=86400&start={iso(start - 86400)}&end={iso(chunk[-1] + 86400)}"
            try:
                rows = await chains.get(url, ttl=chains.LONG if chunk[-1] < now - 2 * 86400 else 3600)
                for r in rows or []: out[(sym, int(r[0]))] = float(r[4])
            except Exception as ex: errs.append(f"historical price {sym}: {type(ex).__name__}")
    try: await asyncio.wait_for(asyncio.gather(*[one(s, d) for s, d in need.items() if d]), 10)
    except asyncio.TimeoutError: errs.append("historical prices: timed out (partial)")
    return out

async def _gbp(days, errs):
    """USD->GBP: ECB euro foreign exchange reference rates via the Frankfurter API (previous working day at weekends/holidays).
    Returns ({day: (rate, rate_date)}, (today_rate, rate_date, source))"""
    hist = {}; today = None
    try:
        lt = await asyncio.wait_for(chains.get("https://api.frankfurter.dev/v1/latest?base=USD&symbols=GBP", ttl=3600), 6)
        today = (float(lt["rates"]["GBP"]), lt.get("date"), "ECB reference rate (Frankfurter API)")
    except Exception as ex:
        errs.append(f"GBP rate (ECB/Frankfurter): {type(ex).__name__}")
        try:
            cb = await asyncio.wait_for(chains.get("https://api.coinbase.com/v2/exchange-rates?currency=USD", ttl=3600), 6)
            today = (float(cb["data"]["rates"]["GBP"]), datetime.now(timezone.utc).strftime("%Y-%m-%d"), "Coinbase spot rate")
        except Exception as ex2: errs.append(f"GBP rate (Coinbase): {type(ex2).__name__}")
    if days:
        a = datetime.fromtimestamp(min(days) - 6 * 86400, timezone.utc).strftime("%Y-%m-%d"); b = datetime.fromtimestamp(max(days), timezone.utc).strftime("%Y-%m-%d")
        try:
            d = await asyncio.wait_for(chains.get(f"https://api.frankfurter.dev/v1/{a}..{b}?base=USD&symbols=GBP", ttl=chains.LONG if max(days) < time.time() - 3 * 86400 else 3600), 8)
            rates = sorted((k, float(v["GBP"])) for k, v in (d.get("rates") or {}).items())
            for dd in days:
                ds = datetime.fromtimestamp(dd, timezone.utc).strftime("%Y-%m-%d")
                prev = [x for x in rates if x[0] <= ds]
                if prev: hist[dd] = (prev[-1][1], prev[-1][0])
        except Exception as ex: errs.append(f"historical GBP rates: {type(ex).__name__}")
    return hist, today

# ---------------- live balances for end addresses (native coin only) ----------------
async def _balance(chain, a):
    try:
        if chain == "btc":
            i = await chains.get(f"{chains.MP}/address/{a}", ttl=120); cs, ms = i["chain_stats"], i["mempool_stats"]
            return (cs["funded_txo_sum"] - cs["spent_txo_sum"] + ms["funded_txo_sum"] - ms["spent_txo_sum"]) / 1e8
        if chain == "eth":
            r = await chains.eth_rpc_any("eth_getBalance", [a, "latest"], 5); return int(r, 16) / 1e18
        if chain == "sol":
            r = await chains.rpc(chains.SOL, "getBalance", [a]); return (r.get("value") if isinstance(r, dict) else r) / 1e9
        if chain == "xrp":
            r = await chains.xrp_rpc("account_info", [{"account": a, "ledger_index": "validated"}]); return int(r["account_data"]["Balance"]) / 1e6
        if chain == "tron":
            r = await chains._tron_get(f"/v1/accounts/{a}", ttl=120); d = (r.get("data") or [{}])[0]; return (d.get("balance") or 0) / 1e6
    except Exception: return None
    return None

# ---------------- the calculation ----------------
class Lot:
    __slots__ = ("t", "amt", "taint", "seq")
    def __init__(s, t, amt, taint, seq): s.t, s.amt, s.taint, s.seq = t, amt, taint, seq

def _cat(n, victims):
    """terminal category of a node, or None to keep following"""
    if not n: return None
    i = n.get("id")
    if any(same(i, v) for v in victims): return "returned"
    k = n.get("kind")
    if n.get("sanctions") or k == "sanctioned": return "sanctioned"
    if k == "mixer": return "mixer"
    if k == "exchange" or (n.get("suggested") and not k): return "exchange"
    if k == "bridge": return "bridge"
    return None

def _entity(n, case_labels):
    ul = case_labels.get(n.get("id")) if isinstance(case_labels, dict) else None
    if isinstance(ul, dict) and ul.get("name"): return ul["name"], False, "investigator label"
    if n.get("kind") == "exchange" and n.get("name"): return n["name"], False, "dataset label"
    s = n.get("suggested")
    if isinstance(s, dict) and s.get("entity"): return f"{s['entity']} (suggested deposit address)", True, s.get("method") or "inferred deposit label"
    return n.get("name") or "Unlabelled", False, ""

async def compute(p, spec=None, live_balances=True):
    t_gen = time.time(); errs = []; warns = []
    spec = spec or p.get("loss") or {}
    method = (spec.get("method") or "proportional").lower()
    if method not in METHODS: method = "proportional"
    nodes = {}
    for n in p.get("nodes") or []:
        if isinstance(n, dict) and n.get("id") and not n.get("grp") and not n.get("meta"): nodes[n["id"]] = n
    case_labels = (p.get("case") or {}).get("labels") or {}
    def canon(a):
        a = str(a or "").strip()
        if not a: return a
        if a in nodes: return a
        for k in nodes:
            if same(k, a): return k
        return a
    victims = [canon(v) for v in dict.fromkeys(str(x).strip() for x in (spec.get("victims") or []) if str(x).strip())][:50]
    vtxs = [str(x).strip().lower().removeprefix("tx:") for x in (spec.get("victim_txs") or []) if str(x).strip()][:50]
    suspect = canon(spec.get("suspect")) if spec.get("suspect") else None
    missing = [v for v in victims if v not in nodes]
    if missing: warns.append(f"{len(missing)} victim address(es) are not on the graph: " + ", ".join(m[:14] + "…" for m in missing[:5]))
    if not victims and not vtxs: raise ValueError("mark at least one victim address or victim payment (tx hash)")
    # ---- edges: drop zero/meta, raw transfers duplicated by a decoded swap or a matched bridge hop ----
    raw = [e for e in (p.get("edges") or []) if isinstance(e, dict) and e.get("source") and e.get("target") and not e.get("meta") and not e.get("tmp")]
    swap_txs = {str(e.get("tx")).lower() for e in raw if isinstance(e.get("swap"), dict) and e.get("tx")}
    x_keys = {(e["source"], str(e.get("tx")).lower()) for e in raw if e.get("xchain") and e.get("tx")}
    txnodes = {str(k).lower() for k in nodes if str(k).startswith("tx:")}; dup_warn = []
    E = []
    for e in raw:
        try: a = float(e.get("amount") or 0)
        except Exception: continue
        if a <= 0 or e["source"] == e["target"]: continue
        tx = str(e.get("tx") or "").lower()
        if not e.get("swap") and tx and tx in swap_txs: continue
        if not e.get("xchain") and tx and (e["source"], tx) in x_keys: continue
        if tx and "tx:" + tx in txnodes and not str(e["source"]).startswith("tx:") and not str(e["target"]).startswith("tx:"):
            if int(e.get("count") or 1) == 1: continue        # same payment already shown through its transaction node
            dup_warn.append(tx)
        E.append(dict(e, _a=a, _u=unit_of(e), _t=etime(e), _i=len(E)))
    if dup_warn: warns.append(f"{len(dup_warn)} merged flow(s) include a transaction that is also shown as a transaction node; that transaction may be counted twice.")
    # ---- prices seen on the graph (fallback valuation) ----
    await chains.ensure_prices()
    seen_px = {}
    for e in E:
        if e.get("usd") and e["_a"]: seen_px.setdefault(e["_u"], float(e["usd"]) / e["_a"])
    def px_now(u):
        if u in STABLE: return 1.0, "par"
        v = chains.PRICE.get(u)
        if v: return float(v), "spot"
        if u in seen_px: return seen_px[u], "graph"
        return None, None
    # ---- victim payments (seeds) ----
    seeds = []; vset = set(victims)
    for h in vtxs:   # a victim tx shown as a transaction node: its input addresses are the paying (victim) wallets
        tn = next((k for k in nodes if str(k).lower() == "tx:" + h), None)
        if tn:
            for e in E:
                if e["target"] == tn and not str(e["source"]).startswith("tx:") and e["source"] != "coinbase": vset.add(e["source"])
    if vset - set(victims): victims = victims + sorted(vset - set(victims))
    def is_victim(a): return any(same(a, v) for v in vset)
    for e in E:
        tx = str(e.get("tx") or "").lower()
        by_tx = tx and tx in vtxs and (not vset or is_victim(e["source"]) or e["source"].startswith("tx:"))
        by_addr = vset and is_victim(e["source"]) and not is_victim(e["target"])
        if not (by_tx or by_addr): continue
        if e["source"].startswith("tx:") and not by_tx: continue
        if is_victim(e["target"]): continue          # change back to the victim
        seeds.append(e)
    # a victim paying through a transaction node (BTC tx lookup): the loss is the tx outputs to non-victims, not the whole input
    exp = []
    for sd in seeds:
        if str(sd["target"]).startswith("tx:"):
            outs_tx = [e for e in E if e["source"] == sd["target"] and not is_victim(e["target"])]
            exp += [dict(e, _viatx=sd["source"]) for e in outs_tx]
        else: exp.append(sd)
    seeds = list({e["_i"]: e for e in exp}.values())
    if suspect:
        to_s = [e for e in seeds if same(e["target"], suspect)]
        if to_s: seeds = to_s
        else: warns.append("No victim payment goes directly to the suspect start address on the graph, so every outgoing payment from the victim address(es) is counted.")
    # victim tx hashes not on the graph: fetch the transaction itself
    found = {str(e.get("tx") or "").lower() for e in seeds}
    fetched = []
    for h in [h for h in vtxs if h not in found][:10]:
        c = (spec.get("chain") or None)
        c0, k = chains.detect(h)
        c = c or c0
        if not c or c not in chains.TX: errs.append(f"victim tx {h[:12]}…: chain not recognised"); continue
        try: d = await asyncio.wait_for(chains.TX[c](h if c != "eth" else h if h.startswith("0x") else "0x" + h), 15)
        except Exception as ex: errs.append(f"victim tx {h[:12]}…: could not be fetched ({type(ex).__name__})"); continue
        t = tnum(d.get("time")); add = []
        if c == "btc":
            ins = {x["address"] for x in d.get("inputs") or []}
            srcs = [a for a in ins if is_victim(a)] or list(ins)
            src = srcs[0] if srcs else "tx:" + h
            for o in d.get("outputs") or []:
                if o["address"] in ins: continue    # change back to the paying wallet
                if suspect and not same(o["address"], suspect): continue
                add.append({"source": src, "target": o["address"], "amount": o["value"], "unit": "BTC", "tx": h, "time": t})
        else:
            for e in d.get("edges") or []:
                s_, t_ = e["source"], e["target"]
                if str(s_).startswith("tx:") or str(t_).startswith("tx:"): continue
                if vset and not is_victim(s_): continue
                if suspect and not same(t_, suspect): continue
                add.append({**e, "tx": h, "time": t or e.get("time")})
        if not add: warns.append(f"Victim tx {h[:12]}… has no payment matching the victim/suspect addresses.")
        for e in add:
            e = dict(e, _a=float(e["amount"]), _u=unit_of(e), _t=tnum(e.get("time")), _i=len(E), _fetched=True)
            E.append(e); seeds.append(e); fetched.append(h)
            for k2 in ("source", "target"):
                if e[k2] not in nodes: nodes[e[k2]] = {"id": e[k2], "chain": c, **(chains.node(c, e[k2]) if not str(e[k2]).startswith("tx:") else {})}
    if not seeds: raise ValueError("no victim payments found: check the victim address/tx is on the graph (or paste the payment tx hash)")
    seed_ids = {s["_i"] for s in seeds}
    # ---- adjacency ----
    outs = defaultdict(list); ins = defaultdict(list)
    for e in E:
        if e["_i"] in seed_ids: continue
        if is_victim(e["source"]): continue      # other victim outflows are not part of the loss
        outs[e["source"]].append(e); ins[e["target"]].append(e)
    stop = {i: _cat(nodes.get(i), vset) for i in set(nodes) | {e["target"] for e in E}}
    def converter(i): n = nodes.get(i) or {}; return n.get("kind") == "swap"
    # reachable from seed targets (not through stop nodes)
    reach = set(); dq = deque()
    depth = {}
    for s in seeds:
        if s["target"] not in depth: depth[s["target"]] = 1; dq.append(s["target"])
    while dq:
        x = dq.popleft(); reach.add(x)
        if stop.get(x): continue
        for e in outs[x]:
            y = e["target"]
            if y not in depth: depth[y] = depth[x] + 1; dq.append(y)
    # ---- lots ----
    seq = [0]
    def nseq(): seq[0] += 1; return seq[0]
    pools = defaultdict(lambda: defaultdict(list))   # node -> unit -> [Lot]
    tainted_in = defaultdict(lambda: defaultdict(float))
    edge_taint = {}            # edge _i -> tainted amount
    edge_note = defaultdict(list)
    for s in seeds:
        pools[s["target"]][s["_u"]].append(Lot(s["_t"], s["_a"], s["_a"], nseq())); edge_taint[s["_i"]] = s["_a"]; tainted_in[s["target"]][s["_u"]] += s["_a"]
    # clean inflows from outside the tainted sub-graph are added when the node is processed
    def avail(l, t): return l.t is None or t is None or l.t <= t
    def draw(lots, amt, t):
        """take `amt` from lots per the method; returns tainted amount taken and amount actually covered by lots"""
        av = [l for l in lots if l.amt > EPS and avail(l, t)]
        tot = sum(l.amt for l in av)
        if tot <= EPS: return 0.0, 0.0
        take = min(amt, tot); tainted = 0.0
        if method == "proportional":
            f = take / tot
            for l in av: tk = l.taint * f; tainted += tk; l.taint -= tk; l.amt -= l.amt * f
        else:
            av.sort(key=lambda l: ((l.t if l.t is not None else -1), l.seq), reverse=(method == "lifo"))
            left = take
            for l in av:
                if left <= EPS: break
                q = min(l.amt, left); fr = q / l.amt if l.amt else 0; tk = l.taint * fr
                tainted += tk; l.taint -= tk; l.amt -= q; left -= q
        return tainted, take
    def value(u, a): pv = px_now(u)[0]; return a * pv if pv else None
    order = []; done = set()
    indeg = {x: sum(1 for e in ins[x] if e["source"] in reach and not stop.get(e["source"])) for x in reach}
    q = deque(sorted([x for x in reach if indeg.get(x, 0) == 0], key=lambda x: depth.get(x, 9)))
    while len(done) < len(reach):
        if not q:
            rest = sorted([x for x in reach if x not in done], key=lambda x: (depth.get(x, 99), x)); q.append(rest[0])
            warns.append("The graph contains a loop; addresses in the loop are processed in hop order and funds arriving after an address was processed are reported with that address's remainder.")
        x = q.popleft()
        if x in done: continue
        done.add(x); order.append(x)
        if not stop.get(x):
            for e in outs[x]:
                y = e["target"]
                if y in indeg and y not in done:
                    indeg[y] -= 1
                    if indeg[y] <= 0: q.append(y)
    conv_out = defaultdict(float); terminals = []; residual = []
    processed = set()
    for x in order:
        # clean inflows on the graph from sources outside the tainted flow
        for e in ins[x]:
            if e["_i"] in edge_taint or e["_i"] in seed_ids: continue
            if e["source"] in reach and not stop.get(e["source"]): continue
            pools[x][e["_u"]].append(Lot(e["_t"], e["_a"], 0.0, nseq()))
        processed.add(x)
        tin = sum(tainted_in[x].values())
        if tin <= EPS: continue
        cat = stop.get(x)
        if cat:
            terminals.append(x); continue
        for e in sorted(outs[x], key=lambda e: ((e["_t"] if e["_t"] is not None else float("inf")), e["_i"])):
            u = e["_u"]; tk = 0.0; notes = []
            if pools[x].get(u) and any(l.amt > EPS for l in pools[x][u]):
                tk, _ = draw(pools[x][u], e["_a"], e["_t"])
            elif converter(x) or e.get("xchain"):
                # value conversion (decoded swap / matched bridge): carry the victim share by USD value across all units held
                units = [uu for uu, ls in pools[x].items() if any(l.amt > EPS and avail(l, e["_t"]) for l in ls)]
                vals = {uu: value(uu, sum(l.amt for l in pools[x][uu] if avail(l, e["_t"]))) for uu in units}
                if units:
                    out_v = value(u, e["_a"]) or (float(e["usd"]) if e.get("usd") else None)
                    if all(v for v in vals.values()) and out_v:
                        tot_v = sum(vals.values()); share = min(1.0, out_v / tot_v) if tot_v else 0; tv = 0.0
                        for uu in units:
                            amt_u = sum(l.amt for l in pools[x][uu] if avail(l, e["_t"])) * share
                            t_u, got = draw(pools[x][uu], amt_u, e["_t"]); conv_out[uu] += t_u; tv += value(uu, t_u) or 0
                        tk = min(e["_a"], tv / (value(u, 1) or (out_v / e["_a"])))
                    else:   # no prices: carry the victim share of the largest pool
                        uu = max(units, key=lambda k: sum(l.amt for l in pools[x][k]))
                        ls = pools[x][uu]; tot = sum(l.amt for l in ls); tt = sum(l.taint for l in ls)
                        fr = tt / tot if tot else 0; tk = e["_a"] * fr; conv_out[uu] += tt
                        for l in ls: l.taint = 0; l.amt = 0
                    notes.append("value carried across a decoded swap" if converter(x) else "value carried across a bridge hop")
            if tk > EPS:
                edge_taint[e["_i"]] = tk; edge_note[e["_i"]] += notes
                y = e["target"]
                if y in processed:
                    residual.append((y, u, tk, "late"))
                else:
                    pools[y][u].append(Lot(e["_t"], e["_a"], tk, nseq())); tainted_in[y][u] += tk
    # ---- remainders ----
    rem = []
    for x in order:
        if stop.get(x): continue
        for u, ls in pools[x].items():
            r = sum(l.taint for l in ls)
            if r > 1e-9: rem.append((x, u, r))
    for y, u, tk, _ in residual:
        if not stop.get(y): rem.append((y, u, tk))
    # live balances for remainder addresses (native coin)
    bal = {}
    cand = []
    for x, u, r in rem:
        n = nodes.get(x) or {}; c = n.get("chain") or chains.detect(x)[0]
        if str(x).startswith("tx:") or n.get("kind") == "swap": continue
        if NATIVE.get(c) == u: cand.append((x, c))
    cand = list(dict.fromkeys(cand))[:20]
    if live_balances and cand:
        try:
            res = await asyncio.wait_for(asyncio.gather(*[_balance(c, x) for x, c in cand]), 12)
            for (x, c), b in zip(cand, res):
                if b is not None: bal[x] = (b, t_gen, "live")
        except asyncio.TimeoutError: errs.append("live balance check timed out (partial)")
    for x, u, r in rem:
        n = nodes.get(x) or {}
        if x not in bal and n.get("balance") is not None and (n.get("unit") or "").upper() == u:
            try: bal[x] = (float(n["balance"]), None, "graph")
            except Exception: pass
    # ---- categorise ----
    dest = []   # rows: category, node, unit, amount, lead, extra
    for x in terminals:
        n = nodes.get(x) or {}; cat = stop[x]
        for u, a in tainted_in[x].items():
            if a > 1e-9: dest.append({"cat": cat, "id": x, "unit": u, "amount": a})
    held_rows = []
    for x, u, r in rem:
        n = nodes.get(x) or {}
        if str(x).startswith("tx:") or n.get("kind") == "swap": dest.append({"cat": "untraced", "id": x, "unit": u, "amount": r}); continue
        has_out = bool(outs.get(x))
        if x in bal and NATIVE.get(n.get("chain") or chains.detect(x)[0]) == u:
            b, bt, src = bal[x]; h = min(r, max(b, 0.0))
            if h > 1e-9: dest.append({"cat": "held", "id": x, "unit": u, "amount": h, "balance": b, "balance_src": src, "balance_time": bt}); held_rows.append(x)
            if r - h > 1e-9: dest.append({"cat": "untraced", "id": x, "unit": u, "amount": r - h})
        else:
            dest.append({"cat": "untraced" if has_out else "end", "id": x, "unit": u, "amount": r})
    # ---- valuation ----
    need = defaultdict(set)
    for s in seeds:
        sym = PXSYM.get(s["_u"])
        if sym and s["_t"]: need[sym].add(day(s["_t"]))
    hp = await _candles(need, errs) if need else {}
    gdays = {day(s["_t"]) for s in seeds if s["_t"]}
    ghist, gtoday = await _gbp(gdays, errs)
    g_now = gtoday[0] if gtoday else None
    def hist_usd(u, a, t):
        if u in STABLE: return a, "par"
        sym = PXSYM.get(u)
        if sym and t and (sym, day(t)) in hp: return a * hp[(sym, day(t))], "daily close"
        return None, None
    def lab(i):
        n = nodes.get(i) or {}; ul = case_labels.get(i) if isinstance(case_labels, dict) else None
        if isinstance(ul, dict) and ul.get("name"): return ul["name"]
        if n.get("name"): return n["name"]
        if isinstance(n.get("suggested"), dict): return n["suggested"].get("label")
        return None
    chain_of = lambda i: (nodes.get(i) or {}).get("chain") or chains.detect(str(i).removeprefix("tx:"))[0]
    # totals per asset
    tot = {}
    pay_rows = []
    for s in sorted(seeds, key=lambda s: (s["_t"] or 0, s["_i"])):
        u = s["_u"]; a = s["_a"]; t = s["_t"]; hv, basis = hist_usd(u, a, t)
        gr = ghist.get(day(t)) if t else None
        pn, pb = px_now(u)
        row = {"tx": s.get("tx"), "time": t, "time_uk": uk(t), "time_utc": utc(t), "from": s.get("_viatx") or s["source"], "from_label": lab(s.get("_viatx") or s["source"]), "to": s["target"], "to_label": lab(s["target"]),
               "chain": chain_of(s["source"]) or chain_of(s["target"]), "asset": u, "amount": r8(a), "count": int(s.get("count") or 1),
               "usd_then": round(hv, 2) if hv is not None else None, "usd_then_basis": basis, "gbp_then": round(hv * gr[0], 2) if hv is not None and gr else None,
               "gbp_rate_date": gr[1] if gr else None, "usd_now": round(a * pn, 2) if pn else None, "gbp_now": round(a * pn * g_now, 2) if pn and g_now else None,
               "source": "fetched from chain" if s.get("_fetched") else "graph", "aggregated": int(s.get("count") or 1) > 1}
        if row["aggregated"]: row["note"] = f"{row['count']} transfers merged on the graph" + (f" ({uk(tnum(s.get('first')))} – {uk(tnum(s.get('last')))})" if s.get("first") and s.get("last") else "") + "; valued at the date of the last transfer"
        pay_rows.append(row)
        T = tot.setdefault(u, {"asset": u, "amount": 0.0, "payments": 0, "usd_then": 0.0, "gbp_then": 0.0, "then_complete": True, "usd_now": None, "gbp_now": None, "price_now": pn, "price_basis": pb})
        T["amount"] += a; T["payments"] += row["count"]
        if row["usd_then"] is not None: T["usd_then"] += row["usd_then"]
        else: T["then_complete"] = False
        if row["gbp_then"] is not None: T["gbp_then"] += row["gbp_then"]
        else: T["then_complete"] = False
    for T in tot.values():
        T["amount"] = r8(T["amount"])
        if T["price_now"]: T["usd_now"] = round(T["amount"] * T["price_now"], 2); T["gbp_now"] = round(T["usd_now"] * g_now, 2) if g_now else None
        T["usd_then"] = round(T["usd_then"], 2) if T["usd_then"] else None; T["gbp_then"] = round(T["gbp_then"], 2) if T["gbp_then"] else None
    # destination rows enriched
    def tainted_edges_into(i): return [e for e in E if e["_i"] in edge_taint and e["target"] == i]
    for d in dest:
        n = nodes.get(d["id"]) or {}; u = d["unit"]; pn, _ = px_now(u)
        d.update(label=lab(d["id"]), chain=chain_of(d["id"]), amount=r8(d["amount"]), usd_now=round(d["amount"] * pn, 2) if pn else None)
        d["gbp_now"] = round(d["usd_now"] * g_now, 2) if d["usd_now"] is not None and g_now else None
        d["cat_name"] = CATNAME[d["cat"]]; d["lead"] = []
        ie = tainted_edges_into(d["id"])
        d["txs"] = [{"tx": e.get("tx"), "time": e["_t"], "time_uk": uk(e["_t"]), "time_utc": utc(e["_t"]), "amount": r8(edge_taint[e["_i"]])} for e in ie if e.get("tx")][:20]
        if d["cat"] == "exchange":
            ent, lead, how = _entity(n, case_labels); d["entity"] = ent; d["attribution"] = how
            if lead: d["lead"].append("suggested (inferred) deposit address")
            tags = sorted({str(t) for e in ie for t in ([e.get("destination_tag")] if e.get("destination_tag") is not None else []) + list(e.get("destination_tags") or [])})
            if tags: d["destination_tags"] = tags
        if d["cat"] == "sanctioned":
            d["sanctions"] = [s.get("wording") for s in (n.get("sanctions") or []) if isinstance(s, dict)][:3]
        if any(e.get("heur") for e in ie): d["lead"].append("reached via a heuristic edge")
        if d.get("lead"): d["lead_text"] = LEAD
    # hop-by-hop table
    hops = []
    for e in sorted([e for e in E if e["_i"] in edge_taint], key=lambda e: (depth.get(e["source"], 0) if e["_i"] not in seed_ids else 0, e["_t"] or 0, e["_i"])):
        tk = edge_taint[e["_i"]]; tgt = e["target"]; n = nodes.get(tgt) or {}
        leads = []
        if e.get("heur"): leads.append("heuristic edge (" + ("peel-chain change" if e.get("peel") else "bridge match") + ")")
        if isinstance(n.get("suggested"), dict) and stop.get(tgt) == "exchange": leads.append("inferred deposit label")
        if e.get("swap") and not (e["swap"] or {}).get("decoded"): leads.append("swap partly inferred")
        onward = CATNAME.get(stop.get(tgt)) if stop.get(tgt) else ("swap" if n.get("kind") == "swap" else "followed" if outs.get(tgt) else "end of graph")
        hops.append({"hop": 0 if e["_i"] in seed_ids else depth.get(e["source"], 0), "tx": e.get("tx"), "time": e["_t"], "time_uk": uk(e["_t"]), "time_utc": utc(e["_t"]),
                     "chain": chain_of(e["source"]) or chain_of(tgt), "from": e["source"], "from_label": lab(e["source"]), "to": tgt, "to_label": lab(tgt),
                     "asset": e["_u"], "amount": r8(e["_a"]), "tainted": r8(tk), "pct": round(100 * tk / e["_a"], 2) if e["_a"] else None,
                     "count": int(e.get("count") or 1), "victim_payment": e["_i"] in seed_ids, "onward": onward,
                     "basis": "; ".join(edge_note[e["_i"]] + (["cross-chain bridge hop"] if e.get("xchain") and not e.get("heur") else [])) or ("victim payment" if e["_i"] in seed_ids else "on-chain transfer"),
                     "lead": leads, "destination_tag": e.get("destination_tag"), "destination_tags": e.get("destination_tags")})
    hops = hops[:400]
    # summaries per category
    cats = []
    for k, h, w in CATS:
        rows = [d for d in dest if d["cat"] == k]
        if not rows: continue
        by_u = defaultdict(float)
        for d in rows: by_u[d["unit"]] += d["amount"]
        cats.append({"cat": k, "name": h, "wording": w, "by_asset": {u: r8(a) for u, a in by_u.items()},
                     "usd_now": round(sum(d["usd_now"] or 0 for d in rows), 2), "gbp_now": round(sum(d["gbp_now"] or 0 for d in rows), 2) if g_now else None,
                     "rows": len(rows), "lead": any(d.get("lead") for d in rows)})
    loss_usd_now = sum(T["usd_now"] or 0 for T in tot.values())
    for c in cats: c["pct_of_loss"] = round(100 * c["usd_now"] / loss_usd_now, 1) if loss_usd_now else None
    swaps = [{"node": i, "text": ((nodes[i].get("swap") or {}).get("text")), "venue": (nodes[i].get("swap") or {}).get("venue"), "tx": (nodes[i].get("swap") or {}).get("tx"),
              "decoded": (nodes[i].get("swap") or {}).get("decoded")} for i in order if (nodes.get(i) or {}).get("kind") == "swap" and sum(tainted_in[i].values()) > EPS]
    bridges_x = [{"tx": e.get("tx"), "dst_tx": e.get("dst_tx"), "bridge": (e.get("bridge") or {}).get("bridge"), "heuristic": bool(e.get("heur")), "tainted": r8(edge_taint[e["_i"]]), "asset": e["_u"]}
                 for e in E if e.get("xchain") and e["_i"] in edge_taint]
    held = [d for d in dest if d["cat"] == "held"]
    recon = []
    for u, T in tot.items():
        acc = sum(d["amount"] for d in dest if d["unit"] == u) + conv_out.get(u, 0)
        recon.append({"asset": u, "lost": T["amount"], "accounted": r8(acc), "converted_out": r8(conv_out.get(u, 0)), "difference": r8(T["amount"] - acc)})
    leads_present = any(h["lead"] for h in hops) or any(d.get("lead") for d in dest)
    undated = sum(1 for s in seeds if not s["_t"])
    if undated: warns.append(f"{undated} victim payment(s) have no date on the graph: they are valued at today's price only.")
    if any(s.get("count", 1) and int(s.get("count") or 1) > 1 for s in seeds): warns.append("Some victim payments are several transfers merged on the graph; they are valued at the date of the last transfer.")
    if method != "proportional" and any(e["_t"] is None for e in E if e["_i"] in edge_taint):
        warns.append("Some flows have no date on the graph, so FIFO/LIFO falls back to the order the flows appear in the graph for those flows.")
    out = {
        "version": "1.0", "generated": int(t_gen), "generated_uk": uk(t_gen), "generated_utc": utc(t_gen),
        "method": method, "method_name": METHODS[method][0], "method_text": METHODS[method][1],
        "spec": {"victims": victims, "victim_txs": vtxs, "suspect": suspect, "method": method},
        "payments": pay_rows, "totals": list(tot.values()),
        "total_usd_now": round(loss_usd_now, 2) if loss_usd_now else None, "total_gbp_now": round(loss_usd_now * g_now, 2) if loss_usd_now and g_now else None,
        "total_usd_then": round(sum(T["usd_then"] or 0 for T in tot.values()), 2) if any(T["usd_then"] for T in tot.values()) else None,
        "total_gbp_then": round(sum(T["gbp_then"] or 0 for T in tot.values()), 2) if any(T["gbp_then"] for T in tot.values()) else None,
        "then_complete": all(T["then_complete"] for T in tot.values()),
        "categories": cats, "destinations": sorted(dest, key=lambda d: (-(d["usd_now"] or 0), d["cat"])), "held": held,
        "held_usd_now": round(sum(d["usd_now"] or 0 for d in held), 2), "held_gbp_now": round(sum(d["gbp_now"] or 0 for d in held), 2) if g_now else None,
        "swaps": swaps, "bridges": bridges_x, "hops": hops, "reconciliation": recon,
        "gbp_rate_now": {"rate": gtoday[0], "date": gtoday[1], "source": gtoday[2]} if gtoday else None,
        "price_sources": "Today: Coinbase spot (CoinGecko when available); stablecoins at $1.00. On the day: Coinbase Exchange daily close (UTC day) for BTC, ETH, SOL and XRP (and wrapped versions); stablecoins at par; no daily price for other tokens. GBP: ECB euro reference rates via the Frankfurter API (previous working day at weekends), Coinbase spot rate as a fallback.",
        "leads_present": leads_present, "warnings": warns, "errors": errs,
        "caveats": [
            "This is an analysis of the transactions shown on the ChainTrace graph. It is only as complete as the graph: flows that were not looked up are not included.",
            f"Amounts attributed to victim funds depend on the tracing method ({METHODS[method][0]}). Other methods give different, equally arguable figures. State the method when quoting a figure.",
            "‘Still held’ is capped at the address balance (checked live for the native coin where possible, otherwise as recorded on the graph). Balances change: check again before applying for restraint or account freezing.",
            "Exchange attributions are labels from public datasets, the investigator or inference. Confirm with the exchange (e.g. production order) before relying on them.",
            "Items marked ‘lead’ come from heuristics (heuristic bridge matches, peel-chain change detection, inferred deposit addresses). " + LEAD + ".",
        ],
    }
    out["csv"] = to_csv(out)
    return out

def to_csv(r):
    b = io.StringIO(); w = csv.writer(b)
    w.writerow(["section", "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"])
    w.writerow(["meta", "generated", r["generated_uk"], r["generated_utc"]])
    w.writerow(["meta", "method", r["method_name"], r["method_text"]])
    w.writerow(["meta", "victim addresses", " ".join(r["spec"]["victims"])])
    w.writerow(["meta", "victim tx hashes", " ".join(r["spec"]["victim_txs"])])
    w.writerow(["meta", "suspect start", r["spec"]["suspect"] or ""])
    w.writerow(["meta", "caveat", LEAD])
    w.writerow([])
    w.writerow(["totals", "asset", "amount", "payments", "usd_on_day", "gbp_on_day", "on_day_complete", "usd_today", "gbp_today", "price_today_usd"])
    for T in r["totals"]: w.writerow(["totals", T["asset"], T["amount"], T["payments"], T["usd_then"], T["gbp_then"], T["then_complete"], T["usd_now"], T["gbp_now"], T["price_now"]])
    w.writerow([])
    w.writerow(["payment", "time_uk", "time_utc", "chain", "tx", "from", "to", "asset", "amount", "usd_on_day", "gbp_on_day", "usd_today"])
    for p in r["payments"]: w.writerow(["payment", p["time_uk"], p["time_utc"], p["chain"], p["tx"], p["from"], p["to"], p["asset"], p["amount"], p["usd_then"], p["gbp_then"], p["usd_now"]])
    w.writerow([])
    w.writerow(["destination", "category", "entity_or_label", "chain", "address", "asset", "amount", "usd_today", "gbp_today", "deposit_tags", "lead", "balance"])
    for d in r["destinations"]:
        w.writerow(["destination", d["cat_name"], d.get("entity") or d.get("label") or "", d.get("chain"), d["id"], d["unit"], d["amount"], d.get("usd_now"), d.get("gbp_now"),
                    " ".join(d.get("destination_tags") or []), "; ".join(d.get("lead") or []), d.get("balance") if d.get("balance") is not None else ""])
    w.writerow([])
    w.writerow(["hop", "hop_no", "time_uk", "time_utc", "chain", "tx", "from", "to", "asset", "amount", "victim_funds", "pct", "basis_and_leads"])
    for h in r["hops"]:
        w.writerow(["hop", h["hop"], h["time_uk"], h["time_utc"], h["chain"], h["tx"], h["from"], h["to"], h["asset"], h["amount"], h["tainted"], h["pct"], "; ".join([h["basis"]] + h["lead"])])
    w.writerow([])
    w.writerow(["reconciliation", "asset", "lost", "accounted", "converted_out", "difference_fees_rounding"])
    for x in r["reconciliation"]: w.writerow(["reconciliation", x["asset"], x["lost"], x["accounted"], x["converted_out"], x["difference"]])
    return b.getvalue()
