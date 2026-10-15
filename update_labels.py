#!/usr/bin/env python3
"""Build data/labels.sqlite from openly licensed public label datasets.
Usage: python3 update_labels.py [--no-download] [--include-unclear]
  --include-unclear  also load sources whose upstream licence is unclear (off by default)
Every row records source, source_url, licence and confidence."""
import csv, json, os, sqlite3, sys, re, glob, urllib.request, yaml, shutil
YL = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
H = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(H, "data", "src"); DBP = os.path.join(H, "data", "labels.sqlite")
GH = "https://raw.githubusercontent.com"
GS_PACKS = ["aft-alqaeda-forfeit_vc","binance_hack","chaininfo","defi-protocols-csh","etherscamdb_tagpack","etherscan-label-word-cloud",
 "etherscan-wordcloud-exchange","etherscan-wordcloud-gambling","etherscan-wordcloud-market","etherscan-wordcloud-miner","etherscan-wordcloud-mixing_service",
 "exchange-wallets-binance","exchange-wallets-bitfinexcom","exchange-wallets-huobi","exchange-wallets-kucoin","hacks","hydra","miners","miners_additional",
 "mixing_fc2021","ponzi_scheme","ransomware","ransomwhere","samourai","service-wallets-checksig","sextortion_excello","sextortion_talos","usdt_blacklist",
 "walletexplorer","richest_addresses"] + [f"exchange-wallets-bitmex_{i}" for i in range(7)]
