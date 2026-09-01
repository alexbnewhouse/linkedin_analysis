"""Third-juror tiebreak for the CIP field jury (audit R3).

The 2026-07-09 two-juror panel (both Qwen-family, llama-server lanes) discarded
2,745 disagree strings and 3,096 abstain-band strings covering ~103k education
rows -- including plainly codeable heads ('Information Systems', 2,996 rows).
This driver fires ONE disjoint-family third juror (gemma3:27b on the Framework
Desktop's Ollama -- no llama-server lane needed) on exactly those strings and
accepts 2-of-3 agreement at CIP2 grain.

    uv run python -m edu_clean.run_cip_tiebreak status
    uv run python -m edu_clean.run_cip_tiebreak calibrate [--execute]
    uv run python -m edu_clean.run_cip_tiebreak fire [--execute]
    uv run python -m edu_clean.run_cip_tiebreak merge [--execute]

calibrate  fire the third juror on the 600-string gold sample and score the
           2-of-3 rule on the subset where the original jurors disagreed.
           Pre-committed gate (same bar as the original panel): >= 0.85.
fire       fire the third juror on the disagree + partial-abstain strings.
           Votes land in the same append-only cache (results/cip_votes.jsonl).
merge      append 2-of-3 accepted strings to mappings/field_cip_jury.parquet
           (method 'llm_jury_v1_tb', n_jurors=3, unanimous=False). Then run
           `make normalize-education` to land the pooled columns.

Everything is resumable and propose-only, per the frozen-cache contract.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from edu_clean import cip_anchors as A
from edu_clean import cip_llm as L
from edu_clean import cip_taxonomy as T
from edu_clean import run_cip_jury as J
from edu_clean.run_cip_jury import _load_candidates, _load_gold_sample

ROOT = Path(__file__).resolve().parent.parent
JURY_PARQUET = ROOT / "normalized" / "mappings" / "field_cip_jury.parquet"
STATS = ROOT / "edu_clean" / "results" / "cip_tiebreak_stats.json"

# Disjoint-family third juror: the original panel is all-Qwen; gemma decorrelates
# errors (the industry jury's calibrated pairing). Served by the Framework
# Desktop's always-on Ollama daemon -- num_ctx is set per-request by
# cip_llm.build_request, so the 2k Ollama default trap does not apply.
THIRD = "ollama/gemma3:27b"
OLLAMA_HOSTS = "framework=http://100.73.40.75:11434|2|ollama"
ALL_JURORS = L.JURY + (THIRD,)

# How many top candidates to scan for vote states. The original tail pass voted
# the top 25k; every disagree/abstain string is inside that window.
SCAN = 25_000


def _make_ollama_pool():
    import os

    os.environ["OLLAMA_HOSTS"] = OLLAMA_HOSTS
    from industry import llm_pool

    return llm_pool.HostPool()


def _fire_via_ollama(items: list[dict], *, execute: bool) -> dict:
    """cip_llm.fire with the pool pointed at the Ollama host (not the
    llama-server lanes cip_llm pins by default)."""
    original = L.make_pool
    L.make_pool = _make_ollama_pool
    try:
        return L.fire(items, jurors=(THIRD,), execute=execute)
    finally:
        L.make_pool = original


def vote_state(v: dict[str, str]) -> str:
    """Classify a string's original-panel vote pattern."""
    codes = [v.get(m) for m in L.JURY]
    if any(c is None for c in codes):
        return "incomplete"
    valid = [c for c in codes if c != T.ABSTAIN and T.is_valid(c)]
    if len(valid) == 2:
        return "unanimous" if codes[0] == codes[1] else "disagree"
    if len(valid) == 1:
        return "partial_abstain"
    return "abstain"


def majority_accept(v: dict[str, str]) -> str | None:
    """2-of-3 at CIP2 grain over whichever of the three jurors voted."""
    codes = [c for c in (v.get(m) for m in ALL_JURORS)
             if c is not None and c != T.ABSTAIN and T.is_valid(c)]
    for code in set(codes):
        if codes.count(code) >= 2:
            return code
    return None


def _targets() -> list[dict]:
    """Disagree + partial-abstain strings from the voted window, minus
    non-field literals (they were excluded from the original pass too)."""
    items = _load_candidates(SCAN)
    items = [it for it in items if not J._non_field(it["field_norm"])]
    votes = L.votes_by_key(items)
    return [
        it for it in items
        if vote_state(votes.get(it["field_norm"], {})) in ("disagree", "partial_abstain")
    ]


def cmd_status() -> None:
    targets = _targets()
    votes3 = L.votes_by_key(targets, jurors=(THIRD,))
    fired = sum(1 for it in targets if THIRD in votes3.get(it["field_norm"], {}))
    rows = sum(it["n_rows"] for it in targets)
    print(f"tiebreak targets: {len(targets):,} strings covering {rows:,} rows")
    print(f"third-juror votes cached: {fired:,} / {len(targets):,}")


