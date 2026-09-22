# Sibling-Methods Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land six methods from the sibling clean-room build (external benchmarks, imputed bachelor's tier, co-majors, occupation-family tier, employer-keyed overrides, person summary + metrics cube v0) as propose-only, gated, tested layers.

**Architecture:** Every piece is a driver that writes a NEW mapping parquet or appends `_pooled`/`_source` columns; deterministic columns are fingerprint-asserted unchanged. Data-independent logic lives in pure functions with plain-assert test modules wired into `make test`; data invariants go into `make test-data`. Each piece is bracketed by a fresh pre-review subagent (design) and a fresh post-review subagent (code + re-derived numbers), recorded in the notes file.

**Tech Stack:** Python 3.14, DuckDB, pyarrow, `uv run`; plain-assert test modules (repo style, no pytest).

**Spec:** `docs/superpowers/specs/2026-09-22-sibling-methods-port-design.md`

## Global Constraints

- Never mutate a deterministic column; assert with `bit_xor(hash(...))` fingerprints as `edu_clean/apply_degree_level_pooled.py` does.
- Every apply is idempotent and dry-run by default; `--execute` writes.
- New mappings are OPTIONAL in `build_normalized.py` (`OPTIONAL_MAPPINGS`), so a fresh clone builds without them.
- Tests are plain-assert modules runnable as `uv run python -m <module>`; add each to `make test` (logic) or `make test-data` (reads parquet).
- Disclosure floor for any reported cell: `portal.common.MIN_SUPPORT` (10).
- Snapshot constants come from `paths.common` (`SNAPSHOT_DATE`, `SNAPSHOT_YEAR=2026`, `LAST_COMPLETE_YEAR=2025`); never re-declare them.
- American spelling in all new prose and identifiers.
- Ruff config in `pyproject.toml` (E4, E7, E9, F, W6); run `make lint` before each commit.
- Notes file: `docs/notes/2026-09-22-sibling-methods-port.md` gets an entry per piece before its commit is called done.
- Review protocol per piece (Tasks 1, 3, 5, 7, 9, 11 are pre-reviews; 2, 4, 6, 8, 10, 12 are build + post-review): the reviewer is a fresh `general-purpose` subagent; it receives the spec section, the notes file, file pointers, and the question; it never receives the implementer's conclusion. Verdicts are quoted verbatim into the notes.
- Working directory is the worktree `/home/alex/linkedin-analysis/.claude/worktrees/sibling-methods-port`. `parsed/`, `data/`, caches are symlinks; everything else is a private copy.

---

## Review-subagent prompt templates

**Pre-review (design).** Prompt body:

```
You are reviewing ONE proposed change to the linkedin-analysis repo before it is built.
Read, in this order: docs/superpowers/specs/2026-09-22-sibling-methods-port-design.md
section <PX>, docs/notes/2026-09-22-sibling-methods-port.md, PIPELINE.md, and the files
listed below. Do not read the sibling project. Answer, with evidence (file:line or a
DuckDB query you ran): (1) Is this an improvement over what the repo does today, and for
whom? (2) What would it break or bias, and is the proposed guard sufficient? (3) Is the
precision gate the right gate, and is the bar right? (4) One concrete change you would
make before building, or "none". End with a single line: VERDICT: BUILD | BUILD WITH
CHANGES | DO NOT BUILD. Files: <list>.
```

**Post-review (code + numbers).** Prompt body:

```
You are reviewing ONE change to the linkedin-analysis repo after it was built. Read the
spec section <PX>, the notes entry for <PX>, then `git diff <base>..<head> -- <paths>`.
Re-run the tests named in the notes entry and re-derive every "after" number in the notes
entry with your own DuckDB query (state the query). Then score the blind sample described
in the spec gate (the sample file path is in the notes entry) and report precision with
the rows you rejected. Answer: (1) Do the numbers reproduce? (2) Does the code honor the
propose-only contract (deterministic columns untouched, idempotent, dry-run default)?
(3) Is the gate met? (4) Defects, ranked. End with: VERDICT: LAND | LAND AS PROPOSE-ONLY |
DO NOT LAND, and one sentence why.
```

---

### Task 1: P1 pre-review

**Files:** none created.

- [ ] **Step 1: Dispatch the pre-review subagent** with the template above, `<PX>` = P1, files: `edu_clean/humanities.py:1-60`, `normalized/education.parquet` schema (via `DESCRIBE`), `reference/README.md`, `edu_clean/results/tier_counts.json`.
- [ ] **Step 2: Record the verdict** under `## P1` in the notes file, verbatim, plus any change adopted.

### Task 2: P1 External benchmarks

**Files:**
- Create: `validation/__init__.py`, `validation/common.py`, `validation/external_benchmarks.py`, `validation/validation_tests.py`, `validation/benchmark_checks.py`, `validation/results/.gitkeep`
- Create: `reference/nces_bachelors_by_field.json`, `reference/humanities_indicators.json`
- Modify: `Makefile` (test, test-data), `reference/README.md`

**Interfaces:**
- Produces: `validation.common.CORE6 = ("05","16","23","24","38","54")`, `validation.common.year_bucket(end_year:int, targets:list[int]) -> int|None`, `validation.common.shares(rows:list[tuple[str,int]]) -> dict[str,float]`, `validation.external_benchmarks.build() -> dict`.

- [ ] **Step 1: Write the NCES reference JSON.** Values from the Digest of Education Statistics Table 322.10 (editions d22, d23). Academic-year key is the END year of the academic year (1990-91 → 1991). Fetch `https://nces.ed.gov/programs/digest/d23/tables/dt23_322.10.asp` with WebFetch and confirm each `total`, `english`, `foreign_lang`, `liberal_arts_hum`, `phil_rel`, `area_ethnic`, `business`, `cs`, `socsci_history` number; correct any that differ; put the fetch date in `verified_on`. `history` comes from Humanities Indicators (indicator "Bachelor's Degrees in History"); record its URL in `history_source`.

```json
{
  "source": "NCES Digest of Education Statistics, Table 322.10, bachelor's degrees conferred by field of study (d22/d23)",
  "url": "https://nces.ed.gov/programs/digest/d23/tables/dt23_322.10.asp",
  "verified_on": "<date>",
  "history_source": "American Academy of Arts & Sciences, Humanities Indicators, Bachelor's degrees in history",
  "cip_map": {"english": "23", "foreign_lang": "16", "liberal_arts_hum": "24", "phil_rel": "38",
              "area_ethnic": "05", "history": "54", "business": "52", "cs": "11",
              "socsci_history": "45+54", "communication": "09", "visual_performing_arts": "50",
              "theology": "39", "psychology": "42", "biology": "26", "engineering": "14",
              "health": "51", "education": "13"},
  "years": {
    "1991": {"total": 1094538, "english": 51064, "foreign_lang": 13937, "liberal_arts_hum": 30526,
             "phil_rel": 7423, "area_ethnic": 4776, "socsci_history": 125107, "history": null,
             "communication": 51650, "visual_performing_arts": 42186, "business": 249165, "cs": 25159},
    "2001": {"total": 1244171, "english": 50569, "foreign_lang": 16128, "liberal_arts_hum": 37962,
             "phil_rel": 9442, "area_ethnic": 6160, "socsci_history": 128036, "history": null,
             "communication": 58013, "visual_performing_arts": 61148, "business": 263515, "cs": 44142},
    "2006": {"total": 1485104, "english": 55094, "foreign_lang": 19393, "liberal_arts_hum": 44898,
             "phil_rel": 12841, "area_ethnic": 7878, "socsci_history": 161468, "history": null,
             "communication": 73658, "visual_performing_arts": 83292, "business": 318043, "cs": 47702},
    "2016": {"total": 1920750, "english": 42797, "foreign_lang": 18436, "liberal_arts_hum": 43669,
             "phil_rel": 12133, "area_ethnic": 7840, "socsci_history": 161211, "history": null,
             "communication": 92551, "visual_performing_arts": 92979, "business": 371690, "cs": 64402},
    "2021": {"total": 2066445, "english": 35762, "foreign_lang": 15518, "liberal_arts_hum": 41909,
             "phil_rel": 11988, "area_ethnic": 7374, "socsci_history": 160827, "history": null,
             "communication": 90775, "visual_performing_arts": 90022, "business": 391375, "cs": 104874},
    "2022": {"total": 2015035, "english": 33429, "foreign_lang": 13912, "liberal_arts_hum": 37887,
             "phil_rel": 11230, "area_ethnic": 6658, "socsci_history": 151109, "history": null,
             "communication": 86043, "visual_performing_arts": 90241, "business": 375418, "cs": 108503,
             "psychology": 129609, "biology": 131462, "engineering": 123017, "health": 263765,
             "education": 89410, "theology": 6394}
  },
  "notes": "history is null where no separately sourced count was verified; core6 then uses socsci_history * history_share_fallback (0.13, Humanities Indicators' long-run share of history within social sciences and history) and marks the year 'history_estimated'."
}
```

