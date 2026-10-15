# ChainTrace
Bitcoin / Ethereum / Solana fund-tracing MVP (FastAPI + cytoscape.js).

Local: `pip install -r requirements.txt && python3 update_labels.py && CHAINTRACE_USER=krixen CHAINTRACE_PASSWORD=... python3 app.py` (port 8090, or $PORT).

Render: `render.yaml` blueprint. The label DB (~200 MB) is not in git; it is built during the Render build from openly licensed sources
(`update_labels.py`; unclear-licence sources excluded). Set `CHAINTRACE_USER` / `CHAINTRACE_PASSWORD` in the Render dashboard.
The free tier disk is ephemeral: the HTTP cache and in-memory trace jobs reset on restart/sleep.
