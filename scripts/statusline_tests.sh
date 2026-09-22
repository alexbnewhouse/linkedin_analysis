#!/usr/bin/env bash
# Checks for .claude/statusline.sh task tracking and cleanup.
#
#   bash scripts/statusline_tests.sh      (make test)
#
# Uses a scratch copy of the script with ROOT pointed at a temp dir so no real task marker
# or .build_status is touched.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/.claude/tasks" "$tmp/edu_clean/results"
sed "s#^ROOT=.*#ROOT=\"$tmp\"#" "$ROOT/.claude/statusline.sh" > "$tmp/statusline.sh"
git -C "$tmp" init -q 2>/dev/null && git -C "$tmp" checkout -q -b testbranch 2>/dev/null
render() { echo '{"model":{"display_name":"TestModel"}}' | STATUSLINE_SKIP_PS=1 bash "$tmp/statusline.sh"; }  # no real-process detection in tests
fail=0
check() { if [ "$2" = "1" ]; then echo "  ok: $1"; else echo "  FAIL: $1"; fail=1; fi; }

out=$(render)
check "model and branch render" "$([[ "$out" == *TestModel* && "$out" == *testbranch* ]] && echo 1 || echo 0)"
check "nothing else when idle" "$([[ "$out" != *"⚙"* && "$out" != *"▶"* ]] && echo 1 || echo 0)"

# running tracked task with a live pid and a progress hint in its log
sleep 60 & spid=$!
printf 'label=demo\npid=%s\nstarted=%s\nlog=%s\n' "$spid" "$(( $(date +%s) - 125 ))" "$tmp/demo.log" > "$tmp/.claude/tasks/demo.task"
printf 'noise\n[2/7] cohorts\n' > "$tmp/demo.log"
out=$(render)
check "running tracked task shows label, elapsed and stage hint" "$([[ "$out" == *"▶ demo 2m [2/7] cohorts"* ]] && echo 1 || echo 0)"
kill "$spid" 2>/dev/null; wait "$spid" 2>/dev/null

# finished task: shown with ✔ then removed after DONE_TTL
printf 'label=done1\npid=1\nstarted=1\nlog=/dev/null\nrc=0\n' > "$tmp/.claude/tasks/done1.task"
out=$(render)
check "finished task shows a check mark" "$([[ "$out" == *"done1 ✔"* ]] && echo 1 || echo 0)"
touch -d '20 minutes ago' "$tmp/.claude/tasks/done1.task"
render > /dev/null
check "finished task marker removed after the grace period" "$([ ! -f "$tmp/.claude/tasks/done1.task" ] && echo 1 || echo 0)"

# failed task shows rc
printf 'label=bad\npid=1\nstarted=1\nlog=/dev/null\nrc=3\n' > "$tmp/.claude/tasks/bad.task"
out=$(render)
check "failed task shows rc" "$([[ "$out" == *"bad ✘ rc=3"* ]] && echo 1 || echo 0)"
rm -f "$tmp/.claude/tasks/bad.task"

# .build_status: fresh 'done' marker shown, stale one removed
printf 'refresh done ✔ (19/19)' > "$tmp/.build_status"
out=$(render)
check "fresh build marker shown" "$([[ "$out" == *"refresh done"* ]] && echo 1 || echo 0)"
touch -d '20 minutes ago' "$tmp/.build_status"
render > /dev/null
check "stale build marker removed" "$([ ! -f "$tmp/.build_status" ] && echo 1 || echo 0)"
printf 'refresh 3/19: paths' > "$tmp/.build_status"
out=$(render)
check "running marker without a driver is flagged" "$([[ "$out" == *"(no driver alive)"* ]] && echo 1 || echo 0)"
touch -d '20 minutes ago' "$tmp/.build_status"
render > /dev/null
check "orphaned running marker removed after the stale TTL" "$([ ! -f "$tmp/.build_status" ] && echo 1 || echo 0)"

if [ "$fail" = "0" ]; then echo "statusline tests passed"; else echo "statusline tests FAILED"; exit 1; fi