`reference/humanities_indicators.json`:

```json
{"source": "American Academy of Arts & Sciences, Humanities Indicators",
 "url": "https://www.amacad.org/humanities-indicators",
 "advanced_degree_rate_humanities_ba": 0.40,
 "note": "share of humanities bachelor's recipients who go on to earn an advanced degree, ~40%; verify against the live indicator and record the date",
 "verified_on": "<date>"}
```

- [ ] **Step 2: Write the failing logic tests** `validation/validation_tests.py`:

```python
"""Logic checks for validation/ (no parquet needed).  uv run python -m validation.validation_tests"""
from validation import common as C


def check(name, cond):
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def main():
    check("year_bucket exact", C.year_bucket(2016, [1991, 2001, 2016]) == 2016)
    check("year_bucket +-1", C.year_bucket(2015, [1991, 2001, 2016]) == 2016)
    check("year_bucket outside", C.year_bucket(2010, [1991, 2001, 2016]) is None)
    check("year_bucket nearest wins on tie-free input", C.year_bucket(2002, [2001, 2006]) == 2001)
    s = C.shares([("23", 10), ("54", 5), ("52", 85)])
    check("shares sum", abs(sum(s.values()) - 1.0) < 1e-9)
    check("shares english", abs(s["23"] - 0.10) < 1e-9)
    check("core6 members", set(C.CORE6) == {"05", "16", "23", "24", "38", "54"})
    nces = C.nces_core6_share({"total": 1000, "english": 50, "foreign_lang": 10, "liberal_arts_hum": 20,
                               "phil_rel": 5, "area_ethnic": 5, "socsci_history": 100, "history": None})
    check("nces core6 uses history fallback 0.13", abs(nces - (50 + 10 + 20 + 5 + 5 + 13) / 1000) < 1e-9)
    print("validation logic tests passed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run to verify it fails**: `uv run python -m validation.validation_tests` → `ModuleNotFoundError: validation`.

- [ ] **Step 4: Implement** `validation/__init__.py` (empty) and `validation/common.py`:

```python
"""Shared config for external-benchmark validation (spec P1)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
EDU_PERSON = ROOT / "normalized" / "education_person.parquet"
NCES = ROOT / "reference" / "nces_bachelors_by_field.json"
HI = ROOT / "reference" / "humanities_indicators.json"
OUT = ROOT / "validation" / "results" / "external_benchmarks.json"

# Six CIP families with a one-to-one NCES line (history via the fallback below).
CORE6 = ("05", "16", "23", "24", "38", "54")
NAMED = {"english": "23", "history": "54", "business": "52", "cs": "11"}
HISTORY_SHARE_FALLBACK = 0.13  # history within "social sciences and history"
YEAR_TOLERANCE = 1


def year_bucket(end_year: int | None, targets: list[int]) -> int | None:
    if end_year is None:
        return None
    best = min(targets, key=lambda t: (abs(t - end_year), t))
    return best if abs(best - end_year) <= YEAR_TOLERANCE else None


def shares(rows: list[tuple[str, int]]) -> dict[str, float]:
    tot = sum(n for _, n in rows)
    return {k: (n / tot if tot else 0.0) for k, n in rows}


def nces_core6_share(y: dict) -> float:
    hist = y.get("history")
    if hist is None:
        hist = y["socsci_history"] * HISTORY_SHARE_FALLBACK
    core = y["english"] + y["foreign_lang"] + y["liberal_arts_hum"] + y["phil_rel"] + y["area_ethnic"] + hist
    return core / y["total"]


def load_nces() -> dict:
    return json.loads(NCES.read_text())


def load_hi() -> dict:
    return json.loads(HI.read_text())
```

- [ ] **Step 5: Run logic tests** → pass.

- [ ] **Step 6: Implement** `validation/external_benchmarks.py`:

```python
"""LinkedIn shares vs NCES Table 322.10 and Humanities Indicators (spec P1).

    uv run python -m validation.external_benchmarks

