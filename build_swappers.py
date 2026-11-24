"""Build data/swappers.json: addresses of instant (no-account / no-KYC) swap services, for heuristic cross-chain swap leads (v29).
Only documented public sources: the openly licensed label datasets in data/labels.sqlite (each row keeps its source + URL; built by
update_labels.py) and data/exposure_curated.json (hand-curated, source URL per entry). Nothing is inferred or invented.
Excluded on purpose: deployer / token contracts, charity or unrelated entities that share a name, hacker-tagged addresses
(e.g. 'Upbit Hacker 9.1: ChangeNow 1' is a hacker deposit, not a service wallet) and scam look-alike domains.
Run: python3 build_swappers.py   (needs data/labels.sqlite)."""
import json, os, re, sqlite3, time
H = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(H, "data")
SERVICES = [("ChangeNOW", r"\bchange\s?now\b"), ("FixedFloat", r"\bfixed\s?float\b"), ("Changelly", r"\bchangelly\b"), ("SideShift", r"\bside\s?shift\b"),
            ("eXch", r"\bexch\b"), ("SimpleSwap", r"\bsimpleswap\b"), ("StealthEX", r"\bstealthex\b"), ("LetsExchange", r"\bletsexchange\b"), ("Exolix", r"\bexolix\b")]
SKIP = re.compile(r"deployer|token|endaoment|hacker|exploiter|scam|phish|\.com|\.io|bitballoon|deposit funder", re.I)
SRCNAME = {"etherscan-labels": "brianleect/etherscan-labels (Etherscan public labels)", "dawsbot": "dawsbot/eth-labels (Etherscan public labels)",
           "graphsense": "GraphSense public TagPacks", "openlabels": "AI DECISIONS openlabels"}
def main():
    out = {}
    def put(c, a, svc, name, src, url):
        k = (c, a.lower() if a.startswith("0x") else a)
        if k in out: return
        out[k] = {"c": k[0], "a": k[1], "service": svc, "name": name, "src": src, "url": url}
    for e in json.load(open(os.path.join(D, "exposure_curated.json")))["entries"]:
        if e["cat"] == "nokyc_swap":
            svc = next((s for s, p in SERVICES if re.search(p, e["name"], re.I)), None)
            if svc: put(e["c"], e["a"], svc, e["name"], e["src"], e["url"])
    db = sqlite3.connect(os.path.join(D, "labels.sqlite"))
    for c, a, cat, name, src, url in db.execute("SELECT chain,address,category,name,source,source_url FROM labels"):
        nm = name or ""
        svc = next((s for s, p in SERVICES if re.search(p, nm, re.I)), None)
        if not svc or SKIP.search(nm) or cat in ("scam", "hack", "phishing"): continue
        put(c, a, svc, nm, SRCNAME.get(src, src), url)
    rows = sorted(out.values(), key=lambda r: (r["service"], r["c"], r["a"]))
    json.dump({"_about": "Instant-swap service addresses from documented public label sources (one source + URL per row). Heuristic swap leads only.",
               "generated": int(time.time()), "entries": rows}, open(os.path.join(D, "swappers.json"), "w"), indent=0)
    print(len(rows), sorted({r["service"] for r in rows}))
if __name__ == "__main__": main()
