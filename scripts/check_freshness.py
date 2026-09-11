"""Freshness check for the downstream DAG (audit 2026-09-02, refactor E-5).

    uv run python scripts/check_freshness.py          # table + exit 1 if stale
    uv run python scripts/check_freshness.py --quiet  # exit code only

An output is STALE when any of its declared inputs has a newer mtime than the
output's manifest (or the manifest is missing). The stage list below is the
real DAG (refactor-team A.1), not the documented one; keep it in sync with
scripts/refresh_downstream.sh.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
N, I, P, T, CO, A, PO = (ROOT / d for d in (
    "normalized", "industry", "paths", "transition_network", "cohorts",
    "archetypes/results", "portal"))

# (stage, manifest-or-output whose mtime dates the stage, inputs)
STAGES: list[tuple[str, Path, list[Path]]] = [
    ("normalized", N / "_manifest.json", [ROOT / "parsed" / "_manifest.json"]),
    ("industry", I / "results" / "build_manifest.json",
     [N / "career_steps.parquet", I / "curated.py", I / "curated_head.py", I / "curated_promoted.py",
      I / "name_rules.py", I / "occupation_prior.py", I / "taxonomy.json"]),
    ("paths", P / "_manifest.json", [N / "career_steps.parquet", P / "seniority_scores.parquet"]),
    ("network:role", T / "role_manifest.json", [P / "transitions.parquet"]),
    ("analyze:role", T / "role_analyze_manifest.json", [T / "role_edges.parquet"]),
    # The revealed-seniority loop (spine -> role network -> seniority -> spine)
    # has no mtime-consistent fixed point: the driver runs it once and then
    # rebuilds the role network on the final spine, so seniority is checked
    # against nothing and the role network against the final transitions.
    ("seniority", P / "seniority_scores.parquet", []),
    ("network:occupation", T / "occupation_manifest.json", [P / "transitions.parquet"]),
    ("analyze:occupation", T / "occupation_analyze_manifest.json", [T / "occupation_edges.parquet"]),
    ("network:soc_major", T / "soc_major_manifest.json", [P / "transitions.parquet"]),
    ("analyze:soc_major", T / "soc_major_analyze_manifest.json", [T / "soc_major_edges.parquet"]),
    ("cohorts", CO / "_panel_manifest.json",
     [P / "steps.parquet", P / "transitions.parquet", N / "education_person.parquet"]),
    ("archetypes", A / "person_year_archetype.parquet",
     [N / "career_steps.parquet", I / "results" / "step_industry.parquet",
      P / "steps.parquet", P / "transitions.parquet", CO / "panel.parquet",
      N / "education_person.parquet"]),
    ("portal", PO / "_manifest.json",
     [N / "education.parquet", P / "steps.parquet", P / "transitions.parquet",
      T / "occupation_nodes_analyzed.parquet", I / "results" / "step_industry.parquet"]),
    ("share", ROOT / "share" / "Humanities-Workforce-portal.html",
     [PO / "results" / "portal_data.json"]),
]


def stale_inputs(manifest: Path, inputs: list[Path]) -> list[Path]:
    """Inputs newer than ``manifest`` (all existing inputs if it is missing).
    Inputs that do not exist are ignored (optional upstream artifacts)."""
    present = [p for p in inputs if p.exists()]
    if not manifest.exists():
        return present
    m = manifest.stat().st_mtime
    return [p for p in present if p.stat().st_mtime > m]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    any_stale = False
    for stage, manifest, inputs in STAGES:
        bad = stale_inputs(manifest, inputs)
        status = "MISSING" if not manifest.exists() else ("STALE" if bad else "ok")
        any_stale |= status != "ok"
        if not args.quiet:
            extra = ", ".join(p.relative_to(ROOT).as_posix() for p in bad)
            print(f"{status:8} {stage:20} {manifest.relative_to(ROOT).as_posix()}"
                  + (f"  <- {extra}" if extra else ""))
    if any_stale and not args.quiet:
        print("\nstale: run `make refresh` (or the specific stage) before trusting downstream numbers")
    return 1 if any_stale else 0


if __name__ == "__main__":
    sys.exit(main())
