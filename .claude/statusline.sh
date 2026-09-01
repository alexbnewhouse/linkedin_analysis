#!/usr/bin/env bash
# Claude Code status line: model | branch | live jury-run progress | build stage.
# Parses llm_pool progress lines from run logs; cheap (tail/grep, no python).
set -o pipefail
ROOT="/home/alex/linkedin-analysis"
RES="$ROOT/edu_clean/results"

input=$(cat)
model=$(printf '%s' "$input" | grep -oE '"display_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"display_name"[[:space:]]*:[[:space:]]*"//;s/"$//')
branch=$(git -C "$ROOT" branch --show-current 2>/dev/null)

# --- jury segment: newest of the known phase logs wins ---
jury=""; log=""; phase=""
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
  if tail -c 4000 "$log" | grep -qE '"gate"|^fire: \{|merged ->|PHASE DONE'; then
    jury="$phase done ✔${total:+ ($total votes)}"
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

# --- build segment: one-liner maintained by driver scripts ---
build=""
[ -f "$ROOT/.build_status" ] && build=$(head -c 120 "$ROOT/.build_status" | tr -d '\n')

out="${model:-Claude}"
[ -n "$branch" ] && out="$out | $branch"
[ -n "$jury" ] && out="$out | jury: $jury"
[ -n "$build" ] && out="$out | $build"
printf '%s' "$out"
