"""One row per person: bachelor's field, tiers, graduate degrees, career summary (spec P6).

    uv run python -m persons.build_person

Single-source rule (pre-review 2026-09-22): every per-person flag that
normalized/education_person.parquet already carries is READ from it, never recomputed.
This table ADDS the bachelor-rung row (pooled), graduate-degree type flags, the IPEDS join,
and the career summary derived from paths/steps.parquet joined NULL-safely to
career_steps (pooled occupation, family, display, state) and step_industry. Both time axes
are carried and never coalesced. The "current" step uses the cohort panel's tie-break
(seniority_score DESC NULLS LAST, tenure_months DESC NULLS LAST).
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone

import duckdb

from persons import common as C

SCHEMA_VERSION = 1
STEP_KEY = "(source_table, linkedin_id, experience_idx, position_idx)"


def _q(p) -> str:
    return str(p).replace("'", "''")


def git_stamp() -> dict:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=C.ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
                                             cwd=C.ROOT, text=True).strip())
    except Exception:  # noqa: BLE001
        sha, dirty = "unknown", True
    return {"git": sha, "git_dirty": dirty}


def snapshot_id() -> str | None:
    """Common prefix of the raw shard names recorded by the parser (e.g. snap_mlsi9jwqziij1k8zq)."""
    try:
        m = json.loads((C.ROOT / "parsed" / "_manifest.json").read_text())
        names = []
        for key in ("files", "inputs", "per_file", "sources"):
            v = m.get(key)
            if isinstance(v, dict):
                names = list(v.keys())
            elif isinstance(v, list):
                names = [x.get("file") or x.get("path") or str(x) for x in v]
            if names:
                break
        if not names:
            return None
        stems = [str(n).rsplit("/", 1)[-1].split(".")[0] for n in names]
        prefix = stems[0]
        for s in stems[1:]:
            while not s.startswith(prefix):
                prefix = prefix[:-1]
        return prefix or None
    except Exception:  # noqa: BLE001
        return None


def inputs_stamp() -> dict:
    out = {}
    for p in (C.EDUCATION, C.EDU_PERSON, C.CAREER_STEPS, C.STEPS, C.STEP_INDUSTRY, C.CIP_HUM,
              C.ROOT / "reference" / "institution_meta.parquet",
              C.ROOT / "normalized" / "mappings" / "school_ipeds.parquet"):
        if p.exists():
            out[str(p.relative_to(C.ROOT))] = {"mtime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()}
    return out


def release() -> dict:
    return {"schema_version": SCHEMA_VERSION, "built": datetime.now(timezone.utc).isoformat(),
            "snapshot_date": C.SNAPSHOT_DATE, "snapshot_id": snapshot_id(),
            "snapshot_cal_year": C.SNAPSHOT_YEAR, "last_complete_year": C.LAST_COMPLETE_YEAR,
            **git_stamp(),
            "params": {"min_support": C.MIN_SUPPORT, "secondary_suppression": True,
                       "min_group_n": C.MIN_GROUP_N, "stages": C.STAGE_ORDER, "horizons": list(C.HORIZONS),
                       "current_step_rule": "is_ongoing; seniority_score DESC NULLS LAST, tenure_months DESC NULLS LAST, row_id",
                       "first_step_rule": "start_dt, end_dt, row_id over datable sane steps",
                       "bachelor_row_rule": "pooled level 4; det source first, earliest end_year, idx",
                       "attainment": "max(seniority_ordinal) >= 6 / 7 / 8 (paths.common.SENIORITY_RANK)"},
            "inputs": inputs_stamp()}


def build(threads: int = 16) -> dict:
    t0 = time.time()
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    LC = C.LAST_COMPLETE_YEAR
    con.execute(f"""
      CREATE TEMP VIEW ep AS SELECT * FROM read_parquet('{_q(C.EDU_PERSON)}');
      CREATE TEMP VIEW edu AS SELECT * FROM read_parquet('{_q(C.EDUCATION)}') WHERE NOT is_duplicate;
      CREATE TEMP TABLE lvl AS
        SELECT s.school_slug, any_value(m.control_label) AS inst_control_label, any_value(m.state) AS inst_state
        FROM read_parquet('{_q(C.ROOT / "normalized" / "mappings" / "school_ipeds.parquet")}') s
        JOIN read_parquet('{_q(C.ROOT / "reference" / "institution_meta.parquet")}') m ON m.unitid = s.unitid
        GROUP BY 1;
    """)
    # bachelor-rung row (pooled), one per person
    con.execute("""
      CREATE TEMP TABLE bach AS
      SELECT linkedin_id,
             cip_code AS bachelor_cip_code, cip2_pooled AS bachelor_cip2, cip4 AS bachelor_cip4,
             cip_source AS bachelor_cip_source, degree_level_source AS bachelor_level_source,
             end_year AS bachelor_row_end_year, humanities_field_group_pooled AS bachelor_field_group,
             nha_level_pooled AS bachelor_nha_level, cip2_secondary AS comajor_cip2, minor_cip2,
             school_slug AS bachelor_school_slug
      FROM edu
      WHERE coalesce(degree_level_pooled, degree_level) = 4
      QUALIFY row_number() OVER (
        PARTITION BY linkedin_id
        ORDER BY (degree_level_source = 'det') DESC, end_year ASC NULLS LAST, idx) = 1
    """)
    con.execute("""
      CREATE TEMP TABLE tiers AS
      SELECT linkedin_id,
             coalesce(bool_or(nha_level_pooled IN (1, 2)), FALSE) AS hum_l2_bachelor,
             coalesce(bool_or(nha_level_pooled IN (1, 2, 3)), FALSE) AS hum_l3_bachelor
      FROM edu WHERE coalesce(degree_level_pooled, degree_level) = 4 GROUP BY 1
    """)
    con.execute("""
      CREATE TEMP TABLE grad AS
      SELECT linkedin_id,
             TRUE AS has_grad_degree,
             coalesce(bool_or(lvl = 6 AND coalesce(degree_type, '') NOT IN ('law', 'medicine', 'dental')), FALSE) AS has_master,
             coalesce(bool_or(lvl = 7 AND coalesce(degree_type, '') NOT IN ('law', 'medicine', 'dental')), FALSE) AS has_doctorate,
             coalesce(bool_or(degree_type = 'law'), FALSE) AS has_jd,
             coalesce(bool_or(degree_type = 'business_admin'), FALSE) AS has_mba,
             coalesce(bool_or(degree_type IN ('medicine', 'dental')), FALSE) AS has_md_prof,
             coalesce(bool_or(degree_type = 'education'), FALSE) AS has_med,
             coalesce(bool_or(degree_type = 'social_work'), FALSE) AS has_msw
      FROM (SELECT linkedin_id, degree_type, coalesce(degree_level_pooled, degree_level) AS lvl FROM edu)
      WHERE lvl >= 6 GROUP BY 1
    """)
    # steps: spine rows joined NULL-safely to career_steps + step_industry, deduped on the key
    con.execute(f"""
      CREATE TEMP TABLE st AS
      SELECT s.linkedin_id, s.row_id, s.start_dt, s.end_dt, year(s.start_dt) AS y0, year(s.end_dt) AS y1,
             s.is_ongoing, s.seniority_score, s.seniority_ordinal, s.tenure_months, s.employment_type,
             c.occupation_major_pooled AS soc_major, c.occupation_code_pooled, c.occupation_source,
             c.title_family, c.title_seniority9, c.role_display, c.company_canonical_id, c.location_us_state,
             i.l1 AS industry_l1
      FROM read_parquet('{_q(C.STEPS)}') s
      LEFT JOIN read_parquet('{_q(C.CAREER_STEPS)}') c
        ON c.source_table = s.source_table AND c.linkedin_id = s.linkedin_id
       AND c.experience_idx = s.experience_idx AND c.position_idx IS NOT DISTINCT FROM s.position_idx
      LEFT JOIN read_parquet('{_q(C.STEP_INDUSTRY)}') i
        ON i.source_table = s.source_table AND i.linkedin_id = s.linkedin_id
       AND i.experience_idx = s.experience_idx AND i.position_idx IS NOT DISTINCT FROM s.position_idx
      WHERE s.datable AND NOT s.bad_negative_duration AND NOT s.bad_future_start
        AND year(s.start_dt) <= {C.SNAPSHOT_YEAR}
      QUALIFY row_number() OVER (PARTITION BY s.row_id
                                 ORDER BY c.is_duplicate, i.confidence DESC NULLS LAST,
                                          c.title_family, c.company_canonical_id, i.l1, c.occupation_major_pooled) = 1
    """)
    n_spine = con.execute(f"""SELECT count(*) FROM read_parquet('{_q(C.STEPS)}')
        WHERE datable AND NOT bad_negative_duration AND NOT bad_future_start AND year(start_dt) <= {C.SNAPSHOT_YEAR}""").fetchone()[0]
    n_st = con.execute("SELECT count(*) FROM st").fetchone()[0]
    assert n_st == n_spine, f"step join changed the row count: {n_spine} -> {n_st}"
    con.execute("""
      CREATE TEMP TABLE first AS
      SELECT linkedin_id, soc_major AS first_soc_major, occupation_code_pooled AS first_occupation_code_pooled,
             title_family AS first_title_family, y0 AS first_start_year, industry_l1 AS first_industry_l1
      FROM st QUALIFY row_number() OVER (PARTITION BY linkedin_id ORDER BY start_dt, end_dt, row_id) = 1
    """)
    con.execute("""
      CREATE TEMP TABLE cur AS
      SELECT linkedin_id, soc_major AS cur_soc_major, occupation_code_pooled AS cur_occupation_code_pooled,
             occupation_source AS cur_occupation_source, title_family AS cur_title_family,
             title_seniority9 AS cur_title_seniority9, role_display AS cur_role_display,
             company_canonical_id AS cur_company_canonical_id, industry_l1 AS cur_industry_l1,
             location_us_state AS cur_us_state, y0 AS cur_start_year, seniority_ordinal AS cur_seniority_ordinal
      FROM st WHERE is_ongoing
      QUALIFY row_number() OVER (PARTITION BY linkedin_id
                                 ORDER BY seniority_score DESC NULLS LAST, tenure_months DESC NULLS LAST, row_id) = 1
    """)
    con.execute(f"""
      CREATE TEMP TABLE agg AS
      SELECT linkedin_id, count(*) AS n_steps, count(DISTINCT company_canonical_id) AS n_employers,
             min(y0) AS entry_year, max(y1) AS last_year,
             coalesce(max(seniority_ordinal) >= {C.MANAGER_RANK}, FALSE) AS ever_manager_plus,
             coalesce(max(seniority_ordinal) >= {C.DIRECTOR_RANK}, FALSE) AS ever_director_plus,
             coalesce(max(seniority_ordinal) >= {C.VP_RANK}, FALSE) AS ever_vp_plus,
             coalesce(bool_or(employment_type IN ('business_owner', 'self_employed')), FALSE) AS ever_founder_owner,
             coalesce(bool_or(is_ongoing), FALSE) AS has_current_step
      FROM st GROUP BY 1
    """)
    # slim per-step table for the metrics build (at+k panels need the step active in a year)
    st_tmp = C.STEPS_OUT.with_suffix(".parquet.tmp")
    con.execute(f"""
      COPY (SELECT linkedin_id, row_id, y0, y1, is_ongoing, seniority_score, tenure_months,
                   seniority_ordinal, soc_major, occupation_code_pooled, title_family, industry_l1, employment_type
            FROM st) TO '{_q(st_tmp)}' (FORMAT parquet, COMPRESSION zstd)
    """)
    if C.STEPS_OUT.exists():
        C.STEPS_OUT.unlink()
    st_tmp.replace(C.STEPS_OUT)
    tmp = C.PERSON_OUT.with_suffix(".parquet.tmp")
    con.execute(f"""
      COPY (
        SELECT ep.linkedin_id,
               b.bachelor_cip_code, b.bachelor_cip2, b.bachelor_cip4, b.bachelor_cip_source, b.bachelor_level_source,
               b.bachelor_row_end_year, ep.bachelor_end_year, b.bachelor_field_group, b.bachelor_nha_level,
               (b.linkedin_id IS NOT NULL) AS has_bachelor,
               ep.hum_l1_bachelor_pooled_any AS hum_l1_bachelor,
               coalesce(t.hum_l2_bachelor, FALSE) AS hum_l2_bachelor,
               coalesce(t.hum_l3_bachelor, FALSE) AS hum_l3_bachelor,
               ep.hum_l1_any, ep.bachelor_imputed_any, ep.double_major_any, ep.hum_l1_comajor_any, ep.minor_hum_l1_any,
               b.comajor_cip2, b.minor_cip2,
               ep.highest_degree_level_pooled,
               coalesce(g.has_grad_degree, FALSE) AS has_grad_degree, coalesce(g.has_master, FALSE) AS has_master,
               coalesce(g.has_doctorate, FALSE) AS has_doctorate, coalesce(g.has_jd, FALSE) AS has_jd,
               coalesce(g.has_mba, FALSE) AS has_mba, coalesce(g.has_md_prof, FALSE) AS has_md_prof,
               coalesce(g.has_med, FALSE) AS has_med, coalesce(g.has_msw, FALSE) AS has_msw,
               l.inst_control_label, l.inst_state,
               a.n_steps, a.n_employers, a.entry_year, a.last_year,
               coalesce(a.ever_manager_plus, FALSE) AS ever_manager_plus,
               coalesce(a.ever_director_plus, FALSE) AS ever_director_plus,
               coalesce(a.ever_vp_plus, FALSE) AS ever_vp_plus,
               coalesce(a.ever_founder_owner, FALSE) AS ever_founder_owner,
               coalesce(a.has_current_step, FALSE) AS has_current_step,
               f.first_soc_major, f.first_occupation_code_pooled, f.first_title_family, f.first_start_year, f.first_industry_l1,
               c.cur_soc_major, c.cur_occupation_code_pooled, c.cur_occupation_source, c.cur_title_family,
               c.cur_title_seniority9, c.cur_role_display, c.cur_company_canonical_id, c.cur_industry_l1,
               c.cur_us_state, c.cur_start_year, c.cur_seniority_ordinal,
               CASE WHEN a.entry_year BETWEEN 1950 AND {LC} THEN {LC} - a.entry_year END AS career_years_entry,
               CASE WHEN ep.bachelor_end_year BETWEEN 1950 AND {LC} THEN {LC} - ep.bachelor_end_year END AS career_years_grad,
               {C.stage_sql(f"(CASE WHEN a.entry_year BETWEEN 1950 AND {LC} THEN {LC} - a.entry_year END)")} AS career_stage_entry,
               {C.stage_sql(f"(CASE WHEN ep.bachelor_end_year BETWEEN 1950 AND {LC} THEN {LC} - ep.bachelor_end_year END)")} AS career_stage_grad
        FROM ep
        LEFT JOIN bach b USING (linkedin_id)
        LEFT JOIN tiers t USING (linkedin_id)
        LEFT JOIN grad g USING (linkedin_id)
        LEFT JOIN lvl l ON l.school_slug = b.bachelor_school_slug
        LEFT JOIN agg a USING (linkedin_id)
        LEFT JOIN first f USING (linkedin_id)
        LEFT JOIN cur c USING (linkedin_id)
      ) TO '{_q(tmp)}' (FORMAT parquet, COMPRESSION zstd)
    """)
    if C.PERSON_OUT.exists():
        C.PERSON_OUT.unlink()
    tmp.replace(C.PERSON_OUT)
    n = con.execute(f"SELECT count(*), count(DISTINCT linkedin_id) FROM read_parquet('{_q(C.PERSON_OUT)}')").fetchone()
    assert n[0] == n[1], f"person table is not one row per person: {n}"
    summary = con.execute(f"""
      SELECT count(*) AS persons, sum(has_bachelor::INT) AS with_bachelor, sum(hum_l1_bachelor::INT) AS l1,
             sum(hum_l2_bachelor::INT) AS l2, sum(hum_l3_bachelor::INT) AS l3,
             sum((entry_year IS NOT NULL)::INT) AS with_entry, sum((bachelor_end_year IS NOT NULL)::INT) AS with_grad_year,
             sum((cur_soc_major IS NOT NULL)::INT) AS with_cur_major, sum(has_grad_degree::INT) AS grad_degree
      FROM read_parquet('{_q(C.PERSON_OUT)}')""").fetchone()
    con.close()
    man = {**release(), "rows": n[0], "steps_joined": n_st, "runtime_s": round(time.time() - t0, 1),
           "summary": dict(zip(["persons", "with_bachelor", "l1", "l2", "l3", "with_entry", "with_grad_year",
                                "with_cur_major", "grad_degree"], summary))}
    C.MANIFEST.write_text(json.dumps(man, indent=1, default=str) + "\n")
    return man


def main() -> None:
    m = build()
    s = m["summary"]
    print(f"persons/person.parquet: {m['rows']:,} rows in {m['runtime_s']}s; steps joined {m['steps_joined']:,}")
    print(f"  with bachelor {s['with_bachelor']:,}; L1 {s['l1']:,} / L2 {s['l2']:,} / L3 {s['l3']:,}; "
          f"entry axis {s['with_entry']:,}; grad axis {s['with_grad_year']:,}; current major {s['with_cur_major']:,}; "
          f"grad degree {s['grad_degree']:,}")
    print(f"  release: git {m['git']}{' (dirty)' if m['git_dirty'] else ''}, snapshot {m['snapshot_id']} {m['snapshot_date']}")


if __name__ == "__main__":
    main()
