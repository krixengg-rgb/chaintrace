#!/usr/bin/env bash
# Starts ChainTrace server + Cloudflare quick tunnel, each in a restart loop. Idempotent.
cd "$(dirname "$0")"
pgrep -f "ct-supervise-server" >/dev/null || nohup bash -c 'exec -a ct-supervise-server bash -c "while true; do python3 -m uvicorn app:app --host 127.0.0.1 --port 8090 >> server.log 2>&1; echo \"server exited, restarting\" >> server.log; sleep 3; done"' >/dev/null 2>&1 &
[ "$1" = "--tunnel" ] && { pgrep -f "ct-supervise-tunnel" >/dev/null || nohup bash -c 'exec -a ct-supervise-tunnel bash -c "while true; do cloudflared tunnel --no-autoupdate --url http://localhost:8090 2>&1 | tee -a tunnel.log | grep --line-buffered -o \"https://[a-z0-9-]*\.trycloudflare\.com\" | while read u; do echo \$u > tunnel_url.txt; done; echo \"tunnel exited, restarting\" >> tunnel.log; sleep 5; done"' >/dev/null 2>&1 & }
sleep 12; echo "URL: $(cat tunnel_url.txt 2>/dev/null)"
