"""ChainTrace server-side watchlist email alerts (no browser needed).

Design (Render free tier: sleeps when idle, ephemeral disk; public GitHub repo):
- A scheduler outside Render (GitHub Actions cron, .github/workflows/watch-alerts.yml) wakes the service and calls
  POST /api/alerts/run with a bearer token (ALERTS_TOKEN). The site password is not needed or shared.
- The watchlist (case data) lives only in the Render env var ALERTS_WATCHLIST: plain JSON, or "enc:..." sealed with
  ALERTS_KEY (Watchlist › ✉ Email › "Create sealed value" produces the sealed form). It is never in the repo.
- State (last-seen cursors, mutes, sent-alert ids) is kept on Render's disk AND returned to the caller as an encrypted
  blob (Fernet, key derived from ALERTS_KEY). The GitHub workflow stores that opaque blob in the Actions cache and
  sends it back next run, so cursors survive Render restarts/redeploys/sleeps. Newest revision wins.
  Lost state => addresses are re-baselined silently (missed alerts possible, never a flood of old ones).
- Email: pluggable sender (Resend HTTPS API, SMTP, or mock). Render free blocks SMTP ports 25/465/587: use Resend there
  (or an SMTP provider on port 2525). Recipients: ALERT_EMAIL_TO (comma-separated).
- Dedupe: per-address cursors (seen tx ids + last time) plus a ring of sent alert ids. A failed send does not advance
  the cursors of the affected addresses, so the alert is retried next run.
CLI: python3 alerts.py --gen-secret   (prints a random value for ALERTS_TOKEN / ALERTS_KEY; run it yourself)"""
import os, json, time, hashlib, base64, asyncio, secrets, html, smtplib, ssl
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from email.message import EmailMessage
H = os.path.dirname(os.path.abspath(__file__))
UK = ZoneInfo("Europe/London")
FMT = "chaintrace-watchlist"
MAX_SENT = 2000
SEV = {"high": 3, "medium": 2, "low": 1}
SEVI = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
SEVC = {"high": "#d7263d", "medium": "#f08a24", "low": "#3a7bd5"}
def env(k, d=None): return os.environ.get(k, d)
def adir():
    """private, gitignored state dir: ALERTS_DIR, else next to the cache (Render: /tmp), else data/alerts"""
    if env("ALERTS_DIR"): return env("ALERTS_DIR")
    if env("CHAINTRACE_CACHE"): return os.path.join(os.path.dirname(env("CHAINTRACE_CACHE")), "ct-alerts")
    return os.path.join(H, "data", "alerts")
def base_url(): return (env("CHAINTRACE_PUBLIC_URL") or "https://chaintrace-d4fv.onrender.com").rstrip("/")

# ---------------- crypto (Fernet; key derived from ALERTS_KEY, any long random string) ----------------
def _fernet():
    k = env("ALERTS_KEY")
    if not k or len(k) < 24: return None
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"chaintrace-alerts-v1|" + k.encode()).digest()))
def seal(obj):
    f = _fernet()
    if not f: raise ValueError("ALERTS_KEY is not set (>= 24 chars)")
    return "enc:" + f.encrypt(json.dumps(obj, separators=(",", ":")).encode()).decode()
def unseal(s, ttl=None):
    f = _fernet()
    if not f: raise ValueError("ALERTS_KEY is not set")
    return json.loads(f.decrypt(s[4:].encode() if s.startswith("enc:") else s.encode(), ttl=ttl))

# ---------------- watchlist (private: env var only) ----------------
def watchlist():
    """-> (items, error). Source: env ALERTS_WATCHLIST (JSON or enc:...), or ALERTS_WATCHLIST_FILE (local/box use)."""
    raw = env("ALERTS_WATCHLIST")
    if not raw and env("ALERTS_WATCHLIST_FILE"):
        try: raw = open(env("ALERTS_WATCHLIST_FILE")).read()
        except Exception as e: return [], f"watchlist file unreadable: {type(e).__name__}"
    if not raw: return [], None
    try: wl = unseal(raw.strip()) if raw.strip().startswith("enc:") else json.loads(raw)
    except Exception as e: return [], f"watchlist could not be read ({type(e).__name__}): check ALERTS_WATCHLIST / ALERTS_KEY"
    items = wl if isinstance(wl, list) else (wl.get("items") or [])
    out = []
    for it in items:
        if not isinstance(it, dict) or not it.get("address"): continue
        it = dict(it); it["id"] = str(it.get("id") or it["address"]); out.append(it)
    return out, None

