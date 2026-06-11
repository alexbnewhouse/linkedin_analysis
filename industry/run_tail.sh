#!/bin/bash
# The S1 big run: fire the bulk juror (llamacpp/qwen3-4b-q4) over the full
# text-bearing residual in FREQUENCY ORDER (highest row-coverage first), in
# 100k-item chunks (keeps the unit list in memory bounded), resuming from the
# frozen cache on every iteration. Stops when a full pass adds <0.1% new votes
# (the remainder is items whose output never validates -- they stay uncached
# as review-queue leftovers).
#
#   status:   industry/results/tail_status.txt   (one-line summary, atomically updated)
#   log:      industry/results/tail_run.log
#
cd "$(dirname "$0")/.." || exit 1
LOG=industry/results/tail_run.log
STATUS=industry/results/tail_status.txt
TOTAL=2027185
STEP=100000
LIMIT=$STEP

cached_count() {  # "N/M votes already cached" from a no-execute preview at full scope
  uv run python -m industry.fire_llm tail --backend local --limit $TOTAL 2>/dev/null \
    | grep -o '[0-9,]*/[0-9,]* votes already cached' | head -1 | tr -d ','
}

echo "$(date -Is) RUN START total=$TOTAL step=$STEP" >> "$LOG"
prev_cached=0
while true; do
  [ $LIMIT -gt $TOTAL ] && LIMIT=$TOTAL
  echo "$(date -Is) chunk: firing uncached remainder of top-$LIMIT" >> "$LOG"
  uv run python -m industry.fire_llm tail --backend local --execute --limit $LIMIT >> "$LOG" 2>&1
  c=$(cached_count); c=${c%%/*}; c=${c:-0}
  pct=$(awk "BEGIN{printf \"%.2f\", 100*$c/$TOTAL}")
  now=$(date -Is)
  printf '%s cached=%s/%s (%s%%) limit=%s\n' "$now" "$c" "$TOTAL" "$pct" "$LIMIT" > "$STATUS.tmp" && mv "$STATUS.tmp" "$STATUS"
  echo "$now PROGRESS cached=$c/$TOTAL (${pct}%) limit=$LIMIT" >> "$LOG"
  if [ $LIMIT -ge $TOTAL ]; then
    gained=$((c - prev_cached))
    if [ $gained -lt 2028 ]; then   # <0.1% gained on a full pass -> done
      echo "$(date -Is) RUN COMPLETE cached=$c/$TOTAL (full-pass gain $gained < 0.1%)" >> "$LOG"
      printf '%s COMPLETE cached=%s/%s (%s%%)\n' "$(date -Is)" "$c" "$TOTAL" "$pct" > "$STATUS.tmp" && mv "$STATUS.tmp" "$STATUS"
      break
    fi
  fi
  prev_cached=$c
  LIMIT=$((LIMIT + STEP))
done
echo "$(date -Is) merging into the company table ..." >> "$LOG"
uv run python -m industry.build_industry --propagate >> "$LOG" 2>&1
echo "$(date -Is) ALL DONE" >> "$LOG"
