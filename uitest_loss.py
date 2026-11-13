"""Test for v14 victim-loss calculator / fund-flow summary.
1) direct loss.compute() on the public Binance case (29 Oct 2026; amounts verified on-chain when the case was built) for all three methods;
2) a small synthetic dated graph where FIFO, LIFO and proportional must give different, hand-checked answers;
3) Playwright on a real BTC flow verified live on mempool.space: tx 03d236de… (block 900,000, 06/06/2025) pays 1.76343013 BTC to bc1q20780…,
   which forwards it in tx 61821df0… -> checks totals, on-the-day USD (Coinbase daily close) and GBP (ECB), CSV, PDF section, evidence pack CSV;
4) phone deep link on the Binance case (screenshots).
Password comes from env LP (never printed). Usage: LP=... python3 uitest_loss.py   (CT_URL for another server, SHOT=prefix for screenshots)"""
import asyncio, os, sys, json, subprocess, tempfile, urllib.request, zipfile, io
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOT = os.environ.get("SHOT", "screenshot_v14_loss")
B14, B16 = "0x28C6c06298d514Db089934071355E5743bf21d60", "0xDFd5293D8e347dFe59E90eFd55b2956a1343963d"
HUB, STASH = "0x5227f603C1eE34CE3C06eFe6477003BDfCCB2f8c", "0x8532FA14ACAf483729C449b8458aedDb900543D4"
TX1 = "03d236de860594b8ba35d1260d0c1d098fa8fba143d9c64129458cdbe90da4ba"; TX2 = "61821df06b6824f8a982bc2e65d8f22be6ca2c7f7e212cf2a4fe459498e50c22"
VICTIM = "bc1q6fgk474qn7kkj26ddwsd9qtynx7qca0phsynp4"; SUSPECT = "bc1q20780dnafnf9mv2thy80hwm8gxr7wtw6e7dqks"
LEAD = "Intelligence lead – not evidence; corroborate (e.g. production order to the VASP)"
ok = []; bad = []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:220], flush=True)
def jget(u): return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "chaintrace-test"}), timeout=25).read())
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush(); return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
def case_payload():
    d = json.load(open(os.path.join(H, "static/cases/binance-2026-10-29.json")))["case"]
    return {"nodes": [{**(n["data"].get("info") or {}), "id": n["data"]["id"]} for n in d["graph"]["nodes"]], "edges": [e["info"] for e in d["graph"]["edges"]],
            "case": {"labels": d["labels"], "name": d["name"]}}
async def direct():
    import loss
    p = case_payload()
    for m in ("proportional", "fifo", "lifo"):
        r = await loss.compute(p, {"victims": [B14, B16], "method": m})
        t = {x["asset"]: x for x in r["totals"]}
        check(f"binance {m}: total lost 195,469.85 ETH (167,464.25 + 28,005.60)", abs(t["ETH"]["amount"] - 195469.85) < 1e-6, t["ETH"]["amount"])
        held = {d["id"]: d for d in r["held"]}
        check(f"binance {m}: 195,460 ETH attributed to the ETH stash and still held", STASH in held and abs(held[STASH]["amount"] - 195460) < 1e-6, {k[:10]: v["amount"] for k, v in held.items()})
        check(f"binance {m}: reconciles (difference 0)", all(abs(x["difference"]) < 1e-6 for x in r["reconciliation"]), r["reconciliation"])
        check(f"binance {m}: method stated", r["method"] == m and r["method_name"] and m.upper()[:4] in (r["method_name"].upper() + "PROPORTIONAL"), r["method_name"])
    check("binance: USDT 500M from the hub is NOT counted as victim funds (no USDT pool from the victims)", not any(h["asset"] == "USDT" for h in r["hops"]))
    check("binance: CSV has every section", all(f"\n{s}," in r["csv"] for s in ("totals", "payment", "destination", "hop", "reconciliation")) and LEAD in r["csv"])
    # XRP victims -> stash -> six peel addresses
    xr = [n["id"] for n in p["nodes"] if n.get("chain") == "xrp" and "(victim)" in (n.get("name") or "")]
    r = await loss.compute(p, {"victims": xr, "method": "proportional"}, live_balances=False)
    t = {x["asset"]: x for x in r["totals"]}
    check("binance XRP: 5 victim hot wallets, 233,461,943.1 XRP", len(xr) == 5 and abs(t["XRP"]["amount"] - 233461943.1) < 1e-3, t.get("XRP", {}).get("amount"))
    # synthetic, dated: victim V pays 1.0 at t=100 into S which already had 1.0 clean (t=50); S pays 0.5 at t=200 to A, then 1.5 at t=300 to X (exchange)
    syn = {"nodes": [{"id": "V", "chain": "btc"}, {"id": "S", "chain": "btc"}, {"id": "C", "chain": "btc"}, {"id": "A", "chain": "btc"}, {"id": "X", "chain": "btc", "kind": "exchange", "name": "Exch"}],
           "edges": [{"source": "C", "target": "S", "amount": 1.0, "unit": "BTC", "time": 50, "tx": "c"}, {"source": "V", "target": "S", "amount": 1.0, "unit": "BTC", "time": 100, "tx": "v"},
                     {"source": "S", "target": "A", "amount": 0.5, "unit": "BTC", "time": 200, "tx": "a"}, {"source": "S", "target": "X", "amount": 1.5, "unit": "BTC", "time": 300, "tx": "x"}]}
    exp = {"proportional": (0.25, 0.75), "fifo": (0.0, 1.0), "lifo": (0.5, 0.5)}
    for m, (a, x) in exp.items():
        r = await loss.compute(syn, {"victims": ["V"], "method": m}, live_balances=False)
        h = {k["to"]: k["tainted"] for k in r["hops"]}
        check(f"synthetic {m}: A gets {a}, exchange gets {x}", abs(h.get("A", 0) - a) < 1e-9 and abs(h.get("X", 0) - x) < 1e-9, h)