# ---------------- state: local file + encrypted blob round-tripped by the scheduler ----------------
def _sp(): return os.path.join(adir(), "state.json")
def empty_state(): return {"v": 1, "rev": 0, "cursors": {}, "muted": {}, "sent": [], "runs": [], "last_run": None}
def load_local():
    try:
        s = open(_sp()).read()
        return unseal(s) if s.startswith("enc:") else json.loads(s)
    except Exception: return None
def save_local(st):
    os.makedirs(adir(), exist_ok=True); tmp = _sp() + ".tmp"
    body = seal(st) if _fernet() else json.dumps(st)
    with open(tmp, "w") as f: f.write(body)
    os.chmod(tmp, 0o600); os.replace(tmp, _sp())
def merged_state(blob=None):
    loc = load_local(); rem = None
    if blob:
        try: rem = unseal(blob)
        except Exception: rem = None
    c = [x for x in (loc, rem) if isinstance(x, dict) and x.get("v") == 1]
    if not c: return empty_state(), ("blob unreadable" if blob and not rem else None)
    st = max(c, key=lambda x: (x.get("rev") or 0, x is rem))
    for k, v in empty_state().items(): st.setdefault(k, v)
    return st, (None if not blob or rem else "blob unreadable (wrong ALERTS_KEY?) - used local state")
def commit(st):
    st["rev"] = int(st.get("rev") or 0) + 1; st["sent"] = st["sent"][-MAX_SENT:]; st["runs"] = st["runs"][-30:]
    save_local(st)
    return seal(st) if _fernet() else None

# ---------------- senders ----------------
class MockSender:
    kind = "mock"
    def __init__(self): self.dir = os.path.join(adir(), "outbox")
    def send(self, to, subject, text, htm):
        os.makedirs(self.dir, exist_ok=True)
        p = os.path.join(self.dir, f"{time.time():.6f}.json")
        with open(p, "w") as f: json.dump({"to": to, "subject": subject, "text": text, "html": htm, "from": sender_from(self.kind)}, f)
        return {"id": os.path.basename(p)}
class ResendSender:
    kind = "resend"
    def send(self, to, subject, text, htm):
        import httpx
        r = httpx.post("https://api.resend.com/emails", timeout=20, headers={"Authorization": f"Bearer {env('RESEND_API_KEY')}"},
                       json={"from": sender_from(self.kind), "to": to, "subject": subject, "text": text, "html": htm})
        if r.status_code >= 300: raise RuntimeError(f"Resend HTTP {r.status_code}: {r.text[:200]}")
        return {"id": (r.json() or {}).get("id")}
class SMTPSender:
    kind = "smtp"
    def send(self, to, subject, text, htm):
        m = EmailMessage(); m["From"] = sender_from(self.kind); m["To"] = ", ".join(to); m["Subject"] = subject
        m.set_content(text); m.add_alternative(htm, subtype="html")
        host, port = env("SMTP_HOST"), int(env("SMTP_PORT") or 587); ctx = ssl.create_default_context()
        s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=25) if port == 465 else smtplib.SMTP(host, port, timeout=25)
        try:
            if port != 465 and env("SMTP_STARTTLS", "1") != "0": s.starttls(context=ctx)
            if env("SMTP_USER"): s.login(env("SMTP_USER"), env("SMTP_PASS") or "")
            s.send_message(m)
        finally:
            try: s.quit()
            except Exception: pass
        return {"id": None}
def sender_kind():
    k = (env("ALERTS_SENDER") or "").lower()
    if k in ("mock", "resend", "smtp"): return k
    if env("RESEND_API_KEY"): return "resend"
    if env("SMTP_HOST"): return "smtp"
    return None
def sender():
    return {"mock": MockSender, "resend": ResendSender, "smtp": SMTPSender}.get(sender_kind() or "", lambda: None)()
def sender_from(kind):
    if env("ALERT_EMAIL_FROM"): return env("ALERT_EMAIL_FROM")
    if kind == "smtp" and env("SMTP_USER") and "@" in env("SMTP_USER"): return f"ChainTrace alerts <{env('SMTP_USER')}>"
    return "ChainTrace alerts <onboarding@resend.dev>"
