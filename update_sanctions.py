#!/usr/bin/env python3
"""Build data/sanctions.json: digital-currency addresses on official sanctions lists, with list metadata.

Sources (both official government publications, public domain / Open Government Licence):
  * US Treasury OFAC SDN list, Advanced XML (designation dates + programs)
      https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ADVANCED.XML
  * UK Sanctions List (FCDO; replaced the OFSI Consolidated List on 28 Jan 2026), CSV.
      https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv
    The UK list has no address field: wallets appear in the free-text "Other Information" column. Only strings that pass the
    chain's own checksum/format check are kept, and only from rows whose text talks about crypto / wallets / digital currency.

Usage: python3 update_sanctions.py [--out PATH] [--no-uk] [--ofac-file sdn_advanced.xml] [--uk-file uk.csv]
Streams downloads to a temp file and parses with iterparse, so peak RAM stays ~tens of MB."""
import csv, datetime as dt, hashlib, io, json, os, re, sys, tempfile, time, urllib.request
import xml.etree.ElementTree as ET
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
import addrutil
OFAC_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ADVANCED.XML"
OFAC_SEARCH = "https://sanctionssearch.ofac.treas.gov/Details.aspx?id="
UK_URL = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv"
UK_PAGE = "https://www.gov.uk/government/publications/the-uk-sanctions-list"
OUT = os.path.join(H, "data", "sanctions.json")
UA = {"User-Agent": "ChainTrace sanctions screening (+https://github.com/krixengg-rgb)"}
EVM_ASSETS = {"ETH", "USDT", "USDC", "ARB", "BSC", "BNB", "ETC"}
SUPPORTED = ("btc", "eth", "sol", "tron", "xrp")

def fetch(url, timeout=240):
    fd, p = tempfile.mkstemp(prefix="ct-sanc-"); os.close(fd)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(p, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b: break
            f.write(b)
    return p

# ---------- address classification (format + checksum; never guesses) ----------
def _b58check(a):
    try:
        raw = addrutil.b58decode(a)
        return raw if len(raw) == 25 and addrutil._chk(raw[:21]) == raw[21:] else None
    except Exception: return None
_BECH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
def _bech32_ok(a):
    a = a.lower()
    if not a.startswith("bc1") or len(a) > 90: return False
    try: data = [_BECH.index(c) for c in a[3:]]
    except ValueError: return False
    gen = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]; chk = 1
    for v in [ord(x) >> 5 for x in "bc"] + [0] + [ord(x) & 31 for x in "bc"] + data:
        b = chk >> 25; chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5): chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk in (1, 0x2bc830a3)   # bech32 / bech32m
def is_btc(a):
    if a.lower().startswith("bc1"): return _bech32_ok(a)
    raw = _b58check(a) if re.fullmatch(r"[13][1-9A-HJ-NP-Za-km-z]{25,34}", a) else None
    return bool(raw) and raw[0] in (0x00, 0x05)
def is_sol(a):
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", a): return False
    try: return len(addrutil.b58decode(a)) == 32
    except Exception: return False
def classify(addr, asset):
    """(chain, normalised key) for a listed address, or (asset.lower(), addr) for chains ChainTrace does not trace."""
    a = addr.strip(); asset = (asset or "").upper()
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", a): return "eth", a.lower()
    if addrutil.is_tron_address(a): return "tron", a
    if asset == "XRP" and addrutil.is_xrp_address(a): return "xrp", a
    if asset == "SOL" and is_sol(a): return "sol", a
    if asset in ("XBT", "USDT", "") and is_btc(a): return "btc", (a.lower() if a.lower().startswith("bc1") else a)
    if asset == "" and addrutil.is_xrp_address(a): return "xrp", a
    if asset == "" and is_sol(a): return "sol", a
    return (asset.lower() or "other"), a

