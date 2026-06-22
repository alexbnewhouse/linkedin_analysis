#!/bin/bash
# Post-bulk follow-ups, run SEQUENTIALLY (all contend for the Framework GPU):
#   1. calibrate  -- the 3-juror panel (gemma3:27b + qwen3:32b + phi4:14b) on the
#                    75-item gold population -> agreement->precision bands.
#   2. jury       -- the same panel on the top-N residual HEAD (errors there
#                    propagate to many rows; consensus is worth the 3x cost).
#   3. head       -- gpt-oss:120b curator on the top-N companies, to grow M1.
# Then merge (build_industry --propagate) + recalibrate (run_industry).
#
#   log:    industry/results/panels_run.log
#   status: industry/results/panels_status.txt
set -u
cd "$(dirname "$0")/.." || exit 1
LOG=industry/results/panels_run.log
STATUS=industry/results/panels_status.txt
JURY_LIMIT=4000
HEAD_LIMIT=5000

say() { printf '%s %s\n' "$(date -Is)" "$1" | tee -a "$LOG"; printf '%s %s\n' "$(date -Is)" "$1" > "$STATUS"; }

say "PANELS START (calibrate -> jury $JURY_LIMIT -> head $HEAD_LIMIT)"

say "STEP 1/3 calibrate (panel on gold)"
uv run python -m industry.fire_llm calibrate --backend local --execute >> "$LOG" 2>&1
say "STEP 1/3 calibrate DONE"

say "STEP 2/3 jury --limit $JURY_LIMIT (panel on residual head)"
uv run python -m industry.fire_llm jury --backend local --limit $JURY_LIMIT --execute >> "$LOG" 2>&1
say "STEP 2/3 jury DONE"

say "STEP 3/3 head --limit $HEAD_LIMIT (gpt-oss:120b curator)"
uv run python -m industry.fire_llm head --backend local --limit $HEAD_LIMIT --execute >> "$LOG" 2>&1
say "STEP 3/3 head DONE"

say "MERGE build_industry --propagate"
uv run python -m industry.build_industry --propagate >> "$LOG" 2>&1
say "RECALIBRATE run_industry"
uv run python -m industry.run_industry >> "$LOG" 2>&1
say "ALL DONE"
