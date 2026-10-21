#!/usr/bin/env bash
# Weekly deposit-address refresh: resume/start scan -> quality gate -> commit+push only if gate passes and no secrets.
# Usage: ./run_weekly_scan.sh                 scan (resume, or new round) then gate+publish
#        ./run_weekly_scan.sh --publish-only  gate+publish the existing export (also used by the scan's on-exit hook)
# env: SCAN_HOURS=24, ROUND_MAX_DAYS=14, SKIP_PUSH=1 (stop before git push), CT_FOREGROUND=1 (don't self-detach)
#
# Robustness (fix for the 18 Oct round that finished but was never published):
#  * the whole body lives in main(), so bash parses it completely before running - editing this file while a
#    run is in progress can no longer corrupt the running instance (bash otherwise reads scripts incrementally);
#  * the runner re-launches itself detached (setsid nohup) so it survives the terminal/agent session that started it,
#    and its own stdout/stderr go to data/depwork/weekly.out (errors are no longer lost);
#  * the scan itself fires `--publish-only` (detached) when it exits, so a scan that finishes on its own is gated and
#    published even if the runner has died; a flock prevents two publishes at once;
#  * on every start, an export newer than the last published report is gated/published first.
main() {
  set -u
  cd "$(dirname "$(readlink -f "$0")")"
  mkdir -p data/depwork
  LOG=data/depwork/scan.log
  if [ "${CT_FOREGROUND:-0}" != "1" ] && [ "${CT_DETACHED:-0}" != "1" ]; then
    CT_DETACHED=1 setsid nohup "$PWD/run_weekly_scan.sh" "$@" >> data/depwork/weekly.out 2>&1 < /dev/null &
    echo "run_weekly_scan.sh: started detached (pid $!); log: $PWD/$LOG"; return 0
  fi
  export CHAINTRACE_CACHE="$PWD/data/depwork/cache.sqlite" CHAINTRACE_CACHE_MAX_ROWS=400000
  PY=/usr/bin/python3
  if [ "${1:-}" = "--publish-only" ]; then publish; return $?; fi
  if pgrep -f "infer_deposits.py scan" >/dev/null; then
    log "a scan is already running (pid $(pgrep -f 'infer_deposits.py scan' | head -1)); publishing a partial snapshot of it instead"
    $PY -c 'import infer_deposits as I; I.export_candidate()' >> "$LOG" 2>&1 || { log "export failed"; return 1; }
    publish; return $?
  fi
  # an export that never got published (e.g. runner died) goes through the gate before anything else
  if [ -f data/depwork/candidate.jsonl.gz ] && [ data/depwork/candidate.jsonl.gz -nt data/deposit_scan_report.json ]; then
    log "found an unpublished export from $(date -r data/depwork/candidate.jsonl.gz '+%Y-%m-%d %H:%M') - gating it first"; publish
  fi
  STATE=$(meta state); AGE=$($PY -c "
import sqlite3,time
try: print(int((time.time()-float(sqlite3.connect('data/depwork/scan.sqlite').execute(\"select v from meta where k='init'\").fetchone()[0]))/86400))
except Exception: print(0)")
  ARGS="--hours ${SCAN_HOURS:-24}"
  # finished rounds, or rounds older than ROUND_MAX_DAYS, start fresh so weeks never stall
  if [ "$STATE" = "finished" ] || [ "$AGE" -ge "${ROUND_MAX_DAYS:-14}" ]; then ARGS="$ARGS --new-round"; fi
  log "starting scan ($ARGS; previous state: $STATE; round age ${AGE}d)"
  # CT_PUBLISH_ON_EXIT: the scan triggers --publish-only itself when it exits (backup if this runner dies)
  CT_PUBLISH_ON_EXIT=1 $PY infer_deposits.py scan $ARGS >> data/depwork/scan.stdout 2>&1 \
    || log "scan exited with error $?; progress is checkpointed - publishing partial export through the gate"
  # always (re-)export what is checkpointed: a round whose time budget expired is published partially (gate still applies)
  $PY -c 'import infer_deposits as I; I.export_candidate()' >> "$LOG" 2>&1 || { log "export failed"; return 1; }
  [ "$(meta state)" = "finished" ] || log "round not finished (budget expired) - publishing PARTIAL results if the gate passes"
  publish
}
log(){ echo "$(date '+%Y-%m-%d %H:%M:%S') [weekly] $*" | tee -a "$LOG"; }
meta(){ $PY -c "
import sqlite3,os
p='data/depwork/scan.sqlite'
r=sqlite3.connect(p).execute(\"select v from meta where k='$1'\").fetchone() if os.path.exists(p) else None
print(r[0] if r else 'none')"; }
publish() {
  exec 9> data/depwork/publish.lock
  if ! flock -w 1800 9; then log "another publish holds the lock; skipping"; return 0; fi
  log "running quality gate"
  if ! $PY quality_gate.py >> "$LOG" 2>&1; then log "quality gate FAILED - not publishing (see report above in this log)"; return 2; fi
  git add data/inferred_deposits.jsonl.gz data/deposit_scan_report.json; git add -u data/inferred_deposits.json 2>/dev/null
  # compare label CONTENT (order/gzip-header independent) with what is committed
  local NEWH OLDH
  NEWH=$(zcat data/inferred_deposits.jsonl.gz | sort | md5sum | cut -c1-32)
  OLDH=$(git show HEAD:data/inferred_deposits.jsonl.gz 2>/dev/null | zcat 2>/dev/null | sort | md5sum | cut -c1-32)
  if [ "$NEWH" = "$OLDH" ] && git diff --cached --quiet -- data/inferred_deposits.json; then
    git reset -q; git checkout -q -- data/deposit_scan_report.json 2>/dev/null; log "gate passed but labels unchanged - nothing to publish"; return 0; fi
  # secret check: only data files may be staged, and no local/Render password in the diff or the data file
  local LP STAGED S
  LP=$(grep -s '^CT_PASS=' .env | cut -d= -f2-)
  STAGED=$(git diff --cached --name-only)
  if echo "$STAGED" | grep -vqE '^data/(inferred_deposits\.jsonl\.gz|inferred_deposits\.json|deposit_scan_report\.json)$'; then log "unexpected staged files: refusing"; git reset -q; return 3; fi
  for S in "$LP" "${CHAINTRACE_PASSWORD:-}"; do
    if [ -n "$S" ] && { git diff --cached | grep -qF -- "$S" || zcat data/inferred_deposits.jsonl.gz | grep -qF -- "$S"; }; then log "SECRET found in staged changes: refusing"; git reset -q; return 3; fi
  done
  git -c user.name="Krixen gg" -c user.email="krixengg@users.noreply.github.com" commit -qm "Weekly inferred deposit labels refresh ($(date +%Y-%m-%d))" && log "committed $(git log --oneline -1)"
  if [ "${SKIP_PUSH:-0}" = "1" ]; then log "SKIP_PUSH=1: not pushing"; return 0; fi
  if git push -q origin main || { gh auth setup-git && git push -q origin main; }; then log "pushed to main"; else log "push failed"; return 4; fi
}
main "$@"; exit $?
