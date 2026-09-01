#!/usr/bin/env bash
# Claude Code status line: model | branch | live progress of local jury runs.
# Reads the llm_pool progress lines from the tiebreak run logs; cheap enough
# to re-run every few seconds (tail/grep only, no python startup).
set -o pipefail
ROOT="/home/alex/linkedin-analysis"
RES="$ROOT/edu_clean/results"

input=$(cat)
model=$(printf '%s' "$input" | grep -oE '"display_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"display_name"[[:space:]]*:[[:space:]]*"//;s/"$//')
branch=$(git -C "$ROOT" branch --show-current 2>/dev/null)

jury=""
# Most recent phase log wins (fire supersedes calibration).
log=""
for cand in "$RES/tiebreak_fire.log" "$RES/tiebreak_calib.log"; do
  [ -f "$cand" ] && { [ -z "$log" ] || [ "$cand" -nt "$log" ]; } && log="$cand"
done

if [ -f "$RES/cip_tiebreak_stats.json" ] && grep -q '"merge"' "$RES/cip_tiebreak_stats.json" 2>/dev/null; then
  jury="tiebreak merged ✔"
elif [ -n "$log" ]; then
  phase="calib"; case "$log" in *fire*) phase="fire";; esac
  total=$(grep -m1 -oE 'firing [0-9,]+ units' "$log" 2>/dev/null | tr -dc '0-9')
  last=$(tail -c 4000 "$log" | grep -oE '\[pool\] [0-9,]+ done.*' | tail -1)
  done_n=$(printf '%s' "$last" | grep -oE '[0-9,]+ done' | tr -dc '0-9')
  eta=$(printf '%s' "$last" | grep -oE '~[0-9]+ (min|h)[a-z]* left' | head -1)
  if tail -c 4000 "$log" | grep -qE '"gate"|^fire: \{'; then
    jury="$phase done ✔ ($total votes)"
  elif [ -n "$total" ] && [ "$total" -gt 0 ] && [ -n "$done_n" ]; then
    filled=$(( done_n * 10 / total )); [ "$filled" -gt 10 ] && filled=10
    bar=""
    for i in 1 2 3 4 5 6 7 8 9 10; do
      if [ "$i" -le "$filled" ]; then bar="${bar}█"; else bar="${bar}░"; fi
    done
    pct=$(( done_n * 100 / total ))
    jury="$phase [$bar] $done_n/$total (${pct}%)${eta:+ $eta}"
  elif [ -n "$total" ]; then
    jury="$phase starting ($total queued)"
  fi
fi

out="${model:-Claude}"
[ -n "$branch" ] && out="$out | $branch"
[ -n "$jury" ] && out="$out | jury: $jury"
printf '%s' "$out"
