"""Drift + doc-lint checks for the NHA humanities boundary-tier counts.

    uv run python -m edu_clean.tier_tests

Plain-assert style (cf. `edu_clean/humanities_tests.py`, `portal/portal_tests.py`).
Two things are checked:

1. **Drift**: the committed `edu_clean/results/tier_counts.json` matches a fresh
   re-derivation from `normalized/education.parquet` (via `edu_clean.run_tier_counts`),
   and the nesting invariant L1 <= L2 <= L3 holds on both records and persons.
   If this fails, someone edited the JSON by hand, or the input parquet changed
   without re-running the driver -- re-run `uv run python -m edu_clean.run_tier_counts`
   and recommit.
2. **Doc-lint**: no root-level or `edu_clean/*.md` doc cites the stale pre-ratchet
   tier figures (186,018 / 341,113 / 597,144, in either comma or bare form)
   outside a context that clearly marks them as historical (the string
   "superseded" or the old coverage denominator "49.1%" nearby). This is a grep,
   not a parser -- it is deliberately simple and only checks *this repo's* docs,
   not portal/ or other packages, per COVERAGE_PLAN.md Plan 1.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import run_tier_counts as RTC

ROOT = Path(__file__).resolve().parent.parent

STALE_NUMBERS = ("186,018", "341,113", "597,144", "186018", "341113", "597144")
MARKER_WORDS = ("superseded", "49.1%")
LINT_GLOBS = ("*.md",) + tuple(f"edu_clean/{p}" for p in ("*.md",))
WINDOW = 8  # lines of context on each side of a match to search for a marker


def check(name: str, cond: bool) -> None:
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


# --------------------------------------------------------------------------
# 1. drift
# --------------------------------------------------------------------------
def check_drift() -> None:
    committed = json.loads(RTC.OUT.read_text())
    fresh = RTC.compute()  # re-derives in-memory only; does not touch the file

    for tk, ck in (("tiers", "cip_coverage"), ("tiers_pooled", "cip_coverage_pooled")):
        for key in ("l1", "l2", "l3"):
            check(f"drift: {tk} {key} records match committed",
                  committed[tk][key]["records"] == fresh[tk][key]["records"])
            check(f"drift: {tk} {key} persons match committed",
                  committed[tk][key]["persons"] == fresh[tk][key]["persons"])
        check(f"drift: {ck} rate matches committed",
              committed[ck]["rate"] == fresh[ck]["rate"])
    check("drift: input fingerprint matches committed",
          committed["input_fingerprint"]["content_hash"]
          == fresh["input_fingerprint"]["content_hash"])

    for tk in ("tiers", "tiers_pooled"):
        t = fresh[tk]
        check(f"nesting: {tk} records L1 <= L2 <= L3",
              t["l1"]["records"] <= t["l2"]["records"] <= t["l3"]["records"])
        check(f"nesting: {tk} persons L1 <= L2 <= L3",
              t["l1"]["persons"] <= t["l2"]["persons"] <= t["l3"]["persons"])
    # pooled coverage is a superset of deterministic
    check("pooled coverage >= deterministic coverage",
          fresh["cip_coverage_pooled"]["coded_rows"] >= fresh["cip_coverage"]["coded_rows"])


# --------------------------------------------------------------------------
# 2. doc-lint
# --------------------------------------------------------------------------
def _lint_targets() -> list[Path]:
    paths = sorted(ROOT.glob("*.md")) + sorted((ROOT / "edu_clean").glob("*.md"))
    return paths


def _flagged_lines(path: Path) -> list[int]:
    lines = path.read_text().splitlines()
    pattern = re.compile("|".join(re.escape(n) for n in STALE_NUMBERS))
    flagged = []
    for i, line in enumerate(lines):
        if not pattern.search(line):
            continue
        lo, hi = max(0, i - WINDOW), min(len(lines), i + WINDOW + 1)
        window_text = "\n".join(lines[lo:hi]).lower()
        if any(marker in window_text for marker in MARKER_WORDS):
            continue
        flagged.append(i + 1)  # 1-indexed for human-readable output
    return flagged


def check_doc_lint() -> None:
    violations = {}
    for path in _lint_targets():
        flagged = _flagged_lines(path)
        if flagged:
            violations[str(path.relative_to(ROOT))] = flagged
    if violations:
        detail = "; ".join(f"{p} lines {ls}" for p, ls in violations.items())
        raise AssertionError(
            "FAIL: doc-lint found stale tier figures (186,018/341,113/597,144) "
            f"without a nearby 'superseded'/'49.1%' marker: {detail}"
        )
    print(f"  ok: doc-lint clean across {len(_lint_targets())} file(s) "
          "(root *.md + edu_clean/*.md)")


def main() -> None:
    check_drift()
    check_doc_lint()
    print("\nall tier-count tests passed")


if __name__ == "__main__":
    main()
