# ChainTrace
Bitcoin / Ethereum / Solana fund-tracing MVP (FastAPI + cytoscape.js).

Local: `pip install -r requirements.txt && python3 update_labels.py && CHAINTRACE_USER=krixen CHAINTRACE_PASSWORD=... python3 app.py` (port 8090, or $PORT).

Render: `render.yaml` blueprint. The label DB (~200 MB) is not in git; it is built during the Render build from openly licensed sources
(`update_labels.py`; unclear-licence sources excluded). Set `CHAINTRACE_USER` / `CHAINTRACE_PASSWORD` in the Render dashboard.
The free tier disk is ephemeral: the HTTP cache and in-memory trace jobs reset on restart/sleep.

## Investigation tools (v6)
- **Counterparties panel**: the top inflow/outflow counterparties of the selected address ranked by USD, with amount, tx count, first/last seen and label or suggested-deposit badges. It has filters for direction, token, min USD and dates, a √-scaled in/out volume histogram, and buttons to add one row or the top N to the graph. More pages come from `GET /api/counterparties?q=&pages=1..5&cursor=` (18 s budget).
- **Direction colouring**: flows into the selected node (or the root) are green and flows out are red. Toggle it with "⇄ In/Out".
- **Entity grouping**: compound groups for the same verified entity, the same suggested-deposit exchange, or the same BTC common-input cluster. The root stays outside any group. Select a group and press **E**, or double-tap it, to collapse it into one node with aggregated Σ edges, or split it again.
- **Noise filter** (on by default): hides dust below a configurable min $, spam/airdrop tokens (Blockscout reputation, URL-like names, or no price with ≥20k holders), zero-value calls and approvals. Unpriced tokens are optional. An "N hidden" counter shows how many flows are filtered. Trace/AutoTrace hop ranking skips noise and scores by USD × (1+0.3·ln count) × label weight.

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