FILES = {  # local name -> url
 **{f"gs/{p}.yaml": f"{GH}/graphsense/graphsense-tagpacks/master/packs/{p}.yaml" for p in GS_PACKS},
 "dawsbot_accounts.csv": f"{GH}/dawsbot/eth-labels/v1/data/csv/accounts.csv",
 "es_accounts.json": f"{GH}/brianleect/etherscan-labels/main/data/etherscan/combined/combinedAccountLabels.json",
 "forta_phishing_scams.csv": f"{GH}/forta-network/labelled-datasets/main/labels/1/phishing_scams.csv",
 "forta_etherscan_malicious_labels.csv": f"{GH}/forta-network/labelled-datasets/main/labels/1/etherscan_malicious_labels.csv",
 "forta_malicious_smart_contracts.csv": f"{GH}/forta-network/labelled-datasets/main/labels/1/malicious_smart_contracts.csv",
 "oli_firstparty.yaml": f"{GH}/ai-decisions/openlabels/main/data/first-party/ai-decisions-first-party-labels.yaml",
 "immike_solana_cex_labels.csv": f"{GH}/ImMike/crypto-wallet-address-labels/main/datasets/solana-wallet-and-program-labels/solana_cex_labels.csv",
 "immike_solana_defi_labels.csv": f"{GH}/ImMike/crypto-wallet-address-labels/main/datasets/solana-wallet-and-program-labels/solana_defi_labels.csv",
 "immike_BTC_ETH_BCH.json": f"{GH}/ImMike/crypto-wallet-address-labels/main/datasets/multi-chain-crypto-address-labels/BTC_ETH_BCH.json",
 "../ofac_ETH.txt": f"{GH}/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_ETH.txt",
 "../ofac_XBT.txt": f"{GH}/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_XBT.txt",
 "../ofac_SOL.txt": f"{GH}/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_SOL.txt",
}
SOURCES = {  # id -> (description, url, licence, default confidence, clear_licence)
 "ofac": ("OFAC SDN digital currency addresses (via 0xB10C extractor)", "https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses", "US Gov public domain data; repo MIT", 1.0, True),
 "graphsense": ("GraphSense public TagPacks", "https://github.com/graphsense/graphsense-tagpacks", "MIT", 0.8, True),
 "dawsbot": ("dawsbot/eth-labels (Etherscan-derived labels)", "https://github.com/dawsbot/eth-labels", "MIT", 0.75, True),
 "etherscan-labels": ("brianleect/etherscan-labels", "https://github.com/brianleect/etherscan-labels", "MIT", 0.7, True),
 "forta": ("Forta labelled datasets (phishing/malicious)", "https://github.com/forta-network/labelled-datasets", "MIT", 0.8, True),
 "openlabels": ("AI DECISIONS openlabels first-party", "https://github.com/ai-decisions/openlabels", "Apache-2.0", 0.6, True),
 "sol-forensic": ("Solana CEX/DeFi labels (ImMike aggregate of apostleoffinance/Solana-Forensic-Analysis-Tool; upstream Vybe/Dune/Flipside-derived)",
                  "https://github.com/ImMike/crypto-wallet-address-labels/tree/main/datasets/solana-wallet-and-program-labels", "MIT (repo); upstream API-derived, provenance caveat", 0.6, True),
 "jasontth": ("Jasontth/crypto_label via ImMike (BTC/ETH)", "https://github.com/Jasontth/crypto_label", "UNCLEAR (no licence upstream)", 0.6, False),
 "builtin": ("ChainTrace hand-curated seed list", "local labels.py", "own work", 0.8, True),
}
EXCH = r"binance|coinbase|kraken|huobi|htx|okx|okex|bitfinex|bittrex|poloniex|kucoin|gate[-. ]?io|bybit|crypto[-. ]?com|gemini|bitstamp|ftx|upbit|bithumb|mexc|bitget|hotbit|robinhood|bitflyer|bitmex|deribit|exchange|cex|hitbtc|\bliquid\b|zb\.com|bitso|coinone|korbit|luno|paxful|localbitcoins|cryptopia|yobit|exmo|wazirx|coincheck|bitpanda"
CAT_RULES = [  # (regex on lowercased label/category text, category)
 (r"sanction|ofac", "sanctioned"), (r"ransom", "ransomware"), (r"darknet|dark[-_ ]?market|^market$|silk ?road|hydra|alphabay|drug", "darknet"),
 (r"tornado|mixer|mixing|whirlpool|samourai|wasabi|coinjoin|chipmixer|blender|sinbad", "mixer"),
 (r"phish|scam|fake_|ponzi|sextortion|fraud|rug|drainer|impersonat", "scam"),
 (r"hack|exploit|heist|attacker|stolen|theft|terror|alqaeda", "hack"), (r"blocked|blacklist|frozen", "blocklisted"),
 (r"gambl|casino|betting|dice|lottery", "gambling"), (r"bridge|layer-2|wormhole|multichain|stargate|hop-protocol|across", "bridge"),
 (EXCH, "exchange"),
 (r"defi|dex|swap|uniswap|sushi|balancer|curve|aave|compound|maker|yearn|lido|1inch|0x-protocol|bancor|synthetix|kyber|dydx|lending|vault|pool|amm|farm|staking|router|raydium|orca|jupiter|marinade|kamino|serum|openbook|meteora|drift|solend", "defi"),
 (r"min(er|ing)|pool", "miner"),
]
RISK = {"sanctioned": 100, "terrorism": 95, "darknet": 85, "ransomware": 85, "hack": 80, "scam": 75, "mixer": 75, "blocklisted": 50, "gambling": 35,
        "exchange": 10, "bridge": 5, "defi": 3, "miner": 0, "other": 0}
def cat_of(*texts):
    t = " ".join(x for x in texts if x).lower()
    for rx, c in CAT_RULES:
        if re.search(rx, t): return c
    return "other"
CONF = {"authority_data": 0.95, "ledger_immanent": 0.9, "service_data": 0.85, "forensic": 0.8, "web_crawl": 0.6, "heuristic": 0.5}
GS_MAP = {"exchange": "exchange", "gambling": "gambling", "miner": "miner", "mixing_service": "mixer", "coinjoin": "mixer",
          "black_list": "blocklisted", "wallet_service": "other", "service": "other"}
GS_PACK = {"aft-alqaeda": "terrorism", "binance_hack": "hack", "etherscamdb": "scam", "hacks": "hack", "ponzi": "scam", "ransom": "ransomware", "sextortion": "scam"}
GS_CUR = {"BTC": "btc", "ETH": "eth", "SOL": "sol"}

def download():
    os.makedirs(os.path.join(SRC, "gs"), exist_ok=True)
    for f, u in FILES.items():
        p = os.path.normpath(os.path.join(SRC, f))
        try:
            with urllib.request.urlopen(u, timeout=120) as r: data = r.read()
            open(p, "wb").write(data); print(f"  fetched {f} ({len(data)//1024} KB)")
        except Exception as e: print(f"  WARN {f}: {e} (keeping old copy if any)")

