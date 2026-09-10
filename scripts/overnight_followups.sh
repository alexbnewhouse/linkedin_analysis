#!/usr/bin/env bash
# Overnight follow-ups after PR #1 (run detached: nohup bash scripts/overnight_followups.sh &).
#
#   1. R4: fire the second CIP jury tail tranche (top-50k candidates; the first
#      25k are cached, so only the NEXT 25k strings actually fire) on the
#      llama-server lanes. ~21h at historical throughput. Resumable.
#   2. Merge the unanimous votes (same calibrated acceptance rule as tranche 1).
#   3. Rebuild the education side (--skip-mappings) + tier-count snapshot.
#   4. R3 retry: calibrate mistral-medium-3.5:128b as the tiebreak third juror
#      on the gold sample. GATE STAYS MANUAL: nothing merges from this step --
#      read edu_clean/results/cip_tiebreak_stats.json next session.
#
# Writes NOTHING to git. Progress: edu_clean/results/*.log (statusline tracks
# tail_tranche2.log and mistral_calib.log) + .build_status.
set -u
cd "$(dirname "$0")/.."
RES=edu_clean/results
status() { printf '%s' "$1" > .build_status; }

status "overnight: R4 tail firing"
PYTHONUNBUFFERED=1 uv run python -m edu_clean.run_cip_jury tail --execute --limit 50000 \
  > "$RES/tail_tranche2.log" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
  status "overnight: R4 fire FAILED (see tail_tranche2.log)"
  exit $rc
fi
echo "PHASE DONE" >> "$RES/tail_tranche2.log"

status "overnight: R4 merge"
PYTHONUNBUFFERED=1 uv run python -m edu_clean.run_cip_jury merge --limit 50000 \
  >> "$RES/tail_tranche2.log" 2>&1 || { status "overnight: R4 merge FAILED"; exit 1; }

status "overnight: education rebuild"
PYTHONUNBUFFERED=1 uv run --with numpy python build_normalized.py \
  --sections education --skip-mappings >> "$RES/tail_tranche2.log" 2>&1 \
  || { status "overnight: rebuild FAILED"; exit 1; }
PYTHONUNBUFFERED=1 uv run python -m edu_clean.run_tier_counts \
  >> "$RES/tail_tranche2.log" 2>&1

status "overnight: mistral tiebreak calibration"
CIP_TIEBREAK_JUROR="ollama/mistral-medium-3.5:128b" PYTHONUNBUFFERED=1 \
  uv run python -m edu_clean.run_cip_tiebreak calibrate --execute \
  > "$RES/mistral_calib.log" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
  status "overnight: mistral calib FAILED (see mistral_calib.log)"
  exit $rc
fi
status "overnight done ✔ (review stats + commit next session)"