def recipients(): return [x.strip() for x in (env("ALERT_EMAIL_TO") or "").split(",") if "@" in x.strip()]
def mask(e): u, _, d = e.partition("@"); return (u[:2] + "…@" + d) if d else "…"
def config_status():
    k = sender_kind(); miss = []
    if not env("ALERTS_TOKEN"): miss.append("ALERTS_TOKEN")
    if not env("ALERTS_KEY") or len(env("ALERTS_KEY")) < 24: miss.append("ALERTS_KEY")
    if not recipients(): miss.append("ALERT_EMAIL_TO")
    if not k: miss.append("RESEND_API_KEY (or SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS)")
    if not (env("ALERTS_WATCHLIST") or env("ALERTS_WATCHLIST_FILE")): miss.append("ALERTS_WATCHLIST")
    notes = []
    if k == "resend" and "onboarding@resend.dev" in sender_from(k): notes.append("Sending from onboarding@resend.dev: Resend delivers only to the Resend account's own email until a domain is verified (then set ALERT_EMAIL_FROM).")
    if k == "smtp" and int(env("SMTP_PORT") or 587) in (25, 465, 587) and env("RENDER"): notes.append("Render free instances block SMTP ports 25/465/587: use Resend, or an SMTP provider on port 2525.")
    return {"sender": k, "from": sender_from(k) if k else None, "to": [mask(x) for x in recipients()], "token_set": bool(env("ALERTS_TOKEN")),
            "key_set": bool(_fernet()), "missing": miss, "notes": notes}

# ---------------- formatting ----------------
def t_uk(ts): return datetime.fromtimestamp(ts, UK).strftime("%d/%m/%Y %H:%M:%S %Z") if ts else "unconfirmed"
def t_utc(ts): return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if ts else ""
def q_of(chain, v):
    import evmcfg
    return evmcfg.nid(chain, v) if chain in evmcfg.NEW else v
def link(chain, v): from urllib.parse import quote; return f"{base_url()}/?q={quote(q_of(chain, v), safe=':')}"
def amt_txt(e):
    xs = e.get("amounts") or []
    return ", ".join(f"{x['amount']:+,.8g} {x['unit']}" + (f" (${abs(x['usd']):,.2f})" if x.get("usd") is not None else "") for x in xs) or "–"
def cp_txt(cp):
    if not cp: return "–", []
    lab = cp.get("name") or (cp.get("suggested") or {}).get("label")
    flags = []
    if cp.get("cat"): flags.append(cp["cat"])
    if cp.get("suggested") and not cp.get("kind"): flags.append("suggested label: lead only")
    for s in cp.get("sanctions") or []: flags.append(f"SANCTIONS: {s.get('wording') or s.get('entry')}")
    if cp.get("reports"): flags.append(f"{cp['reports']['count']} community report(s), unverified")
    if cp.get("risk"): flags.append(f"risk {cp['risk']}")
    return (f"{cp.get('id')}" + (f" ({lab})" if lab else "")), flags
def event_lines(e):
    who = (e.get("name") or e.get("address")) + (f" [{e['ref']}]" if e.get("ref") else "")
    L = {"Severity": SEVI.get(e.get("severity"), "?"), "Watched": f"{who} · {e.get('chain', '').upper()} · {e.get('address')}",
         "When": f"{t_uk(e.get('time'))} ({t_utc(e.get('time'))})", "Why": "; ".join(e.get("rules") or [])}
    if e.get("type") == "tx":
        cp, flags = cp_txt(e.get("counterparty"))
        L.update({"Direction": "OUT (sent)" if e.get("dir") == "out" else "IN (received)", "Amount": amt_txt(e) + (f" · net ${e['usd']:,.2f}" if e.get("usd") is not None else ""),
                  "Counterparty": cp, "Flags": "; ".join(flags) or "none", "Transaction": e.get("tx_url") or e.get("tx"),
                  "Open in ChainTrace": link(e["chain"], e["tx"]), "Address in ChainTrace": link(e["chain"], e["address"])})
        more = [x for x in (e.get("flagged") or []) if x.get("id") != (e.get("counterparty") or {}).get("id")]
        if more: L["Other flagged counterparties"] = "; ".join(f"{x.get('id')} [{x.get('cat')}]" for x in more[:4])
    else:
        L.update({"Amount": amt_txt(e), "Open in ChainTrace": link(e["chain"], e["address"])})
    return L
CAVEAT = ("Automated alert from public blockchain data. Labels marked 'suggested' and heuristic links are investigative leads, not evidence; "
          "sanctions matches must be confirmed against the official list before any action. Times shown in UK time and UTC.")
