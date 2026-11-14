"""Server-side email alerts test (alerts.py, /api/alerts/*, Watchlist › ✉ Email panel, scheduler script, sanctions as-of date).
Starts its OWN local server on a spare port with throwaway credentials, a temp state dir, a temp sealed watchlist of two public
addresses and the MOCK email sender (emails are written to a temp outbox; nothing is ever sent). No real case data is touched.
Usage: python3 uitest_alerts.py   (SHOTS=0 to skip screenshots)"""
import asyncio, os, sys, json, glob, time, secrets, shutil, socket, subprocess, tempfile, textwrap
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
SHOTS = os.environ.get("SHOTS", "1") != "0"; SHOT = lambda n: os.path.join(H, f"screenshot_v17_alerts_{n}.png")
WATCH_ETH = "0x85faa6c1f2450b9caea300838981c2e6e120c35c"   # public ETH wallet with labelled exchange/bridge counterparties
WATCH_BTC = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"           # genesis address (receives dust constantly): used for the mute test
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
def port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

T = tempfile.mkdtemp(prefix="ct-alerts-test-")
ENV = {k: v for k, v in os.environ.items() if not (k.startswith("SMTP_") or k in ("RESEND_API_KEY", "ALERTS_WATCHLIST", "ALERTS_WATCHLIST_FILE", "ALERT_EMAIL_FROM", "ALERTS_TOKEN", "ALERTS_KEY", "ALERT_EMAIL_TO"))}
TOKEN, KEY, PW = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(16)
ENV.update(ALERTS_DIR=os.path.join(T, "alerts"), ALERTS_SENDER="mock", ALERTS_TOKEN=TOKEN, ALERTS_KEY=KEY, ALERT_EMAIL_TO="test@example.invalid",
           CHAINTRACE_USER="tester", CHAINTRACE_PASSWORD=PW, CHAINTRACE_CACHE=os.path.join(T, "cache.sqlite"))
os.environ.update({k: ENV[k] for k in ("ALERTS_DIR", "ALERTS_SENDER", "ALERTS_TOKEN", "ALERTS_KEY", "ALERT_EMAIL_TO")})
for k in ("RESEND_API_KEY", "SMTP_HOST", "ALERTS_WATCHLIST"): os.environ.pop(k, None)
import alerts
OUT = os.path.join(T, "alerts", "outbox")
def outbox(): return [json.load(open(p)) for p in sorted(glob.glob(os.path.join(OUT, "*.json")))]

def unit():
    # sanctions "as of" date: DateOfIssue children sit at item depth in the streamed OFAC XML (was printed as 0000-00-00)
    import update_sanctions
    x = os.path.join(T, "sdn.xml"); open(x, "w").write(textwrap.dedent("""<?xml version="1.0"?><Sanctions xmlns="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ADVANCED_XML">
      <DateOfIssue><Year>2026</Year><Month>11</Month><Day>13</Day></DateOfIssue><ReferenceValueSets><FeatureTypeValues>
      <FeatureType ID="345">Digital Currency Address - XBT</FeatureType></FeatureTypeValues></ReferenceValueSets></Sanctions>"""))
    out, issued = update_sanctions.parse_ofac(x)
    check("sanctions: OFAC issue date parsed from streamed XML", issued == "2026-11-13", issued)
    sj = json.load(open(os.path.join(H, "data", "sanctions.json")))
    asof = json.dumps({k: v for k, v in sj.items() if k != "addresses" and k != "a"})[:2000]
    check("sanctions: shipped baseline has no 0000-00-00 date", "0000-00-00" not in asof and "2026-" in asof, asof[:160])
    # crypto + state
    v = alerts.seal({"x": 1}); check("seal/unseal round-trip", v.startswith("enc:") and alerts.unseal(v) == {"x": 1})
    os.environ["ALERTS_KEY"] = "another-key-of-sufficient-length-123"
    try: alerts.unseal(v); check("unseal with wrong key refused", False)
    except Exception: check("unseal with wrong key refused", True)
    os.environ["ALERTS_KEY"] = KEY
    # email content (sample events cover the sanctions / suggested-label / reports branches)
    s, t, h = alerts.compose(alerts.sample_events(), test=True)
    for need in ["UTC", "GMT", "/?q=", "sanction", "lead", "$4,500.00", "ETH", "Counterparty", "risk 100"]:
        check(f"compose: text contains {need!r}", need.lower() in t.lower() or need in t, need)
    check("compose: HTML escapes and links", "<a href='https://chaintrace-d4fv.onrender.com/?q=" in h and "<script" not in h)
    ev = dict(alerts.sample_events()[0], chain="bsc", address="0x8894E0a0c962CB723c1976a4421c95949bE2D4E3")
    check("compose: EVM L2 deep link is chain-prefixed", "?q=bsc:" in alerts.compose([ev])[1])