Bachelor's rung = degree_level_pooled = 4 with a non-null end_year; field = cip2_pooled.
Writes validation/results/external_benchmarks.json (committed). Reporting only.
"""
from __future__ import annotations

import json
import subprocess
from datetime import date

import duckdb

from paths import common as PC
from validation import common as C


def _sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=C.ROOT, text=True).strip()
    except Exception:
        return "unknown"


def build() -> dict:
    nces = C.load_nces(); hi = C.load_hi()
    targets = sorted(int(y) for y in nces["years"])
    con = duckdb.connect(); con.execute("PRAGMA threads=8")
    con.create_function("bucket", lambda y: C.year_bucket(y, targets), ["INTEGER"], "INTEGER", null_handling="special")
    rows = con.execute(f"""
        SELECT bucket(end_year) AS yb, cip2_pooled, count(*) AS n
        FROM read_parquet('{C.EDUCATION}')
        WHERE NOT is_duplicate AND degree_level_pooled = 4 AND end_year IS NOT NULL
          AND cip2_pooled IS NOT NULL AND cip2_pooled <> '53'
        GROUP BY 1, 2
    """).fetchall()
    by_year: dict[int, list[tuple[str, int]]] = {}
    for yb, cip2, n in rows:
        if yb is not None:
            by_year.setdefault(yb, []).append((cip2, n))
    out_years = {}
    for y in targets:
        li = C.shares(by_year.get(y, []))
        n = sum(n for _, n in by_year.get(y, []))
        ny = nces["years"][str(y)]
        li_core6 = sum(li.get(c, 0.0) for c in C.CORE6)
        nc_core6 = C.nces_core6_share(ny)
        entry = {"linkedin_n": n, "core6": {"linkedin": li_core6, "nces": nc_core6,
                 "ratio": li_core6 / nc_core6 if nc_core6 else None,
                 "history_estimated": ny.get("history") is None}}
        for name, cip in C.NAMED.items():
            key = "socsci_history" if name == "history" and ny.get("history") is None else name
            nces_share = (ny[key] * (C.HISTORY_SHARE_FALLBACK if key == "socsci_history" else 1)) / ny["total"]
            entry[name] = {"linkedin": li.get(cip, 0.0), "nces": nces_share,
                           "ratio": li.get(cip, 0.0) / nces_share if nces_share else None}
        out_years[str(y)] = entry
    adv = con.execute(f"""
        SELECT avg((highest_degree_level_pooled >= 6)::INT), count(*)
        FROM read_parquet('{C.EDU_PERSON}') WHERE hum_l1_bachelor_pooled_any
    """).fetchone()
    con.close()
    return {"release": {"built": date.today().isoformat(), "git": _sha(),
                        "snapshot_date": PC.SNAPSHOT_DATE, "last_complete_year": PC.LAST_COMPLETE_YEAR},
            "nces_source": nces["source"], "nces_verified_on": nces.get("verified_on"),
            "years": out_years,
            "advanced_degree_rate": {"linkedin_hum_l1_bachelor": adv[0], "n": adv[1],
                                     "humanities_indicators": hi["advanced_degree_rate_humanities_ba"],
                                     "ratio": adv[0] / hi["advanced_degree_rate_humanities_ba"]}}


def main() -> None:
    r = build()
    C.OUT.parent.mkdir(parents=True, exist_ok=True)
    C.OUT.write_text(json.dumps(r, indent=1) + "\n")
    for y, e in r["years"].items():
        print(f"{y}: n={e['linkedin_n']:,} core6 LinkedIn {100*e['core6']['linkedin']:.1f}% "
              f"vs NCES {100*e['core6']['nces']:.1f}% (x{e['core6']['ratio']:.2f})")
    a = r["advanced_degree_rate"]
    print(f"advanced-degree rate, L1 bachelor's: {100*a['linkedin_hum_l1_bachelor']:.1f}% vs HI {100*a['humanities_indicators']:.0f}% (n={a['n']:,})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Implement** `validation/benchmark_checks.py` (data check): loads `C.OUT`; asserts every year has `linkedin_n >= 1000`; every `core6.ratio` in `[0.5, 1.5]`; `advanced_degree_rate.n >= 10000`; prints ok lines.

- [ ] **Step 8: Run** `uv run python -m validation.external_benchmarks` then `uv run python -m validation.benchmark_checks`; record all printed numbers in the notes under P1 "after".

- [ ] **Step 9: Wire Makefile**: add `$(UV) python -m validation.validation_tests` to `test`, `$(UV) python -m validation.benchmark_checks` to `test-data`; add a `benchmarks:` target running the build. Add a line in `reference/README.md` for the two JSON files.

- [ ] **Step 10: Lint, test, commit**: `make lint && make test`; `git add validation reference/*.json reference/README.md Makefile docs/notes/...; git commit -m "feat(validation): NCES 322.10 and Humanities Indicators benchmarks"`.

- [ ] **Step 11: Post-review**: dispatch the post-review subagent (template, `<PX>`=P1, base = the commit before Step 10). Record verdict in notes. If it finds a defect, fix, re-run, amend the notes, commit `fix(validation): ...`.

### Task 3: P2 pre-review

- [ ] **Step 1: Dispatch** pre-review, `<PX>` = P2, files: `edu_clean/apply_degree_level_pooled.py`, `edu_clean/apply_cip_pooled.py:1-80`, `edu_clean/degree_level_rescue.py:1-60`, `build_normalized.py:591-760`, `normalized/mappings/school_ipeds.parquet` + `reference/institution_meta.parquet` schemas. Ask specifically whether the five guards are enough and whether `bachelor_end_year` should stay deterministic-only.
- [ ] **Step 2: Record** verdict in notes.

### Task 4: P2 Imputed bachelor's tier

**Files:**
- Create: `edu_clean/imputed_bachelor.py` (pure predicate pieces), `edu_clean/apply_bachelor_imputed.py`, `edu_clean/imputed_tests.py`
- Modify: `build_normalized.py` (person rollup: `bachelor_imputed_any`; hook the apply into the education section after the CIP apply), `edu_clean/tier_tests.py` (data invariants), `Makefile`, `PIPELINE.md`

**Interfaces:**
- Produces: `edu_clean.imputed_bachelor.school_excluded(school_raw:str|None) -> bool`; `edu_clean.imputed_bachelor.SOURCE = "imputed_bachelor"`; `edu_clean.apply_bachelor_imputed.run(execute:bool) -> dict`.
- Columns: `education.degree_level_source` gains value `'imputed_bachelor'`; `education_person.bachelor_imputed_any: BOOLEAN`.

- [ ] **Step 1: Failing tests** `edu_clean/imputed_tests.py`:

```python
"""Logic checks for the imputed-bachelor tier.  uv run python -m edu_clean.imputed_tests"""
from edu_clean.imputed_bachelor import SOURCE, school_excluded, predicate_sql


def check(name, cond):
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def main():
    for s in ("Lincoln High School", "Coursera", "Udemy", "General Assembly", "Harvard Law School",
              "Stanford Graduate School of Business", "Princeton Theological Seminary",
              "Johns Hopkins School of Medicine", "St. Mary's Preparatory", "Codecademy",
              "Community College of Denver"):
        check(f"excluded: {s}", school_excluded(s))
    for s in ("University of Colorado Boulder", "Oberlin College", "Rutgers University–New Brunswick",
              "The Ohio State University", "Yale University", "School of Visual Arts"):
        check(f"kept: {s}", not school_excluded(s))
    check("None excluded", school_excluded(None))
    check("source constant", SOURCE == "imputed_bachelor")
    sql = predicate_sql("e", "g")
    for frag in ("degree_level_pooled IS NULL", "cip2_pooled <> '53'", "school_excluded", "iclevel", "grad_same_school"):
        check(f"predicate mentions {frag}", frag in sql)
    print("imputed-bachelor logic tests passed")


if __name__ == "__main__":
    main()
```

Note: "Community College of Denver" is excluded because a community college row without a level word is an associate's, not a bachelor's; "School of Visual Arts" is kept (four-year art college).

- [ ] **Step 2: Run** → fails (module missing).

- [ ] **Step 3: Implement** `edu_clean/imputed_bachelor.py`:

```python
"""Pure predicate pieces for the imputed-bachelor tier (spec P2).

