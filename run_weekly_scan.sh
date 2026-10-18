#!/usr/bin/env bash
# Weekly deposit-address refresh: resume/start scan -> quality gate -> commit+push only if gate passes and no secrets.
# Usage: ./run_weekly_scan.sh            (env: SCAN_HOURS=24, SKIP_PUSH=1 to stop before git push)
set -u
cd "$(dirname "$0")"
LOG=data/depwork/scan.log; mkdir -p data/depwork
log(){ echo "$(date '+%Y-%m-%d %H:%M:%S') [weekly] $*" | tee -a "$LOG"; }
export CHAINTRACE_CACHE="$PWD/data/depwork/cache.sqlite" CHAINTRACE_CACHE_MAX_ROWS=400000
PY=/usr/bin/python3
if pgrep -f "infer_deposits.py scan" >/dev/null; then
  log "a scan is already running (pid $(pgrep -f 'infer_deposits.py scan' | head -1)); publishing a partial snapshot of it instead"
  SNAPSHOT=1
else SNAPSHOT=0; fi
STATE=$($PY - <<'P'
import sqlite3,os
p="data/depwork/scan.sqlite"
print(sqlite3.connect(p).execute("select v from meta where k='state'").fetchone()[0] if os.path.exists(p) else "none")
P
)
AGE=$($PY - <<'P'
import sqlite3,os,time
p="data/depwork/scan.sqlite"
try: v=sqlite3.connect(p).execute("select v from meta where k='init'").fetchone()[0]; print(int((time.time()-float(v))/86400))
except Exception: print(0)
P
)
if [ "$SNAPSHOT" = "0" ]; then
  ARGS="--hours ${SCAN_HOURS:-24}"
  # finished rounds, or rounds older than ROUND_MAX_DAYS, start fresh (re-page hubs for new deposits) so weeks never stall
  if [ "$STATE" = "finished" ] || [ "$AGE" -ge "${ROUND_MAX_DAYS:-14}" ]; then ARGS="$ARGS --new-round"; fi
  log "starting scan ($ARGS; previous state: $STATE; round age ${AGE}d)"
  $PY infer_deposits.py scan $ARGS >> data/depwork/scan.stdout 2>&1 || log "scan exited with error $?; progress is checkpointed - publishing partial export through the gate"
fi
# always (re-)export what is checkpointed: a round whose time budget expired is published partially (gate still applies)
$PY -c 'import infer_deposits as I; I.export_candidate()' >> "$LOG" 2>&1 || { log "export failed"; exit 1; }
NEWSTATE=$($PY -c "import sqlite3;print(sqlite3.connect('data/depwork/scan.sqlite').execute(\"select v from meta where k='state'\").fetchone()[0])")
[ "$NEWSTATE" = "finished" ] || log "round not finished (budget expired or snapshot) - publishing PARTIAL results if the gate passes"
log "running quality gate"
if ! $PY quality_gate.py >> "$LOG" 2>&1; then log "quality gate FAILED - not publishing"; exit 2; fi
git add data/inferred_deposits.jsonl.gz data/deposit_scan_report.json; git add -u data/inferred_deposits.json 2>/dev/null
if git diff --cached --quiet; then log "gate passed but nothing changed"; exit 0; fi
# secret check: staged diff must not contain any local/Render password, and only data files may be staged
LP=$(grep -s '^CT_PASS=' .env | cut -d= -f2-)
STAGED=$(git diff --cached --name-only)
if echo "$STAGED" | grep -vqE '^data/(inferred_deposits\.jsonl\.gz|inferred_deposits\.json|deposit_scan_report\.json)$'; then log "unexpected staged files: refusing"; git reset -q; exit 3; fi
for S in "$LP" "${CHAINTRACE_PASSWORD:-}"; do
  if [ -n "$S" ] && { git diff --cached | grep -qF -- "$S" || zcat data/inferred_deposits.jsonl.gz | grep -qF -- "$S"; }; then log "SECRET found in staged changes: refusing"; git reset -q; exit 3; fi
done
git -c user.name="Krixen gg" -c user.email="krixengg@users.noreply.github.com" commit -qm "Weekly inferred deposit labels refresh ($(date +%Y-%m-%d))" && log "committed $(git log --oneline -1)"
if [ "${SKIP_PUSH:-0}" = "1" ]; then log "SKIP_PUSH=1: not pushing"; exit 0; fi
git push -q origin main && log "pushed to main" || { log "push failed"; exit 4; }
