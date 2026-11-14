"""v19 Timeline of fund movements: real mainnet graph (Ethereum wallet 0x85fa… that paid Gate.io and the Base bridge), victim/suspect marks,
filters (chain, asset, address, UK date range), GBP, graph <-> timeline sync, CSV, phone width, and the PDF timeline section.
One flow is re-checked against the public RPC receipt. Password from env LP (never printed).
Usage: LP=... python3 uitest_timeline.py   (CT_URL for another server; SHOTS=0 to skip screenshots)"""
import asyncio, os, sys, json, base64, subprocess, tempfile, re
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__))
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v19_timeline_{n}{TAG}.png")
W = "0x85FAa6C1F2450b9caEA300838981C2e6E120C35c"
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush(); return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
def receipt_has(tx, frm, to):
    r = httpx.post("https://ethereum-rpc.publicnode.com", json={"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [tx]}, timeout=20).json().get("result") or {}
    t = httpx.post("https://ethereum-rpc.publicnode.com", json={"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionByHash", "params": [tx]}, timeout=20).json().get("result") or {}
    f, d = frm.lower(), to.lower()
    if (t.get("from") or "").lower() == f and (t.get("to") or "").lower() == d: return True
    return any(len(l["topics"]) == 3 and "0x" + l["topics"][1][-40:] == f and "0x" + l["topics"][2][-40:] == d for l in r.get("logs") or [])

async def desktop(b):
    ctx = await b.new_context(viewport={"width": 1600, "height": 950}, http_credentials=AUTH, accept_downloads=True)
    pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(U + f"/?q={W}"); await pg.wait_for_function("cy.nodes().length>=6", timeout=120000); await pg.wait_for_timeout(1500)
    gate = await pg.evaluate(f"cy.nodes().filter(n=>(n.data('kind')==='exchange')&&n.id()!=='{W}').map(n=>n.id())")
    check("graph has an exchange counterparty (Gate.io)", len(gate) >= 1, gate[:3])
    # victim = the watched wallet, suspect = first non-exchange counterparty that received funds
    sus = await pg.evaluate(f"cy.edges().filter(e=>e.data('source')==='{W}'&&e.target().data('kind')!=='exchange'&&!e.target().id().startsWith('tx:')).map(e=>e.target().id())[0]")
    await pg.evaluate(f"ctLossMark('{W}','v');ctLossMark('{sus}','s')")
    await pg.click("#tlbtn"); await pg.wait_for_selector("#tlp.open .tlr", timeout=10000); await pg.wait_for_timeout(800)
    R = await pg.evaluate("ctTlRows().map(r=>({t:r.t,ch:r.ch,unit:r.unit,amt:r.amt,gbp:r.gbp,src:r.src,dst:r.dst,tx:r.tx,role:r.role,id:r.id}))")
    ne = await pg.evaluate("cy.edges().filter(e=>!e.data('grp')&&!e.data('meta')&&!e.data('tmp')&&!e.hasClass('noise')).length")
    check("timeline lists every flow on the graph", len(R) == ne and len(R) >= 5, (len(R), ne))
    ts = [r["t"] for r in R if r["t"]]; check("rows are chronological (oldest first)", ts == sorted(ts), ts[:4])
    check("GBP shown for priced rows (today's ECB rate)", any(r["gbp"] for r in R) and "£" in await pg.inner_text("#tlbody"))
    check("victim rows marked", any("v" in r["role"] for r in R) and "💷 victim" in await pg.inner_text("#tlbody"))
    check("suspect row marked", any("s" in r["role"] for r in R if sus in (r["src"], r["dst"])), sus)
    check("exchange hop marked", any("x" in r["role"] for r in R) and "to exchange" in await pg.inner_text("#tlbody"))
    real = next((r for r in R if r["tx"] and not r["src"].startswith("tx:") and not r["dst"].startswith("tx:")), None)
    check("a timeline flow matches the on-chain receipt", real and receipt_has(real["tx"], real["src"], real["dst"]), real)
    # filters
    units = sorted({r["unit"] for r in R}); u0 = next((u for u in units if sum(1 for r in R if r["unit"] == u) < len(R)), units[0])
    await pg.select_option("#tlas", u0); await pg.wait_for_timeout(300)
    F = await pg.evaluate("ctTlRows().map(r=>r.unit)"); check(f"asset filter ({u0})", F and set(F) == {u0} and len(F) == sum(1 for r in R if r["unit"] == u0), (len(F), u0))
    await pg.select_option("#tlas", ""); g0 = gate[0][-6:]
    await pg.fill("#tlad", g0); await pg.wait_for_timeout(500)
    F = await pg.evaluate("ctTlRows().map(r=>r.src+'>'+r.dst)"); check("address filter (Gate deposit)", F and all(g0.lower() in x.lower() for x in F), F[:2])
    await pg.fill("#tlad", ""); await pg.wait_for_timeout(400)
    mid = sorted(ts)[len(ts) // 2]; day = await pg.evaluate(f"new Intl.DateTimeFormat('en-CA',{{timeZone:'Europe/London'}}).format(new Date({mid}*1000))")
    await pg.fill("#tlfr", day); await pg.fill("#tlto", day); await pg.dispatch_event("#tlfr", "change"); await pg.dispatch_event("#tlto", "change"); await pg.wait_for_timeout(400)
    F = await pg.evaluate("ctTlRows().map(r=>new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/London'}).format(new Date(r.t*1000)))")
    check(f"UK date-range filter ({day})", F and set(F) == {day}, (len(F), set(F)))
    await pg.fill("#tlfr", ""); await pg.fill("#tlto", ""); await pg.dispatch_event("#tlfr", "change"); await pg.dispatch_event("#tlto", "change")
    chs = await pg.evaluate("[...document.querySelectorAll('#tlch option')].map(o=>o.value)"); check("chain filter offers the graph's chains", "eth" in chs, chs)
    # sync: click a row -> edge highlighted; tap an edge -> row selected
    rid = R[len(R) // 2]["id"]
    await pg.click(f".tlr[data-id='{rid}']"); await pg.wait_for_timeout(600)
    check("click row highlights the flow on the graph", await pg.evaluate(f"cy.getElementById({json.dumps(rid)}).selected()&&cy.getElementById({json.dumps(rid)}).hasClass('hot')"))
    other = R[0]["id"]; await pg.evaluate(f"cy.getElementById({json.dumps(other)}).emit('tap')"); await pg.wait_for_timeout(300)
    check("tap flow on graph selects its timeline row", await pg.evaluate(f"document.querySelector('.tlr.on')?.dataset.id==={json.dumps(other)}"))
    if SHOTS: await pg.screenshot(path=SHOT("desktop"))
    async with pg.expect_download() as dl: await pg.click("#tlp h2 button:has-text(\"CSV\")")
    csv = open(await (await dl.value).path()).read(); check("CSV export has header + one line per row", csv.startswith("time_uk,time_utc,chain") and csv.count("\n") == len(R), csv[:80])
    # PDF with a filter: only that asset
    await pg.select_option("#tlas", u0); await pg.wait_for_timeout(200)
    pl = await pg.evaluate("ctReportPayload({ref:'TL-TEST',investigator:'uitest',marking:'',notes:'',img:false,noise:false})")
    check("report payload carries the timeline filter + loss marks", pl.get("timeline", {}).get("asset") == u0 and pl.get("loss", {}).get("suspect") == sus, pl.get("timeline"))
    r = httpx.post(U + "/api/report", json=pl, auth=(AUTH["username"], AUTH["password"]), timeout=180)
    txt = pdftext(r.content) if r.status_code == 200 else ""
    open("/workspace/scratch/tl_pdf.txt", "w").write(txt)
    check("PDF has the timeline section with the filter", "3.0 Timeline of fund movements" in txt and f"asset = {u0}" in txt, r.status_code)
    sec = txt[txt.find("as filtered in the ChainTrace Timeline view"):]; sec = sec[:sec.find("Total of the priced rows") + 200]
    check("PDF timeline: GBP + roles", "£" in sec and ("VICTIM" in sec or "SUSPECT" in sec or "EXCHANGE" in sec), sec[:200])
    check("PDF timeline: lead caveat", "not evidence" in sec)
    check("desktop: no JS errors", not errs, errs[:2]); await ctx.close()

async def phone(b):
    ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, http_credentials=AUTH)
    pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(U + f"/?q={W}"); await pg.wait_for_function("cy.nodes().length>=6", timeout=120000); await pg.wait_for_timeout(1200)
    await pg.evaluate("ctTimeline(true)"); await pg.wait_for_selector("#tlp.open .tlr", timeout=10000); await pg.wait_for_timeout(500)
    bb = await pg.evaluate("(()=>{const r=document.getElementById('tlp').getBoundingClientRect();return{top:r.top,w:r.width,h:r.height}})()")
    check("phone: bottom sheet leaves the graph visible above", bb["top"] > 250 and bb["w"] <= 390, bb)
    check("phone: filters folded away by default", not await pg.is_visible("#tlas"))
    sw = await pg.evaluate("document.getElementById('tlbody').scrollWidth<=document.getElementById('tlbody').clientWidth+2")
    check("phone: no horizontal overflow in rows", sw)
    if SHOTS: await pg.screenshot(path=SHOT("phone"))
    rid = await pg.evaluate("document.querySelectorAll('.tlr')[1].dataset.id"); await pg.tap(f".tlr[data-id='{rid}']"); await pg.wait_for_timeout(500)
    check("phone: tap row highlights flow", await pg.evaluate(f"cy.getElementById({json.dumps(rid)}).selected()"))
    await pg.wait_for_timeout(700)
    vis = await pg.evaluate("(()=>{const g=cy.container().getBoundingClientRect(),t=document.getElementById('tlp').getBoundingClientRect();return{min:document.getElementById('tlp').classList.contains('min'),gtop:g.top,gbot:g.bottom,ttop:t.top}})()")
    check("phone: sheet minimises and the highlighted graph is in view", vis["min"] and vis["gtop"] < vis["ttop"] - 200, vis)
    if SHOTS: await pg.screenshot(path=SHOT("phone_graph"))
    await pg.tap("#tlminb"); await pg.wait_for_timeout(300)
    check("phone: list restores with the row still selected", await pg.evaluate(f"!document.getElementById('tlp').classList.contains('min')&&document.querySelector('.tlr.on')?.dataset.id==={json.dumps(rid)}"))
    await pg.tap("text=⚙ Filters"); await pg.wait_for_timeout(200)
    check("phone: filters fold out", await pg.is_visible("#tlas"))
    check("phone: no JS errors", not errs, errs[:2]); await ctx.close()

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        await desktop(b); await phone(b); await b.close()
    print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
    sys.exit(1 if bad else 0)
asyncio.run(main())
