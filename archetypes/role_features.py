"""Phase 1 — per-role_canonical feature aggregate.

One row per `role_canonical` over all non-duplicate career steps, carrying the
signals the assignment needs: modal detailed SOC, triangulated modal SOC-major,
modal industry L1, self-employment share, seniority profile, person-support,
and role text for keyword/embedding matching.
"""

from __future__ import annotations

from . import common as C


def build(con) -> str:
    cs = f"read_parquet('{C.CAREER_STEPS}')"
    jury = f"read_parquet('{C.ROLE_SOC_JURY}')"
    # Pre-collapse industry + steps to ONE row per step key: both tables carry
    # a handful of non-unique (linkedin_id, source_table, NULL, NULL) groups
    # that would otherwise fan out the LEFT JOIN and inflate count(*)/n_steps
    # (red-team finding 5).
    ind = f"""(
      SELECT linkedin_id, source_table, experience_idx, position_idx,
             any_value(l1) AS l1
      FROM read_parquet('{C.STEP_INDUSTRY}')
      GROUP BY 1, 2, 3, 4)"""
    steps = f"""(
      SELECT linkedin_id, source_table, experience_idx, position_idx,
             any_value(seniority_ordinal) AS seniority_ordinal
      FROM read_parquet('{C.STEPS}')
      GROUP BY 1, 2, 3, 4)"""

    soc_major = C.soc_major_expr("c", "j")
    soc_major_method = C.soc_major_method_expr("c", "j")

    # Per-step enriched view: triangulated soc_major, detail, industry l1,
    # seniority ordinal, owner flag. Industry + seniority joined by step key.
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE step_enriched AS
      SELECT
        c.linkedin_id,
        c.role_canonical,
        c.role_display,
        c.title_raw,
        c.occupation_code                                  AS soc_detail,
        {soc_major}                                        AS soc_major,
        {soc_major_method}                                 AS soc_major_method,
        i.l1                                               AS industry_l1,
        s.seniority_ordinal                                AS seniority_ordinal,
        CASE WHEN c.employment_type IN ('self_employed','business_owner')
             THEN 1 ELSE 0 END                             AS is_owner
      FROM {cs} c
      LEFT JOIN {jury} j ON c.role_canonical = j.role_canonical
      LEFT JOIN {ind} i
        ON c.linkedin_id = i.linkedin_id
       AND c.source_table = i.source_table
       AND c.experience_idx IS NOT DISTINCT FROM i.experience_idx
       AND c.position_idx  IS NOT DISTINCT FROM i.position_idx
      LEFT JOIN {steps} s
        ON c.linkedin_id = s.linkedin_id
       AND c.source_table = s.source_table
       AND c.experience_idx IS NOT DISTINCT FROM s.experience_idx
       AND c.position_idx  IS NOT DISTINCT FROM s.position_idx
      WHERE c.role_canonical IS NOT NULL AND NOT c.is_duplicate
    """)

    out = C.RESULTS / "role_features.parquet"
    # Modal SOC detail/major are carried WITH their support (modal count) so the
    # assignment can refuse to trust a code backed by only a handful of steps
    # (e.g. "owner" coded 29-1229 from 5 of thousands of steps -> not Healthcare).
    con.execute(f"""
      COPY (
        WITH agg AS (
          SELECT
            role_canonical,
            count(*)                                        AS n_steps,
            count(DISTINCT linkedin_id)                     AS n_persons,
            mode(role_display)                              AS role_display,
            lower(coalesce(mode(role_display), '') || ' ' ||
                  coalesce(mode(title_raw), ''))            AS role_text,
            mode(soc_major_method) FILTER (WHERE soc_major_method IS NOT NULL)
                                                            AS soc_major_method,
            mode(industry_l1) FILTER (WHERE industry_l1 IS NOT NULL) AS industry_l1,
            avg(is_owner)                                   AS owner_share,
            avg(seniority_ordinal)                          AS mean_seniority
          FROM step_enriched GROUP BY role_canonical
        ),
        dcnt AS (
          SELECT role_canonical, soc_detail, count(*) AS c
          FROM step_enriched WHERE soc_detail IS NOT NULL GROUP BY 1, 2),
        dtop AS (
          SELECT role_canonical, arg_max(soc_detail, c) AS soc_detail,
                 max(c) AS soc_detail_support, sum(c) AS n_soc_detail
          FROM dcnt GROUP BY 1),
        mcnt AS (
          SELECT role_canonical, soc_major, count(*) AS c
          FROM step_enriched WHERE soc_major IS NOT NULL GROUP BY 1, 2),
        mtop AS (
          SELECT role_canonical, arg_max(soc_major, c) AS soc_major,
                 max(c) AS soc_major_support, sum(c) AS n_soc_major
          FROM mcnt GROUP BY 1)
        SELECT a.*,
               dtop.soc_detail,
               coalesce(dtop.soc_detail_support, 0) AS soc_detail_support,
               coalesce(dtop.n_soc_detail, 0)       AS n_soc_detail,
               mtop.soc_major,
               coalesce(mtop.soc_major_support, 0)  AS soc_major_support,
               coalesce(mtop.n_soc_major, 0)        AS n_soc_major
        FROM agg a
        LEFT JOIN dtop USING (role_canonical)
        LEFT JOIN mtop USING (role_canonical)
      ) TO '{out}' (FORMAT parquet)
    """)
    return str(out)
