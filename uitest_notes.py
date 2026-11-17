"""v21 case notes journal + tamper-evident audit log: notes on case / address / flow (author, UK+UTC time, tags, edit history,
soft delete), audit entries for every case action, SHA-256 hash chain (same result in browser and server), tamper detection,
server-signed anchor receipts, persistence across reloads, PDF report section + appendix, evidence-pack CSV/JSON, phone layout.
Uses only pasted public addresses (no lookups). Password from env LP (never printed).
Usage: LP=... python3 uitest_notes.py   (CT_URL for another server; SHOTS=0 to skip screenshots)"""
import asyncio, os, sys, json, io, zipfile, base64, subprocess, tempfile
import httpx
from playwright.async_api import async_playwright
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
U = os.environ.get("CT_URL", "http://localhost:8090").rstrip("/"); AUTH = {"username": os.environ.get("LU", "krixen"), "password": os.environ["LP"]}
A = (AUTH["username"], AUTH["password"])
SHOTS = os.environ.get("SHOTS", "1") != "0"; TAG = os.environ.get("SHOT_TAG", ""); SHOT = lambda n: os.path.join(H, f"screenshot_v21_notes_{n}{TAG}.png")
GEN, B14 = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "0x28C6c06298d514Db089934071355E5743bf21d60"
ok, bad = [], []
def check(name, cond, info=""):
    (ok if cond else bad).append(name); print(("PASS " if cond else "FAIL ") + name, str(info)[:240], flush=True)

def api():
    import auditlog
    r = httpx.post(U + "/api/audit/anchor", json={"case_id": "x", "seq": 1, "head": "a" * 64}, timeout=20); check("anchor: requires login", r.status_code == 401, r.status_code)
    r = httpx.post(U + "/api/audit/anchor", json={"case_id": "c1", "seq": 3, "head": "ab" * 32}, auth=A, timeout=20); j = r.json()
    check("anchor: signed receipt", r.status_code == 200 and len(j.get("sig", "")) == 64 and j["head"] == "ab" * 32 and j["seq"] == 3, {k: j.get(k) for k in ("seq", "t", "alg")})
    r2 = httpx.post(U + "/api/audit/verify", json=j, auth=A, timeout=20).json(); check("verify: genuine receipt valid", r2.get("valid") is True)
    r3 = httpx.post(U + "/api/audit/verify", json=dict(j, seq=4), auth=A, timeout=20).json(); check("verify: altered receipt invalid", r3.get("valid") is False)
    r = httpx.post(U + "/api/audit/anchor", json={"case_id": "c1", "seq": 1, "head": "nothex"}, auth=A, timeout=20); check("anchor: bad head -> 400", r.status_code == 400)
    # python-side chain (same formula as the browser)
    e1 = {"seq": 1, "t": 1, "actor": "a", "action": "x", "target": "", "detail": {"k": "£ → ✓\nz"}, "prev": "0" * 64}; e1["h"] = auditlog.entry_hash(e1)
    e2 = {"seq": 2, "t": 2, "actor": "a", "action": "y", "target": "t", "detail": {}, "prev": e1["h"]}; e2["h"] = auditlog.entry_hash(e2)
    check("auditlog.verify: intact chain", auditlog.verify([e1, e2])["ok"])
    check("auditlog.verify: altered entry detected", auditlog.verify([dict(e1, actor="b"), e2]) == {"ok": False, "n": 2, "at": 1, "why": "entry altered"})
    check("auditlog.verify: deleted entry detected", not auditlog.verify([e2])["ok"])

