#!/usr/bin/env python3
"""ChainTrace watchlist checker for scheduled runs on the box (no browser, no server needed).

Reads a watchlist JSON (the browser's "Export watchlist" format), checks every address with the same code as
POST /api/watch/check, keeps last-seen cursors in a local state file, and prints new alert events as markdown or JSON.

  python3 watch_check.py                       # markdown summary of new events (default files under data/)
  python3 watch_check.py --format json         # machine-readable
  python3 watch_check.py --add 0xADDR --name "Suspect wallet" --ref OP-1/2026 --out-usd 10000
  python3 watch_check.py --export-browser /tmp/wl.json   # watchlist + current cursors, for "Import" in the browser

Files (all gitignored, private case data, never commit): data/watchlist.json, data/watch_state.json, data/watch_events.jsonl
Exit code: 0 ok (with or without events), 2 bad input, 3 every check failed."""
import argparse, asyncio, json, os, sys, time, uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
import watch, chains
UK = ZoneInfo("Europe/London"); BASE = os.environ.get("CHAINTRACE_URL", "https://chaintrace-d4fv.onrender.com").rstrip("/")
FMT = "chaintrace-watchlist"
def t_uk(ts): return datetime.fromtimestamp(ts, UK).strftime("%d/%m/%Y %H:%M %Z") if ts else "unconfirmed (mempool)"
def t_utc(ts): return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M UTC") if ts else ""
def load(p, default):
    try: return json.load(open(p))
    except FileNotFoundError: return default
def save(p, d):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True); tmp = p + ".tmp"; json.dump(d, open(tmp, "w"), indent=1); os.replace(tmp, p)
def items_of(wl):
    if isinstance(wl, list): return wl
    if wl.get("format") not in (None, FMT): raise SystemExit(f"not a {FMT} file")
    return wl.get("items") or []
def money(v): return "–" if v is None else f"${v:,.2f}"
def amt(e): return ", ".join(f"{x['amount']:+,.8g} {x['unit']}" for x in e.get("amounts") or [])
SEVI = {"high": "🔴 HIGH", "medium": "🟠 MED", "low": "🔵 LOW"}
def md(run, mx=25):
    ev = run["events"]; more = max(0, len(ev) - mx); ev = ev[:mx]; L = [f"**ChainTrace watchlist** · {t_uk(run['checked_at'])} ({t_utc(run['checked_at'])}) · {run['watched']} watched · "
                             f"{len(ev)} new alert(s)" + (f" · {len(run['errors'])} check error(s)" if run["errors"] else "") + (f" · {run['baselined']} baselined" if run["baselined"] else "")]
    for e in ev:
        who = f"{e.get('name') or e['address'][:12]}" + (f" [{e['ref']}]" if e.get("ref") else "") + f" ({e['chain'].upper()})"
        if e["type"] == "tx":
            cp = e.get("counterparty") or {}; arrow = "→" if e.get("dir") == "out" else "←"
            cps = f" {arrow} {cp.get('name') or cp.get('id', '')[:14]}" + (f" [{cp['cat']}]" if cp.get("cat") else "") if cp else ""
            L.append(f"- {SEVI[e['severity']]} · {t_uk(e.get('time'))} · {who} {'OUT' if e.get('dir') == 'out' else 'IN'} {money(e.get('usd'))} ({amt(e)}){cps}"
                     f" · {'; '.join(e['rules'])} · tx {e['tx_url']} · graph {BASE}/?q={e['tx']}")
        else: L.append(f"- {SEVI[e['severity']]} · {t_uk(e.get('time'))} · {who} · {'; '.join(e['rules'])}" + (f" · {BASE}/?q={e['address']}" if e["type"] == "balance" else ""))
    if more: L.append(f"- … {more} more alert(s) (lowest severity) omitted; run with --format json or open the Watchlist drawer for all")
    for x in run["errors"]: L.append(f"- ⚠️ {x['name'] or x['address'][:12]}: {x['error']}")
    for x in run["warnings"]: L.append(f"- ℹ️ {x}")
    if not ev and not run["errors"]: L.append("No new alert events since the last check.")
    return "\n".join(L)
