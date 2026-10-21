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