async def server_tests(U):
    A = ("tester", PW); c = httpx.AsyncClient(timeout=150)
    r = await c.post(U + "/api/alerts/run", json={}); check("run: refused without token (401)", r.status_code == 401, r.status_code)
    r = await c.post(U + "/api/alerts/run", json={}, headers={"Authorization": "Bearer " + "x" * 43}); check("run: refused with wrong token (401)", r.status_code == 401, r.status_code)
    r = await c.post(U + "/api/alerts/run", json={}, auth=A); check("run: site password alone is not enough (401)", r.status_code == 401, r.status_code)
    r = await c.get(U + "/api/alerts/status"); check("status: requires site login", r.status_code == 401, r.status_code)
    r = await c.get(U + "/api/alerts/status", auth=A); st = r.json()
    check("status: config complete with mock sender", r.status_code == 200 and st["config"]["missing"] == [] and st["config"]["sender"] == "mock", st.get("config"))
    check("status: recipient masked", st["config"]["to"] == ["te…@example.invalid"], st["config"]["to"])
    check("status: 2 server watch items", len(st["items"]) == 2, len(st["items"]))
    BT = {"Authorization": "Bearer " + TOKEN}
    # mute the BTC item before the first run
    r = await c.post(U + "/api/alerts/mute", json={"id": "btc1", "muted": True}, auth=A); check("mute: saved", r.status_code == 200 and r.json()["muted"], r.text[:120])
    r = await c.post(U + "/api/alerts/mute", json={"id": "nope", "muted": True}, auth=A); check("mute: unknown id -> 404", r.status_code == 404)
    # run 1: ETH item has since=1 -> its recent history counts as new activity -> one digest email; BTC muted -> skipped
    r = await c.post(U + "/api/alerts/run", json={"blob": None}, headers=BT); j = r.json()
    check("run 1: ok, 1 checked, 1 muted", r.status_code == 200 and j["checked"] == 1 and j["muted"] == 1, {k: j.get(k) for k in ("checked", "muted", "alerts", "errors", "notes")})
    check("run 1: alerts found and emailed", j["alerts"] > 0 and j["emailed"] is True, (j["alerts"], j["emailed"]))
    check("run 1: response carries no address / case data in clear", WATCH_ETH.lower() not in r.text.lower() and "Case 7" not in r.text and j["blob"].startswith("enc:"))
    blob1 = j["blob"]; mails = outbox(); check("run 1: exactly one email in mock outbox", len(mails) == 1, len(mails))
    m = mails[-1] if mails else {"subject": "", "text": "", "html": ""}; t = m["text"]
    check("email: to the configured recipient", m.get("to") == ["test@example.invalid"])
    check("email: subject names the alert count", "ChainTrace" in m["subject"] and sum(int(x) for x in __import__("re").findall(r"(\d+) (?:high|medium|low)", m["subject"])) == j["alerts"], m["subject"])
    check("email: watched item name + ref", "Victim wallet" in t and "Case 7" in t, t[:200])
    check("email: amount + asset", any(u in t for u in ("USDC", "USDT", "ETH ", "TOWNS")) and ("$" in t), t[:300])
    check("email: counterparty + label", "Counterparty" in t and ("Gate" in t or "Bridge" in t or "exchange" in t.lower()), "")
    check("email: risk/flags line", "Risk" in t or "risk" in t, "")
    check("email: UK time and UTC", ("GMT" in t or "BST" in t) and "UTC" in t, "")
    check("email: deep link back to ChainTrace", "https://chaintrace-d4fv.onrender.com/?q=" in t and "https://chaintrace-d4fv.onrender.com/?q=" in m["html"])
    check("email: leads-not-evidence caveat", "not evidence" in t)
    # run 2: same state -> nothing new (dedupe by cursor + sent ids)
    r = await c.post(U + "/api/alerts/run", json={"blob": blob1}, headers=BT); j2 = r.json()
    check("run 2: dedupe, no new alerts, no email", j2["alerts"] == 0 and not j2["emailed"] and len(outbox()) == 1, (j2["alerts"], len(outbox())))
    # wipe the server's local state (Render restart / sleep): blob from the scheduler restores cursors -> still no repeats
    shutil.rmtree(os.path.join(T, "alerts", "state.json"), ignore_errors=True); os.remove(os.path.join(T, "alerts", "state.json"))
    r = await c.post(U + "/api/alerts/run", json={"blob": j2["blob"]}, headers=BT); j3 = r.json()
    check("run 3: state restored from encrypted blob after disk wipe (no repeats)", j3["alerts"] == 0 and len(outbox()) == 1 and j3["muted"] == 1, (j3["alerts"], j3["muted"], j3.get("notes")))
    # lost everything (no blob, no disk): silent re-baseline - would only alert for since-dated items; drop since to show it
    # garbage blob is tolerated
    r = await c.post(U + "/api/alerts/run", json={"blob": "enc:garbage"}, headers=BT); j4 = r.json()
    check("run 4: unreadable blob tolerated (local state used)", r.status_code == 200 and j4["alerts"] == 0 and any("unreadable" in n for n in j4["notes"]), j4.get("notes"))
    st = (await c.get(U + "/api/alerts/status", auth=A)).json()
    check("status: last run + per-item last_checked shown", st["last_run"] and any(i["last_checked"] for i in st["items"]) and len(st["runs"]) >= 4)
    # test email
    r = await c.post(U + "/api/alerts/test", auth=A); check("test email: sent via mock", r.status_code == 200 and r.json()["sender"] == "mock" and len(outbox()) == 2, r.text[:160])
    check("test email: marked as test", "test" in outbox()[-1]["subject"].lower(), outbox()[-1]["subject"])
    # seal endpoint
    r = await c.post(U + "/api/alerts/seal", json={"items": [{"id": "x", "address": WATCH_BTC, "name": "N", "last": {"secret": 1}}]}, auth=A); sj = r.json()
    check("seal: returns enc: value that decrypts to the watchlist (cursor data stripped)", r.status_code == 200 and alerts.unseal(sj["value"])["items"] == [{"id": "x", "address": WATCH_BTC, "name": "N"}])
    r = await c.post(U + "/api/alerts/seal", json={"items": []}, auth=A); check("seal: empty rejected", r.status_code == 400)
    r = await c.post(U + "/api/alerts/seal", json={"items": [{"address": "a"}]}); check("seal: requires login", r.status_code == 401)
    await c.aclose()

