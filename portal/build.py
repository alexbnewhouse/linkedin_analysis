"""Build the shared substrate tables in a DuckDB connection:

  membership   one row per (group_key, linkedin_id, anchor, anchor_method).
               A person's several qualifying degrees in one group collapse to
               ONE anchor (edu_clean.anchors precedence A1 > A2 > A3) -> the
               join to steps never fans out on linkedin_id. anchor_method
               records which tier produced the anchor (COVERAGE_PLAN.md Plan
               2); which tiers are even eligible is governed by
               `common.ANCHOR_TIERS` (default: the two tiers that cleared the
               validation gate -- edu_clean/results/anchor_eval.json).
  panel        person-year primary step for every population person, with the
               step's occupation / seniority / job-zone / role / dwell and its
               resolved industry L1 sector attached. career_age is derived per
               group at query time (= calendar_year - group anchor).

Also returns the boundary tier counts (re-derived from the committed crosswalk)
and the per-major record / person / windowed-person funnel.
"""

from __future__ import annotations

import json
import os

from edu_clean import anchors
from portal import common as C

# --- Substrate cache --------------------------------------------------------
# build_panel is the pipeline's dominant cost (scans ~1 GB of steps + industry,
# unnests to person-years, windows). It is rebuilt from scratch by the driver,
# ~5x inside portal_tests, and once per bias check. The DEFAULT substrate
# (membership + panel under common.{ANCHOR_TIERS,SOC_SOURCES,CIP_SOURCES}) is
# deterministic in its inputs, so we cache it to parquet keyed on the inputs'
# mtime+size AND this module's + common.py's source stat (so a logic edit busts
# it). Parametrized rebuilds (bias checks, det-only test comparisons) still call
# build_* directly -- only the default substrate is cached. Disable with
# PORTAL_SUBSTRATE_CACHE=0.
_CACHE_DIR = C.OUT_DIR / "_cache"


def _file_stat(p) -> list:
    try:
        s = os.stat(p)
        return [str(p), s.st_mtime_ns, s.st_size]
    except FileNotFoundError:
        return [str(p), None, None]


def _substrate_key(tiers, cip_sources, soc_sources) -> dict:
    # inputs that determine membership (education, cip jury) + panel (steps,
    # industry, role jury), plus the build code itself.
    inputs = [C.EDUCATION, C.FIELD_CIP_JURY, C.STEPS, C.STEP_INDUSTRY,
              C.ROLE_SOC_JURY, __file__, C.__file__]
    return {
        "tiers": list(tiers),
        "cip_sources": list(cip_sources),
        "soc_sources": list(soc_sources),
        "inputs": [_file_stat(p) for p in inputs],
    }


def load_or_build_substrate(con, tiers=None, cip_sources=None,
                            soc_sources=None, force=False) -> str:
    """Materialize the default `membership` + `panel` temp tables, reusing a
    parquet cache when inputs+params+build-code are unchanged. Returns "cache"
    or "built". Only downstream consumers of `membership`/`panel` (the driver's
    analyses) are served from cache -- the intermediate temps (vstep, step_ind,
    role_jury, ...) are NOT recreated, so callers that need those must use
    build_panel/build_membership directly."""
    tiers = tuple(tiers) if tiers else C.ANCHOR_TIERS
    cip_sources = tuple(cip_sources) if cip_sources else C.CIP_SOURCES
    soc_sources = tuple(soc_sources) if soc_sources else C.SOC_SOURCES
    disabled = os.environ.get("PORTAL_SUBSTRATE_CACHE") == "0"
    mem_pq, pan_pq = _CACHE_DIR / "membership.parquet", _CACHE_DIR / "panel.parquet"
    key_f = _CACHE_DIR / "substrate_key.json"
    key = _substrate_key(tiers, cip_sources, soc_sources)
    if (not force and not disabled and mem_pq.exists() and pan_pq.exists()
            and key_f.exists()):
        try:
            cached = json.loads(key_f.read_text())
        except (ValueError, OSError):
            cached = None
        if cached == key:
            con.execute(f"CREATE OR REPLACE TEMP TABLE membership AS "
                        f"SELECT * FROM read_parquet('{C.q(mem_pq)}')")
            con.execute(f"CREATE OR REPLACE TEMP TABLE panel AS "
                        f"SELECT * FROM read_parquet('{C.q(pan_pq)}')")
            return "cache"
    build_membership(con, tiers=tiers, cip_sources=cip_sources)
    build_panel(con, soc_sources=soc_sources)
    if not disabled:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY membership TO '{C.q(mem_pq)}' (FORMAT parquet)")
        con.execute(f"COPY panel TO '{C.q(pan_pq)}' (FORMAT parquet)")
        key_f.write_text(json.dumps(key, indent=2))
    return "built"


