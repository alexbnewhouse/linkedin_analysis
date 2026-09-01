"""Driver for the degree-LEVEL LLM jury (mirror of edu_clean/run_cip_jury.py).

    uv run python -m edu_clean.run_dlevel_jury calibrate --execute [--limit N]
    uv run python -m edu_clean.run_dlevel_jury tail      --execute [--limit N]
    uv run python -m edu_clean.run_dlevel_jury merge      [--limit N]

calibrate  fire the panel on a gold sample of deterministically-leveled keys and
           score unanimous-band accuracy against the true level. GATE (human-read):
           unanimous accuracy >= 0.85, else ship flagged experimental.
tail       fire the panel over the top-N uncoded (degree,field) keys by row count.
merge      unanimous non-abstain votes -> normalized/mappings/degree_level_jury.parquet
           (NEW file). Per (linkedin_id, idx) rows are expanded from the key at
           apply time; here we store key -> level.
"""
from __future__ import annotations

import argparse
import json
from datetime import date

import duckdb

from edu_clean import dlevel_jury as J
from edu_clean import dlevel_taxonomy as T

RESULTS = J.CACHE_FILE.parent
CAL_OUT = RESULTS / "dlevel_calibration.json"
STATS_OUT = RESULTS / "dlevel_jury_stats.json"
MERGE_OUT = J.ROOT / "normalized" / "mappings" / "degree_level_jury.parquet"


def cmd_calibrate(execute: bool, limit: int) -> None:
    items = J.gold(limit or 600)
    print(f"gold: {len(items)} keys")
    print("fire:", J.fire(items, execute=execute))
    votes = J.votes_by_key(items)
    band = {"unanimous_n": 0, "unanimous_ok": 0, "disagree": 0, "abstain_any": 0,
            "incomplete": 0}
    per = {m: {"n": 0, "ok": 0, "abstain": 0} for m in J.JURY}
    gold_by_key = {it["key"]: it["gold_code"] for it in items}
    for it in items:
        v = votes.get(it["key"], {})
        for m in J.JURY:
            if m in v:
                c = v[m]
                if c == T.ABSTAIN:
                    per[m]["abstain"] += 1
                else:
                    per[m]["n"] += 1
                    per[m]["ok"] += int(c == it["gold_code"])
        if len(v) < len(J.JURY):
            band["incomplete"] += 1; continue
        codes = [v[m] for m in J.JURY]
        acc = J.unanimous_accept(codes)
        if acc is not None:
            band["unanimous_n"] += 1
            band["unanimous_ok"] += int(acc == gold_by_key[it["key"]])
        elif T.ABSTAIN in codes:
            band["abstain_any"] += 1
        else:
            band["disagree"] += 1

    def rate(a, b):
        return round(a / b, 4) if b else None
    report = {
        "generated": date.today().isoformat(), "gold_n": len(items),
        "per_juror": {m: {"voted": s["n"], "accuracy": rate(s["ok"], s["n"]),
                          "abstain": s["abstain"]} for m, s in per.items()},
        "unanimous": {"n": band["unanimous_n"],
                      "coverage": rate(band["unanimous_n"], len(items)),
                      "accuracy": rate(band["unanimous_ok"], band["unanimous_n"])},
        "disagree": band["disagree"], "abstain_any": band["abstain_any"],
        "incomplete": band["incomplete"],
        "gate_note": "GATE: unanimous accuracy >= 0.85 (human-read).",
    }
    CAL_OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["unanimous"], indent=2))


def cmd_tail(execute: bool, limit: int) -> None:
    items = J.candidates(limit or 25000)
    cov = sum(it["n_rows"] for it in items)
    print(f"tail: {len(items):,} keys covering {cov:,} rows")
    print("fire:", J.fire(items, execute=execute))


def cmd_merge(limit: int) -> None:
    items = J.candidates(limit or 25000)
    votes = J.votes_by_key(items)
    n_by_key = {it["key"]: it["n_rows"] for it in items}
    accepted, stats = [], {"accepted": 0, "disagree": 0, "abstain": 0, "incomplete": 0,
                           "accepted_rows": 0}
    for key, v in votes.items():
        if len(v) < len(J.JURY):
            stats["incomplete"] += 1; continue
        acc = J.unanimous_accept([v[m] for m in J.JURY])
        if acc is not None:
            accepted.append((key, int(acc)))
            stats["accepted"] += 1
            stats["accepted_rows"] += n_by_key.get(key, 0)
        elif T.ABSTAIN in v.values():
            stats["abstain"] += 1
        else:
            stats["disagree"] += 1
    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE acc (key VARCHAR, degree_level_jury TINYINT)")
    con.executemany("INSERT INTO acc VALUES (?, ?)", accepted)
    MERGE_OUT.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY (SELECT key, degree_level_jury, 'llm_jury_v1' AS method "
                f"FROM acc ORDER BY key) TO '{MERGE_OUT}' (FORMAT parquet, COMPRESSION zstd)")
    con.close()
    stats["generated"] = date.today().isoformat()
    STATS_OUT.write_text(json.dumps(stats, indent=2) + "\n")
    print(f"wrote {MERGE_OUT}: {stats['accepted']:,} keys, {stats['accepted_rows']:,} rows")
    print(json.dumps(stats, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["calibrate", "tail", "merge"])
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    if a.mode == "calibrate":
        cmd_calibrate(a.execute, a.limit)
    elif a.mode == "tail":
        cmd_tail(a.execute, a.limit)
    else:
        cmd_merge(a.limit)


if __name__ == "__main__":
    main()
