#!/usr/bin/env bash
# Claude Code status line for this repo: model | branch | running tasks | build stage | jury run.
#
# Auto-tracking (2026-09-22): every long pipeline process is detected by its process name
# (no wrapper needed) and shown with its elapsed time; ad-hoc jobs started through
# scripts/track.sh get a label, a progress hint from their log, and a finished marker that
# expires on its own. Stale one-liners in .build_status are cleared after a grace period once
# no driver is alive. Cheap: ps/grep/tail only, no python.
set -o pipefail
ROOT="/home/alex/linkedin-analysis"
RES="$ROOT/edu_clean/results"
TASKS="$ROOT/.claude/tasks"
DONE_TTL=600        # seconds a finished task / build marker stays visible
STALE_TTL=900       # seconds before a .build_status with no live driver is removed
now=$(date +%s)

input=$(cat)
model=$(printf '%s' "$input" | grep -oE '"display_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"display_name"[[:space:]]*:[[:space:]]*"//;s/"$//')
branch=$(git -C "$ROOT" branch --show-current 2>/dev/null)

fmt_elapsed() {  # seconds -> 4m / 1h12m / 2d3h
  local s=$1
  if [ "$s" -lt 3600 ]; then printf '%dm' $(( s / 60 ))
  elif [ "$s" -lt 86400 ]; then printf '%dh%02dm' $(( s / 3600 )) $(( (s % 3600) / 60 ))
  else printf '%dd%dh' $(( s / 86400 )) $(( (s % 86400) / 3600 )); fi
}

# --- 1. known pipeline processes, detected by name (label:pattern) ---------------------------
PATTERNS="refresh:scripts/refresh_downstream.sh overnight:scripts/overnight_followups.sh parse:parse_linkedin.py normalize:build_normalized.py industry:industry.build_industry industry-llm:industry.fire_llm spine:paths.build_spine network:transition_network.build_network analyze:transition_network.analyze seniority:paths.seniority cohorts:cohorts.build_panel archetypes:archetypes.run_all portal:portal.run_portal_data share:portal.run_share_build persons:persons.build_person metrics:persons.build_metrics cip-jury:edu_clean.run_cip_jury dlevel-jury:edu_clean.run_dlevel_jury soc-jury:career_clean.run_soc_jury families:career_clean.run_families overrides:career_clean.run_overrides comajors:edu_clean.run_comajors imputed:edu_clean.apply_bachelor_imputed benchmarks:validation.external_benchmarks knn:edu_clean.knn_tail"
running=""
# one ps call; match patterns against full command lines of live processes
ps_out=""
[ -z "${STATUSLINE_SKIP_PS:-}" ] && ps_out=$(ps -eo pid=,etimes=,args= 2>/dev/null)   # tests set STATUSLINE_SKIP_PS=1
for entry in $PATTERNS; do
  label="${entry%%:*}"; pat="${entry#*:}"
  line=$(printf '%s\n' "$ps_out" | grep -F -- "$pat" | grep -vE 'grep|statusline\.sh|track\.sh|ps -eo' | head -1)
  [ -z "$line" ] && continue
  et=$(printf '%s' "$line" | awk '{print $2}')
  running="${running:+$running, }$label $(fmt_elapsed "${et:-0}")"
done

