"""Test for v15 BTC change-address heuristics and peel-chain detection.
Real example verified live on mempool.space: a Bitcoin peel chain starting at tx 03d236de… (block 900,000, 06/06/2025): each tx has one input and
two outputs, a small payment and a large change output that is spent by the next tx in the same shape.
Checks: on-chain facts, each heuristic on synthetic transactions, /api/btc/change and /api/btc/peel against the chain, the graph (dotted amber edges,
grouped path, peeled branches), AutoTrace 'follow change', the victim-loss lead flag, the PDF section, and phone/desktop screenshots.
Password from env LP (never printed). Usage: LP=... python3 uitest_peel.py   (CT_URL for another server, SHOT=prefix for screenshots)"""
import asyncio, os, sys, json, subprocess, tempfile, urllib.request, base64
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOT = os.environ.get("SHOT", "screenshot_v15_peel")
TX1 = "03d236de860594b8ba35d1260d0c1d098fa8fba143d9c64129458cdbe90da4ba"; C1 = "bc1q20780dnafnf9mv2thy80hwm8gxr7wtw6e7dqks"
HOPS = 7
ok = []; bad = []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:220], flush=True)
def jget(u, auth=False):
    rq = urllib.request.Request(u, headers={"User-Agent": "chaintrace-test"})
    if auth: rq.add_header("Authorization", "Basic " + base64.b64encode(f"{AUTH['username']}:{AUTH['password']}".encode()).decode())
    return json.loads(urllib.request.urlopen(rq, timeout=90).read())
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush(); return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
def onchain_chain(n):
    """walk the chain on mempool.space independently of ChainTrace: follow the larger output of each 1-in/2-out tx to its spender"""
    out = []; h = TX1
    for _ in range(n):
        t = jget(f"https://mempool.space/api/tx/{h}"); assert len(t["vin"]) == 1 and len(t["vout"]) == 2, h
        big = max(range(2), key=lambda i: t["vout"][i]["value"])
        s = jget(f"https://mempool.space/api/tx/{h}/outspend/{big}")
        out.append({"tx": h, "from": t["vin"][0]["prevout"]["scriptpubkey_address"], "change": t["vout"][big]["scriptpubkey_address"], "change_value": t["vout"][big]["value"] / 1e8,
                    "pay": t["vout"][1 - big]["scriptpubkey_address"], "pay_value": t["vout"][1 - big]["value"] / 1e8, "next": s.get("txid")})
        h = s["txid"]
    return out
def mk(ins, outs, txid="f" * 64):
    return {"txid": txid, "fee": sum(v for _, _, v in ins) - sum(v for _, _, v in outs), "status": {"confirmed": False},
            "vin": [{"prevout": {"scriptpubkey_address": a, "scriptpubkey_type": t, "value": v}} for a, t, v in ins],
            "vout": [{"scriptpubkey_address": a, "scriptpubkey_type": t, "value": v} for a, t, v in outs]}
async def direct():
    import peel
    # synthetic transactions isolate each heuristic (fresh-address check cannot resolve fake addresses, so it abstains)
    A = await peel.analyse(mk([("i1", "v0_p2wpkh", 5_000_000)], [("p", "p2pkh", 1_234_567), ("c", "v0_p2wpkh", 3_765_433 - 500)]))
    check("heuristic: address type picks the output matching the inputs' type", next(h for h in A["heuristics"] if h["h"] == "type")["output"] == 1)
    A = await peel.analyse(mk([("i1", "v0_p2wpkh", 5_000_000)], [("p", "v0_p2wpkh", 2_000_000), ("c", "v0_p2wpkh", 2_987_654)]))
    check("heuristic: round payment -> the non-round output is change", next(h for h in A["heuristics"] if h["h"] == "round")["output"] == 1)
    A = await peel.analyse(mk([("i1", "v0_p2wpkh", 3_000_000), ("i2", "v0_p2wpkh", 2_000_000)], [("p", "v0_p2wpkh", 4_100_000), ("c", "v0_p2wpkh", 890_000)]))
    check("heuristic: unnecessary input -> only the small output is consistent as change", next(h for h in A["heuristics"] if h["h"] == "unnecessary")["output"] == 1)
    check("heuristic: optimal change -> the only output smaller than every input", next(h for h in A["heuristics"] if h["h"] == "optimal")["output"] == 1)
    A = await peel.analyse(mk([("i1", "v0_p2wpkh", 5_000_000)], [("p", "v0_p2wpkh", 1_000_000), ("i1", "v0_p2wpkh", 3_990_000)]))
    check("heuristic: change back to an input address", A["best"] == 1 and any(h["h"] == "self" and h["output"] == 1 for h in A["heuristics"]))
    A = await peel.analyse(mk([("i1", "v0_p2wpkh", 5_000_000)], [("p", "v0_p2wpkh", 2_500_000), ("c", "v0_p2wpkh", 2_490_000)]))
    check("no discriminating heuristic -> 50/50, no change proposed", peel.pick(A, 0.6) is None and abs(A["p_best"] - 0.5) < 1e-6, A["p_best"])