def _usable_anchor_sql(alias: str = "e") -> str:
    """A1 usability predicate (unchanged rule) -- kept here for the funnel's
    "anchored" count and the byte-identical-A1-only regression test."""
    return anchors.a1_predicate_sql(alias)


def _edu_table(con, cip_sources: tuple[str, ...]) -> str:
    """The education table every membership/funnel query reads. Deterministic-
    only mode reads the committed parquet untouched (byte-identical to the
    pre-CIP-jury pipeline; regression-tested). With "llm_jury" enabled AND the
    calibrated mapping present, a pooled temp table fills cip2 ONLY where
    cip_code IS NULL (det always wins) and records cip_source provenance.
    Verified: cip2 IS NULL <=> cip_code IS NULL on the committed parquet, so
    cip2-based predicates are det-equivalent."""
    if "llm_jury" not in cip_sources or not C.FIELD_CIP_JURY.exists():
        return f"read_parquet('{C.q(C.EDUCATION)}')"
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE field_jury AS
      SELECT field_norm, cip2 AS jury_cip2
      FROM read_parquet('{C.q(C.FIELD_CIP_JURY)}')
    """)
    dup = con.execute(
        "SELECT count(*) - count(DISTINCT field_norm) FROM field_jury").fetchone()[0]
    if dup:
        raise ValueError(
            f"field_cip_jury.parquet has {dup} duplicate field_norm rows -- "
            "joining it would fan out education rows; rebuild it with "
            "edu_clean.run_cip_jury merge")
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE edu_pooled AS
      SELECT e.* EXCLUDE (cip2_pooled, cip_source, nha_level_pooled,
                          humanities_field_group_pooled)
                 REPLACE (coalesce(e.cip2, fj.jury_cip2) AS cip2),
             CASE WHEN e.cip2 IS NOT NULL THEN 'det'
                  WHEN fj.jury_cip2 IS NOT NULL THEN 'jury' END AS cip_source
      FROM read_parquet('{C.q(C.EDUCATION)}') e
      -- Pure equijoin so DuckDB hash-joins (the old `e.cip_code IS NULL AND ...`
      -- in the ON clause forced a nested loop: 3.58M x 18.7k, ~minutes -> 0.1s).
      -- Behavior-identical: field_jury has unique field_norm (no fan-out, asserted
      -- above) and coalesce/CASE use the jury value only where cip2 (<=> cip_code)
      -- is NULL, so matches on already-coded rows are computed-but-ignored.
      LEFT JOIN field_jury fj ON fj.field_norm = lower(trim(e.field_raw))
    """)
    return "edu_pooled"


def build_membership(con, tiers: tuple[str, ...] = C.ANCHOR_TIERS,
                     cip_sources: tuple[str, ...] = None) -> None:
    if cip_sources is None:
        cip_sources = C.CIP_SOURCES
    edu = _edu_table(con, cip_sources)
    if "A3" in tiers:
        anchors.register_a3_onset(con)
    selects = []
    # per-major qualifying bachelor populations
    for key, (_name, fams, _tier) in C.MAJORS.items():
        pred = C.major_cip_predicate(fams, "e")
        selects.append(anchors.group_anchor_sql(
            key, pred, degree_level=C.BACHELOR_LEVEL, alias="e", tiers=tiers, edu_table=edu))
    # baseline: any CIP-coded bachelor with a usable anchor (cip2-based so the
    # pooled table admits jury-coded rows; det-equivalent -- see _edu_table)
    selects.append(anchors.group_anchor_sql(
        C.BASELINE_KEY, "e.cip2 IS NOT NULL", degree_level=C.BACHELOR_LEVEL,
        alias="e", tiers=tiers, edu_table=edu))
    con.execute("CREATE OR REPLACE TEMP TABLE membership AS "
                + "\nUNION ALL\n".join(f"({s})" for s in selects))