A row is imputed to the bachelor's rung when the deterministic parser and the
level jury both found no level, a real field is coded, and the school is a
plausible four-year institution. The tier is propose-only and excludable
through degree_level_source = 'imputed_bachelor'.
"""
from __future__ import annotations

import re

SOURCE = "imputed_bachelor"

# High school, MOOC/bootcamp, and named graduate/professional schools. A row at
# one of these with no level word is NOT a bachelor's.
_EXCLUDE = re.compile(
    r"(high school|highschool|\bhs\b|secondary school|preparatory|prep school|\bprep\b|academy$|"
    r"coursera|udemy|udacity|edx|linkedin learning|lynda|bootcamp|general assembly|codecademy|"
    r"khan academy|pluralsight|"
    r"community college|junior college|technical college|vocational|"
    r"graduate school|school of law|law school|school of medicine|medical school|school of business|"
    r"business school|seminary|divinity school|theological|school of public health|school of nursing|"
    r"dental school|school of dentistry|pharmacy school|veterinary)",
    re.I)


def school_excluded(school_raw: str | None) -> bool:
    if not school_raw or not school_raw.strip():
        return True
    return bool(_EXCLUDE.search(school_raw))


def predicate_sql(e: str, g: str) -> str:
    """SQL boolean over education alias ``e`` joined to ``g`` (per-person
    same-school graduate rows) and the IPEDS level view ``lvl``."""
    return f"""(
        {e}.degree_level_pooled IS NULL
        AND {e}.cip2_pooled IS NOT NULL AND {e}.cip2_pooled <> '53'
        AND NOT school_excluded({e}.school_raw)
        AND coalesce(lvl.iclevel_label, '4yr+') = '4yr+'
        AND {g}.grad_same_school IS NULL
    )"""
```

- [ ] **Step 4: Implement** `edu_clean/apply_bachelor_imputed.py` mirroring `apply_degree_level_pooled.py`: register `school_excluded` as a DuckDB scalar function; build `lvl` as `school_slug → school_ipeds.unitid → institution_meta.iclevel_label`; build `g` as `SELECT linkedin_id, school_raw, TRUE AS grad_same_school FROM education WHERE degree_level_pooled >= 6 GROUP BY 1,2`; rebuild `degree_level_pooled` = `CASE WHEN existing IS NOT NULL THEN existing WHEN <predicate> THEN 4 END`, `degree_level_source` = `CASE WHEN existing source IS NOT NULL THEN it WHEN <predicate> THEN 'imputed_bachelor' END`; assert row count, fingerprint `bit_xor(hash(linkedin_id, idx, degree_level))`, and that no `det`/`jury` row changed. Idempotent: treat existing `'imputed_bachelor'` rows as NULL before recomputing. Manifest `normalized/_bachelor_imputed_manifest.json` with rows imputed, persons gaining a first level, distribution of school patterns. Dry-run default.

- [ ] **Step 5: Draw the blind sample** in the same script under `--sample N` (default 100): `ORDER BY hash(linkedin_id || idx || 'p2salt')` over imputed rows, columns school_raw, degree_raw, field_raw, description (first 200 chars), end_year; write `edu_clean/results/imputed_bachelor_sample.jsonl`.

- [ ] **Step 6: Run** dry-run, then `--execute`, then `uv run python -m edu_clean.rebuild_education_person` after Step 7.

- [ ] **Step 7: Person rollup**: in `build_normalized.write_education_person` `agg` CTE add `coalesce(bool_or(degree_level_source = 'imputed_bachelor'), FALSE) AS bachelor_imputed_any` and select it in the final SELECT after `hum_l1_bachelor_pooled_any`. Hook: find where `build_normalized` runs the pooled applies (`grep -n apply_cip_pooled build_normalized.py`) and call `apply_bachelor_imputed.run(execute=True)` immediately after the CIP apply.

- [ ] **Step 8: Data invariants** appended to `edu_clean/tier_tests.py` as `check_imputed()`: every `'imputed_bachelor'` row has `degree_level IS NULL`, `cip2_pooled <> '53'`, `degree_level_pooled = 4`; count matches the manifest.

- [ ] **Step 9: Measure after** (notes): rows imputed, persons gaining first level, `hum_l1_bachelor_pooled_any` before/after, `highest_degree_level_pooled` coverage before/after.

- [ ] **Step 10: Makefile/PIPELINE.md**: add `edu_clean.imputed_tests` to `test`; document the tier in PIPELINE.md's jury table row order (degree jury → CIP → imputed bachelor → person).

- [ ] **Step 11: Lint, test, commit** `feat(edu): imputed-bachelor tier (propose-only, excludable)`.

- [ ] **Step 12: Post-review** with the sample file; gate 0.90. If below, re-run with `--execute --unland` (implement: rebuild without the tier) and record "propose-only".

### Task 5: P3 pre-review

- [ ] **Step 1: Dispatch** pre-review, `<PX>` = P3, files: `edu_clean/final_hybrid.py:424-454` (`_field_cip_lookup`), `cleanlib/text.py:35-63`, `normalized/mappings/edu_field.parquet` (method distribution), `reference/cip_codes.csv` head, the compound-string evidence: `SELECT value, canonical_id, method FROM mapping WHERE lower(value) IN ('history and political science', 'english/journalism', 'biology, chemistry minor')` (they resolve to `raw`/`typo`, i.e. no CIP today).
- [ ] **Step 2: Record** verdict.

### Task 6: P3 Co-majors and minors

**Files:**
- Create: `edu_clean/comajors.py`, `edu_clean/run_comajors.py`, `edu_clean/apply_comajors.py`, `edu_clean/comajor_tests.py`
- Modify: `build_normalized.py` (person rollup columns; hook the apply after the imputed apply), `edu_clean/tier_tests.py`, `Makefile`, `PIPELINE.md`

**Interfaces:**
- Produces: `edu_clean.comajors.split_field(field_raw:str|None) -> Split` where `Split` is a dataclass `status: str` (`single|split|unresolved|empty`), `components: list[Component]` with `Component(text:str, role:str, cip:str|None)` and role in `major|minor|concentration`; helper `primary(split) -> str|None`, `secondary(split) -> str|None`, `minor(split) -> str|None`.
- Mapping `normalized/mappings/edu_field_components.parquet`: `value, status, components (JSON), primary_cip, secondary_cip, minor_cip, n_majors, n_minors`.
- Education columns: `cip_secondary, cip2_secondary, minor_cip, minor_cip2, field_components_n, comajor_source` (`'split'|'conflict'|NULL`).
- Person columns: `double_major_any, hum_l1_comajor_any, minor_hum_l1_any`.

- [ ] **Step 1: Failing tests** `edu_clean/comajor_tests.py`:

```python
"""Logic checks for the co-major splitter.  uv run python -m edu_clean.comajor_tests"""
import csv
from pathlib import Path

from edu_clean.comajors import primary, secondary, minor, split_field

ROOT = Path(__file__).resolve().parent.parent


def check(name, cond):
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def cip2(code):
    return code[:2] if code else None


def main():
    s = split_field("History and Political Science")
    check("h&ps splits", s.status == "split")
    check("h&ps primary 54", cip2(primary(s)) == "54")
    check("h&ps secondary 45", cip2(secondary(s)) == "45")
    s = split_field("Biology, Chemistry Minor")
    check("bio/chem status", s.status == "split")
    check("bio primary 26", cip2(primary(s)) == "26")
    check("chem minor 40", cip2(minor(s)) == "40" and secondary(s) is None)
    s = split_field("English/Journalism")
    check("eng/journ", s.status == "split" and cip2(primary(s)) == "23" and cip2(secondary(s)) == "09")
    s = split_field("Double Major in History and French")
    check("double major", s.status == "split" and cip2(primary(s)) == "54" and cip2(secondary(s)) == "16")
    s = split_field("Business Administration, Concentration in Finance")
    check("concentration role", s.status == "split" and [c.role for c in s.components] == ["major", "concentration"])
    check("concentration is not a secondary major", secondary(s) is None)
    s = split_field("Psychology (Minor in Sociology)")
    check("paren minor", s.status == "split" and cip2(minor(s)) == "45")
    for whole in ("Business Administration and Management, General", "English Language and Literature, General",
                  "Criminal Justice and Corrections", "Kinesiology and Exercise Science",
                  "Logistics, Materials, and Supply Chain Management", "History"):
        check(f"single: {whole}", split_field(whole).status == "single")
    check("empty", split_field("").status == "empty" and split_field(None).status == "empty")
    check("unresolved", split_field("study of people and stuff").status in ("unresolved", "single"))
    # every CIP 2020 title is ONE field
    n = bad = 0
    with (ROOT / "reference" / "cip_codes.csv").open() as fh:
        for row in csv.DictReader(fh):
            title = row.get("title") or row.get("CIPTitle") or next(v for k, v in row.items() if "title" in k.lower())
            n += 1
            if split_field(title).status == "split":
                bad += 1
                if bad <= 10:
                    print("   SPLIT CIP TITLE:", title)
    check(f"no CIP title splits ({n} titles, {bad} split)", bad == 0)
    print("comajor logic tests passed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run** → fails.

- [ ] **Step 3: Implement** `edu_clean/comajors.py`:

```python
"""Co-major / minor / concentration splitter over the raw field string (spec P3).

Splitting LOGIC is ported from the sibling build; resolution of each component
goes through the repo's own field->CIP lookup (final_hybrid._field_cip_lookup),
so no second taxonomy exists. Precision-first:

  1. whole string resolves -> ONE field (never split a CIP title);
  2. otherwise split on explicit markers/separators; every kept component must
     itself resolve; fewer than two resolved components -> no split.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from edu_clean import final_hybrid as FH

_MINOR_MARK = re.compile(r"\b(?:with\s+(?:a\s+)?)?minors?\b\s*(?:\bin\b|\bof\b|:|;|-|=)?\s*", re.I)
_MAJOR_MARK = re.compile(r"\b(?:double|dual|triple|second|first|primary)?\s*majors?(?:ing)?\b\s*(?:\bin\b|\bof\b|:|;|-|=)?\s*", re.I)
_CONC_MARK = re.compile(
    r"\b(?:with\s+(?:a\s+)?)?(?:concentrations?|emphasis|specializations?|specialisations?|"
    r"focus(?:ed|ing)?|tracks?|options?|specialty|areas? of study|studies in)\b\s*"
    r"(?:\bin\b|\bon\b|\bof\b|:|;|-|=)?\s*", re.I)
_PAREN = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")
_SEP = re.compile(r"\s*(?:[;/|,]|\band\b|&)\s*", re.I)


@dataclass
class Component:
    text: str
    role: str  # major | minor | concentration
    cip: str | None


@dataclass
class Split:
    status: str  # single | split | unresolved | empty
    components: list[Component] = field(default_factory=list)


def _resolve(text: str) -> str | None:
    t = text.strip(" .,;:-/")
    return FH._field_cip_lookup(t) if t else None


def _pieces(text: str) -> list[str]:
    return [p for p in (x.strip(" .,;:-") for x in _SEP.split(text)) if p]


