"""Driver for the SOC major-group LLM jury.

    uv run python -m career_clean.run_soc_jury extract
    uv run python -m career_clean.run_soc_jury calibrate [--execute] [--limit N]
    uv run python -m career_clean.run_soc_jury tail [--execute] [--limit N]
    uv run python -m career_clean.run_soc_jury merge

extract    build soc_candidates.parquet + soc_gold.parquet (pure DuckDB).
calibrate  fire the two-juror panel on the 600-string gold sample, then score
           agreement against the deterministic labels. Writes
           results/soc_calibration.json. The accept/reject GATE IS NOT CODED
           HERE -- a human reads the table and decides (pre-committed bar:
           unanimous-band accuracy >= 0.85).
tail       fire the panel over the top-N uncoded candidates by step count
           (default 50,000). Resumable: cached votes are never re-fired.
merge      unanimous non-abstain votes -> normalized/mappings/role_soc_jury.parquet
           (a NEW file; nothing existing is modified). Stats to
           results/soc_jury_stats.json.

Default (no --execute) for calibrate/tail is a dry-run: prints what would fire.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date

import duckdb

from career_clean import approach_a_rules as R
from career_clean import common as CC
from career_clean import soc_anchors as A
from career_clean import soc_candidates as SC
from career_clean import soc_llm as L
from career_clean import soc_taxonomy as T

# Employment-FORM nouns: a role string that is nothing but one of these names
# a form of employment, not an occupation, so no occupation label can honestly
# attach to it (the jury was instructed to abstain on these but missed some,
# e.g. "Internship" -> 21 in the first full merge). Same curation class as
# occupation._GENERIC_STATUS_TITLES. Extend ONLY with employment forms --
# never exclude a string because its label looks wrong (that is what the
# measured calibration error rate covers).
EMPLOYMENT_FORMS = {
    "internship", "apprenticeship", "volunteer", "volunteering",
    "work study", "temp", "temporary", "seasonal", "part time", "full time",
    "student", "students", "extern", "externship", "trainee", "apprentice",
    "intern",
}
# Head-noun forms (audit 2026-09-02 red H4): "Nursing Student", "PhD Student",
# "Legal Extern" name a person's STATUS in a field, not an occupation -- the
# jury coded "Student" as Education (12,452 rows) and nursing / medical
# students as practitioners. "Student Teacher" / "Student Assistant" keep a
# role head noun and stay. The clinical trainee list covers the one common
# inversion ("Student Nurse" = nursing student).
_STATUS_HEAD_RE = re.compile(
    r"(?:^|\s)(?:student|students|extern|externs|trainee|trainees|apprentice|apprentices)$")
_CLINICAL_TRAINEE_RE = re.compile(
    r"^student (?:nurse|nurses|physical therapist|athletic trainer|clinician|"
    r"physician assistant|pharmacist|midwife|dietitian|occupational therapist|"
    r"physician|doctor|dentist|optometrist|veterinarian)\b")


def _non_occupation(role_display: str | None) -> bool:
    """True when the string carries no occupational content: de-leveling
    leaves an empty base (pure level tokens like 'Intern', 'Senior'), the
    whole string is an employment-form noun, or its head noun is a status
    (student / extern / trainee / apprentice)."""
    if not role_display:
        return True
    norm = CC.normalize(role_display)
    if norm in EMPLOYMENT_FORMS:
        return True
    if _STATUS_HEAD_RE.search(norm) or _CLINICAL_TRAINEE_RE.match(norm):
        return True
    _lvl, base = R.parse_title(role_display)
    return not base.strip()

CAL_OUT = SC.RESULTS / "soc_calibration.json"
STATS_OUT = SC.RESULTS / "soc_jury_stats.json"
MERGE_OUT = SC.ROOT / "normalized" / "mappings" / "role_soc_jury.parquet"

_ITEM_COLS = ("role_canonical", "n_steps", "n_persons", "role_display",
              "top_titles", "industry_l1_label", "modal_seniority")


def _rows_to_items(rows, cols=_ITEM_COLS) -> list[dict]:
    return [dict(zip(cols, r)) for r in rows]


def _load_gold_sample(limit: int | None) -> list[dict]:
    con = duckdb.connect()
    q = (f"SELECT {', '.join(_ITEM_COLS)}, gold_major, tercile "
         f"FROM read_parquet('{SC.GOLD}') WHERE in_sample "
         f"ORDER BY n_steps DESC, role_canonical ASC")
    if limit:
        q += f" LIMIT {limit}"
    rows = con.execute(q).fetchall()
    items = _rows_to_items(rows, _ITEM_COLS + ("gold_major", "tercile"))
    con.close()
    A.attach_anchors(items)
    return items


def _load_candidates(limit: int) -> list[dict]:
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT {', '.join(_ITEM_COLS)} FROM read_parquet('{SC.CANDIDATES}') "
        f"ORDER BY n_steps DESC, role_canonical ASC LIMIT {limit}").fetchall()
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
        v = votes.get(it["role_canonical"], {})
        for m in L.JURY:
            if m in v:
                code = v[m]
                if code == T.ABSTAIN:
                    per_juror[m]["abstain"] += 1
                else:
                    per_juror[m]["n"] += 1
                    per_juror[m]["ok"] += int(code == it["gold_major"])
        if len(v) < len(L.JURY):
            band["incomplete"] += 1
            continue
        codes = [v[m] for m in L.JURY]
        acc = L.unanimous_accept(codes)
        if acc is not None:
            band["unanimous_n"] += 1
            ok = int(acc == it["gold_major"])
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
                      "deterministically-codable ones (selection bias toward easy "
                      "titles) -- documented, and abstention is the mitigation."),
    }
    CAL_OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def cmd_tail(execute: bool, limit: int) -> None:
    items = _load_candidates(limit)
    covered = sum(it["n_steps"] for it in items)
    print(f"tail: top {len(items):,} uncoded strings, covering {covered:,} steps")
    stats = L.fire(items, execute=execute)
    print(f"fire: {stats}")


def cmd_merge(limit: int) -> None:
    # Same item construction (incl. anchors) as `tail`, so cache keys match
    # exactly; strings beyond the fired prefix simply have no cached votes.
    items = _load_candidates(limit)

    # Mixed-population exclusion (2026-07-08 review finding): deterministic
    # coding is per RAW TITLE, so a role string can have coded AND uncoded
    # steps. Strings with ANY deterministically coded step already carry det
    # signal (and the jury contradicted it on ~30% of the head overlap) --
    # they are excluded from pooling rather than given a second, possibly
    # conflicting label. Their uncoded steps stay honestly unclassified.
    con = duckdb.connect()
    det_strings = {r[0] for r in con.execute(
        f"SELECT DISTINCT role_canonical FROM read_parquet('{SC.STEPS}') "
        f"WHERE occupation_code IS NOT NULL AND role_canonical IS NOT NULL").fetchall()}
    con.close()
    n_before = len(items)
    items = [it for it in items if it["role_canonical"] not in det_strings]
    excluded_mixed = n_before - len(items)
    n_before = len(items)
    items = [it for it in items if not _non_occupation(it["role_display"])]
    excluded_non_occupation = n_before - len(items)

    votes = L.votes_by_key(items)

    accepted: list[tuple[str, str]] = []
    stats = {"voted_strings": len(votes), "excluded_mixed_strings": excluded_mixed,
             "excluded_non_occupation": excluded_non_occupation,
             "accepted": 0, "disagree": 0,
             "abstained": 0, "incomplete": 0,
             "accepted_step_coverage": 0, "voted_step_coverage": 0}
    n_steps_by_key = {it["role_canonical"]: it["n_steps"] for it in items}
    for key, v in votes.items():
        stats["voted_step_coverage"] += n_steps_by_key.get(key, 0)
        if len(v) < len(L.JURY):
            stats["incomplete"] += 1
            continue
        codes = [v[m] for m in L.JURY]
        acc = L.unanimous_accept(codes)
        if acc is not None:
            accepted.append((key, acc))
            stats["accepted"] += 1
            stats["accepted_step_coverage"] += n_steps_by_key.get(key, 0)
        elif T.ABSTAIN in codes:
            stats["abstained"] += 1
        else:
            stats["disagree"] += 1

    MERGE_OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE acc (role_canonical VARCHAR, soc_major VARCHAR)")
    con.executemany("INSERT INTO acc VALUES (?, ?)", accepted)
    con.execute(f"""
        COPY (
          SELECT role_canonical, soc_major,
                 'llm_jury_v1' AS method, 2 AS n_jurors, TRUE AS unanimous
          FROM acc ORDER BY role_canonical
        ) TO '{MERGE_OUT}' (FORMAT parquet)
    """)
    con.close()
    stats["generated"] = date.today().isoformat()
    STATS_OUT.write_text(json.dumps(stats, indent=2) + "\n")
    print(f"wrote {MERGE_OUT} ({stats['accepted']:,} accepted strings, "
          f"{stats['accepted_step_coverage']:,} steps)")
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
        cmd_tail(args.execute, args.limit or 50000)
    elif args.mode == "merge":
        cmd_merge(args.limit or 50000)


if __name__ == "__main__":
    main()