def compose(events, errors=0, test=False):
    n = {k: sum(1 for e in events if e.get("severity") == k) for k in SEV}
    first = events[0] if events else {}
    who = first.get("name") or (first.get("address") or "")[:12]
    subj = ("[TEST] " if test else "") + "ChainTrace alert: " + ", ".join(f"{v} {k}" for k, v in n.items() if v) + (f" · {who} ({(first.get('chain') or '').upper()})" if who else "") + (f" +{len(events) - 1} more" if len(events) > 1 else "")
    now = int(time.time())
    txt = [("TEST EMAIL - sample data, not a real alert.\n" if test else "") + f"ChainTrace watchlist: {len(events)} new alert(s) · checked {t_uk(now)} ({t_utc(now)})", ""]
    hb = [f"<div style='font-family:Arial,sans-serif;font-size:14px;color:#1b1f2a'>"]
    if test: hb.append("<p style='background:#fff4ce;padding:8px;border-radius:6px'><b>TEST EMAIL</b>: sample data, not a real alert.</p>")
    hb.append(f"<p><b>ChainTrace watchlist</b>: {len(events)} new alert(s) · checked {html.escape(t_uk(now))} ({html.escape(t_utc(now))})</p>")
    for i, e in enumerate(events, 1):
        L = event_lines(e)
        txt.append(f"#{i} [{L['Severity']}]"); txt += [f"  {k}: {v}" for k, v in L.items() if k != "Severity"]; txt.append("")
        rows = "".join(f"<tr><td style='color:#666;padding:2px 10px 2px 0;vertical-align:top;white-space:nowrap'>{html.escape(k)}</td><td style='padding:2px 0'>"
                       + (f"<a href='{html.escape(v)}'>{html.escape(v)}</a>" if str(v).startswith("http") else html.escape(str(v))) + "</td></tr>" for k, v in L.items() if k != "Severity")
        hb.append(f"<div style='border-left:4px solid {SEVC.get(e.get('severity'), '#999')};padding:6px 10px;margin:10px 0;background:#f7f8fb'>"
                  f"<b style='color:{SEVC.get(e.get('severity'), '#999')}'>#{i} {L['Severity']}</b><table style='font-size:13px;border-collapse:collapse'>{rows}</table></div>")
    if errors: txt.append(f"{errors} watched address(es) could not be checked this run; they are retried next run."); hb.append(f"<p>{errors} watched address(es) could not be checked this run; retried next run.</p>")
    txt += ["", CAVEAT, f"Mute an address: ChainTrace › Watchlist › Email alerts ({base_url()})"]
    hb.append(f"<p style='color:#666;font-size:12px'>{html.escape(CAVEAT)}<br>Mute an address: ChainTrace › Watchlist › Email alerts.</p></div>")
    return subj[:200], "\n".join(txt), "".join(hb)
def sample_events():
    now = int(time.time())
    return [{"type": "tx", "severity": "high", "name": "TEST wallet", "ref": "TEST/0", "chain": "eth", "address": "0x0000000000000000000000000000000000000001",
             "tx": "0x" + "ab" * 32, "tx_url": "https://etherscan.io/tx/0x" + "ab" * 32, "time": now, "dir": "out",
             "amounts": [{"unit": "ETH", "amount": -1.5, "usd": -4500.0}], "usd": 4500.0,
             "counterparty": {"id": "0x0000000000000000000000000000000000000002", "name": "Example sanctioned entity (sample)", "cat": "sanctioned", "risk": 100,
                              "sanctions": [{"wording": "matches OFAC SDN list entry EXAMPLE (sample data): confirm before action"}]},
             "flagged": [], "rules": ["new transaction", "to sanctioned address (sample)"]}]