# ---------- OFAC SDN Advanced XML ----------
def parse_ofac(path):
    ns = ""; ftypes = {}; subtypes = {}; ptypes = {}; issued = None
    parties = {}   # profile id -> {name, type, fixed, addrs:[(asset, addr)]}
    entries = {}   # profile id -> {date, programs}
    t0 = time.time()
    def _item(tag, el):
        if tag == "DistinctParty":
            prof = el.find(ns + "Profile")
            if prof is None: return
            addrs = []
            for f in prof.findall(ns + "Feature"):
                asset = ftypes.get(f.get("FeatureTypeID"))
                if not asset: continue
                for vd in f.iter(ns + "VersionDetail"):
                    if vd.text and vd.text.strip(): addrs.append((asset, vd.text.strip()))
            if not addrs: return
            name = None
            for al in prof.iter(ns + "Alias"):
                if al.get("Primary") == "true":
                    dn = al.find(ns + "DocumentedName")   # first documented name = Latin-script form
                    name = " ".join(x.text.strip() for x in (dn if dn is not None else al).iter(ns + "NamePartValue") if x.text); break
            parties[prof.get("ID")] = {"name": name, "sub": prof.get("PartySubTypeID"), "fixed": el.get("FixedRef"), "addrs": addrs}
        elif tag == "SanctionsEntry":
            pid = el.get("ProfileID")
            if pid not in parties: return
            ds = []
            for e2 in el.findall(ns + "EntryEvent"):
                d = e2.find(ns + "Date")
                if d is not None:
                    try: ds.append(f"{int(d.findtext(ns + 'Year')):04d}-{int(d.findtext(ns + 'Month')):02d}-{int(d.findtext(ns + 'Day')):02d}")
                    except Exception: pass
            progs = [m.findtext(ns + "Comment").strip() for m in el.findall(ns + "SanctionsMeasure")
                     if m.get("SanctionsTypeID") == "1" and (m.findtext(ns + "Comment") or "").strip()]
            entries[pid] = {"listed": min(ds) if ds else None, "programs": progs, "list_id": el.get("ListID")}
    stack = []
    for ev, el in ET.iterparse(path, events=("start", "end")):
        tag = el.tag.split("}", 1)[-1]
        if ev == "start":
            if not ns and "}" in el.tag: ns = el.tag.split("}", 1)[0] + "}"
            stack.append(el); continue
        stack.pop()
        if len(stack) == 2:   # Sanctions > Section > Item: process (below) then drop it so the tree never grows (peak RAM ~ tens of MB)
            try: _item(tag, el)
            finally: stack[-1].remove(el)
            continue
        if tag == "FeatureType" and (el.text or "").startswith("Digital Currency Address - "):
            ftypes[el.get("ID")] = el.text.rsplit("- ", 1)[1].strip()
        elif tag == "PartySubType": subtypes[el.get("ID")] = ((el.text or "").strip(), el.get("PartyTypeID"))
        elif tag == "PartyType": ptypes[el.get("ID")] = (el.text or "").strip()
        elif tag == "DateOfIssue":
            g = lambda k: int(el.findtext(ns + k) or 0)
            issued = f"{g('Year'):04d}-{g('Month'):02d}-{g('Day'):02d}"
    out = []
    for pid, p in parties.items():
        e = entries.get(pid, {}); st, pt = subtypes.get(p["sub"], ("", None))
        p["type"] = ptypes.get(pt) or (st if st != "Unknown" else "")
        for asset, a in p["addrs"]:
            c, k = classify(a, asset)
            out.append({"a": k, "raw": a, "c": c, "asset": asset, "l": "ofac", "uid": p["fixed"], "name": p["name"], "type": p["type"],
                        "programs": e.get("programs") or [], "listed": e.get("listed"), "url": OFAC_SEARCH + str(p["fixed"])})
    print(f"OFAC: {len(parties)} parties with addresses, {len(out)} addresses, issued {issued} ({time.time() - t0:.1f}s)")
    return out, issued

# ---------- UK Sanctions List CSV ----------
CRYPTO_TXT = re.compile(r"crypto|wallet|digital currency|virtual asset|bitcoin|ethereum|tron|usdt|tether", re.I)
CAND = re.compile(r"0x[0-9a-fA-F]{40}|bc1[02-9ac-hj-np-z]{11,71}|T[1-9A-HJ-NP-Za-km-z]{33}|[13][1-9A-HJ-NP-Za-km-z]{25,34}|r[1-9A-HJ-NP-Za-km-z]{24,34}")
def _uk_date(s):
    try: return dt.datetime.strptime(s.strip(), "%d/%m/%Y").date().isoformat()
    except Exception: return None
