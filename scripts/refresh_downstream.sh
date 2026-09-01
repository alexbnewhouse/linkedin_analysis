#!/usr/bin/env bash
# Refresh every downstream analysis layer against the new normalized tables
# (PR #1: pooled SOC major, degree-type CIP, parsed dates, cert axis).
# Run detached: nohup bash scripts/refresh_downstream.sh &
# Sequential and fail-fast (later stages read earlier outputs). Writes NOTHING
# to git; progress in .build_status + refresh.log.
set -u
cd "$(dirname "$0")/.."
LOG=refresh.log
UVR="uv run --group embed --group graph --group cohort --with numpy"
: > "$LOG"

run_stage() {  # run_stage <n/total> <name> <command...>
  printf '%s' "refresh $1: $2" > .build_status
  echo "=== [$1] $2 :: $(date -Is) ===" >> "$LOG"
  shift 2
  "$@" >> "$LOG" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    printf '%s' "refresh FAILED at $2 (see refresh.log)" > .build_status
    exit $rc
  fi
}

run_stage 1/7 industry   $UVR python -m industry.build_industry --propagate --no-llm
run_stage 2/7 archetypes $UVR python -m archetypes.run_all
run_stage 3/7 paths      $UVR python -m paths.build_spine
run_stage 4/7 cohorts    $UVR python -m cohorts.build_panel
run_stage 5/7 network    $UVR python -m transition_network.build_network
run_stage 6/7 portal     $UVR python -m portal.run_portal_data
run_stage 7/7 share      $UVR python -m portal.run_share_build
printf '%s' "refresh done ✔ (7/7)" > .build_status
