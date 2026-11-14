#!/usr/bin/env python3
"""Scheduler side of ChainTrace email alerts (runs in GitHub Actions; stdlib only).
Wakes the Render service, POSTs /api/alerts/run with the bearer token and the encrypted state blob from the Actions
cache, saves the new blob. Prints counts only: Actions logs of a public repo are public, so no addresses / case data.
Env: CHAINTRACE_URL, ALERTS_TOKEN (secret), STATE_DIR (default .alerts-state)."""
import json, os, sys, time, urllib.request, urllib.error
URL = (os.environ.get("CHAINTRACE_URL") or "https://chaintrace-d4fv.onrender.com").rstrip("/")
TOKEN = os.environ.get("ALERTS_TOKEN") or ""
SD = os.environ.get("STATE_DIR") or ".alerts-state"; BP = os.path.join(SD, "blob")
def req(path, body=None, timeout=120):
    r = urllib.request.Request(URL + path, data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST",
                               headers={"Content-Type": "application/json", "User-Agent": "chaintrace-alerts-scheduler", **({"Authorization": "Bearer " + TOKEN} if body is not None else {})})
    with urllib.request.urlopen(r, timeout=timeout) as f: return f.status, f.read()
def main():
    if len(TOKEN) < 24:
        print("ALERTS_TOKEN secret not set (or too short): skipping. See docs in alerts.py / README."); return 0
    t0 = time.time()
    while True:   # free Render instances sleep: the first request wakes them (can take a minute or more)
        try:
            st, _ = req("/healthz", timeout=60)
            if st == 200: break
        except Exception as e: err = type(e).__name__
        if time.time() - t0 > 300: print("service did not wake within 5 minutes"); return 1
        time.sleep(10)
    print(f"service awake after {time.time() - t0:.0f}s")
    blob = open(BP).read().strip() if os.path.exists(BP) else None
    tot = {"checked": 0, "alerts": 0, "errors": 0, "emailed": 0}
    for rnd in range(8):   # big watchlists: repeat while the server reports deferred addresses
        try: st, b = req("/api/alerts/run", {"blob": blob, "budget": 45}, timeout=110)
        except urllib.error.HTTPError as e:
            print(f"run failed: HTTP {e.code}"); return 1 if e.code in (401, 403) else 0
        except Exception as e: print(f"run failed: {type(e).__name__}"); return 1
        r = json.loads(b)
        if r.get("blob"):
            os.makedirs(SD, exist_ok=True); open(BP, "w").write(r["blob"]); blob = r["blob"]
        for k in tot: tot[k] += int(r.get(k) or 0)
        if not r.get("ok", True): print("server reported a configuration problem (see the Email alerts panel on the site)")
        if not r.get("more"): break
    print(f"done: rounds={rnd + 1} checked={tot['checked']} alerts={tot['alerts']} emailed={tot['emailed']} errors={tot['errors']} state={'saved' if blob else 'none'}")
    return 0
if __name__ == "__main__": sys.exit(main())