async def run_checks(items, state, since_h):
    cur = state.setdefault("cursors", {}); out = []
    todo = []
    for it in items:
        it = dict(it); it.setdefault("id", it.get("address"))
        c = cur.get(it["id"]) or it.get("cursor")
        if c: it["cursor"] = c
        elif since_h: it["since"] = int(time.time() - since_h * 3600)
        todo.append(it)
    for i in range(0, len(todo), 6):   # batches of 6, staggered inside, short pause between batches (free API rate limits)
        if i: await asyncio.sleep(2)
        out += await watch.check_many(todo[i:i + 6], budget=75, conc=3, per=25)
    return todo, out
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", default=os.path.join(H, "data", "watchlist.json")); ap.add_argument("--state", default=os.path.join(H, "data", "watch_state.json"))
    ap.add_argument("--format", choices=("md", "json"), default="md"); ap.add_argument("--max", type=int, default=25, help="max alert lines in markdown output"); ap.add_argument("--min-severity", choices=("low", "medium", "high"), default="low")
    ap.add_argument("--since-hours", type=float, default=0, help="for addresses never checked: alert on the last N hours instead of just setting a baseline")
    ap.add_argument("--dry-run", action="store_true", help="do not update cursors / event log")
    ap.add_argument("--add"); ap.add_argument("--name"); ap.add_argument("--ref"); ap.add_argument("--note")
    ap.add_argument("--out-usd", type=float); ap.add_argument("--bal-pct", type=float); ap.add_argument("--no-any-tx", action="store_true")
    ap.add_argument("--export-browser", metavar="FILE", help="write watchlist + cursors in the browser import format and exit")
    a = ap.parse_args()
    wl = load(a.list, {"format": FMT, "version": 1, "items": []}); items = items_of(wl); state = load(a.state, {"cursors": {}})
    if a.add:
        c, k = chains.detect(a.add)
        if not c or k != "address": print("not a BTC/ETH/SOL address", file=sys.stderr); return 2
        if any(x["address"].lower() == a.add.lower() for x in items): print("already watched", file=sys.stderr); return 2
        r = dict(watch.DEFAULT_RULES, any_tx=not a.no_any_tx, out_usd=a.out_usd, bal_pct=a.bal_pct)
        items.append({"id": uuid.uuid4().hex[:12], "address": a.add, "chain": c, "name": a.name or "", "ref": a.ref or "", "note": a.note or "", "rules": r, "added": int(time.time() * 1000)})
        save(a.list, {"format": FMT, "version": 1, "exported": int(time.time() * 1000), "items": items}); print(f"added {a.add} ({c}); {len(items)} watched"); return 0
    if a.export_browser:
        save(a.export_browser, {"format": FMT, "version": 1, "exported": int(time.time() * 1000), "source": "watch_check.py",
                                "items": [dict(x, cursor=state["cursors"].get(x.get("id") or x["address"]) or x.get("cursor")) for x in items]})
        print(f"wrote {len(items)} item(s) to {a.export_browser}"); return 0
    if not items: print("watchlist is empty: export it from the ChainTrace Watchlist drawer to " + a.list + " or use --add", file=sys.stderr); return 2
    t0 = time.time(); todo, res = asyncio.run(run_checks(items, state, a.since_hours))
    minsev = watch.SEV[a.min_severity]; events = []; errors = []; warns = []; summaries = []; baselined = 0
    for it, r in zip(todo, res):
        if r["status"] in ("ok", "baseline"):
            if not a.dry_run: state["cursors"][it["id"]] = r["cursor"]
            baselined += r["status"] == "baseline"
            events += [e for e in r["events"] if watch.SEV[e["severity"]] >= minsev]
            warns += [f"{it.get('name') or it['address'][:12]}: {w}" for w in r.get("warnings") or []]
        else: errors.append({"id": it["id"], "address": it["address"], "name": it.get("name"), "error": r.get("error") or r["status"]})
        summaries.append({"id": it["id"], "address": it["address"], "name": it.get("name"), "ref": it.get("ref"), "status": r["status"], **(r.get("summary") or {})})
    events.sort(key=lambda e: (-watch.SEV[e["severity"]], -(e.get("time") or 9e12)))
    run = {"format": "chaintrace-watch-run", "checked_at": int(time.time()), "elapsed": round(time.time() - t0, 1), "watched": len(items),
           "new_events": len(events), "baselined": baselined, "events": events, "errors": errors, "warnings": warns[:10], "addresses": summaries}
    if not a.dry_run:
        state["last_run"] = run["checked_at"]; save(a.state, state)
        if events:
            with open(os.path.join(os.path.dirname(a.state), "watch_events.jsonl"), "a") as f:
                for e in events: f.write(json.dumps(e) + "\n")
    print(json.dumps(run, indent=1) if a.format == "json" else md(run, a.max))
    return 3 if errors and len(errors) == len(items) else 0
if __name__ == "__main__": sys.exit(main())