def parse_uk(path):
    fh = open(path, encoding="utf-8-sig", errors="replace", newline="")
    first = fh.readline()
    report = None
    m = re.search(r"Report Date:\s*(\d{2}-[A-Za-z]{3}-\d{4})", first)
    if m: report = dt.datetime.strptime(m.group(1), "%d-%b-%Y").date().isoformat()
    by = {}
    for r in csv.DictReader(fh):
        uid = r.get("Unique ID"); txt = r.get("Other Information") or ""
        b = by.setdefault(uid, {"name": None, "regime": r.get("Regime Name"), "listed": _uk_date(r.get("Date Designated") or ""),
                                "type": r.get("Designation Type"), "ofsi": r.get("OFSI Group ID"), "addrs": set()})
        if (r.get("Name type") or "").lower().startswith("primary name") and not b["name"]:
            b["name"] = " ".join(x for x in (r.get(f"Name {i}") for i in (1, 2, 3, 4, 5, 6)) if x and x.strip()).strip()
        if txt and CRYPTO_TXT.search(txt):
            pos = 0
            while True:   # wallets are sometimes concatenated without spaces in the source text: scan, don't split
                m = CAND.search(txt, pos)
                if not m: break
                cand = m.group(0); hit = None
                for ln in range(len(cand), 24, -1):   # longest prefix that passes a checksum
                    s = cand[:ln]
                    if (s.startswith("0x") and ln == 42) or addrutil.is_tron_address(s) or is_btc(s) or (s[0] == "r" and addrutil.is_xrp_address(s)):
                        hit = s; break
                if hit: b["addrs"].add(hit); pos = m.start() + len(hit)
                else: pos = m.start() + 1
    out = []
    for uid, b in by.items():
        for a in sorted(b["addrs"]):
            c, k = classify(a, "")
            if c not in SUPPORTED: continue
            out.append({"a": k, "raw": a, "c": c, "asset": "", "l": "uk", "uid": uid, "name": b["name"] or uid, "type": b["type"] or "",
                        "programs": [b["regime"]] if b["regime"] else [], "listed": b["listed"], "url": UK_PAGE})
    print(f"UK: {sum(1 for b in by.values() if b['addrs'])} designations with wallet text, {len(out)} addresses, report date {report}")
    return out, report

def build(out=OUT, uk=True, ofac_file=None, uk_file=None):
    t0 = time.time(); lists = {}; entries = []; tmp = []
    try:
        p = ofac_file or fetch(OFAC_URL); tmp += [] if ofac_file else [p]
        e, issued = parse_ofac(p); entries += e
        lists["ofac"] = {"name": "US Treasury OFAC Specially Designated Nationals (SDN) List", "short": "OFAC SDN", "as_of": issued,
                         "url": OFAC_URL, "page": "https://ofac.treasury.gov/specially-designated-nationals-and-blocked-persons-list-sdn-human-readable-lists",
                         "licence": "US Government work (public domain)", "addresses": len(e)}
    finally:
        for x in tmp: os.path.exists(x) and os.remove(x)
    if uk:
        tmp = []
        try:
            p = uk_file or fetch(UK_URL); tmp += [] if uk_file else [p]
            e, rep = parse_uk(p); entries += e
            lists["uk"] = {"name": "UK Sanctions List (FCDO)", "short": "UK Sanctions List", "as_of": rep, "url": UK_URL, "page": UK_PAGE,
                           "licence": "Open Government Licence v3.0", "addresses": len(e),
                           "note": "Wallets are parsed from the free-text 'Other Information' field and kept only if they pass the chain's checksum."}
        except Exception as ex: print("UK list failed (kept OFAC only):", ex)
        finally:
            for x in tmp: os.path.exists(x) and os.remove(x)
    entries.sort(key=lambda x: (x["l"], x["c"], x["a"]))
    counts = {}
    for x in entries: counts.setdefault(x["l"], {}).setdefault(x["c"], 0); counts[x["l"]][x["c"]] += 1
    doc = {"generated": int(time.time()), "lists": lists, "counts": counts, "entries": entries}
    body = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
    doc["sha256"] = hashlib.sha256(body.encode()).hexdigest()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out + ".tmp", "w") as f: json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(out + ".tmp", out)
    print("wrote", out, os.path.getsize(out) // 1024, "KB", counts, f"{time.time() - t0:.1f}s")
    return doc

if __name__ == "__main__":
    a = sys.argv; g = lambda k: a[a.index(k) + 1] if k in a else None
    build(g("--out") or OUT, "--no-uk" not in a, g("--ofac-file"), g("--uk-file"))