def build(include_unclear=False):
    rows = []
    def add(chain, addr, category, name, source, url=None, conf=None, entity=None):
        if not addr or chain not in ("btc", "eth", "sol"): return
        addr = addr.strip().strip("'\"")
        if chain == "eth":
            if not re.fullmatch(r"0x[0-9a-fA-F]{40}", addr): return
            addr = addr.lower()
        if not SOURCES[source][4] and not include_unclear: return
        rows.append((chain, addr, category, (entity or name or "")[:80], (name or "")[:120], source, url or SOURCES[source][1],
                     SOURCES[source][2], conf if conf is not None else SOURCES[source][3]))
    # OFAC
    for c, f in (("btc", "XBT"), ("eth", "ETH"), ("sol", "SOL")):
        for a in open(os.path.join(H, "data", f"ofac_{f}.txt")):
            if a.strip(): add(c, a, "sanctioned", "OFAC SDN listed", "ofac", conf=1.0)
    # builtin seed list from labels.py
    import labels as L
    for c, d in L.EXCH.items():
        for a, n in d.items(): add(c, a, "exchange", n, "builtin", entity=n.split()[0])
    for a, n in L.MIXERS_ETH.items(): add("eth", a, "mixer", n, "builtin", entity="Tornado Cash")
    # GraphSense
    for f in sorted(glob.glob(os.path.join(SRC, "gs", "*.yaml"))):
        try: p = yaml.load(open(f), Loader=YL)
        except Exception as e: print("  bad yaml", f, e); continue
        for t in p.get("tags") or []:
            cur = str(t.get("currency") or p.get("currency") or "").upper(); ch = GS_CUR.get(cur)
            if not ch: continue
            lab = t.get("label") or p.get("label") or p.get("title"); gc = t.get("category") or p.get("category")
            pk = os.path.basename(f)
            if gc in GS_MAP: cat = GS_MAP[gc]
            elif gc and gc.startswith("defi"): cat = "defi"
            elif gc == "market": cat = "darknet" if cur == "BTC" else "other"   # BTC markets = darknet (Hydra etc.); ETH 'market' = NFT marketplaces
            else: cat = next((v for k, v in GS_PACK.items() if pk.startswith(k)), None) or cat_of(lab)
            conf = CONF.get(t.get("confidence") or p.get("confidence"), 0.75)
            add(ch, str(t.get("address")), cat, lab, "graphsense", t.get("source") or p.get("source") or f"graphsense pack {os.path.basename(f)}", conf,
                entity=t.get("actor") or p.get("actor") or lab)
    # dawsbot
    for r in csv.DictReader(open(os.path.join(SRC, "dawsbot_accounts.csv"))):
        if r["chainId"] != "1": continue
        slug = r["label"]; c = cat_of(slug) if slug not in ("ofac-sanctions-lists",) else ("mixer" if "tornado" in r["nameTag"].lower() else "blocklisted")
        add("eth", r["address"], c, r["nameTag"] or slug, "dawsbot", entity=slug)
    # brianleect etherscan-labels
    for a, v in json.load(open(os.path.join(SRC, "es_accounts.json"))).items():
        ls = [x for x in v.get("labels", []) if x not in ("take-action", "old-contract", "deprecated", "v2")]
        c = cat_of(*ls) if "ofac-sanctions-lists" not in ls else ("mixer" if "tornado-cash" in ls else "blocklisted")
        add("eth", a, c, v.get("name") or (ls[0] if ls else ""), "etherscan-labels", entity=ls[0] if ls else None)
    # Forta
    for r in csv.DictReader(open(os.path.join(SRC, "forta_phishing_scams.csv"))): add("eth", r["address"], "scam", r["etherscan_tag"] or "phishing", "forta", entity="phishing")
    for r in csv.DictReader(open(os.path.join(SRC, "forta_etherscan_malicious_labels.csv"))):
        add("eth", r["banned_address"], cat_of(r["wallet_tag"], r["data_source"]) if not re.search("phish", r["wallet_tag"], re.I) else "scam", r["wallet_tag"], "forta", entity=r["data_source"])
    for r in csv.DictReader(open(os.path.join(SRC, "forta_malicious_smart_contracts.csv"))):
        add("eth", r["contract_address"], "hack", r["contract_tag"] or "malicious contract", "forta", entity="malicious contract")
        if r.get("contract_creator"): add("eth", r["contract_creator"], "hack", r["contract_creator_tag"] or "malicious contract deployer", "forta", conf=0.7)
    # openlabels first party
    try:
        for t in (yaml.load(open(os.path.join(SRC, "oli_firstparty.yaml")), Loader=YL).get("tags") or []):
            ch = GS_CUR.get(str(t.get("currency", "")).upper())
            try: ctx = json.loads(t.get("context") or "{}")
            except Exception: ctx = {}
            add(ch, str(t.get("address")), cat_of(ctx.get("type"), ctx.get("subtype"), t.get("label")), t.get("label"), "openlabels",
                t.get("source"), CONF.get(t.get("confidence"), 0.6))
    except FileNotFoundError: pass
    # Solana
    for fn in ("immike_solana_cex_labels.csv", "immike_solana_defi_labels.csv"):
        for r in csv.DictReader(open(os.path.join(SRC, fn))):
            c = "exchange" if r["LABEL_TYPE"] == "cex" else cat_of(r["LABEL_TYPE"], r["LABEL_SUBTYPE"], r["ADDRESS_NAME"])
            if r["LABEL_TYPE"] != "cex": c = "bridge" if re.search("bridge|wormhole", r["ADDRESS_NAME"] or "", re.I) else "defi"
            add("sol", r["ADDRESS"], c, r["ADDRESS_NAME"], "sol-forensic", entity=r["PROJECT_NAME"])
    # unclear-licence BTC data (opt-in)
    try:
        d = json.load(open(os.path.join(SRC, "immike_BTC_ETH_BCH.json")))
        for a, v in d.get("BTC", {}).items():
            add("btc", a, cat_of(v.get("type"), v.get("entity"), v.get("description")) if v.get("entity") != "Braiins" else "miner", v.get("name") or v.get("entity"), "jasontth", entity=v.get("entity"))
    except FileNotFoundError: pass
    # write
    tmp = DBP + ".tmp"
    if os.path.exists(tmp): os.remove(tmp)
    db = sqlite3.connect(tmp)
    db.executescript("""CREATE TABLE labels(chain TEXT, address TEXT, category TEXT, entity TEXT, name TEXT, source TEXT, source_url TEXT, licence TEXT, confidence REAL);
      CREATE TABLE sources(id TEXT PRIMARY KEY, description TEXT, url TEXT, licence TEXT, included INTEGER, rows INTEGER);""")
    db.executemany("INSERT INTO labels VALUES(?,?,?,?,?,?,?,?,?)", rows)
    db.execute("DELETE FROM labels WHERE rowid NOT IN (SELECT min(rowid) FROM labels GROUP BY chain,address,category,source)")
    db.execute("CREATE INDEX ix ON labels(chain,address)")
    for k, (d, u, l, _, ok) in SOURCES.items():
        n = db.execute("select count(*) from labels where source=?", (k,)).fetchone()[0]
        db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)", (k, d, u, l, int(ok or include_unclear), n))
    db.commit(); db.execute("VACUUM")
    print("rows", db.execute("select count(*) from labels").fetchone()[0], "unique addresses", db.execute("select count(*) from (select distinct chain,address from labels)").fetchone()[0])
    for r in db.execute("select chain,category,count(distinct address) from labels group by 1,2 order by 1,3 desc"): print(" ", *r)
    db.close(); os.replace(tmp, DBP)   # atomic swap so a running app never sees a half-built db
    print("labels.sqlite", os.path.getsize(DBP) // 2**20, "MB")
if __name__ == "__main__":
    sys.path.insert(0, H)
    if "--no-download" not in sys.argv: download()
    build("--include-unclear" in sys.argv)
    if "--cleanup" in sys.argv: shutil.rmtree(os.path.join(SRC), ignore_errors=True); print("removed data/src")