async def main():
    await direct()
    oc = onchain_chain(HOPS)
    check(f"on-chain: {HOPS} successive 1-in/2-out txs, each spending the previous large output", all(oc[i]["next"] == oc[i + 1]["tx"] and oc[i + 1]["from"] == oc[i]["change"] for i in range(HOPS - 1)) and oc[0]["change"] == C1)
    A = jget(f"{U}/api/btc/change?tx={TX1}", auth=True)
    check("API change: output 1 (bc1q20780…) is the likely change", (A.get("change") or {}).get("address") == C1 and A["change"]["confidence"] >= 0.7, (A.get("change") or {}).get("confidence"))
    hs = {h["h"]: h for h in A["heuristics"]}
    check("API change: every heuristic reported with what it saw", {"type", "round", "fresh", "unnecessary", "optimal", "pattern"} <= set(hs) and all(h["saw"] for h in A["heuristics"]), sorted(hs))
    check("API change: reasons shown (round payment, fresh address, peel pattern)", hs["round"]["output"] == 1 and hs["fresh"]["output"] == 1 and hs["pattern"]["output"] == 1)
    P = jget(f"{U}/api/btc/peel?q={TX1}&max_hops={HOPS}", auth=True)
    check("API peel: detected as a peel chain", P["is_peel"] and P["hops"] == HOPS, (P["hops"], P["stop_reason"]))
    check("API peel: steps match the on-chain chain (tx, change address, change value)", all(s["tx"] == o["tx"] and s["change"]["address"] == o["change"] and abs(s["change"]["value"] - o["change_value"]) < 1e-9 for s, o in zip(P["steps"], oc)))
    check("API peel: peeled payments match on-chain", all(len(s["payments"]) == 1 and s["payments"][0]["address"] == o["pay"] and abs(s["payments"][0]["value"] - o["pay_value"]) < 1e-9 for s, o in zip(P["steps"], oc)))
    check("API peel: change edges are heuristic (heur) with reasons, payments are branches", sum(1 for e in P["edges"] if e.get("heur") and e.get("peel") and e["change"]["reasons"]) == HOPS and sum(1 for e in P["edges"] if e.get("peeled")) == HOPS)
    check("API peel: total peeled", abs(P["total_peeled"] - round(sum(o["pay_value"] for o in oc), 8)) < 1e-9, P["total_peeled"])
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
        errs = []
        ctx = await b.new_context(viewport={"width": 1500, "height": 950}, http_credentials=AUTH, accept_downloads=True)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + f"/?q={TX1}&peel={TX1}&hops={HOPS}")
        await pg.wait_for_function("window.CT_LAST_PEEL", timeout=150000); await pg.wait_for_timeout(2500)
        n = await pg.evaluate("cy.edges('[?peel]').length"); st = await pg.evaluate("(()=>{const e=cy.edges('[?peel]')[0];return e?e.style('line-style')+'|'+e.style('line-color'):''})()")
        check("UI: change hops drawn as dotted amber edges", n >= HOPS and st.startswith("dotted"), (n, st))
        check("UI: peeled payments drawn as branches", await pg.evaluate("cy.edges('[?peeled]').length") >= HOPS)
        g = await pg.evaluate("(()=>{const g=cy.nodes('[?grp][gkind=\"peel\"]');return g.length?{lbl:g.data('lbl'),kids:cy.nodes().filter(n=>n.data('parent')===g.id()).length}:null})()")
        check("UI: chain shown as a grouped path (heuristic lead)", bool(g) and g["kids"] >= HOPS and "heuristic lead" in g["lbl"], g)
        txt = await pg.evaluate("document.getElementById('det').textContent")
        check("UI: peel card with verdict + lead warning", "Peel-chain pattern" in txt and "not attribution" in txt)
        await pg.screenshot(path=f"{SHOT}_desktop.png")
        await pg.evaluate(f"(()=>{{const e=cy.edges('[?peel]').filter(e=>e.data('source')==='{C1}')[0]||cy.edges('[?peel]')[0];cy.elements().unselect();e.select();e.emit('tap')}})()"); await pg.wait_for_timeout(600)
        check("UI: tapping a change edge shows confidence + reasons", "Likely change (heuristic)" in await pg.evaluate("document.getElementById('det').textContent") and "round" in (await pg.evaluate("document.getElementById('det').textContent")).lower())
        await pg.evaluate(f"cy.getElementById('tx:{TX1}').emit('tap')"); await pg.wait_for_function("document.querySelector('#det .chgcard .out')", timeout=60000)
        check("UI: tx node shows the change analysis card", "Change analysis" in await pg.evaluate("document.getElementById('det').textContent"))
        await pg.evaluate("document.querySelector('#det .chgcard').scrollIntoView()"); await pg.wait_for_timeout(400); await pg.screenshot(path=f"{SHOT}_desktop_change.png")
        # victim-loss through the chain: hops through likely change are flagged as leads
        await pg.evaluate(f"ctLossOpen()"); await pg.fill("#losst", TX1); await pg.fill("#losss", C1); await pg.click("#lossgo")
        await pg.wait_for_function("window.CT_LOSS_LAST", timeout=120000); L = await pg.evaluate("window.CT_LOSS_LAST")
        check("loss: hops via likely change flagged 'heuristic edge (peel-chain change)'", any("peel-chain change" in " ".join(h["lead"]) for h in L["hops"]) and L["leads_present"])
        await pg.evaluate("ctLossClose()")
        await pg.click("#rptbtn"); await pg.wait_for_selector("#rptm.on"); await pg.fill("#rptref", "PEEL/UITEST/1")
        async with pg.expect_download(timeout=150000) as dl: await pg.click("#rptgo")
        t = " ".join(pdftext(open(await (await dl.value).path(), "rb").read()).split())
        check("PDF: peel-chain section, method note and lead wording", all(s in t for s in ("Change-address and peel-chain leads", "HEURISTIC LEAD", "unnecessary input", "Peel chain", C1[:20])))
        await ctx.close()
        # AutoTrace with 'follow change'
        ctx = await b.new_context(viewport={"width": 1500, "height": 950}, http_credentials=AUTH)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + "/"); await pg.fill("#q", C1); await pg.fill("#amin", "0"); await pg.select_option("#amax", "4"); await pg.check("#pfollow")
        await pg.evaluate("document.getElementById('stxt').textContent=''"); await pg.click("#autobtn")
        await pg.wait_for_function("document.getElementById('stxt').textContent.includes('done')||document.getElementById('stxt').textContent.toLowerCase().includes('error')", timeout=240000)
        await pg.wait_for_timeout(1500)
        pe = await pg.evaluate("cy.edges('[?peel]').map(e=>[e.data('source'),e.data('target')])")
        exp = [(o["from"], o["change"]) for o in oc[1:4]]
        check("AutoTrace follow change: follows the chain's change outputs (dotted amber)", all(list(x) in pe for x in exp), (len(pe), exp[:1]))
        check("AutoTrace follow change: side card lists change followed", "Change followed" in await pg.evaluate("document.getElementById('side').textContent"))
        await pg.screenshot(path=f"{SHOT}_autotrace_desktop.png"); await ctx.close()
        # phone
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, http_credentials=AUTH)
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + f"/?q={TX1}&peel={TX1}&hops={HOPS}"); await pg.wait_for_function("window.CT_LAST_PEEL", timeout=150000); await pg.wait_for_timeout(2500)
        sw = await pg.evaluate("document.documentElement.scrollWidth")
        check("phone: no horizontal overflow", sw <= 392, sw)
        await pg.evaluate("window.scrollTo(0,0)"); await pg.screenshot(path=f"{SHOT}_phone_graph.png")
        await pg.evaluate("document.querySelector('.peelcard')?.scrollIntoView()"); await pg.wait_for_timeout(400); await pg.screenshot(path=f"{SHOT}_phone.png")
        await ctx.close()
        check("no page errors", not errs, errs[:3])
        await b.close()
    print(f"\n{len(ok)} passed, {len(bad)} failed", bad)
    sys.exit(1 if bad else 0)
asyncio.run(main())