def scheduler_script(U):
    sd = os.path.join(T, "sched"); e = dict(ENV, CHAINTRACE_URL=U, STATE_DIR=sd)
    p = subprocess.run([sys.executable, os.path.join(H, ".github", "scripts", "alerts_call.py")], env=e, capture_output=True, text=True, timeout=600)
    out = p.stdout + p.stderr
    check("scheduler script: runs, saves blob", p.returncode == 0 and "done:" in out and os.path.exists(os.path.join(sd, "blob")), out[-300:])
    check("scheduler script: log has counts only (no addresses, names, token)", WATCH_ETH.lower() not in out.lower() and "Victim" not in out and TOKEN not in out and "@" not in out)
    e2 = dict(e); e2.pop("ALERTS_TOKEN")
    p = subprocess.run([sys.executable, os.path.join(H, ".github", "scripts", "alerts_call.py")], env=e2, capture_output=True, text=True, timeout=60)
    check("scheduler script: missing secret -> clean skip", p.returncode == 0 and "skipping" in p.stdout, p.stdout[-120:])
    e3 = dict(e, ALERTS_TOKEN="y" * 43)
    p = subprocess.run([sys.executable, os.path.join(H, ".github", "scripts", "alerts_call.py")], env=e3, capture_output=True, text=True, timeout=120)
    check("scheduler script: wrong token -> fails loudly (401)", p.returncode == 1 and "401" in p.stdout, p.stdout[-120:])