# --- 2. ad-hoc tracked jobs (scripts/track.sh writes .claude/tasks/<id>.json) ----------------
tracked=""
if [ -d "$TASKS" ]; then
  for f in "$TASKS"/*.task; do
    [ -f "$f" ] || continue
    label=$(sed -n 's/^label=//p' "$f" | head -1)
    pid=$(sed -n 's/^pid=//p' "$f" | head -1)
    started=$(sed -n 's/^started=//p' "$f" | head -1)
    log=$(sed -n 's/^log=//p' "$f" | head -1)
    rc=$(sed -n 's/^rc=//p' "$f" | head -1)
    mt=$(stat -c %Y "$f" 2>/dev/null || echo "$now")
    if [ -n "$rc" ]; then
      # finished: show for DONE_TTL then clean up
      if [ $(( now - mt )) -gt "$DONE_TTL" ]; then rm -f "$f"; continue; fi
      if [ "$rc" = "0" ]; then mark="✔"; else mark="✘ rc=$rc"; fi
      tracked="${tracked:+$tracked, }$label $mark $(fmt_elapsed $(( now - mt ))) ago"
    elif [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      hint=""
      if [ -n "$log" ] && [ -f "$log" ]; then
        # progress hints: llm_pool "[pool] N done ..." or a driver "[k/N] stage" line
        last=$(tail -c 3000 "$log" 2>/dev/null | grep -oE '\[pool\] [0-9,]+ done[^|]*|\[[0-9]+/[0-9]+\] [a-z0-9_-]+' | tail -1)
        [ -n "$last" ] && hint=" $last"
      fi
      tracked="${tracked:+$tracked, }$label $(fmt_elapsed $(( now - ${started:-$now} )))$hint"
    else
      # pid gone without an rc line: the wrapper was killed; expire like a finished task
      if [ $(( now - mt )) -gt "$DONE_TTL" ]; then rm -f "$f"; continue; fi
      tracked="${tracked:+$tracked, }$label ? (no process)"
    fi
  done
fi

# --- 3. build one-liner from the drivers, with cleanup ---------------------------------------
build=""
if [ -f "$ROOT/.build_status" ]; then
  build=$(head -c 120 "$ROOT/.build_status" | tr -d '\n')
  bmt=$(stat -c %Y "$ROOT/.build_status" 2>/dev/null || echo "$now")
  driver_alive=$(printf '%s\n' "$ps_out" | grep -E 'refresh_downstream\.sh|overnight_followups\.sh' | grep -v grep | head -1)
  if [ -z "$driver_alive" ]; then
    case "$build" in
      *done*|*FAILED*|*✔*)
        if [ $(( now - bmt )) -gt "$DONE_TTL" ]; then rm -f "$ROOT/.build_status"; build=""; fi ;;
      *)
        # says "running" but nothing is: stale after STALE_TTL
        if [ $(( now - bmt )) -gt "$STALE_TTL" ]; then rm -f "$ROOT/.build_status"; build=""
        else build="$build (no driver alive)"; fi ;;
    esac
  fi
fi

# --- 4. jury segment: newest of the known phase logs wins (only while a jury driver runs) ----
jury=""; log=""; phase=""
if printf '%s\n' "$ps_out" | grep -qE 'run_cip_jury|run_dlevel_jury|run_soc_jury|run_cip_tiebreak|overnight_followups'; then
  for entry in "cip-tail:$RES/tail_tranche2.log" "calib-mm:$RES/mistral_calib.log" \
               "fire:$RES/tiebreak_fire.log" "calib:$RES/tiebreak_calib.log"; do
    p="${entry%%:*}"; f="${entry#*:}"
    [ -f "$f" ] && { [ -z "$log" ] || [ "$f" -nt "$log" ]; } && { log="$f"; phase="$p"; }
  done
  if [ -n "$log" ]; then
    total=$(grep -m1 -oE 'firing [0-9,]+ units' "$log" 2>/dev/null | tr -dc '0-9')
    last=$(tail -c 4000 "$log" | grep -oE '\[pool\] [0-9,]+ done.*' | tail -1)
    done_n=$(printf '%s' "$last" | grep -oE '[0-9,]+ done' | tr -dc '0-9')
    eta=$(printf '%s' "$last" | grep -oE '~[0-9]+ (min|h)[a-z]* left' | head -1)
    if [ -n "$total" ] && [ "$total" -gt 0 ] && [ -n "$done_n" ]; then
      filled=$(( done_n * 10 / total )); [ "$filled" -gt 10 ] && filled=10
      bar=""
      for i in 1 2 3 4 5 6 7 8 9 10; do
        if [ "$i" -le "$filled" ]; then bar="${bar}█"; else bar="${bar}░"; fi
      done
      jury="$phase [$bar] $done_n/$total ($(( done_n * 100 / total ))%)${eta:+ $eta}"
    elif [ -n "$total" ]; then
      jury="$phase starting ($total queued)"
    fi
  fi
fi

out="${model:-Claude}"
[ -n "$branch" ] && out="$out | $branch"
[ -n "$running" ] && out="$out | ⚙ $running"
[ -n "$tracked" ] && out="$out | ▶ $tracked"
[ -n "$build" ] && out="$out | $build"
[ -n "$jury" ] && out="$out | jury: $jury"
printf '%s' "$out"
