#!/usr/bin/env bash
# Refresh every downstream analysis layer against the current normalized tables,
# in TRUE dependency order (audit 2026-09-02, refactor A.4: the previous driver
# ran archetypes before paths/cohorts rewrote its inputs, never ran the network
# analysis or revealed-seniority pass, and dropped the industry jury cache).
#
#   nohup bash scripts/refresh_downstream.sh &          # full refresh
#   START=5 nohup bash scripts/refresh_downstream.sh &   # resume at stage 5
#   INDUSTRY_ARGS="--no-llm" ...                          # skip the jury cache
#
# Sequential and fail-fast (later stages read earlier outputs). Writes NOTHING
# to git; progress in .build_status + refresh.log; ends with the freshness check.
set -u
cd "$(dirname "$0")/.."
LOG=refresh.log
UVR="uv run --group embed --group graph --group cohort --with numpy"
START="${START:-1}"
INDUSTRY_ARGS="${INDUSTRY_ARGS:---force-vocab}"
[ "$START" = "1" ] && : > "$LOG"

N_STAGES=17
stage_i=0
run_stage() {  # run_stage <name> <command...>
  name=$1; shift
  stage_i=$((stage_i + 1))
  if [ "$stage_i" -lt "$START" ]; then return 0; fi
  printf '%s' "refresh $stage_i/$N_STAGES: $name" > .build_status
  echo "=== [$stage_i/$N_STAGES] $name :: $(date -Is) ===" >> "$LOG"
  "$@" >> "$LOG" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    printf '%s' "refresh FAILED at $name (see refresh.log)" > .build_status
    exit $rc
  fi
}

# 1 industry: company -> industry, propagated to steps (reads the jury cache if any)
run_stage industry     $UVR python -m industry.build_industry --propagate $INDUSTRY_ARGS
# 2-5 the revealed-seniority loop: spine (with whatever scores exist) -> role
#     network -> analyze -> seniority scores -> spine again (now enriched)
run_stage paths        $UVR python -m paths.build_spine --force
run_stage net-role     $UVR python -m transition_network.build_network role
run_stage an-role      $UVR python -m transition_network.analyze role
run_stage seniority    $UVR python -m paths.seniority
run_stage paths2       $UVR python -m paths.build_spine --force
# 7-8 the role network again on the FINAL spine (the first pass only fed the
#     seniority bootstrap; consumers must read a network built on the spine
#     they see). seniority is the loop's fixed point and is not rebuilt again.
run_stage net-role2    $UVR python -m transition_network.build_network role
run_stage an-role2     $UVR python -m transition_network.analyze role
# 9-12 occupation axes (6-digit O*NET, and the pooled SOC-major grain)
run_stage net-occ      $UVR python -m transition_network.build_network occupation
run_stage an-occ       $UVR python -m transition_network.analyze occupation
run_stage net-socmajor $UVR python -m transition_network.build_network soc_major
run_stage an-socmajor  $UVR python -m transition_network.analyze soc_major
# 13-14 cohorts panel, then archetypes (reads career_steps, step_industry,
#       paths/steps, paths/transitions AND cohorts/panel)
run_stage cohorts      $UVR python -m cohorts.build_panel --force
run_stage archetypes   $UVR python -m archetypes.run_all
# 15-16 portal + share build
run_stage portal       $UVR python -m portal.run_portal_data
run_stage share        $UVR python -m portal.run_share_build
# 17 prove it: every stage's inputs older than its manifest
run_stage freshness    uv run python scripts/check_freshness.py
printf '%s' "refresh done ✔ ($N_STAGES/$N_STAGES)" > .build_status
