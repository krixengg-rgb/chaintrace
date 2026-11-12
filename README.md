# ChainTrace
Bitcoin / Ethereum / Solana fund-tracing MVP (FastAPI + cytoscape.js).

Local: `pip install -r requirements.txt && python3 update_labels.py && CHAINTRACE_USER=krixen CHAINTRACE_PASSWORD=... python3 app.py` (port 8090, or $PORT).

Render: `render.yaml` blueprint. The label DB (~200 MB) is not in git; it is built during the Render build from openly licensed sources
(`update_labels.py`; unclear-licence sources excluded). Set `CHAINTRACE_USER` / `CHAINTRACE_PASSWORD` in the Render dashboard.
The free tier disk is ephemeral: the HTTP cache and in-memory trace jobs reset on restart/sleep.

## Sanctions screening and community reports (v11)
Every address ChainTrace shows is screened against official sanctions lists and community scam reports.
- **Sanctions (hard flag, red):** digital-currency addresses from the US Treasury **OFAC SDN list** (official Advanced XML: entry name, ID, programmes, designation date) and the **UK Sanctions List** (FCDO CSV, which replaced the OFSI Consolidated List on 28 Jan 2026; wallets are parsed from the free-text field and kept only if they pass the chain checksum). Built by `update_sanctions.py` into `data/sanctions.json` (shipped baseline, refreshed on deploy and, when older than a day, in a nice'd subprocess at runtime; ~30 MB peak RAM). A match sets the node to *sanctioned* (risk 100), adds a red ⛔ badge, and is listed in the side panel, counterparties panel, risk reasons, AutoTrace (branch stops, root warning), watchlist alerts and the PDF report with the wording "matches OFAC SDN list entry X (as of date): confirm before action". Third-party "sanctioned" tags that are not on the current lists are downgraded to *blocklisted* with a "possibly delisted" note.
- **Community reports (amber, unverified leads):** scam / hack / phishing labels from GraphSense, Forta, dawsbot, etherscan-labels and the ScamSniffer address blacklist (GPL-3.0, frozen upstream since Feb 2024), plus **Chainabuse** when `CHAINABUSE_API_KEY` is set. Free Chainabuse keys allow about 10 calls a month, so calls are only made when you press "Check Chainabuse" (cached 7 days; budget via `CHAINABUSE_MONTHLY_LIMIT`). Without a key every address gets a "Search Chainabuse" link.
- **API:** `GET /api/screen?addr=…[&chain=…][&chainabuse=1]`, `POST /api/screen/batch` with `{"addresses":[…]}` or `{"text":"pasted list"}` (max 500, local lists only), `GET /api/screen/status`.
- **UI:** 🛡 Screen (paste a list, get a table, download CSV; deep link `?screen=addr1,addr2`), ⛔ graph button (count + "flagged only" filter).
- Test: `LP=… python3 uitest_screen.py` (CT_URL for another server).

## Investigation tools (v6)
- **Counterparties panel**: the top inflow/outflow counterparties of the selected address ranked by USD, with amount, tx count, first/last seen and label or suggested-deposit badges. It has filters for direction, token, min USD and dates, a √-scaled in/out volume histogram, and buttons to add one row or the top N to the graph. More pages come from `GET /api/counterparties?q=&pages=1..5&cursor=` (18 s budget).
- **Direction colouring**: flows into the selected node (or the root) are green and flows out are red. Toggle it with "⇄ In/Out".
- **Entity grouping**: compound groups for the same verified entity, the same suggested-deposit exchange, or the same BTC common-input cluster. The root stays outside any group. Select a group and press **E**, or double-tap it, to collapse it into one node with aggregated Σ edges, or split it again.
- **Noise filter** (on by default): hides dust below a configurable min $, spam/airdrop tokens (Blockscout reputation, URL-like names, or no price with ≥20k holders), zero-value calls and approvals. Unpriced tokens are optional. An "N hidden" counter shows how many flows are filtered. Trace/AutoTrace hop ranking skips noise and scores by USD × (1+0.3·ln count) × label weight.

## Public shared cases

Open a read-only investigation case from a URL on phone or desktop:

`https://chaintrace-d4fv.onrender.com/?case=<slug>`

Cases live as JSON under `static/cases/<slug>.json` (public on-chain data + public reporting only — never private case notes). The first open copies the case into your browser storage so you can annotate a local copy. Example: the 29 Oct 2026 Binance hot-wallet drain → `?case=binance-2026-10-29`.

## Watchlist & alerts (v8)

Watch any BTC / ETH / SOL address and get alerted on new activity.

- **Add from anywhere**: the 👁 button in the node menu, on each counterparties-panel row, "Watch subject" on a case card, or the form in the Watchlist drawer (👁 Watch in the header).
- **Each entry** has a name, a case ref, a note and its own rules: any new tx · outflow ≥ $X · transfer to/from a risky or labelled entity (sanctioned, mixer, risky, exchange, inferred exchange deposit, bridge) · native balance change ≥ X%.
- **Alert feed**: event cards with UK time (plus UTC), amount and USD, direction, counterparty label and risk, rule chips, and one-click *Open in graph*. There is also an unread badge, auto-check on load and every N minutes while the tab is open, and optional browser notifications.
- **Private by design**: the watchlist lives **only in your browser (IndexedDB)**, never in this repo or on the server. Use Export/Import (JSON) to back it up or move it.
- **Stateless API**: `POST /api/watch/check` takes `{items:[{id,address,rules,cursor|since}]}` (≤ 8 per call) and returns new events plus updated cursors. The server stores nothing. The first check of an address only records a baseline, unless `since` is given.

### Box / scheduled CLI

```bash
python3 watch_check.py                      # markdown summary of new alert events
python3 watch_check.py --format json        # machine-readable
python3 watch_check.py --min-severity medium --max 25
python3 watch_check.py --add <ADDR> --name "Suspect A" --ref CASE-1 --out-usd 10000
python3 watch_check.py --export-browser out.json   # file for the browser's Import
```

It reads `data/watchlist.json` (a browser Export file works as-is) and keeps cursors in `data/watch_state.json`. Events are appended to `data/watch_events.jsonl`. All three files are **gitignored**. Exit code 0 means OK, 2 means bad input, 3 means every check failed.

Caveats: only the latest page of history is scanned per check (very busy wallets get a gap warning and a summary event). The balance rule covers the native coin only. Inferred deposit labels are leads, not proof. Mempool BTC txs have no time yet.

## PDF investigation report (v8)
Click **📄 Report** in the header, choose **Export ▾ → PDF report…**, or use **PDF** on a case in the cases drawer. Enter a case reference, investigator, an optional handling marking and notes, then click **Generate PDF**. The browser sends the current graph or case as JSON to `POST /api/report` and gets back an A4 PDF built server-side with fpdf2 (no headless browser needed). The report contains:
- **Cover:** case, reference, investigator, scope, report time in UK time (Europe/London) and UTC, ChainTrace version and commit, and SHA-256 hashes of the case data and graph image.
- **1 Executive summary:** subject, flows, key endpoints and the highest-risk exposures.
- **2 Graph image.**
- **3 Chronological trail:** UK and UTC times, chain, full tx hash, from/to, asset, amount, USD and an explorer link per row.
- **4 Bridge hops:** method and confidence.
- **5 Entities:** label, category, source dataset, licence and confidence.
- **6 Case notes.**
- **7 Methodology and limitations.**
- **Appendix A:** the query log, upstream API URLs with fetch times, explorer links and label datasets.
- **Appendix B:** integrity details.

AI-inferred deposit labels and heuristic bridge matches are marked "Intelligence lead – not evidence; corroborate (e.g. production order to the VASP)". The exact case JSON is embedded as `case_data.json` (extract it with `pdfdetach -saveall`, then check it with `sha256sum`). Response headers carry `X-Report-SHA256`, `X-Case-SHA256` and `X-Report-Pages`. USD for each row is the daily close on the transaction date where Coinbase has candles (D), par for stablecoins (P), or the trace-time price otherwise (T). The report is a ChainTrace output, not an official police or agency template. Test: `LP=... python3 uitest_report.py`.

## Cross-chain bridge tracing (v7)

When a flow hits a bridge, ChainTrace looks up the matching transfer on the destination chain and draws it as a **dashed cyan cross-chain edge** (`⇄`). Each edge records the bridge, the method and a confidence score. Heuristic leads are drawn **dotted amber**.

| Bridge | How it's matched (free, keyless) | Lookup by |
|---|---|---|
| Wormhole (Portal/NTT/CCTP-via-WH) | Wormholescan `operations` → VAA id links source and target tx | src or dst tx, address |
| THORChain / Maya | Midgard `actions` (liquify gateway, fallback vanaheimex; Maya midgard) inbound + outbound txs | src or dst tx, address |
| Mayan (Swift/WH/MCTP) | `explorer-api.mayan.finance` swap record | src or dst tx, address |
| deBridge (DLN) | `Transaction/{hash}/orderIds` → `Orders/{id}` (fulfil tx) | src tx, address |
| Across | `app.across.to/api/deposit` (deposit → fill tx) | src tx, address |
| LayerZero / Stargate | `scan.layerzero-api.com` message; recipient decoded from Stargate/OFT payload | src or dst tx, address |
| Relay | `api.relay.link/requests/v2` (best effort; public API is rate limited) | src or dst tx, address |

* **Deterministic** (confidence 0.99): the bridge's own indexer links both txs by a message, order or VAA id, and ChainTrace checks that the returned record contains the queried hash.
* **Heuristic** (≤ 0.6, labelled *heuristic, lead only*): this only runs for ETH-mainnet ERC-20 (USDC/USDT/WETH/WBTC) outflows. It looks for a Transfer of the same asset to the same address on Arbitrum, Optimism, Base or Polygon within 3 h, with the amount within 5 %. Treat these as investigative leads, not evidence.
* API: `GET /api/bridge?q=<tx|address>[&anchor=<node>][&heuristic=auto|false|always]` returns matches and a graph fragment. `GET /api/bridges` lists the supported bridges. Results are cached in SQLite (completed: 30 days).
* AutoTrace: when the **⇄ bridges** box is ticked (the default), AutoTrace follows deterministic bridge hops (≤ 8 per run) and keeps tracing on BTC, ETH or SOL. It never follows heuristic hops automatically.
* UI: tx lookups auto-detect bridge transfers. Addresses get a **⇄ Cross-chain activity** button, and bridge nodes and edges get **⇄ Follow across bridge**. L2 and other foreign-chain nodes are shown for context only, with explorer links.
* Not covered yet: Circle CCTP direct, native L2 canonical bridges, the Relay v3 key-only API, and labels for historical rotated THORChain vaults.
* UI test: `LP=... python3 uitest_bridge.py`.

## UK police evidence pack (v12)
Report → **🇬🇧 UK police evidence pack** (or open any case with `&pack=1`). Optional, investigator-entered fields: force crime ref, Report Fraud / Action Fraud (NFRC) ref, NFIB code, victim/case ref, offence, period of interest, facts, officer details (remembered on the device only). **Evidence pack (.zip)** gives:
- the PDF report with a "UK case details" section and Appendix C (every exchange / VASP address: chain, address, XRP destination tags, memos, traced amounts, tx hashes, first/last seen UK + UTC);
- `vasp_drafts/` – one **DRAFT records request per exchange** (DOCX + TXT), marked "DRAFT – NOT A COURT ORDER" on every page, with legal-route options (POCA 2002 s.345 / PACE 1984 Sch 1 / POCA s.363 & s.370 / DPA 2018 Sch 2 para 2 voluntary request / MLA via UKCA for overseas firms) for the officer to choose, complete and serve;
- `vasp_schedule.csv`, `HOW_TO_USE.txt`, `SHA256SUMS.txt`.
ChainTrace is not an official Home Office / NCA / Report Fraud / court system; drafts are analysis products, on-chain data is an intelligence lead to corroborate with the VASP's records, and officers must take their own legal advice. API: `POST /api/evidence-pack` (same body as `/api/report`, plus `meta.le`).

## Readable ETH DEX swaps (v13)
Ethereum lookups flag likely swaps (the address sent one asset and received another in the same tx); `POST /api/eth/swaps` decodes them from free public data (RPC receipt logs + `eth_call`, Blockscout internal txs when available) into one graph step: trader → **⇆ 10 ETH → 25,000 USDT · Uniswap V3** → recipient, with USD, pools/fee, router and tx hash. Searching a swap tx hash shows the same step. Decoded from Swap events: Uniswap V2/V3 (and SushiSwap, PancakeSwap forks via `factory()`), Balancer V2, Curve; Uniswap V4 swaps are recognised but pool tokens are taken from the trader's transfers (marked inferred). Aggregators (1inch, 0x, CoW, ParaSwap, MetaMask, Uniswap Universal Router) are named from the called contract. Teal dashed legs = decoded; amber = partly inferred. The PDF lists swaps in Section 3.1. Raw transfers stay in the graph; AutoTrace, bridges and the noise filter are unchanged.
