"""Phase 4 — cohort trajectory typologies + cohort mobility composition.

    uv run python -m cohorts.typologies

Two cohort comparisons, both reusing existing artifacts:

  1. ARCHETYPE MIX BY COHORT — joins the Phase-5 trajectory archetypes
     (`transition_network/trajectory_features.parquet`) with entry cohort and
     reports each cohort's distribution over archetypes. (Caveat: archetypes were
     computed on whole careers, so older cohorts have more steps — an
     observation-length confound; read shifts cautiously.)

  2. TRANSITION-TYPE MIX AT EQUAL OBSERVATION — for moves made within each
     person's first `COMMON_WINDOW_YEARS`, the share of each `transition_type`
     by entry cohort. Restricting to a common early-career window is the control
     that makes this comparison fair (vs the confounded #1): it asks "in their
     first 8 years, did later cohorts move up / switch employers / go independent
     at different rates than earlier ones?"

Outputs `cohorts/typologies.json`.
"""

from __future__ import annotations

import json
import time

import duckdb

from cohorts import common as C

FEATURES = C.ROOT / "transition_network" / "trajectory_features.parquet"


def build(threads: int = 8) -> dict:
    con = duckdb.connect(); con.execute(f"PRAGMA threads={threads}")
    prof = f"read_parquet('{str(C.PROFILES_OUT)}')"
    trans = f"read_parquet('{str(C.TRANSITIONS)}')"
    started = time.monotonic()

    # 1. archetype mix by entry cohort (share within cohort)
    archetype_mix = {}
    if FEATURES.exists():
        rows = con.sql(f"""
          SELECT p.entry_cohort_bin, f.archetype, count(*) n
          FROM read_parquet('{str(FEATURES)}') f
          JOIN {prof} p USING (linkedin_id)
          WHERE p.valid_cohort
          GROUP BY 1, 2
        """).df()
        for b, g in rows.groupby("entry_cohort_bin"):
            tot = g["n"].sum()
            archetype_mix[int(b)] = {int(r.archetype): round(r.n / tot, 3)
                                     for r in g.itertuples(index=False)}

    # 2. transition-type mix among first-window moves, by entry cohort
    tmix = con.sql(f"""
      WITH m AS (
        SELECT p.entry_cohort_bin, e.transition_type,
               (year(e.to_start_dt) - p.entry_year) AS move_age
        FROM {trans} e JOIN {prof} p USING (linkedin_id)
        WHERE p.valid_cohort AND e.transition_type IS NOT NULL
          AND (year(e.to_start_dt) - p.entry_year) BETWEEN 0 AND {C.COMMON_WINDOW_YEARS}
      )
      SELECT entry_cohort_bin, transition_type, count(*) n
      FROM m GROUP BY 1, 2
    """).df()
    type_mix = {}
    for b, g in tmix.groupby("entry_cohort_bin"):
        tot = g["n"].sum()
        type_mix[int(b)] = {r.transition_type: round(r.n / tot, 3)
                            for r in g.itertuples(index=False)}

    # headline: how the upward-move share among early moves shifts across cohorts
    up_share = {b: round(sum(v.get(t, 0) for t in
                ("promotion", "employer_move_up", "occupation_change_up")), 3)
                for b, v in type_mix.items()}
    se_share = {b: round(v.get("into_self_employment", 0), 3) for b, v in type_mix.items()}

    # humanities vs non: same equal-window transition mix, split by field group
    hmix = con.sql(f"""
      WITH m AS (
        SELECT CASE WHEN p.hum_l1_any THEN 'humanities' ELSE 'non_humanities' END AS hum_group,
               e.transition_type
        FROM {trans} e JOIN {prof} p USING (linkedin_id)
        WHERE p.valid_cohort AND e.transition_type IS NOT NULL
          AND (year(e.to_start_dt) - p.entry_year) BETWEEN 0 AND {C.COMMON_WINDOW_YEARS}
      )
      SELECT hum_group, transition_type, count(*) n FROM m GROUP BY 1, 2
    """).df()
    hum_mix = {}
    for g, sub in hmix.groupby("hum_group"):
        tot = sub["n"].sum()
        d = {r.transition_type: round(r.n / tot, 3) for r in sub.itertuples(index=False)}
        hum_mix[g] = {
            "transition_mix": d,
            "upward_move_share": round(sum(d.get(t, 0) for t in
                ("promotion", "employer_move_up", "occupation_change_up")), 3),
            "into_self_employment_share": round(d.get("into_self_employment", 0), 3),
        }
    con.close()

    return {
        "common_window_years": C.COMMON_WINDOW_YEARS,
        "archetype_mix_by_cohort": archetype_mix,
        "transition_type_mix_first_window_by_cohort": type_mix,
        "upward_move_share_first_window_by_cohort": up_share,
        "into_self_employment_share_first_window_by_cohort": se_share,
        "humanities_vs_non_transition_mix": hum_mix,
        "note": ("Comparison #2 (equal-window transition mix) is the fair cohort "
                 "comparison; #1 (whole-career archetypes) is confounded by "
                 "observation length. Even #2 carries the recency/backfill caveat: "
                 "recent cohorts' early moves are better documented."),
        "runtime_s": round(time.monotonic() - started, 1),
    }


def main() -> None:
    summary = build()
    (C.OUT_DIR / "typologies.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