def split_field(field_raw: str | None) -> Split:
    if not field_raw or not field_raw.strip():
        return Split("empty")
    whole = _resolve(field_raw)
    if whole:
        return Split("single", [Component(field_raw.strip(), "major", whole)])
    text = field_raw
    minors: list[str] = []
    concs: list[str] = []

    def paren(m):
        inner = m.group(1).strip()
        if not inner:
            return " "
        if _MINOR_MARK.search(inner):
            rest = _MINOR_MARK.sub(" ", inner).strip(" ,;:-")
            if rest:
                minors.append(rest)
            return " ; "
        if _CONC_MARK.search(inner):
            rest = _CONC_MARK.sub(" ", inner).strip(" ,;:-")
            if rest:
                concs.append(rest)
            return " ; "
        return " ; " + inner + " ; "
    text = _PAREN.sub(paren, text)
    m = _MINOR_MARK.search(text)
    if m:
        head, rest = text[:m.start()], text[m.end():]
        if rest.strip(" ,;:-/"):
            minors.extend(_pieces(_MINOR_MARK.sub(" ; ", rest)))
        else:  # trailing "<x> minor": last segment of the head is the minor
            parts = _pieces(head)
            if parts:
                minors.append(parts[-1]); head = " ; ".join(parts[:-1])
        text = head
    m = _CONC_MARK.search(text)
    if m:
        concs.extend(_pieces(text[m.end():])); text = text[:m.start()]
    text = _MAJOR_MARK.sub(" ; ", text)
    majors = _pieces(text)
    comps = [Component(t, "major", _resolve(t)) for t in majors]
    comps += [Component(t, "concentration", _resolve(t)) for t in concs]
    comps += [Component(t, "minor", _resolve(t)) for t in minors]
    kept = [c for c in comps if c.cip]
    if not kept or not any(c.role == "major" for c in kept):
        return Split("unresolved", comps)
    if len(kept) < 2:
        return Split("unresolved", comps)
    # dedupe on cip2, majors first
    seen: set[str] = set(); out: list[Component] = []
    for c in kept:
        if c.cip[:2] in seen:
            continue
        seen.add(c.cip[:2]); out.append(c)
    if len(out) < 2:
        return Split("unresolved", comps)
    return Split("split", out)


def primary(s: Split) -> str | None:
    return next((c.cip for c in s.components if c.role == "major" and c.cip), None)


def secondary(s: Split) -> str | None:
    majors = [c.cip for c in s.components if c.role == "major" and c.cip]
    return majors[1] if len(majors) > 1 else None


def minor(s: Split) -> str | None:
    return next((c.cip for c in s.components if c.role == "minor" and c.cip), None)
```

- [ ] **Step 4: Run tests**; iterate on the regexes until every listed case and the CIP-title sweep pass. The CIP sweep is the load-bearing regression: if a title splits, it means both halves resolve; that is only possible when `_field_cip_lookup` fails on the whole title, so first check the whole-title lookup (case/punctuation) before touching separators.

- [ ] **Step 5: Implement** `edu_clean/run_comajors.py`: iterate every `value` in `normalized/mappings/edu_field.parquet`, call `split_field`, write `normalized/mappings/edu_field_components.parquet` (columns per Interfaces; `components` as JSON string). Multiprocessing with `Pool(16)` over chunks of 20k. Print status distribution, weighted by row counts from `education.parquet` (join on `field_raw`). Write `edu_clean/results/comajors_stats.json`.

- [ ] **Step 6: Implement** `edu_clean/apply_comajors.py` mirroring `apply_degree_level_pooled.py`: join `education.field_raw = mapping.value`; append columns; `comajor_source = CASE WHEN status='split' AND (cip2_pooled IS NULL OR substr(primary_cip,1,2) = cip2_pooled) THEN 'split' WHEN status='split' THEN 'conflict' END`; secondary/minor columns populated only when `comajor_source='split'`; fingerprint `bit_xor(hash(linkedin_id, idx, cip_code, degree_level))` asserted; manifest `normalized/_comajors_manifest.json`; `--sample 100` writes `edu_clean/results/comajors_sample.jsonl` (field_raw, components, cip_code, cip2_pooled).

- [ ] **Step 7: Person rollup** in `write_education_person` `agg`: join `reference/cip_humanities.parquet` twice (`h2 ON h2.cip_code = e.cip_secondary`, `hm ON hm.cip_code = e.minor_cip`; check the column name for the L1 flag in that parquet first with `DESCRIBE`) and add
  `coalesce(bool_or(cip2_secondary IS NOT NULL AND coalesce(degree_level_pooled, degree_level) = 4), FALSE) AS double_major_any`,
  `coalesce(bool_or(h2.<l1flag> AND coalesce(degree_level_pooled, degree_level) = 4), FALSE) AS hum_l1_comajor_any`,
  `coalesce(bool_or(hm.<l1flag>), FALSE) AS minor_hum_l1_any`. Hook the apply after the imputed apply in the education section.

- [ ] **Step 8: Run** `run_comajors`, `apply_comajors --execute --sample 100`, `rebuild_education_person`. Measure after: rows with `comajor_source='split'`, conflicts, persons with `double_major_any`, share among `hum_l1_bachelor_pooled_any`, top 15 co-major CIP2 pairs for L1.

- [ ] **Step 9: Data invariants** in `tier_tests.check_comajors()`: `cip_secondary` never equals `cip_code`; `comajor_source IS NULL` ⇒ all secondary columns NULL; conflict rows carry no secondary.

- [ ] **Step 10: Makefile/PIPELINE.md**; lint; test; commit `feat(edu): co-major and minor extraction (propose-only)`.

- [ ] **Step 11: Post-review** with the sample; gate 0.90; record.

### Task 7: P4 pre-review

- [ ] **Step 1: Dispatch** pre-review, `<PX>` = P4, files: `career_clean/run_soc_jury.py:1-80`, `career_clean/results/soc_calibration.json`, `career_clean/results/soc_gold.parquet` schema, `build_normalized.py:930-1000`, `career_clean/soc_data_checks.py`, and the sibling's family → SOC anchor table copied into the prompt (the FAMILIES dict). Ask: is a per-family 2-digit anchor honest for every family; which families should be forbidden from landing regardless of the gate; is 30 gold roles enough.
- [ ] **Step 2: Record** verdict.

### Task 8: P4 Occupation-family tier

**Files:**
- Create: `career_clean/families/__init__.py`, `career_clean/families/taxonomy.py` (verbatim from the sibling's `pipeline/taxonomy.py` FAMILIES + SENIORITY only), `career_clean/families/classify.py` (verbatim `classify_titles.py`, imports changed), `career_clean/families/family_tests.py` (verbatim tests, imports changed, `main()` prints a pass line), `career_clean/run_families.py`, `career_clean/family_data_checks.py`
- Modify: `build_normalized.py` (mapping path `title_family`, `OPTIONAL_MAPPINGS`, join, three columns, pooled precedence), `career_clean/soc_data_checks.py` (family rows: det and jury null), `Makefile`, `PIPELINE.md`

**Interfaces:**
- `career_clean.families.classify.classify_title(s:str) -> {'family','seniority','flags','confidence'}` (unchanged API).
- `career_clean.families.taxonomy.FAMILIES: dict[code -> (label, group, soc_major|None)]`, `SENIORITY: list[str]`, `NEVER_LAND = {"student","intern","volunteer_board","not_working","unclassified"}`.
- Mapping `normalized/mappings/title_family.parquet`: `value, family, seniority9, flags (VARCHAR[]), confidence, soc_major_anchor, landable (BOOLEAN)`.
- Gate file `career_clean/results/family_gate.json`: per family `{n_gold, precision, landable}` + `bar`, `min_gold`.
- career_steps columns: `title_family, title_family_confidence, title_seniority9`; `occupation_source` gains `'family'`.

- [ ] **Step 1: Port files.** `cp` the three sibling files; in `classify.py` replace `from taxonomy import FAMILIES, SENIORITY` with `from career_clean.families.taxonomy import FAMILIES, SENIORITY` and delete the `sys.path.insert`; same in `family_tests.py` (`from career_clean.families.classify import classify_title, normalize`). Add `NEVER_LAND` to `taxonomy.py`. Run `uv run python -m career_clean.families.family_tests` → must report 631 assertions passing (the port is verbatim; a failure here is an import or lint change, not a rule change).

- [ ] **Step 2: Failing driver test** — add to `family_tests.py`:

```python
from career_clean.families.taxonomy import FAMILIES, NEVER_LAND
from transition_network.common import SOC_MAJOR
for code, (_label, _grp, soc) in FAMILIES.items():
    assert soc is None or soc in SOC_MAJOR, f"anchor {soc} for {code} is not a SOC major"
