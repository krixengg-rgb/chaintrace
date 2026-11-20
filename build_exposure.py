"""Build data/exposure_labels.json.gz: mixer / privacy / no-KYC swap / gambling labels for exposure screening (v25).
Only documented public sources: OFAC SDN digital-currency addresses (data/sanctions.json), the openly licensed label datasets in
data/labels.sqlite (each row keeps its source and source URL), and data/exposure_curated.json (hand-curated, source URL per entry).
Run: python3 build_exposure.py   (needs data/labels.sqlite from update_labels.py)."""
import gzip, json, os, re, sqlite3, time
H = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(H, "data")
TORNADO_POOL = re.compile(r"tornado\.?cash[^:]*:\s*(?:[\d,.]+\s*(?:eth|dai|cdai|usdt|usdc|cusdc|wbtc)\b|router|proxy|old proxy|mixer \d)", re.I)
NOKYC = re.compile(r"\b(fixedfloat|exch)\b", re.I)
SRCNAME = {"etherscan-labels": "brianleect/etherscan-labels (Etherscan public labels)", "dawsbot": "dawsbot/eth-labels (Etherscan public labels)",
           "graphsense": "GraphSense public TagPacks", "builtin": "ChainTrace seed list (labels.py)", "openlabels": "AI DECISIONS openlabels"}
def main():
    out = {}; n = {}
    def put(c, a, cat, name, src, url, note=None):
        k = (c, a.lower() if c in ("eth", "bsc", "arb", "base", "polygon", "op") else a)
        if k in out: return
        out[k] = {"c": k[0], "a": k[1], "cat": cat, "name": name, "src": src, "url": url, **({"note": note} if note else {})}; n[cat] = n.get(cat, 0) + 1
    for e in json.load(open(os.path.join(D, "exposure_curated.json")))["entries"]: put(e["c"], e["a"], e["cat"], e["name"], e["src"], e["url"])
    for e in json.load(open(os.path.join(D, "sanctions.json")))["entries"]:
        nm = e.get("name") or ""
        if re.search(r"\b(sinbad|blender|tornado)\b", nm, re.I):
            put(e["c"], e["a"], "mixer", f"{nm} (OFAC SDN, listed {e.get('listed')})", "US Treasury OFAC SDN list", e.get("url"))
    db = sqlite3.connect(os.path.join(D, "labels.sqlite"))
    for c, a, cat, name, src, url in db.execute("SELECT chain,address,category,name,source,source_url FROM labels WHERE category IN ('mixer','gambling') OR lower(name) LIKE '%fixedfloat%' OR lower(name) LIKE '%exch%' OR lower(name) LIKE '%tornado%'"):
        s = SRCNAME.get(src, src)
        if "tornado" in (name or "").lower():
            if TORNADO_POOL.search(name or ""): put(c, a, "mixer", name, s, url, "Tornado Cash was designated by OFAC on 8 Aug 2022 and removed from the SDN list on 21 Mar 2025; it remains a mixer")
            continue
        if NOKYC.search(name or "") and not re.search(r"exchange|proxy", name or "", re.I): put(c, a, "nokyc_swap", name, s, url); continue
        if cat == "mixer":
            put(c, a, "privacy" if (name or "").lower().startswith(("samourai", "wasabi")) else "mixer", name + (" (Whirlpool CoinJoin address)" if (name or "").lower().startswith("samourai") else ""), s, url)
        elif cat == "gambling" and not re.search(r"\(\w{2,8}\)\s*$|token", name or "", re.I): put(c, a, "gambling", name, s, url)
    rows = sorted(out.values(), key=lambda r: (r["cat"], r["c"], r["a"]))
    with gzip.open(os.path.join(D, "exposure_labels.json.gz"), "wt") as f:
        json.dump({"generated": int(time.time()), "counts": n, "sources": SRCNAME, "entries": rows}, f, separators=(",", ":"))
    print(n, len(rows))
if __name__ == "__main__": main()