# ---------------- run ----------------
_LOCK = asyncio.Lock()
async def run(blob=None, budget=None):
    """one scheduled round: check due watched addresses, email new alerts, return counts + encrypted state blob (no case data in clear)"""
    if _LOCK.locked(): return {"ok": False, "busy": True}
    async with _LOCK:
        import watch
        t0 = time.time(); budget = float(budget or env("ALERTS_BUDGET", "45"))
        items, err = watchlist()
        st, serr = merged_state(blob)
        res = {"ok": True, "watched": len(items), "checked": 0, "baselined": 0, "deferred": 0, "errors": 0, "alerts": 0, "emailed": False, "notes": []}
        if err: res.update(ok=False, error=err)
        if serr: res["notes"].append(serr)
        ids = {it["id"] for it in items}
        active = [it for it in items if not it.get("muted") and not st["muted"].get(it["id"])]
        res["muted"] = len(items) - len(active)
        # least recently checked first, so a short budget still rotates through every address
        active.sort(key=lambda it: (st["cursors"].get(it["id"]) or {}).get("checked") or 0)
        todo = [dict(it, cursor=st["cursors"].get(it["id"])) for it in active]
        out = await watch.check_many(todo, budget=budget, conc=3, per=min(20.0, budget - 2)) if todo else []
        sent = set(st["sent"]); minsev = SEV.get(env("ALERTS_MIN_SEVERITY", "low"), 1)
        events, upd = [], {}
        for it, r in zip(todo, out):
            if r["status"] in ("ok", "baseline"):
                res["checked"] += 1; res["baselined"] += r["status"] == "baseline"
                ev = [e for e in r.get("events") or [] if SEV.get(e.get("severity"), 1) >= minsev and e["id"] not in sent]
                upd[it["id"]] = (r["cursor"], ev); events += ev
            elif r["status"] == "deferred": res["deferred"] += 1
            else: res["errors"] += 1
        events.sort(key=lambda e: (-SEV.get(e.get("severity"), 1), -(e.get("time") or 9e12)))
        ok_send = True
        if events:
            s, to = sender(), recipients()
            if not s or not to:
                ok_send = False; res["notes"].append("alerts found but no email sender/recipient configured: cursors held, retried next run")
            else:
                try:
                    subj, txt, htm = compose(events[:60], res["errors"])
                    await asyncio.to_thread(s.send, to, subj, txt, htm); res["emailed"] = True
                except Exception as e:
                    ok_send = False; res["notes"].append(f"email send failed ({type(e).__name__}): retried next run")
        for wid, (cur, ev) in upd.items():
            if ev and not ok_send: continue        # keep the old cursor: these alerts are retried next run
            st["cursors"][wid] = cur
        if ok_send: st["sent"] += [e["id"] for e in events]
        res["alerts"] = len(events)
        st["cursors"] = {k: v for k, v in st["cursors"].items() if k in ids}   # forget removed addresses
        st["last_run"] = int(time.time())
        st["runs"].append({k: res[k] for k in ("checked", "baselined", "deferred", "errors", "alerts", "emailed")} | {"t": st["last_run"], "secs": round(time.time() - t0, 1)})
        res["blob"] = commit(st); res["more"] = res["deferred"] > 0; res["secs"] = round(time.time() - t0, 1)
        if not res["blob"]: res["notes"].append("ALERTS_KEY not set: state kept only on the server disk (lost on restart)")
        return res
def status():
    items, err = watchlist(); st, _ = merged_state()
    return {"config": config_status(), "watchlist_error": err, "last_run": st.get("last_run"), "runs": st.get("runs", [])[-5:],
            "items": [{"id": it["id"], "address": it["address"], "chain": it.get("chain"), "name": it.get("name"), "ref": it.get("ref"),
                       "muted": bool(it.get("muted") or st["muted"].get(it["id"])), "muted_in_env": bool(it.get("muted")),
                       "last_checked": (st["cursors"].get(it["id"]) or {}).get("checked")} for it in items]}
def set_mute(wid, muted):
    items, _ = watchlist()
    if not any(it["id"] == wid for it in items): raise KeyError(wid)
    st, _ = merged_state()
    if muted: st["muted"][wid] = int(time.time())
    else: st["muted"].pop(wid, None)
    commit(st); return {"id": wid, "muted": muted, "note": "Saved on the server; carried into the encrypted state on the next scheduled run. To make it permanent, set \"muted\": true on the item in ALERTS_WATCHLIST."}
def send_test():
    s, to = sender(), recipients()
    if not s: raise RuntimeError("no email sender configured (RESEND_API_KEY, or SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS)")
    if not to: raise RuntimeError("ALERT_EMAIL_TO is not set")
    subj, txt, htm = compose(sample_events(), test=True)
    r = s.send(to, subj, txt, htm)
    return {"sent": True, "sender": s.kind, "to": [mask(x) for x in to], "id": (r or {}).get("id")}

if __name__ == "__main__":
    import sys
    if "--gen-secret" in sys.argv: print(secrets.token_urlsafe(32))
    else: print(__doc__)
