#!/usr/bin/env bash
# Run a long command with a label the status line can show, and clean up after itself.
#
#   scripts/track.sh <label> [--log FILE] -- <command...>
#   scripts/track.sh refresh -- bash scripts/refresh_downstream.sh
#   scripts/track.sh soc-tail --log career_clean/results/soc_tail5.log -- uv run python -m career_clean.run_soc_jury tail --execute
#
# Writes .claude/tasks/<label>.task (label, pid, started, log) while the command runs; on exit
# it appends rc=<code>. The status line shows "▶ <label> <elapsed> [progress hint]" while
# alive, then "<label> ✔ 3m ago" (or ✘ rc=N) for ten minutes, then removes the file. Output
# goes to the log (default .claude/tasks/<label>.log) and is not echoed; tail it to watch.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASKS="$ROOT/.claude/tasks"
mkdir -p "$TASKS"

label="${1:?usage: track.sh <label> [--log FILE] -- <command...>}"; shift
log=""
if [ "${1:-}" = "--log" ]; then log="$2"; shift 2; fi
[ "${1:-}" = "--" ] && shift
[ $# -gt 0 ] || { echo "track.sh: no command given" >&2; exit 2; }
case "$log" in
  "") log="$TASKS/$label.log" ;;
  /*) ;;
  *) log="$ROOT/$log" ;;
esac
safe=$(printf '%s' "$label" | tr -c 'A-Za-z0-9_.-' '_')
task="$TASKS/$safe.task"

"$@" > "$log" 2>&1 &
pid=$!
{
  echo "label=$label"
  echo "pid=$pid"
  echo "started=$(date +%s)"
  echo "log=$log"
  echo "cmd=$*"
} > "$task"
echo "tracking '$label' as pid $pid; log: $log"
wait "$pid"
rc=$?
echo "rc=$rc" >> "$task"
exit $rc