async def ui(U):
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w, hgt, tag in ((1600, 950, "desktop"), (390, 844, "phone")):
            ctx = await b.new_context(viewport={"width": w, "height": hgt}, is_mobile=tag == "phone", has_touch=tag == "phone", http_credentials={"username": "tester", "password": PW})
            pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U + "/"); await pg.wait_for_function("typeof ctWatch==='function'")
            await pg.evaluate("ctWatch(true)"); await pg.wait_for_selector("#wt-email", timeout=8000); await pg.click("#wt-email")
            await pg.wait_for_selector("#alc-status h4", timeout=15000)
            tx = await pg.inner_text("#wbody")
            check(f"ui {tag}: email panel shows ready + mock sender + masked recipient", "ready" in tx and "mock" in tx and "te…@example.invalid" in tx, tx[:200])
            check(f"ui {tag}: server watchlist with mute state", "Victim wallet" in tx and "Muted" in tx and "Alerting" in tx, "")
            if tag == "desktop":
                await pg.click("#al-test"); await pg.wait_for_function("window.CT_ALERT_TEST", timeout=15000)
                check("ui: Send test email -> mock outbox", "sent via mock" in await pg.inner_text("#al-msg") and len(outbox()) >= 3, await pg.inner_text("#al-msg"))
                n0 = len(outbox())
                await pg.click("#alc-items .it[data-id='btc1'] .al-mute"); await pg.wait_for_timeout(1500)
                await pg.wait_for_selector("#alc-items .it[data-id='btc1']", timeout=10000)
                tx2 = await pg.inner_text("#alc-items .it[data-id='btc1']")
                check("ui: unmute toggle persists on server", "Alerting" in tx2 and not alerts.status()["items"][1]["muted"], tx2)
                await pg.evaluate("ctAlertMute('btc1',true)"); await pg.wait_for_timeout(1500)
                check("ui: re-mute", alerts.status()["items"][1]["muted"])
                # seal: put an address into the browser watchlist, then create the sealed value
                await pg.evaluate(f"""()=>{{ctWatchAdd({{address:'{WATCH_BTC}',name:'UI test'}});}}""")
                await pg.wait_for_selector("#wf-save", timeout=5000); await pg.click("#wf-save"); await pg.wait_for_timeout(500)
                await pg.click("#wt-email"); await pg.wait_for_selector("#alc-status h4")
                await pg.click("text=Create sealed value"); await pg.wait_for_function("document.getElementById('al-seal').value.startsWith('enc:')", timeout=10000)
                v = await pg.input_value("#al-seal")
                check("ui: Create sealed value -> decrypts to the browser watchlist", alerts.unseal(v)["items"][0]["address"] == WATCH_BTC and "sealed" in await pg.inner_text("#al-smsg"))
                if SHOTS: await pg.screenshot(path=SHOT("desktop"))
                await pg.click("#wt-alerts"); await pg.wait_for_timeout(300)
                check("ui: switching back to Alerts tab leaves the email panel", not await pg.query_selector("#alc-status"))
            elif SHOTS: await pg.screenshot(path=SHOT("phone"), full_page=False)
            check(f"ui {tag}: no JS errors", not errs, errs[:3]); await ctx.close()
        await b.close()

def main():
    unit()
    wl = {"format": "chaintrace-watchlist", "version": 1, "items": [
        {"id": "eth1", "address": WATCH_ETH, "chain": "eth", "name": "Victim wallet (test)", "ref": "Case 7 (test)", "since": 1},
        {"id": "btc1", "address": WATCH_BTC, "chain": "btc", "name": "Genesis (test)"}]}
    ENV["ALERTS_WATCHLIST"] = alerts.seal(wl); os.environ["ALERTS_WATCHLIST"] = ENV["ALERTS_WATCHLIST"]
    P = port(); U = f"http://127.0.0.1:{P}"
    log = open(os.path.join(T, "server.log"), "w")
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--port", str(P), "--host", "127.0.0.1"], cwd=H, env=ENV, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                if httpx.get(U + "/healthz", timeout=2).status_code == 200: break
            except Exception: pass
            time.sleep(0.5)
        asyncio.run(server_tests(U))
        scheduler_script(U)
        asyncio.run(ui(U))
    finally:
        srv.terminate(); srv.wait(10)
        print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
        shutil.rmtree(T, ignore_errors=True)
    sys.exit(1 if bad else 0)
if __name__ == "__main__": main()