async def main():
    await direct()
    # on-chain facts for the real BTC flow (mempool.space)
    t1 = jget(f"https://mempool.space/api/tx/{TX1}"); t2 = jget(f"https://mempool.space/api/tx/{TX2}")
    pay = next(o["value"] for o in t1["vout"] if o["scriptpubkey_address"] == SUSPECT) / 1e8
    check("on-chain: tx1 spends the victim address and pays the suspect address", t1["vin"][0]["prevout"]["scriptpubkey_address"] == VICTIM and abs(pay - 1.76343013) < 1e-9, pay)
    check("on-chain: tx2 spends exactly that output", t2["vin"][0]["txid"] == TX1 and t2["vin"][0]["prevout"]["scriptpubkey_address"] == SUSPECT)
    bt = t1["status"]["block_time"]; day = bt // 86400 * 86400
    from datetime import datetime, timezone
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    cand = jget(f"https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400&start={iso(day - 86400)}&end={iso(day + 86400)}")
    close = next(float(c[4]) for c in cand if int(c[0]) == day)
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
        errs = []
        ctx = await b.new_context(viewport={"width": 1500, "height": 950}, http_credentials=AUTH, accept_downloads=True)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + "/?q=" + TX1); await pg.wait_for_function("cy.nodes().length>=3", timeout=120000); await pg.wait_for_timeout(1500)
        await pg.evaluate(f"expand('{SUSPECT}')"); await pg.wait_for_function(f"cy.edges().filter(e=>e.data('source')==='{SUSPECT}').length>=1", timeout=120000)
        await pg.wait_for_timeout(1200)
        await pg.click("#lossbtn"); await pg.wait_for_selector("#lossm.on")
        await pg.fill("#losst", TX1); await pg.fill("#losss", SUSPECT); await pg.select_option("#lossmth", "proportional")
        await pg.click("#lossgo"); await pg.wait_for_function("window.CT_LOSS_LAST||document.querySelector('#lossres .warnbox')", timeout=120000)
        j = await pg.evaluate("window.CT_LOSS_LAST||null")
        check("UI: calculation returned", bool(j), await pg.inner_text("#lossres") if not j else "")
        if j:
            T = {x["asset"]: x for x in j["totals"]}
            check("UI: total lost = on-chain payment 1.76343013 BTC", abs(T["BTC"]["amount"] - pay) < 1e-9, T["BTC"]["amount"])
            check("UI: on-the-day USD = amount × Coinbase daily close", T["BTC"]["usd_then"] and abs(T["BTC"]["usd_then"] - round(pay * close, 2)) < 0.05, (T["BTC"]["usd_then"], close))
            pr = j["payments"][0]
            check("UI: GBP on the day uses the ECB rate of that date", pr["gbp_then"] and pr["gbp_rate_date"] and 0.6 < pr["gbp_then"] / pr["usd_then"] < 0.9, (pr["gbp_then"], pr["gbp_rate_date"]))
            check("UI: payment time in UK + UTC", "BST" in pr["time_uk"] and "UTC" in pr["time_utc"], pr["time_uk"])
            hop1 = [h for h in j["hops"] if h["tx"] == TX2]
            out2 = {o["scriptpubkey_address"]: o["value"] / 1e8 for o in t2["vout"]}
            check("UI: hop 1 follows tx2 outputs at 100% victim funds", len(hop1) == len(out2) and all(abs(h["tainted"] - out2[h["to"]]) < 1e-9 for h in hop1), [(h["to"][:10], h["tainted"]) for h in hop1])
            rs = [d for d in j["destinations"] if d["id"] == SUSPECT]
            check("UI: only the tx2 network fee is left unexplained at the suspect address (balance now 0)", len(rs) == 1 and abs(rs[0]["amount"] - t2["fee"] / 1e8) < 1e-8 and rs[0]["cat"] == "untraced", [(d["cat"], d["amount"]) for d in rs])
            check("UI: reconciles (lost = accounted)", abs(j["reconciliation"][0]["difference"]) < 1e-8, j["reconciliation"])
            check("UI: summary panel shows statement + method", "payment(s) were made from the victim" in await pg.inner_text("#lossres") and "Proportional" in await pg.inner_text("#lossres"))
            check("UI: flows highlighted on graph", await pg.evaluate("cy.edges('.losshl').length") >= 2)
            async with pg.expect_download(timeout=30000) as dl: await pg.click("#losscsv")
            csvb = open(await (await dl.value).path(), "rb").read().decode()
            check("UI: CSV download has method + payment + hops", "Proportional (haircut)" in csvb and TX1 in csvb and TX2 in csvb)
            await pg.screenshot(path=f"{SHOT}_desktop.png")
            await pg.evaluate("ctLossClose()")
            # PDF + evidence pack carry the section
            await pg.click("#rptbtn"); await pg.wait_for_selector("#rptm.on"); await pg.fill("#rptref", "LOSS/UITEST/1")
            async with pg.expect_download(timeout=120000) as dl: await pg.click("#rptgo")
            t = " ".join(pdftext(open(await (await dl.value).path(), "rb").read()).split())
            check("PDF: victim-loss section with method, hop table and lead caveat", all(s in t for s in ("Victim loss and fund-flow summary", "Tracing method: Proportional", "Hop-by-hop table", "Reconciliation", LEAD)))
            check("PDF: statement wording + amount", "payment(s) were made from the victim address(es)" in t and "1.76343013 BTC" in t)
            async with pg.expect_download(timeout=150000) as dl: await pg.click("#packgo")
            z = zipfile.ZipFile(io.BytesIO(open(await (await dl.value).path(), "rb").read()))
            names = z.namelist(); lc = [n for n in names if n.endswith("victim_loss_summary.csv")]
            check("evidence pack: victim_loss_summary.csv included and hashed", bool(lc) and any("victim_loss_summary.csv" in l for l in z.read([n for n in names if n.endswith("SHA256SUMS.txt")][0]).decode().splitlines()), names)
        await ctx.close()
        # phone: Binance case deep link computes on open
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, http_credentials=AUTH)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + f"/?case=binance-2026-10-29&loss=1&victims={B14},{B16}&method=proportional")
        await pg.wait_for_function("window.CT_LOSS_LAST||document.querySelector('#lossres .warnbox')", timeout=150000); await pg.wait_for_timeout(1200)
        j = await pg.evaluate("window.CT_LOSS_LAST||{}")
        check("phone deep link: Binance loss computed", abs(({x['asset']: x for x in j.get('totals', [])}.get('ETH') or {}).get('amount', 0) - 195469.85) < 1e-6)
        r = await pg.evaluate("(()=>{const c=document.querySelector('#lossm .card').getBoundingClientRect();return{l:c.left,r:c.right,sw:document.documentElement.scrollWidth}})()")
        check("phone: panel within viewport (tables scroll inside)", r["l"] >= 0 and r["r"] <= 391 and r["sw"] <= 392, r)
        await pg.screenshot(path=f"{SHOT}_phone.png")
        await pg.evaluate("document.querySelector('#lossres h4:nth-of-type(2)')?.scrollIntoView()"); await pg.wait_for_timeout(300)
        await pg.screenshot(path=f"{SHOT}_phone_dest.png"); await ctx.close()
        check("no page errors", not errs, errs[:3])
        await b.close()
    print(f"\n{len(ok)} passed, {len(bad)} failed", bad)
    sys.exit(1 if bad else 0)
asyncio.run(main())
