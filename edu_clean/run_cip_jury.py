"""Driver for the CIP 2-digit family LLM jury.

    uv run python -m edu_clean.run_cip_jury extract
    uv run python -m edu_clean.run_cip_jury calibrate [--execute] [--limit N]
    uv run python -m edu_clean.run_cip_jury tail [--execute] [--limit N]
    uv run python -m edu_clean.run_cip_jury merge

extract    build cip_candidates.parquet + cip_gold.parquet (pure DuckDB).
calibrate  fire the two-juror panel on the 600-string gold sample, then score
           agreement against the deterministic labels. Writes
           results/cip_calibration.json. The accept/reject GATE IS NOT CODED
           HERE -- a human reads the table and decides (pre-committed bar:
           unanimous-band accuracy >= 0.85).
tail       fire the panel over the top-N uncoded candidates by row count
           (default 25,000). Resumable: cached votes are never re-fired.
merge      unanimous non-abstain votes -> normalized/mappings/field_cip_jury.parquet
           (a NEW file; nothing existing is modified). Stats to
           results/cip_jury_stats.json.

Default (no --execute) for calibrate/tail is a dry-run: prints what would fire.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date

import duckdb

from edu_clean import cip_anchors as A
from edu_clean import cip_candidates as SC
from edu_clean import cip_llm as L
from edu_clean import cip_taxonomy as T

# Literal non-answers: a field string that is nothing but one of these names
# NO field of study, so no CIP family can honestly attach to it (the jury is
# instructed to abstain on these but, per the SOC-jury experience with
# "Internship" -> 21, rule-level backstops are needed). All members were
# observed among the uncoded strings (probe 2026-07-09: "n/a" 1,320 rows,
# "none" 1,024, "cum laude" 933, "minor" / "undeclared" in the tail).
# Deliberately NOT here: "general studies" (a REAL family -- the coded data
# maps it to CIP 24 on 29,361 rows) and "general" (left to the jury/XUN).
# Extend ONLY with literal non-answers -- never exclude a string because its
# label looks wrong (that is what the measured calibration error rate covers).
NON_FIELD_LITERALS = {
    # explicit non-answers / placeholders
    "n/a", "n.a.", "na", "none", "nil", "null", "not applicable", "n/a.",
    "no", "yes", "-", "--", ".", "..", "...", "x", "xx", "xxx", "tbd",
    "unknown", "other", "misc", "miscellaneous",
    # enrollment-status words that name no field
    "undeclared", "undecided", "minor", "major", "double major",
    # class-year / enrollment words (audit R4, 2026-09-01: observed in the
    # uncoded tail -- 'Senior' 366 rows, 'Study Abroad' etc.)
    "senior", "junior", "sophomore", "freshman", "freshmen",
    "graduate", "undergraduate", "student", "gpa",
    "study abroad", "exchange program", "exchange student", "semester abroad",
    # honors/grade phrases (grades are also caught by the numeric rule)
    "cum laude", "magna cum laude", "summa cum laude",
    "with honors", "with honours", "honors", "honours",
    "high honors", "highest honors", "dean's list", "deans list",
}

# GPA / year / grade strings: "4.0", "3.8", "12", "2005-2009" -- digits and
# digit punctuation only, no letters (matched against the lower/trim key).
_NUMERIC = re.compile(r"^[0-9][0-9 ./,+-]*$")


def _non_field(field_norm: str | None) -> bool:
    """True when the string carries no field-of-study content BY RULE:
    empty/single character, purely numeric (GPA/year), or a literal
    non-answer from the documented set above."""
    if not field_norm:
        return True
    s = field_norm.strip()
    if len(s) <= 1:
        return True
    if _NUMERIC.match(s):
        return True
    return s in NON_FIELD_LITERALS


CAL_OUT = SC.RESULTS / "cip_calibration.json"
STATS_OUT = SC.RESULTS / "cip_jury_stats.json"
MERGE_OUT = SC.ROOT / "normalized" / "mappings" / "field_cip_jury.parquet"

_ITEM_COLS = ("field_norm", "n_rows", "n_persons", "top_raw_variants",
              "modal_degree_text", "n_bachelor_rows")


def _rows_to_items(rows, cols=_ITEM_COLS) -> list[dict]:
    return [dict(zip(cols, r)) for r in rows]


def _load_gold_sample(limit: int | None) -> list[dict]:
    con = duckdb.connect()
    q = (f"SELECT {', '.join(_ITEM_COLS)}, gold_cip2, tercile "
         f"FROM read_parquet('{SC.GOLD}') WHERE in_sample "
         f"ORDER BY n_rows DESC, field_norm ASC")
    if limit:
        q += f" LIMIT {limit}"
    rows = con.execute(q).fetchall()
    items = _rows_to_items(rows, _ITEM_COLS + ("gold_cip2", "tercile"))
    con.close()
    A.attach_anchors(items)
    return items


def _load_candidates(limit: int) -> list[dict]:
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT {', '.join(_ITEM_COLS)} FROM read_parquet('{SC.CANDIDATES}') "
        f"ORDER BY n_rows DESC, field_norm ASC LIMIT {limit}").fetchall()
    con.close()
    items = _rows_to_items(rows)
    A.attach_anchors(items)
    return items


def cmd_extract() -> None:
    counts = SC.build()
    print(f"candidates: {counts['candidates']:,} rows -> {SC.CANDIDATES}")
    print(f"gold:       {counts['gold']:,} rows ({counts['gold_in_sample']} in_sample) -> {SC.GOLD}")
    con = duckdb.connect()
    for name, path in (("candidates", SC.CANDIDATES), ("gold", SC.GOLD)):
        print(f"-- {name} preview:")
        for r in con.execute(
                f"SELECT * FROM read_parquet('{path}') LIMIT 5").fetchall():
            print("  ", r)
    con.close()


def cmd_calibrate(execute: bool, limit: int | None) -> None:
    items = _load_gold_sample(limit)
    print(f"gold sample: {len(items)} strings")
    stats = L.fire(items, execute=execute)
    print(f"fire: {stats}")
    if not execute and stats["pending_units"]:
        print("(dry-run -- pass --execute to fire; scoring whatever is cached)")

    votes = L.votes_by_key(items)
    per_juror: dict[str, dict[str, int]] = {m: {"n": 0, "ok": 0, "abstain": 0} for m in L.JURY}
    band = {"unanimous_n": 0, "unanimous_ok": 0, "disagree": 0,
            "abstain_any": 0, "incomplete": 0}
    by_tercile: dict[int, dict[str, int]] = {}

    for it in items:
        v = votes.get(it["field_norm"], {})
        for m in L.JURY:
            if m in v:
                code = v[m]
                if code == T.ABSTAIN:
                    per_juror[m]["abstain"] += 1
                else:
                    per_juror[m]["n"] += 1
                    per_juror[m]["ok"] += int(code == it["gold_cip2"])
        if len(v) < len(L.JURY):
            band["incomplete"] += 1
            continue
        codes = [v[m] for m in L.JURY]
        acc = L.unanimous_accept(codes)
        if acc is not None:
            band["unanimous_n"] += 1
            ok = int(acc == it["gold_cip2"])
            band["unanimous_ok"] += ok
            tc = by_tercile.setdefault(it["tercile"], {"n": 0, "ok": 0})
            tc["n"] += 1
            tc["ok"] += ok
        elif T.ABSTAIN in codes:
            band["abstain_any"] += 1
        else:
            band["disagree"] += 1

    def _rate(ok, n):
        return round(ok / n, 4) if n else None

    report = {
        "generated": date.today().isoformat(),
        "gold_n": len(items),
        "per_juror": {
            m: {"voted_non_abstain": s["n"], "accuracy": _rate(s["ok"], s["n"]),
                "abstain": s["abstain"]}
            for m, s in per_juror.items()
        },
        "unanimous": {
            "n": band["unanimous_n"],
            "coverage": _rate(band["unanimous_n"], len(items)),
            "accuracy": _rate(band["unanimous_ok"], band["unanimous_n"]),
        },
        "disagree": band["disagree"],
        "abstain_any": band["abstain_any"],
        "incomplete": band["incomplete"],
        "by_tercile": {str(t): {"n": s["n"], "accuracy": _rate(s["ok"], s["n"])}
                       for t, s in sorted(by_tercile.items())},
        "gate_note": ("Pre-committed bar: unanimous-band accuracy >= 0.85 on this "
                      "gold sample, else the jury ships flagged experimental and "
                      "stays out of every default consumer. Gold strings are the "
                      "deterministically-codable ones (selection bias toward clean "
                      "field names) -- documented, and abstention is the mitigation. "
                      "Anchors come from the gold mapping itself and cannot be made "
                      "fully leak-proof against the coder's fuzzy typo_to_cip "
                      "surface (Jaccard >= 0.85 anchors are excluded as mitigation), "
                      "so calibration may be slightly optimistic."),
    }
    CAL_OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def cmd_tail(execute: bool, limit: int) -> None:
    items = _load_candidates(limit)
    covered = sum(it["n_rows"] for it in items)
    print(f"tail: top {len(items):,} uncoded strings, covering {covered:,} education rows")
    stats = L.fire(items, execute=execute)
    print(f"fire: {stats}")


def cmd_merge(limit: int) -> None:
    # Same item construction (incl. anchors) as `tail`, so cache keys match
    # exactly; strings beyond the fired prefix simply have no cached votes.
    items = _load_candidates(limit)

    # Mixed-population exclusion (SOC-jury 2026-07-08 review finding, same
    # mechanism here): coding is per RAW STRING but lower/trim collapses
    # distinct raws onto one field_norm, so a string can have coded AND
    # uncoded rows. Strings with ANY deterministically coded row already
    # carry det signal -- they are excluded from pooling rather than given a
    # second, possibly conflicting label. Their uncoded rows stay honestly
    # unclassified.
    con = duckdb.connect()
    det_strings = {r[0] for r in con.execute(
        f"SELECT DISTINCT lower(trim(field_raw)) FROM read_parquet('{SC.EDUCATION}') "
        f"WHERE cip_code IS NOT NULL AND field_raw IS NOT NULL "
        f"AND trim(field_raw) <> ''").fetchall()}
    con.close()
    n_before = len(items)
    items = [it for it in items if it["field_norm"] not in det_strings]
    excluded_mixed = n_before - len(items)
    n_before = len(items)
    items = [it for it in items if not _non_field(it["field_norm"])]
    excluded_non_field = n_before - len(items)

    votes = L.votes_by_key(items)

    accepted: list[tuple[str, str]] = []
    stats = {"voted_strings": len(votes), "excluded_mixed_strings": excluded_mixed,
             "excluded_non_field": excluded_non_field,
             "accepted": 0, "disagree": 0,
             "abstained": 0, "incomplete": 0,
             "accepted_row_coverage": 0, "voted_row_coverage": 0}
    n_rows_by_key = {it["field_norm"]: it["n_rows"] for it in items}
    for key, v in votes.items():
        stats["voted_row_coverage"] += n_rows_by_key.get(key, 0)
        if len(v) < len(L.JURY):
            stats["incomplete"] += 1
            continue
        codes = [v[m] for m in L.JURY]
        acc = L.unanimous_accept(codes)
        if acc is not None:
            accepted.append((key, acc))
            stats["accepted"] += 1
            stats["accepted_row_coverage"] += n_rows_by_key.get(key, 0)
        elif T.ABSTAIN in codes:
            stats["abstained"] += 1
        else:
            stats["disagree"] += 1

    MERGE_OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE acc (field_norm VARCHAR, cip2 VARCHAR)")
    con.executemany("INSERT INTO acc VALUES (?, ?)", accepted)
    con.execute(f"""
        COPY (
          SELECT field_norm, cip2,
                 'llm_jury_v1' AS method, 2 AS n_jurors, TRUE AS unanimous
          FROM acc ORDER BY field_norm
        ) TO '{MERGE_OUT}' (FORMAT parquet)
    """)
    con.close()
    stats["generated"] = date.today().isoformat()
    STATS_OUT.write_text(json.dumps(stats, indent=2) + "\n")
    print(f"wrote {MERGE_OUT} ({stats['accepted']:,} accepted strings, "
          f"{stats['accepted_row_coverage']:,} education rows)")
    print(json.dumps(stats, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["extract", "calibrate", "tail", "merge"])
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    if args.mode == "extract":
        cmd_extract()
    elif args.mode == "calibrate":
        cmd_calibrate(args.execute, args.limit)
    elif args.mode == "tail":
        cmd_tail(args.execute, args.limit or 25000)
    elif args.mode == "merge":
        cmd_merge(args.limit or 25000)


if __name__ == "__main__":
    main()
