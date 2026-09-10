#!/usr/bin/env bash
# Refresh every downstream analysis layer against the new normalized tables
# (PR #1: pooled SOC major, degree-type CIP, parsed dates, cert axis).
# Run detached: nohup bash scripts/refresh_downstream.sh &
# Resume after a failure: START=3 nohup bash scripts/refresh_downstream.sh &
# Sequential and fail-fast (later stages read earlier outputs). Writes NOTHING
# to git; progress in .build_status + refresh.log.
set -u
cd "$(dirname "$0")/.."
LOG=refresh.log
UVR="uv run --group embed --group graph --group cohort --with numpy"
START="${START:-1}"
[ "$START" = "1" ] && : > "$LOG"

stage_i=0
run_stage() {  # run_stage <name> <command...>
  name=$1; shift
  stage_i=$((stage_i + 1))
  if [ "$stage_i" -lt "$START" ]; then return 0; fi
  printf '%s' "refresh $stage_i/7: $name" > .build_status
  echo "=== [$stage_i/7] $name :: $(date -Is) ===" >> "$LOG"
  "$@" >> "$LOG" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    printf '%s' "refresh FAILED at $name (see refresh.log)" > .build_status
    exit $rc
  fi
}

run_stage industry   $UVR python -m industry.build_industry --propagate --no-llm
run_stage archetypes $UVR python -m archetypes.run_all
run_stage paths      $UVR python -m paths.build_spine --force
run_stage cohorts    $UVR python -m cohorts.build_panel --force
run_stage network    $UVR python -m transition_network.build_network
run_stage portal     $UVR python -m portal.run_portal_data
run_stage share      $UVR python -m portal.run_share_build
printf '%s' "refresh done ✔ (7/7)" > .build_status