async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1600, "height": 950}, http_credentials=AUTH, accept_downloads=True)
        pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept("Notes test case (renamed)" if d.type == "prompt" else None)))
        await pg.goto(U + "/"); await pg.evaluate("localStorage.ct_author='DC Test'"); await pg.reload()
        await pg.wait_for_function("typeof ctNotes==='function'&&typeof ctImport==='function'")
        check("toolbar: 📝 Notes button present", await pg.is_visible("#notesbtn"))
        await pg.evaluate("ctImport(true)")
        await pg.fill("#impt", f"{GEN}, Genesis (test), victim, first victim wallet\n{B14}, Binance 14 (test), exchange")
        await pg.click("#impv"); await pg.wait_for_selector("#impres table", timeout=20000); await pg.click("#impcase")
        await pg.wait_for_function("window.CT_IMPORT_DONE", timeout=10000); await pg.evaluate("ctImport(false)")
        await pg.wait_for_function("curCase&&curCase.audit&&curCase.audit.some(e=>e.action==='graph.changed')", timeout=8000)
        st = await pg.evaluate("({j:curCase.journal,a:curCase.audit.map(e=>e.action),n:curCase.notes.nodes})")
        check("import note -> journal entry by the investigator", len(st["j"]) == 1 and st["j"][0]["author"] == "DC Test" and st["j"][0]["source"] == "import" and st["j"][0]["target"] == GEN, st["j"][:1])
        check("import note mirrored into node notes (graph decoration)", "first victim wallet" in (st["n"].get(GEN) or "") and await pg.evaluate(f"cy.getElementById('{GEN}').data('note')===1"))
        check("audit: case.created first, then import, note, graph", st["a"][0] == "case.created" and {"import", "note.added", "graph.changed", "role.marked"} <= set(st["a"]), st["a"])
        # case-level note from the panel (unicode + newline + tags)
        await pg.evaluate("ctNotes(true)"); await pg.wait_for_selector("#cn-new")
        await pg.fill("#cn-new", "Victim reported £5,000 loss → called Action Fraud ✓\nNext: VASP request"); await pg.fill("#cn-tags", "call log, next step")
        await pg.click("#cn-add"); await pg.wait_for_function("curCase.journal.length===2")
        tx = await pg.inner_text("#cn-list")
        check("panel: case note listed with author, UK time, tags", "DC Test" in tx and ("GMT" in tx or "BST" in tx) and "UTC" in tx and "call log" in tx and "£5,000" in tx, tx[:200])
        await pg.evaluate("ctNotes(false)")
        # address note from the side card
        await pg.evaluate(f"const n=cy.getElementById('{B14}');cy.elements().unselect();n.select();n.emit('tap')")
        await pg.wait_for_selector("#noteCard #noteAdd", timeout=5000)
        await pg.fill("#noteTxt", "Deposit address seen in the victim's exchange statement"); await pg.click("#noteAdd")
        await pg.wait_for_function("curCase.journal.length===3")
        check("side card: note added and listed", "exchange statement" in await pg.inner_text("#noteList"))
        nid = await pg.evaluate("curCase.journal[2].id")
        await pg.click(f"#noteList [data-note='{nid}'] button:has-text('Edit')"); await pg.fill(f"#noteList [data-note='{nid}'] textarea", "Deposit address (Binance) seen in the victim's statement, 03/11")
        await pg.click(f"#noteList [data-note='{nid}'] button:has-text('Save edit')"); await pg.wait_for_function(f"curCase.journal[2].rev.length===1")
        st = await pg.evaluate("({e:curCase.journal[2],n:curCase.notes.nodes})")
        check("edit keeps the earlier version", st["e"]["rev"][0]["text"].startswith("Deposit address seen") and "03/11" in st["e"]["text"] and "03/11" in st["n"].get(B14, ""))
        # custom label via the side card
        await pg.fill("#clName", "Suspect cash-out (test)"); await pg.click("#noteCard button:has-text('Apply')"); await pg.wait_for_timeout(400)
        # delete the first (import) note
        await pg.evaluate("ctNotes(true)"); await pg.wait_for_selector("#cn-list")
        inid = await pg.evaluate("curCase.journal[0].id")
        await pg.click(f"#cn-list [data-note='{inid}'] button:has-text('Delete')"); await pg.wait_for_function("curCase.journal[0].deleted")
        dv = await pg.evaluate(f"[!!curCase.journal[0].deleted,!curCase.notes.nodes['{GEN}'],cy.getElementById('{GEN}').data('note')]")
        check("delete is soft: kept + marked, removed from node notes", dv[0] and dv[1] and not dv[2], dv)
        await pg.select_option("#cn-k", "deleted"); check("filter: deleted notes", "first victim wallet" in await pg.inner_text("#cn-list"))
        await pg.select_option("#cn-k", ""); await pg.fill("#cn-q", "VASP"); await pg.wait_for_timeout(200)
        check("search filter", "Action Fraud" in await pg.inner_text("#cn-list") and "statement" not in await pg.inner_text("#cn-list"))
        await pg.fill("#cn-q", ""); await pg.wait_for_timeout(200)
        # rename (prompt auto-accepted)
        cid_ = await pg.evaluate("curCase.id"); await pg.evaluate(f"renameCase('{cid_}')"); await pg.wait_for_timeout(500)
        await pg.evaluate("persist()"); await pg.wait_for_timeout(800)
        acts = await pg.evaluate("curCase.audit.map(e=>e.action)")
        for a in ("note.added", "note.edited", "note.deleted", "label.set", "case.renamed", "role.marked"): check(f"audit records {a}", a in acts, acts)
        # audit tab: verify, anchor, receipts
        await pg.click("#cn-ta"); await pg.wait_for_selector("#cn-ver")
        check("audit tab: chain intact", "Chain intact" in await pg.inner_text("#cn-ver"), await pg.inner_text("#cn-ver"))
        await pg.click("#cnm button:has-text('Anchor')"); await pg.wait_for_function("curCase.anchors&&curCase.anchors.length===1", timeout=8000)
        await pg.wait_for_selector("#cnm button:has-text('Check receipts'):not([disabled])"); await pg.click("#cnm button:has-text('Check receipts')"); await pg.wait_for_function("window.CT_ANCHOR_CHECK", timeout=8000)
        check("anchor receipt valid and matches the log", await pg.evaluate("CT_ANCHOR_CHECK.n===1&&CT_ANCHOR_CHECK.bad===0"), await pg.evaluate("CT_ANCHOR_CHECK"))
        if SHOTS: await pg.screenshot(path=SHOT("audit_desktop"))
        # cross-language: server recomputes the browser's chain
        au = await pg.evaluate("curCase.audit"); anc = await pg.evaluate("curCase.anchors[0]")
        r = httpx.post(U + "/api/audit/verify", json={"entries": au, "receipt": anc}, auth=A, timeout=20).json()
        check("server verifies the browser's hash chain + receipt", r["ok"] and r["head"] == au[-1]["h"] and r.get("receipt_matches") is True, r)
        # tamper detection (in-page), then restore
        v = await pg.evaluate("(async()=>{const e=curCase.audit[2];const o=e.actor;e.actor='someone else';const v=await ctAuditVerify();e.actor=o;return v})()")
        check("tamper: edited entry breaks the chain", v["ok"] is False and v["at"] == 3, v)
        v = await pg.evaluate("(async()=>{const x=curCase.audit.splice(1,1);const v=await ctAuditVerify();curCase.audit.splice(1,0,x[0]);return v})()")
        check("tamper: deleted entry breaks the chain", v["ok"] is False and v["at"] == 3, v)
        # exports
        async with pg.expect_download() as dl: await pg.click("#cnm button:has-text('⬇ CSV')")
        c = open(await (await dl.value).path(), encoding="utf-8-sig").read(); check("audit CSV export", c.startswith("seq,time_uk") and "note.edited" in c and c.count("\n") >= 8)
        await pg.click("#cn-tn"); await pg.wait_for_selector("#cn-list")
        async with pg.expect_download() as dl: await pg.click("#cnm button:has-text('Notes CSV')")
        c = open(await (await dl.value).path(), encoding="utf-8-sig").read(); check("notes CSV export (with deleted + edited)", "deleted" in c and "edited" in c and "£5,000" in c)
        if SHOTS: await pg.screenshot(path=SHOT("desktop"))
        await pg.evaluate("ctNotes(false)")
        # report + evidence pack
        res = await pg.evaluate("""(async()=>{const pl=ctReportPayload({ref:'NOTES-TEST',investigator:'DC Test',marking:'',notes:'',noise:false,img:false});
          const r=await fetch('/api/report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pl)});const b=new Uint8Array(await r.arrayBuffer());let s='';for(const x of b)s+=String.fromCharCode(x);
          const r2=await fetch('/api/evidence-pack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pl)});const b2=new Uint8Array(await r2.arrayBuffer());let s2='';for(const x of b2)s2+=String.fromCharCode(x);
          return {st:r.status,pdf:btoa(s),st2:r2.status,zip:btoa(s2)}})()""")
        check("report generated", res["st"] == 200, res["st"])
        td = tempfile.mkdtemp(); pp = os.path.join(td, "r.pdf"); open(pp, "wb").write(base64.b64decode(res["pdf"]))
        t = subprocess.run(["pdftotext", "-layout", pp, "-"], capture_output=True, text=True).stdout
        check("PDF: notes journal with author + earlier version + deleted marker", "Notes journal" in t and "DC Test" in t and "earlier version" in t and "DELETED" in t, "")
        check("PDF: audit log appendix, chain intact, receipt matches", "A.6 Case audit log" in t and "Intact" in t and "receipt valid and matches this log" in t, "")
        check("evidence pack generated", res["st2"] == 200, res["st2"])
        z = zipfile.ZipFile(io.BytesIO(base64.b64decode(res["zip"]))); names = [n.split("/", 1)[1] for n in z.namelist()]
        check("pack: case_notes.csv + audit CSV/JSON", {"case_notes.csv", "case_audit_log.csv", "case_audit_log.json"} <= set(names), names)
        jj = json.loads(z.read([n for n in z.namelist() if n.endswith("case_audit_log.json")][0]))
        check("pack: audit JSON verification ok", jj["verification"]["ok"], jj["verification"])
        sums = z.read([n for n in z.namelist() if n.endswith("SHA256SUMS.txt")][0]).decode(); check("pack: new files listed in SHA256SUMS", "case_audit_log.json" in sums)
        await pg.wait_for_function("curCase.audit.some(e=>e.action==='evidence.pack')&&curCase.audit.some(e=>e.action==='report.pdf')", timeout=8000)
        check("audit records report.pdf + evidence.pack", True)
        await pg.evaluate("persist()"); await pg.wait_for_timeout(800)
        # persistence across reload
        await pg.goto(U + f"/?case={cid_}"); await pg.wait_for_function(f"curCase&&curCase.id==='{cid_}'", timeout=15000)
        await pg.wait_for_function("curCase.audit.some(e=>e.action==='case.opened')", timeout=8000)
        v = await pg.evaluate("(async()=>({v:await ctAuditVerify(),j:curCase.journal.length,a:curCase.anchors.length}))()")
        check("reload: journal, audit (intact) and receipts persisted", v["v"]["ok"] and v["j"] == 3 and v["a"] == 1, v)
        check("desktop: no JS errors", not errs, errs[:3]); await ctx.close()
        # phone
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, http_credentials=AUTH)
        pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U + "/"); await pg.evaluate("localStorage.ct_author='DC Phone'")
        await pg.evaluate(f"ctImport(true)"); await pg.fill("#impt", f"{GEN}, Genesis, victim"); await pg.tap("#impv"); await pg.wait_for_selector("#impres table", timeout=20000)
        await pg.tap("#impcase"); await pg.wait_for_function("window.CT_IMPORT_DONE", timeout=10000); await pg.evaluate("ctImport(false)")
        await pg.evaluate("ctNotes(true)"); await pg.wait_for_selector("#cn-new")
        await pg.fill("#cn-new", "Phone note"); await pg.tap("#cn-add"); await pg.wait_for_function("curCase.journal.length===1")
        fits = await pg.evaluate("document.querySelector('#cnm .card').scrollWidth<=document.querySelector('#cnm .card').clientWidth+2")
        check("phone: notes sheet fits the width", fits); check("phone: note by DC Phone listed", "DC Phone" in await pg.inner_text("#cn-list"))
        if SHOTS: await pg.screenshot(path=SHOT("phone"))
        await pg.tap("#cn-ta"); await pg.wait_for_selector("#cn-ver")
        fits = await pg.evaluate("document.querySelector('#cnm .card').scrollWidth<=document.querySelector('#cnm .card').clientWidth+2")
        check("phone: audit tab fits + intact", fits and "intact" in await pg.inner_text("#cn-ver"))
        if SHOTS: await pg.screenshot(path=SHOT("audit_phone"))
        check("phone: no JS errors", not errs, errs[:3]); await ctx.close(); await b.close()

api(); asyncio.run(ui())
print(f"\n{len(ok)} passed, {len(bad)} failed" + ("" if not bad else ": " + "; ".join(bad)))
sys.exit(1 if bad else 0)
