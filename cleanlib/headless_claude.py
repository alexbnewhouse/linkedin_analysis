"""Headless Claude Code as a juror backend (subscription login, no API key).

One call = one `claude -p` process with its own system prompt, no tools, no
settings, no MCP, structured output enforced by --json-schema. Returns the
parsed structured output plus the usage the CLI reports (tokens, notional
USD, model snapshot id), so callers can cache votes keyed by the exact model.

    from cleanlib.headless_claude import call
    r = call("haiku", system, user, schema)
    r["output"], r["model"], r["usage"], r["duration_s"], r["cost_usd"]

Sanctioned route for the Claude.ai login (Claude Code / Agent SDK); never the
raw Messages API with the OAuth token. Temperature is not controllable here,
so reproducibility rests on the append-only vote cache (record the raw result).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

CLAUDE = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
DEFAULT_TIMEOUT = 600


class HeadlessError(RuntimeError):
    pass


def call(model: str, system: str, user: str, schema: dict, *,
         timeout: int = DEFAULT_TIMEOUT, max_turns: int = 3,
         thinking_tokens: int = 0) -> dict:
    """max_turns >= 2: the structured output arrives as a tool call in a second
    turn (max_turns=1 ends with error_max_turns). thinking_tokens=0 disables
    extended thinking, which Claude Code turns on by default -- measured on a
    25-role batch: 10.7k thinking tokens and 126s with it, 0 and 34s without."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["MAX_THINKING_TOKENS"] = str(thinking_tokens)
    cmd = [CLAUDE, "-p", user, "--model", model, "--output-format", "json",
           "--system-prompt", system, "--json-schema", json.dumps(schema),
           "--tools", "", "--setting-sources", "", "--strict-mcp-config",
           "--no-session-persistence", "--max-turns", str(max_turns)]
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        raise HeadlessError(f"timeout after {timeout}s") from e
    dt = time.monotonic() - t0
    if p.returncode != 0 and not p.stdout.strip():
        raise HeadlessError(f"exit {p.returncode}: {p.stderr[-500:]}")
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise HeadlessError(f"non-JSON stdout: {p.stdout[:300]!r} stderr: {p.stderr[-300:]!r}") from e
    if d.get("is_error"):
        raise HeadlessError(f"CLI error: subtype={d.get('subtype')} result={str(d.get('result'))[:200]} "
                            f"errors={d.get('errors')}")
    out = d.get("structured_output")
    if out is None:
        # fall back: result text may carry JSON (possibly fenced)
        txt = (d.get("result") or "").strip()
        if txt.startswith("```"):
            txt = txt.strip("`")
            txt = txt[txt.find("{"):txt.rfind("}") + 1]
        try:
            out = json.loads(txt)
        except json.JSONDecodeError:
            out = None
    # modelUsage has one entry per model touched. Claude Code makes a small
    # Haiku side-call on every run; the juror is the entry with the most output.
    usage = d.get("modelUsage") or {}
    main = max(usage, key=lambda m: usage[m].get("outputTokens", 0)) if usage else None
    u = usage.get(main, {}) if main else {}
    side = {m: round(x.get("costUSD", 0), 6) for m, x in usage.items() if m != main}
    return {
        "output": out, "model": main, "duration_s": round(dt, 2),
        "cost_usd": d.get("total_cost_usd"),
        "usage": {"input": u.get("inputTokens"), "output": u.get("outputTokens"),
                  "cache_read": u.get("cacheReadInputTokens"),
                  "cache_create": u.get("cacheCreationInputTokens"),
                  "thinking": u.get("thinkingTokens"), "cost_main": u.get("costUSD")},
        "side_calls": side, "num_turns": d.get("num_turns"), "stop_reason": d.get("stop_reason"),
        "session_id": d.get("session_id"),
        "stderr": p.stderr[-300:] if p.returncode else "",
    }