assert NEVER_LAND <= set(FAMILIES)
```

- [ ] **Step 3: Implement** `career_clean/run_families.py`:

```python
"""Occupation-family tier driver (spec P4).

    uv run python -m career_clean.run_families classify   # -> normalized/mappings/title_family.parquet
    uv run python -m career_clean.run_families gate       # score anchors vs soc_gold; set landable

classify runs the ported rules classifier over every distinct raw title value in
normalized/mappings/career_title.parquet. gate scores each family's SOC-major anchor
against career_clean/results/soc_gold.parquet (role_display is the string classified)
and marks a family landable when precision >= BAR on >= MIN_GOLD roles at
confidence 'high'. Non-occupation families never land.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from career_clean.families.classify import classify_title
from career_clean.families.taxonomy import FAMILIES, NEVER_LAND

ROOT = Path(__file__).resolve().parent.parent
TITLES = ROOT / "normalized" / "mappings" / "career_title.parquet"
OUT = ROOT / "normalized" / "mappings" / "title_family.parquet"
GOLD = ROOT / "career_clean" / "results" / "soc_gold.parquet"
GATE = ROOT / "career_clean" / "results" / "family_gate.json"
BAR = 0.85
MIN_GOLD = 30
CHUNK = 40_000


def _work(vals):
    out = []
    for v in vals:
        r = classify_title(v or "")
        out.append((v, r["family"], r["seniority"], r["flags"], r["confidence"], FAMILIES[r["family"]][2]))
    return out


def classify() -> None:
    con = duckdb.connect()
    vals = [r[0] for r in con.execute(f"SELECT value FROM read_parquet('{TITLES}')").fetchall()]
    chunks = [vals[i:i + CHUNK] for i in range(0, len(vals), CHUNK)]
    rows = []
    with Pool(16) as pool:
        for part in pool.imap(_work, chunks, chunksize=1):
            rows.extend(part)
    landable = _landable_from_gate() if GATE.exists() else {}
    t = pa.table({
        "value": [r[0] for r in rows], "family": [r[1] for r in rows],
        "seniority9": [r[2] for r in rows], "flags": pa.array([r[3] for r in rows], pa.list_(pa.string())),
        "confidence": [r[4] for r in rows], "soc_major_anchor": [r[5] for r in rows],
        "landable": [bool(landable.get(r[1], False)) and r[4] == "high" for r in rows],
    })
    pq.write_table(t, OUT, compression="zstd")
    print(f"wrote {OUT} ({t.num_rows:,} titles)")


def _landable_from_gate() -> dict[str, bool]:
    g = json.loads(GATE.read_text())
    return {k: v["landable"] for k, v in g["families"].items()}


def gate() -> None:
    con = duckdb.connect()
    gold = con.execute(f"SELECT role_display, gold_major FROM read_parquet('{GOLD}') WHERE gold_major IS NOT NULL").fetchall()
    per: dict[str, list[int]] = {}
    for disp, major in gold:
        r = classify_title(disp or "")
        if r["confidence"] != "high":
            continue
        fam = r["family"]; anchor = FAMILIES[fam][2]
        if anchor is None:
            continue
        per.setdefault(fam, []).append(int(anchor == major))
    fams = {}
    for fam, hits in sorted(per.items()):
        n = len(hits); p = sum(hits) / n
        fams[fam] = {"n_gold": n, "precision": round(p, 4),
                     "landable": (n >= MIN_GOLD and p >= BAR and fam not in NEVER_LAND)}
    for fam in FAMILIES:
        fams.setdefault(fam, {"n_gold": 0, "precision": None, "landable": False})
    GATE.write_text(json.dumps({"generated": date.today().isoformat(), "bar": BAR, "min_gold": MIN_GOLD,
                                "families": fams}, indent=1) + "\n")
    for fam, v in sorted(fams.items(), key=lambda kv: -(kv[1]["n_gold"])):
        print(f"{fam:24s} n={v['n_gold']:4d} p={v['precision']}  {'LAND' if v['landable'] else '-'}")
    # re-stamp landable on the mapping if it exists
    if OUT.exists():
        classify()


if __name__ == "__main__":
    {"classify": classify, "gate": gate}[sys.argv[1]]()
```

- [ ] **Step 4: Run** `classify` then `gate` (gate re-runs classify to stamp `landable`). Record the per-family table in the notes.

- [ ] **Step 5: build_normalized**: in `build_mappings` add `"title_family": mappings / "title_family.parquet"`; `OPTIONAL_MAPPINGS = frozenset({"role_soc_jury", "title_family"})`; in `write_career_steps` add after the `rsj` join:

```sql
LEFT JOIN {_optional_mapping_relation(mappings["title_family"], "value VARCHAR, family VARCHAR, seniority9 VARCHAR, confidence VARCHAR, soc_major_anchor VARCHAR, landable BOOLEAN")} tf
  ON s.title IS NOT DISTINCT FROM tf.value
```

and columns (after `occupation_source`):

```sql
tf.family AS title_family,
tf.confidence AS title_family_confidence,
tf.seniority9 AS title_seniority9,
```

and change the pooled pair to:

```sql
CASE WHEN starts_with(occupation.canonical_id, 'soc:') THEN substr(occupation.canonical_id, 5, 2)
     WHEN rsj.soc_major IS NOT NULL THEN rsj.soc_major
     WHEN coalesce(tf.landable, FALSE) THEN tf.soc_major_anchor END AS occupation_major_pooled,
CASE WHEN starts_with(occupation.canonical_id, 'soc:') THEN 'det'
     WHEN rsj.soc_major IS NOT NULL THEN 'jury'
     WHEN coalesce(tf.landable, FALSE) THEN 'family' END AS occupation_source,
```

Note: `_optional_mapping_relation` derives `NULL::TYPE` from `schema.split(",")` entries of the form `name TYPE`; `flags` is omitted from that relation on purpose (list type), we do not read it in the build.

- [ ] **Step 6: Rebuild** `make normalize-career` (75 s) then `uv run --with numpy python normalization_regression_checks.py`.

- [ ] **Step 7: Data checks** `career_clean/family_data_checks.py`: family rows have `occupation_code IS NULL` and no jury match; every landed family is `landable` in the gate file; coverage printed (`occupation_major_pooled` non-null share before → after; the before value is in the notes baseline). Extend `soc_data_checks.py` so the `occupation_source` enum check accepts `'family'`.

- [ ] **Step 8: Blind sample**: `SELECT title_raw, company_raw, l1, title_family, occupation_major_pooled FROM career_steps JOIN step_industry ... WHERE occupation_source='family' ORDER BY hash(...) LIMIT 100` → `career_clean/results/family_sample.jsonl`.

- [ ] **Step 9: Makefile** (`family_tests` in `test`, `family_data_checks` in `test-data`, `families:` target running classify+gate), PIPELINE.md jury table row; lint; test; commit `feat(career): occupation-family tier (rules, gated per family)`.

- [ ] **Step 10: Post-review**; gate: per-family file plus sample ≥ 0.85; families the reviewer rejects get `landable=false` via an `EXCLUDE` set in `run_families.gate` and a rebuild.

### Task 9: P5 pre-review

- [ ] **Step 1: Dispatch** pre-review, `<PX>` = P5, files: `docs/audits/2026-09-13-journey-data-capacity-audit.md` §2.10, `build_normalized.py:930-1000`, `industry/taxonomy.py` L1/L2 for EDU and PRO, the measured title table (Vice President 26,016 rows → 11-1011; Principal 20,792 rows uncoded; Partner 14,511 uncoded; Of Counsel 1,208 → 23-1011). Ask whether 11-1021 is the right home for vice presidents and whether `assistant manager` seniority deserves a propose-only column.
- [ ] **Step 2: Record** verdict.

### Task 10: P5 Employer-keyed overrides

**Files:**
- Create: `career_clean/overrides.py`, `career_clean/run_overrides.py`, `career_clean/override_tests.py`
- Modify: `build_normalized.py` (mapping `career_occupation_override`, optional; join on the four step keys; `occupation_code_pooled`; precedence), `career_clean/soc_data_checks.py`, `Makefile`, `PIPELINE.md`

**Interfaces:**
- `career_clean.overrides.override(title_raw, seniority_level, role_canonical, industry_l1, industry_l2) -> Override | None`, `Override(occupation_code:str, soc_major:str, reason:str)`.
- Mapping `normalized/mappings/career_occupation_override.parquet`: `source_table, linkedin_id, experience_idx, position_idx, occupation_code_override, soc_major_override, reason`.
- career_steps: `occupation_code_pooled` (override > det), `occupation_source` gains `'override'` and precedence override > det > jury > family.

- [ ] **Step 1: Failing tests** `career_clean/override_tests.py`:

```python
from career_clean.overrides import override


def check(name, cond):
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def main():
    o = override("Vice President", "vice", "president", "FIN", "FIN.BNK")
    check("VP -> 11-1021", o and o.occupation_code == "11-1021" and o.reason == "vice_president")
    o = override("Senior Vice President, Marketing", "senior,vice", "marketing president", "TEC", None)
    check("SVP with dept still VP", o and o.occupation_code == "11-1021")
    check("President untouched", override("President", "", "president", "FIN", None) is None)
    o = override("Principal", None, None, "EDU", "EDU.K12")
    check("K-12 principal", o and o.occupation_code == "11-9032" and o.reason == "k12_principal")
    o = override("Assistant Principal", "principal", "assistant", "EDU", "EDU.K12")
    check("assistant principal", o and o.occupation_code == "11-9032")
    check("principal at higher ed untouched", override("Principal", None, None, "EDU", "EDU.HED") is None)
    o = override("Principal", None, None, "PRO", "PRO.CONSL")
    check("firm principal", o and o.occupation_code == "11-1021" and o.reason == "firm_principal")
    check("Principal Software Engineer untouched", override("Principal Software Engineer", "principal", "engineer software", "TEC", None) is None)
    o = override("Partner", "", "partner", "PRO", "PRO.LEGAL")
    check("law partner", o and o.occupation_code == "23-1011" and o.reason == "law_firm_partner")
    o = override("Associate", None, None, "PRO", "PRO.LEGAL")
    check("law associate", o and o.occupation_code == "23-1011")
    check("Associate at a bank untouched", override("Associate", None, None, "FIN", "FIN.BNK") is None)
    check("Partner at consulting untouched", override("Partner", "", "partner", "PRO", "PRO.CONSL") is None)
    check("none industry, VP still fires", override("VP", "vice", "president", None, None) is not None)
    print("override tests passed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run** → fails.

- [ ] **Step 3: Implement** `career_clean/overrides.py`:

```python
"""Employer-keyed occupation overrides (spec P5). Pure rule table; row-level
mapping built by run_overrides.py. Every rule names a reason so a consumer can
exclude it."""
from __future__ import annotations

import re
from dataclasses import dataclass

from cleanlib.text import normalize


@dataclass(frozen=True)
class Override:
    occupation_code: str
    soc_major: str
    reason: str


_VP = re.compile(r"^(?:(?:senior|executive|associate|assistant|regional|group|first|corporate|global|area|divisional)\s+)*"
                 r"(?:vice president|vp|svp|evp|avp)\b")
_PRINCIPAL = re.compile(r"^(?:assistant |associate |vice |interim |acting |school )?principal$")
_LAW_TITLES = {"partner", "managing partner", "senior partner", "equity partner", "junior partner",
               "name partner", "founding partner", "associate", "senior associate", "junior associate",
               "of counsel", "counsel", "shareholder", "member", "associate attorney"}


def override(title_raw, seniority_level, role_canonical, industry_l1, industry_l2) -> Override | None:
    t = normalize(title_raw)
    if not t:
        return None
    toks = set((seniority_level or "").split(","))
    if _VP.match(t) or ("vice" in toks and role_canonical == "president"):
        return Override("11-1021", "11", "vice_president")
    if _PRINCIPAL.match(t):
        if industry_l2 == "EDU.K12" or (industry_l1 == "EDU" and industry_l2 in (None, "EDU")):
            return Override("11-9032", "11", "k12_principal")
        if industry_l1 in ("PRO", "FIN", "TEC", "RE"):
            return Override("11-1021", "11", "firm_principal")
        return None
    if t in _LAW_TITLES and industry_l2 == "PRO.LEGAL":
        return Override("23-1011", "23", "law_firm_partner")
    return None
```

- [ ] **Step 4: Run tests** → pass (adjust `_VP` so "President" alone never matches; "VP" normalizes to "vp").

- [ ] **Step 5: Implement** `career_clean/run_overrides.py`: DuckDB join `career_steps` × `industry/results/step_industry.parquet` on `(source_table, linkedin_id, experience_idx, position_idx)`; pre-filter candidates in SQL (`lower(title_raw)` matching the VP/principal/law vocab OR `seniority_level LIKE '%vice%'`) so Python only sees ~300k rows; apply `override`; write the mapping parquet; print counts per reason; write `career_clean/results/overrides_stats.json`; `--sample 50` per reason → `career_clean/results/override_sample.jsonl`.

- [ ] **Step 6: build_normalized**: mapping key `career_occupation_override` (optional); join `ov` on the four keys like `fc`; add `coalesce(ov.occupation_code_override, CASE WHEN starts_with(occupation.canonical_id,'soc:') THEN substr(occupation.canonical_id,5) END) AS occupation_code_pooled`; prepend `WHEN ov.soc_major_override IS NOT NULL THEN ov.soc_major_override` / `'override'` to the pooled-major CASEs.

- [ ] **Step 7: Rebuild** `make normalize-career`; regression checks; extend `soc_data_checks.py`: override rows carry `occupation_code_pooled = override`; `occupation_source` enum includes `override`; `occupation_code_pooled = occupation_code` wherever no override.

- [ ] **Step 8: Measure after**: rows per reason; steps on 11-1011 before/after; count of the audit's "Chief Executives modal" symptom (11-1011 share of management steps among L1 persons) before/after.

- [ ] **Step 9: Makefile/PIPELINE.md**; lint; test; commit `feat(career): employer-keyed occupation overrides (VP, principal, law-firm titles)`.

- [ ] **Step 10: Post-review** with the per-reason sample; reasons under 0.90 removed and rebuilt.

### Task 11: P6 pre-review

- [ ] **Step 1: Dispatch** pre-review, `<PX>` = P6, files: `FOUNDATION.md` §1.2-1.3, `docs/audits/2026-09-13-journey-data-capacity-audit.md` §2.1, §2.11, §6, `portal/common.py:120-160`, `cohorts/profiles.parquet` + `paths/steps.parquet` schemas, `cohorts/common.py`. Ask: does the person table duplicate `cohorts/profiles.parquet`, and if so what should be the single source; is carrying both axes without coalescing enough; is the suppression rule right.
- [ ] **Step 2: Record** verdict.

### Task 12: P6 Person summary and metrics cube v0

**Files:**
- Create: `persons/__init__.py`, `persons/common.py`, `persons/build_person.py`, `persons/build_metrics.py`, `persons/person_tests.py`, `persons/person_checks.py`, `persons/README.md`, `persons/results/.gitkeep`
- Modify: `Makefile` (`persons` target; `test`, `test-data`), `scripts/refresh_downstream.sh` (stage after archetypes; `N_STAGES` +1), `scripts/check_freshness.py` (stage), `.gitignore` (`/persons/*.parquet`, `/persons/results/tables/`), `PIPELINE.md`

**Interfaces:**
- `persons.common`: `STAGES = [(0,2,"0-2"),(3,5,"3-5"),(6,10,"6-10"),(11,20,"11-20"),(21,999,"21+")]`, `stage(years:int|None) -> str|None`, `attainment(seniority_level:str|None) -> dict(manager_plus,director_plus,vp_plus)` using `paths.common.SENIORITY_RANK` (≥6, ≥7, ≥8), `entropy(counts:list[int]) -> float`, `cover80(counts) -> int`, `top3(counts) -> float`, `suppress(cells:list[tuple[str,int]], floor:int) -> tuple[list, int]`.
- Outputs: `persons/person.parquet` (columns per spec P6), `persons/results/metrics.json`, `persons/results/tables/*.csv`, `persons/_manifest.json`.

- [ ] **Step 1: Failing tests** `persons/person_tests.py`:

```python
from persons import common as C


def check(name, cond):
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def main():
    check("stage 0", C.stage(0) == "0-2"); check("stage 5", C.stage(5) == "3-5")
    check("stage 10", C.stage(10) == "6-10"); check("stage 20", C.stage(20) == "11-20")
    check("stage 40", C.stage(40) == "21+"); check("stage None", C.stage(None) is None)
    check("stage negative", C.stage(-1) is None)
    a = C.attainment("senior,vice")
    check("vp attainment", a == {"manager_plus": True, "director_plus": True, "vp_plus": True})
    check("manager only", C.attainment("manager") == {"manager_plus": True, "director_plus": False, "vp_plus": False})
    check("empty", C.attainment("") == {"manager_plus": False, "director_plus": False, "vp_plus": False})
    check("entropy uniform", abs(C.entropy([1, 1, 1, 1]) - 1.386294) < 1e-5)
    check("entropy single", C.entropy([7]) == 0.0)
    check("cover80", C.cover80([50, 30, 10, 10]) == 2)
    check("top3", abs(C.top3([50, 30, 10, 10]) - 0.9) < 1e-9)
    kept, n_sup = C.suppress([("a", 12), ("b", 9), ("c", 10)], 10)
    check("suppress", kept == [("a", 12), ("c", 10)] and n_sup == 1)
    print("persons logic tests passed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run** → fails. **Step 3: Implement** `persons/common.py` per the interface (entropy in nats with `math.log`; `cover80` = smallest k with cumulative share ≥ 0.8 on descending counts; `suppress` keeps cells with n ≥ floor and returns the count dropped). **Step 4: tests pass.**

- [ ] **Step 5: Implement** `persons/build_person.py` (DuckDB, `PRAGMA threads=16`). Sources: `normalized/education.parquet` (NOT is_duplicate), `normalized/education_person.parquet`, `normalized/career_steps.parquet`, `paths/steps.parquet`, `industry/results/step_industry.parquet`, `reference/cip_humanities.parquet`, `reference/institution_meta.parquet` + `normalized/mappings/school_ipeds.parquet`. CTEs:
  - `bach`: per person the bachelor-rung row (`coalesce(degree_level_pooled, degree_level) = 4`), ordered `degree_level_source = 'det' first, end_year ASC NULLS LAST, idx`; carry `cip_code, cip2, cip2_pooled, cip_source, degree_level_source, end_year, humanities_field_group_pooled, nha_level, nha_level_pooled, cip2_secondary, minor_cip2, school_slug`.
  - `grad`: per person flags from rows with `coalesce(degree_level_pooled, degree_level) >= 6`: `has_master` (=6), `has_doctorate` (=7 and degree_type NOT IN law/medicine/dental), `has_jd` (degree_type='law'), `has_mba` (degree_type='business_admin' AND level 6), `has_md_prof` (degree_type IN medicine/dental), `has_med` (degree_type='education' AND level 6), `has_msw` (degree_type='social_work' AND level 6); `has_grad_degree` = any.
  - `steps`: from `paths/steps.parquet` `WHERE datable AND NOT bad_negative_duration AND NOT bad_future_start`, joined to `career_steps` on `(source_table, linkedin_id, experience_idx, position_idx)` for `occupation_major_pooled, occupation_code_pooled, occupation_source, title_family, role_display, company_canonical_id, location_us_state, is_current, start_year` and to `step_industry` for `l1`.
  - `first`: earliest primary (`NOT is_concurrent_secondary` if that column exists in steps; else all) step by `start_dt`.
  - `cur`: `is_ongoing` steps, one per person by `seniority_score DESC NULLS LAST, start_dt DESC`.
  - `agg`: `n_steps, n_employers, entry_year = min(year(start_dt))`, attainment via `max` over `seniority_ordinal >= 6/7/8` (use `paths/steps.seniority_ordinal`), `ever_founder_owner = bool_or(employment_type IN ('business_owner','self_employed'))`.
  - final SELECT one row per `linkedin_id` from `education_person` (left joins), computing `career_years_entry = LAST_COMPLETE_YEAR - entry_year`, `career_years_grad = LAST_COMPLETE_YEAR - bachelor_end_year` (det rung), stages via a SQL CASE mirroring `common.stage`, `hum_l1_bachelor = bach.nha_level_pooled = 1`, `hum_l2_bachelor = bach.nha_level_pooled IN (1,2)`, `hum_l3_bachelor = IN (1,2,3)`, `double_major_any`, `hum_l1_comajor_any`, `minor_hum_l1_any` from education_person, `inst_control_label`, `inst_state` from education_person. Write `persons/person.parquet` via tmp+replace; `persons/_manifest.json` with row count, timings, input mtimes, git SHA.

- [ ] **Step 6: Implement** `persons/build_metrics.py`: membership table `M(linkedin_id, g)` for `all`, `tier:l1|l2|l3`, `group:<bachelor_field_group>`, `cip2:<code>` (n ≥ 300); one SQL per metric grouped by `g`, aggregated in Python with `common.suppress` applied to every categorical panel (floor `portal.common.MIN_SUPPORT`) and `suppressed_cells` recorded per panel. Panels: `basic` (n, n_bachelor_year, n_entry_year, grad-degree rates, attainment rates, double_major, bachelor_imputed share); `cur_soc_major`, `cur_family`, `first_soc_major`, `cur_industry_l1`, `cur_state`, `top_employers` (company_canonical_id, top 20); `breadth` (entropy, cover80, top3 on `cur_soc_major`); `transitions` first→current SOC major (top 60); `at_k_entry` and `at_k_grad` for k in (1,5,10,20): the step active in `anchor_year + k` (start_year ≤ y ≤ end_year, ongoing counts) → SOC-major distribution; `seniority_by_stage_entry` / `_grad`: manager+/director+/vp+ on the current step by stage; `time_to_first_job` (grad axis: first step start_year − bachelor_end_year, capped at 6); `cohort_trend`: L1 share of bachelor-rung rows by end_year 1985..LAST_COMPLETE_YEAR. Top-level `release` = `{snapshot_date, snapshot_year, last_complete_year, git, built, inputs: {path: mtime}}`, `floor`. Also write `tables/group_summary.csv` and `tables/cur_soc_major_by_group.csv`.

- [ ] **Step 7: Run** both builds; record timings and the five reconciliation numbers in notes (n by tier; grad-degree rate L1; current SOC-major distribution L1 top 5; at+10 L1 on each axis n; total suppressed cells).

- [ ] **Step 8: Implement** `persons/person_checks.py`: row count == distinct persons in `education_person`; every person with `bachelor_cip2` has `bachelor_level_source`; `career_years_entry` and `career_years_grad` are independently nullable (assert both NULL/non-NULL combos occur); group `n` in metrics equals the count from `person.parquet` for `all`, `tier:l1`; every categorical cell ≥ floor; `release.git` present.

- [ ] **Step 9: Wiring**: Makefile `persons:` target + tests; `refresh_downstream.sh` stage `persons` after `archetypes` (`N_STAGES=18`); `check_freshness.py` stage `("persons", ROOT/"persons"/"_manifest.json", [N/"education_person.parquet", N/"career_steps.parquet", P/"steps.parquet", I/"results"/"step_industry.parquet"])`; `.gitignore` entries; `persons/README.md` (what it is, the two axes, the floor, how to read `metrics.json`); PIPELINE.md diagram line.

- [ ] **Step 10: Lint; test; test-data; commit** `feat(persons): person summary table and metrics cube v0 (both axes, all tiers, floor 10)`.

- [ ] **Step 11: Post-review**; record.

### Task 13: Close-out

- [ ] **Step 1:** Run `make test` and `make test-data` end to end; `uv run python scripts/check_freshness.py` (expect stale downstream stages listed: paths, network, cohorts, archetypes, portal are stale after the career_steps rebuild; note it).
- [ ] **Step 2:** Notes file: a summary table (piece, before, after, gate, verdict, decision) at the top.
- [ ] **Step 3:** Update `PIPELINE.md` (new mappings in the jury table; the `persons` stage in the diagram; the OPTIONAL mappings list) and `reference/README.md`.
- [ ] **Step 4:** Commit `docs: sibling-methods port close-out notes`; report to the owner with the summary table and the list of stale downstream stages to refresh in the main checkout.
