"""v20 bulk import: CSV / pasted lists -> chain detection, checksum validation, de-duplication, per-row errors, size caps,
roles / labels / notes into the case, addresses into the watchlist, template CSV. Uses real mainnet addresses and hashes and
looks the imported addresses up afterwards. Password from env LP (never printed).
Usage: LP=... python3 uitest_import.py   (CT_URL for another server; SHOTS=0 to skip screenshots)"""
import asyncio, os, sys, json, tempfile
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__))
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
A = (AUTH["username"], AUTH["password"])
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v20_import_{n}{TAG}.png")
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)
def parse(t): return httpx.post(U + "/api/import/parse", json={"text": t}, auth=A, timeout=60)
MIX = """value;chain;label;role;notes
1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa;bitcoin;Genesis (test);victim;first victim wallet
0x85FAa6C1F2450b9caEA300838981C2e6E120C35c;eth;Gate user (test);suspect;paid Gate.io
0x85faa6c1f2450b9caea300838981c2e6e120c35c;;dup lower;;
0x85FAa6C1F2450b9caEA300838981C2e6E120C35C;;eip55 typo;;
bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3x;;bad btc checksum;;
not-an-address;;;;
0xaeb1e2fd27ef697b648a14ac94ff8e245294f31f;base;Base wallet (test);exchange;
0x3b9e6a9a7b5f1c4d0a0f0e7fa7a1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9;eth;;wizard;unknown role
TXFBqBbqJommqZf7BV8NNYzePh97UmJodJ;tron;;;
"""
def api():
    r = httpx.get(U + "/api/import/template", auth=A, timeout=30)
    check("template CSV downloads", r.status_code == 200 and r.text.startswith("value,chain,label,role,notes") and "attachment" in r.headers.get("content-disposition", ""))
    j = parse(r.text).json(); s = j["summary"]
    check("template validates cleanly (7 rows, 6 chains)", s["ok"] == 7 and s["errors"] == 0 and len(s["chains"]) == 6, s)
    j = parse(MIX).json(); R = {x["row"]: x for x in j["rows"]}; s = j["summary"]
    check("semicolon CSV with header read", s["format"] == "csv" and s["rows"] == 9, s)
    check("BTC detected + role victim", R[2]["chain"] == "btc" and R[2]["role"] == "victim" and R[2]["status"] == "ok")
    check("EVM canonicalised to EIP-55", R[3]["id"] == "0x85FAa6C1F2450b9caEA300838981C2e6E120C35c")
    check("lower-case duplicate reported", R[4]["status"] == "duplicate" and "row 3" in R[4]["error"], R[4])
    check("EIP-55 typo rejected", R[5]["status"] == "error" and "EIP-55" in R[5]["error"], R[5]["error"])
    check("bad Bitcoin checksum rejected", R[6]["status"] == "error" and "checksum" in R[6]["error"], R[6]["error"])
    check("garbage rejected with a reason", R[7]["status"] == "error" and R[7]["error"], R[7]["error"])
    check("chain column picks Base for a 0x address", R[8]["chain"] == "base" and R[8]["id"].startswith("base:0xAeb1"), R[8]["id"])
    check("tx hash detected; unknown role warned", R[9]["kind"] == "tx" and any("unknown role" in w for w in R[9]["warnings"]), R[9])
    check("TRON detected", R[10]["chain"] == "tron" and R[10]["status"] == "ok")
    j = parse("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa\n0x28C6c06298d514Db089934071355E5743bf21d60\tBinance 14\texchange\n").json()
    check("pasted list (tab separated) with label + role", j["summary"]["format"] == "list" and j["rows"][1]["label"] == "Binance 14" and j["rows"][1]["role"] == "exchange" and any("assumed Ethereum" in w for w in j["rows"][1]["warnings"]))
    big = "\n".join(["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"] * 600); j = parse(big).json()
    check("row cap: only the first 500 read, duplicates flagged", j["summary"]["capped"] and j["summary"]["rows"] == 500 and j["summary"]["duplicates"] == 499, j["summary"])
    r = parse("x" * 300000); check("size cap -> 413", r.status_code == 413, r.status_code)
    r = httpx.post(U + "/api/import/parse", json={"text": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"}, timeout=30); check("requires login", r.status_code == 401)
    # the imported real addresses resolve on-chain
    for q in ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "base:0xAeb1e2fd27eF697b648a14aC94ff8E245294f31f"):
        d = httpx.get(U + "/api/lookup", params={"q": q}, auth=A, timeout=120).json()
        check(f"imported {q[:12]}… looks up on mainnet", d.get("txs") or d.get("tx_count"), d.get("detail"))

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1600, "height": 950}, http_credentials=AUTH, accept_downloads=True)
        pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + "/"); await pg.wait_for_function("typeof ctImport==='function'")
        await pg.click("#impbtn"); await pg.wait_for_selector("#impm.on")
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False); f.write(MIX); f.close()
        await pg.set_input_files("#impf", f.name); await pg.wait_for_selector("#impres table", timeout=20000)
        txt = await pg.inner_text("#impres")
        check("ui: file upload validates and shows per-row status", "5 valid" in txt and "3 error(s)" in txt and "1 duplicate(s)" in txt and "EIP-55" in txt, txt[:160])
        if SHOTS: await pg.screenshot(path=SHOT("desktop"))
        await pg.click("#impcase"); await pg.wait_for_function("window.CT_IMPORT_DONE", timeout=10000)
        st = await pg.evaluate("""(()=>({n:cy.nodes().length,ids:cy.nodes().map(n=>n.id()),lab:effLabel('1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'),ex:cy.getElementById('base:0xAeb1e2fd27eF697b648a14aC94ff8E245294f31f').data('kind'),
              v:CT_LOSS.victims,s:CT_LOSS.suspect,case:curCase&&curCase.name,note:JSON.stringify(curCase.notes.nodes['1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa']||'')}))()""")
        check("ui: valid rows added to the graph", st["n"] >= 5 and "tx:0x3b9e6a9a7b5f1c4d0a0f0e7fa7a1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9" in st["ids"], st["n"])
        check("ui: labels applied to the case", (st["lab"] or {}).get("name") == "Genesis (test)", st["lab"])
        check("ui: exchange role -> exchange node", st["ex"] == "exchange")
        check("ui: victim + suspect roles -> loss marks", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" in st["v"] and st["s"] == "0x85FAa6C1F2450b9caEA300838981C2e6E120C35c", (st["v"], st["s"]))
        check("ui: notes stored on the node", "first victim wallet" in st["note"], st["note"])
        await pg.click("#impwatch"); await pg.wait_for_function("window.CT_IMPORT_WATCH", timeout=5000)
        wl = await pg.evaluate("ctWItems().map(x=>x.address)")
        check("ui: addresses added to the watchlist (no tx hashes)", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" in wl and not any(x.startswith("tx:") for x in wl) and len(wl) >= 4, wl)
        await pg.click("#impwatch"); await pg.wait_for_timeout(300)
        check("ui: re-adding skips already-watched", await pg.evaluate("CT_IMPORT_WATCH.added===0&&CT_IMPORT_WATCH.skipped>=4"))
        async with pg.expect_download() as dl: await pg.click("text=⬇ Error report")
        e = open(await (await dl.value).path()).read(); check("ui: error report CSV lists the bad rows", e.count("\n") >= 4 and "EIP-55" in e, e[:100])
        check("desktop: no JS errors", not errs, errs[:2]); await ctx.close()
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, http_credentials=AUTH)
        pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + "/"); await pg.wait_for_function("typeof ctImport==='function'"); await pg.evaluate("ctImport(true)")
        await pg.fill("#impt", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa, Genesis, victim\nbad\n0x28C6c06298d514Db089934071355E5743bf21d60, Binance 14, exchange")
        await pg.tap("#impv"); await pg.wait_for_selector("#impres table", timeout=20000)
        ov = await pg.evaluate("document.querySelector('#impm .card').scrollWidth<=document.querySelector('#impm .card').clientWidth+2")
        check("phone: import sheet fits the width", ov)
        if SHOTS: await pg.screenshot(path=SHOT("phone"))
        await pg.tap("#impcase"); await pg.wait_for_function("window.CT_IMPORT_DONE", timeout=10000)
        check("phone: add to case works", await pg.evaluate("cy.nodes().length>=2"))
        check("phone: no JS errors", not errs, errs[:2]); await ctx.close(); await b.close()

api(); asyncio.run(ui())
print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
sys.exit(1 if bad else 0)
