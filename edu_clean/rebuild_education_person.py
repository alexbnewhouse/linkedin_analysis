"""Regenerate normalized/education_person.parquet from the current (pooled)
normalized/education.parquet -- WITHOUT a full 15-minute build_normalized run.

    uv run python -m edu_clean.rebuild_education_person

Reuses the canonical `build_normalized.write_education_person` so the rollup
logic has a single source of truth; only the input parquet is newer (it now
carries the CIP-jury pooled columns). Run after `edu_clean.apply_cip_pooled`.
"""

from __future__ import annotations

from pathlib import Path

import build_normalized as B

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "normalized"


def main() -> None:
    timings: list[B.StepTiming] = []
    B.write_education_person(OUT, threads=8, timings=timings)
    t = timings[-1]
    print(f"rebuilt {t.path} ({t.rows:,} rows) in {t.runtime_s:.1f}s")


if __name__ == "__main__":
    main()