def build_panel(con, soc_sources: tuple[str, ...] = None) -> None:
    """Person-year primary step for every population person, industry attached.

    ``soc_major`` / ``soc_source`` implement the pooled occupation column at
    major-group grain: the deterministic 6-digit backbone ALWAYS wins; a jury
    label fills in only where the backbone abstained, and only when "llm_jury"
    is in ``soc_sources`` AND the calibrated mapping parquet exists. 6-digit
    consumers keep reading ``occupation_code`` (deterministic-only)."""
    if soc_sources is None:
        soc_sources = C.SOC_SOURCES
    steps = f"read_parquet('{C.q(C.STEPS)}')"
    ind = f"read_parquet('{C.q(C.STEP_INDUSTRY)}')"
    use_jury = "llm_jury" in soc_sources and C.ROLE_SOC_JURY.exists()
    if use_jury:
        con.execute(f"""
          CREATE OR REPLACE TEMP TABLE role_jury AS
          SELECT role_canonical, soc_major AS jury_code
          FROM read_parquet('{C.q(C.ROLE_SOC_JURY)}')
        """)
        dup = con.execute(
            "SELECT count(*) - count(DISTINCT role_canonical) FROM role_jury"
        ).fetchone()[0]
        if dup:
            raise ValueError(
                f"role_soc_jury.parquet has {dup} duplicate role_canonical rows -- "
                "joining it would silently fan out the panel; rebuild it with "
                "career_clean.run_soc_jury merge")
    else:
        con.execute("CREATE OR REPLACE TEMP TABLE role_jury "
                    "(role_canonical VARCHAR, jury_code VARCHAR)")
    con.execute("""
      CREATE OR REPLACE TEMP TABLE pop_persons AS
      SELECT DISTINCT linkedin_id FROM membership
    """)
    # valid steps for population persons only
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE vstep AS
      SELECT s.row_id, s.linkedin_id, s.experience_idx, s.position_idx,
             s.source_table,
             year(s.start_dt) AS y0, year(s.end_dt) AS y1,
             s.seniority_score, s.occupation_code, s.job_zone_norm,
             s.role_canonical, s.tenure_months, s.company_raw
      FROM {steps} s
      SEMI JOIN pop_persons p ON p.linkedin_id = s.linkedin_id
      WHERE s.datable AND NOT s.bad_negative_duration AND NOT s.bad_future_start
        AND year(s.start_dt) <= {C.SNAPSHOT_CAL_YEAR}
    """)
    # normalize industry L1 to top-level code (a few rows leak dotted subcodes)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE step_ind AS
      SELECT linkedin_id, experience_idx, position_idx, source_table,
             min(split_part(l1, '.', 1)) AS l1
      FROM {ind}
      GROUP BY linkedin_id, experience_idx, position_idx, source_table
    """)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE panel AS
      WITH expanded AS (
        SELECT v.*, unnest(range(v.y0, least(v.y1, {C.SNAPSHOT_CAL_YEAR}) + 1)) AS cal_year
        FROM vstep v
      ),
      prim AS (
        SELECT * FROM expanded
        QUALIFY row_number() OVER (
          PARTITION BY linkedin_id, cal_year
          ORDER BY seniority_score DESC NULLS LAST, tenure_months DESC NULLS LAST,
                   row_id ASC
        ) = 1
      )
      SELECT p.linkedin_id, p.cal_year, p.y0 AS step_start_year,
             p.seniority_score, p.occupation_code, p.job_zone_norm,
             p.role_canonical, p.tenure_months, p.company_raw,
             si.l1 AS industry_l1,
             CASE WHEN p.occupation_code IS NOT NULL
                    THEN {C.soc_major_case('p.occupation_code')}
                  ELSE {C.soc_major_label_case('rj.jury_code')}
             END AS soc_major,
             CASE WHEN p.occupation_code IS NOT NULL THEN 'det'
                  WHEN rj.jury_code IS NOT NULL THEN 'jury'
             END AS soc_source
      FROM prim p
      LEFT JOIN step_ind si
        ON si.linkedin_id = p.linkedin_id
       AND si.experience_idx IS NOT DISTINCT FROM p.experience_idx
       AND si.position_idx  IS NOT DISTINCT FROM p.position_idx
       AND si.source_table   = p.source_table
      LEFT JOIN role_jury rj
        ON p.occupation_code IS NULL AND rj.role_canonical = p.role_canonical
    """)


def boundary_counts(con) -> dict:
    """Nested humanities-tier record and person counts, re-derived from the
    committed education crosswalk (supersedes the stale doc figures)."""
    edu = f"read_parquet('{C.q(C.EDUCATION)}')"
    out = {}
    for tier, levels in (("l1", "= 1"), ("l2", "IN (1, 2)"), ("l3", "IN (1, 2, 3)")):
        r = con.execute(
            f"SELECT count(*), count(DISTINCT linkedin_id) "
            f"FROM {edu} WHERE nha_level {levels}").fetchone()
        out[tier] = {"records": int(r[0]), "persons": int(r[1])}
    return out


def _group_funnel_one(con, edu: str, key: str, base: str, win_cut: int) -> dict:
    records = con.execute(f"SELECT count(*) {base}").fetchone()[0]
    persons = con.execute(f"SELECT count(DISTINCT e.linkedin_id) {base}").fetchone()[0]
    # A1-only anchored count, for direct before/after comparability with the
    # pre-Plan-2 funnel (portal/FINDINGS.md). Independent of `membership`.
    anchored_a1 = con.execute(
        f"SELECT count(DISTINCT e.linkedin_id) {base} AND {_usable_anchor_sql('e')}"
    ).fetchone()[0]
    # Tiered anchored count: whatever common.ANCHOR_TIERS produced into
    # `membership` (default A1+A2; see edu_clean/results/anchor_eval.json).
    anchored = con.execute(
        f"SELECT count(DISTINCT linkedin_id) FROM membership WHERE group_key = '{key}'"
    ).fetchone()[0]
    w10 = con.execute(
        f"SELECT count(DISTINCT linkedin_id) FROM membership "
        f"WHERE group_key = '{key}' AND anchor <= {win_cut}").fetchone()[0]
    mix_rows = con.execute(
        f"SELECT anchor_method, count(*) FROM membership WHERE group_key = '{key}' "
        f"GROUP BY 1").fetchall()
    anchor_method_mix = {m: round(n / anchored, 4) for m, n in mix_rows} if anchored else {}
    return {
        "records": int(records), "persons": int(persons),
        "persons_anchored_a1": int(anchored_a1),
        "persons_anchored": int(anchored),
        "persons_windowed_y10": int(w10),
        "anchor_drop_rate_a1": round(1 - anchored_a1 / persons, 4) if persons else None,
        "anchor_drop_rate": round(1 - anchored / persons, 4) if persons else None,
        "anchor_method_mix": anchor_method_mix,
    }


def group_funnel(con, cip_sources: tuple[str, ...] = None) -> dict:
    """Per group: raw qualifying records, distinct persons, the windowed
    year-10 analyzable person count, the (tiered) anchor drop rate, the
    anchor_method_mix (COVERAGE_PLAN.md Plan 2), and -- when CIP pooling is
    active -- the cip_source_mix (share of the group's persons admitted only
    by jury-coded field rows). `persons_anchored_a1` / `anchor_drop_rate_a1`
    are kept alongside the tiered numbers so the Plan-2 before/after funnel
    in portal/FINDINGS.md is directly derivable."""
    if cip_sources is None:
        cip_sources = C.CIP_SOURCES
    edu = _edu_table(con, cip_sources)
    pooled = edu == "edu_pooled"
    win_cut = C.SNAPSHOT_YEAR - C.FAN_YEAR
    out = {}

    def one(key, pred):
        base = f"FROM {edu} e WHERE e.degree_level = {C.BACHELOR_LEVEL} AND ({pred})"
        f = _group_funnel_one(con, edu, key, base, win_cut)
        if pooled:
            rows = con.execute(f"""
              SELECT src, count(*) FROM (
                SELECT e.linkedin_id,
                       CASE WHEN bool_or(e.cip_source = 'det') THEN 'det'
                            ELSE 'jury' END AS src
                {base} GROUP BY e.linkedin_id
              ) GROUP BY 1""").fetchall()
            tot = sum(n for _, n in rows)
            f["cip_source_mix"] = {s: round(n / tot, 4) for s, n in rows} if tot else {}
        else:
            f["cip_source_mix"] = {"det": 1.0}
        return f

    for key, (_name, fams, _tier) in C.MAJORS.items():
        out[key] = one(key, C.major_cip_predicate(fams, "e"))
    out[C.BASELINE_KEY] = one(C.BASELINE_KEY, "e.cip2 IS NOT NULL")
    return out