def cmd_calibrate(execute: bool) -> None:
    items = _load_gold_sample(None)
    stats = _fire_via_ollama(items, execute=execute)
    print(f"fire: {stats}")
    votes = L.votes_by_key(items, jurors=ALL_JURORS)

    solo = {"n": 0, "ok": 0, "abstain": 0}
    tb = {"n": 0, "ok": 0, "resolved": 0}
    for it in items:
        v = votes.get(it["field_norm"], {})
        third = v.get(THIRD)
        if third is not None:
            if third == T.ABSTAIN:
                solo["abstain"] += 1
            else:
                solo["n"] += 1
                solo["ok"] += int(third == it["gold_cip2"])
        if vote_state(v) in ("disagree", "partial_abstain") and third is not None:
            tb["n"] += 1
            acc = majority_accept(v)
            if acc is not None:
                tb["resolved"] += 1
                tb["ok"] += int(acc == it["gold_cip2"])

    report = {
        "generated": date.today().isoformat(),
        "third_juror": THIRD,
        "solo_accuracy": round(solo["ok"] / solo["n"], 4) if solo["n"] else None,
        "solo_voted": solo["n"], "solo_abstain": solo["abstain"],
        "tiebreak_band": {
            "gold_disagree_or_partial": tb["n"],
            "resolved": tb["resolved"],
            "accuracy": round(tb["ok"] / tb["resolved"], 4) if tb["resolved"] else None,
        },
        "gate": "merge only if tiebreak accuracy >= 0.85 "
                "(solo accuracy is secondary evidence when the band is small)",
    }
    print(json.dumps(report, indent=2))
    STATS.parent.mkdir(parents=True, exist_ok=True)
    STATS.write_text(json.dumps({"calibration": report}, indent=2) + "\n")


def cmd_fire(execute: bool) -> None:
    targets = _targets()
    stats = _fire_via_ollama(targets, execute=execute)
    print(f"fire: {stats}")
    if not execute:
        print("(dry-run -- pass --execute to fire)")


def cmd_merge(execute: bool) -> None:
    targets = _targets()
    votes = L.votes_by_key(targets, jurors=ALL_JURORS)
    con = duckdb.connect()
    existing = {r[0] for r in con.execute(
        f"SELECT field_norm FROM read_parquet('{JURY_PARQUET}')").fetchall()}

    additions, rows_covered = [], 0
    for it in targets:
        key = it["field_norm"]
        if key in existing:
            continue
        v = votes.get(key, {})
        if THIRD not in v:
            continue
        code = majority_accept(v)
        if code is not None:
            additions.append((key, code))
            rows_covered += it["n_rows"]

    print(f"accepted by 2-of-3: {len(additions):,} strings covering "
          f"{rows_covered:,} education rows")
    if not execute:
        print("(dry-run -- pass --execute to rewrite field_cip_jury.parquet)")
        con.close()
        return

    con.execute("CREATE TEMP TABLE adds (field_norm VARCHAR, cip2 VARCHAR)")
    con.executemany("INSERT INTO adds VALUES (?, ?)", additions)
    tmp = JURY_PARQUET.with_name(JURY_PARQUET.name + ".tmp")
    con.execute(f"""
        COPY (
          SELECT * FROM read_parquet('{JURY_PARQUET}')
          UNION ALL
          SELECT field_norm, cip2, 'llm_jury_v1_tb' AS method,
                 3 AS n_jurors, FALSE AS unanimous
          FROM adds
        ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)
    """)
    dup = con.execute(
        f"SELECT count(*) - count(DISTINCT field_norm) FROM read_parquet('{tmp}')"
    ).fetchone()[0]
    assert dup == 0, f"merge would create {dup} duplicate field_norm rows"
    tmp.replace(JURY_PARQUET)
    con.close()
    prior = json.loads(STATS.read_text()) if STATS.exists() else {}
    prior["merge"] = {
        "generated": date.today().isoformat(),
        "accepted_strings": len(additions),
        "rows_covered": rows_covered,
    }
    STATS.write_text(json.dumps(prior, indent=2) + "\n")
    print(f"merged -> {JURY_PARQUET}")
    print("now run: make normalize-education  (lands the pooled columns)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("status", "calibrate", "fire", "merge"),
                    nargs="?", default="status")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    A.ensure_ready() if hasattr(A, "ensure_ready") else None
    {"status": cmd_status,
     "calibrate": lambda: cmd_calibrate(args.execute),
     "fire": lambda: cmd_fire(args.execute),
     "merge": lambda: cmd_merge(args.execute)}[args.cmd]()


if __name__ == "__main__":
    main()
