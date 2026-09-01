"""Choices: how concrete decisions relate to the possibility space.

Person-level choice flags (double major / grad school / internship / military /
service year / self-employment) joined to the membership spine with NO fan-out
(one row per (group_key, linkedin_id); tested), outcomes computed on the
windowed year-10 cohort under the existing equal-window discipline. Minors and
study abroad exist only as free text in the data and ship as honest
"not measured" counts.

Every named cell clears C.MIN_SUPPORT (the single global bar); a choice-subset
fan that cannot populate ships null plus a suppressed-cell count, never a
thinner bar. All comparisons are DESCRIPTIVE associations among LinkedIn
survivors -- the choice flags are self-selected, so nothing here is a causal
effect of the choice (the caveat ships in `choices_notes.causal_caveat`).

Definitions were probed against the committed parquets 2026-07-13 (pooled
five-major windowed cohort, n=22,294) -- probe numbers are recorded next to
each knob and restated in `choices_notes`.
"""

from __future__ import annotations

from edu_clean import cip_taxonomy
from portal import build, common as C
from portal import launchboard as LB

ALL_GROUPS = list(C.MAJORS.keys()) + [C.BASELINE_KEY]

# --- Internship ---------------------------------------------------------------
# Word-boundary match so "international sales manager" / "internal auditor" /
# "internist" never count. Probe (humanities steps): LIKE '%intern%' = 5,070
# steps vs word-boundary = 4,678; every excluded string inspected was an
# international/internal/internet/internist role; kept matches are face-valid
# ("graphic design intern", "legal intern", ...).
INTERN_RE = r"\b(intern|interns|internship|internships)\b"
# Start-year window relative to the graduation anchor. Probed distribution
# peaks at rel -1/0 (senior year and graduation year); [-4, +1] = 2,147 pooled
# persons vs 2,286 at [-4, +2] -- the +2 tail is mostly post-grad placements,
# not degree-attached internships. Chosen: degree years plus the first year out.
INTERN_WINDOW = (-4, 1)

# --- Military service ---------------------------------------------------------
# Branch names on company_raw, word-boundary; explicit exclusions for the
# probed false positives (71 of 821 naive pooled matches): The Salvation Army,
# Old Navy, Navy Federal Credit Union, AAFES / exchange services.
MILITARY_RE = (r"\b(army|navy|marine corps|marines|air force|national guard"
               r"|coast guard)\b")
MILITARY_EXCLUDE_RE = (r"salvation army|old navy|navy federal|aafes"
                       r"|air ?force exchange|navy exchange")
# Probed rel-year distribution is bimodal: pre-college service (rel <= -5,
# veterans who enrolled after serving) and degree-attached service (ROTC years
# and post-grad commissioning, rel -4..+5). [-4, +5] = 367 pooled persons and
# captures the degree-launch-relevant service; earlier veteran service is a
# different life sequence and is excluded (documented in choices_notes).
MILITARY_WINDOW = (-4, 5)

# --- Service year -------------------------------------------------------------
# company_raw program matches. Fulbright needs an exclusion: "Norton Rose
# Fulbright" / "Fulbright & Jaworski" are a law firm (7 of 20 naive pooled
# matches). Window [-1, +5]: probed starts concentrate at graduation..+2; -1
# absorbs anchor imprecision (senior-year starts).
SERVICE_PROGRAMS: tuple[tuple[str, str, str | None], ...] = (
    ("Peace Corps", r"peace corps", None),
    ("AmeriCorps", r"americorps", None),
    ("Teach For America", r"teach for america", None),
    ("Fulbright", r"fulbright", r"norton rose|jaworski"),
    ("City Year", r"\bcity year\b", None),
)
SERVICE_WINDOW = (-1, 5)

# --- Self-employment ----------------------------------------------------------
# Any post-anchor step whose employment_type marks working for oneself.
# steps.employment_type values probed: business_owner 267k / self_employed 192k
# repo-wide; 'freelance' does not exist as a type (freelancers carry these two).
SE_TYPES = ("business_owner", "self_employed")

# Grad-school flag REUSES the launchboard grad-track definition (a grad /
# professional degree STARTED within GRAD_HORIZON years of the bachelor
# anchor; start-dated, so equal-window) so the two surfaces can never disagree
# on what "went to grad school" means. Levels/horizon are imported, not copied.
GRAD_LEVELS = LB.GRAD_LEVELS
GRAD_HORIZON = LB.GRAD_HORIZON

SE_TOP_GROUPS = 8
PARTNER_TOP = 10


def _service_pred(comp: str) -> str:
    """SQL predicate: `comp` (a lowered company string column) matches any
    service-year program, applying per-program exclusions."""
    parts = []
    for _name, pat, exc in SERVICE_PROGRAMS:
        p = f"regexp_matches({comp}, '{pat}')"
        if exc:
            p += f" AND NOT regexp_matches({comp}, '{exc}')"
        parts.append(f"({p})")
    return "(" + " OR ".join(parts) + ")"


def _se_list() -> str:
    return ", ".join(f"'{t}'" for t in SE_TYPES)


def _fan_cells(counts: list[tuple[str | None, int]], base_share: dict[str, float]):
    """counts: (soc_major|None, n) rows for ONE choice subset. Returns
    (fan|None, suppressed_cells, unclassified_share, subset_n)."""
    subset_n = sum(n for _s, n in counts)
    unclass = sum(n for s, n in counts if s is None)
    cells, suppressed = [], 0
    for s, n in counts:
        if s is None:
            continue
        if n < C.MIN_SUPPORT:
            suppressed += 1
            continue
        share = n / subset_n
        bs = base_share.get(s)
        cells.append({"group": s, "n": int(n), "share": round(share, 4),
                      "rr": round(share / bs, 3) if bs else None})
    cells.sort(key=lambda c: (-c["share"], c["group"]))
    return (cells or None), suppressed, \
        (round(unclass / subset_n, 4) if subset_n else None), subset_n


def _materialize(con) -> None:
    """Build every choices temp table on `con`. Requires membership + panel."""
    cut = C.SNAPSHOT_YEAR - C.FAN_YEAR
    steps = f"read_parquet('{C.q(C.STEPS)}')"
    edu_raw = f"read_parquet('{C.q(C.EDUCATION)}')"

    # windowed cohort at (group, person) grain; pooled = union of the five
    # majors' windowed cohorts, deduped by person (earliest anchor wins so the
    # pooled window discipline is at least as strict as any member group's).
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE ch_cohort AS
      SELECT group_key, linkedin_id, anchor FROM membership WHERE anchor <= {cut}
    """)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE ch_pool AS
      SELECT linkedin_id, min(anchor) AS anchor FROM ch_cohort
      WHERE group_key != '{C.BASELINE_KEY}' GROUP BY 1
    """)

    # valid dated steps for cohort persons (same validity filters as build.vstep)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE ch_steps AS
      SELECT s.linkedin_id, s.row_id, year(s.start_dt) AS sy,
             lower(coalesce(s.title_raw, '')) AS title,
             lower(coalesce(s.company_raw, '')) AS comp,
             s.employment_type, s.occupation_code, s.role_canonical
      FROM {steps} s
      SEMI JOIN (SELECT DISTINCT linkedin_id FROM ch_cohort) p
        ON p.linkedin_id = s.linkedin_id
      WHERE s.datable AND NOT s.bad_negative_duration AND NOT s.bad_future_start
        AND year(s.start_dt) <= {C.SNAPSHOT_CAL_YEAR}
    """)

    # person-level step-derived flags at (group, person) grain -- GROUP BY the
    # spine keys, so the join can NEVER fan out (asserted in portal_tests).
    i0, i1 = INTERN_WINDOW
    m0, m1 = MILITARY_WINDOW
    s0, s1 = SERVICE_WINDOW
    flag_sql = f"""
      SELECT c.group_key, c.linkedin_id,
        coalesce(bool_or(regexp_matches(s.title, '{INTERN_RE}')
                 AND s.sy - c.anchor BETWEEN {i0} AND {i1}), FALSE) AS intern,
        coalesce(bool_or(regexp_matches(s.comp, '{MILITARY_RE}')
                 AND NOT regexp_matches(s.comp, '{MILITARY_EXCLUDE_RE}')
                 AND s.sy - c.anchor BETWEEN {m0} AND {m1}), FALSE) AS military,
        coalesce(bool_or({_service_pred('s.comp')}
                 AND s.sy - c.anchor BETWEEN {s0} AND {s1}), FALSE) AS service,
        coalesce(bool_or(s.employment_type IN ({_se_list()})
                 AND s.sy >= c.anchor), FALSE) AS se,
        min(CASE WHEN s.employment_type IN ({_se_list()}) AND s.sy >= c.anchor
                 THEN s.sy - c.anchor END) AS se_first_years
      FROM ch_cohort c
      LEFT JOIN ch_steps s ON s.linkedin_id = c.linkedin_id
      GROUP BY 1, 2
    """
    con.execute(f"CREATE OR REPLACE TEMP TABLE ch_flags AS {flag_sql}")
    # same flags at pooled grain (pooled anchor)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE ch_pool_flags AS
      {flag_sql.replace("c.group_key, c.linkedin_id,", "c.linkedin_id,")
               .replace("FROM ch_cohort c", "FROM ch_pool c")
               .replace("GROUP BY 1, 2", "GROUP BY 1")}
    """)

    # double major: 2+ distinct CIP2 families among non-duplicate bachelor rows
    # (the same pooled det+jury education table membership itself is built on)
    edu_t = build._edu_table(con, C.CIP_SOURCES)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE ch_dm_fields AS
      SELECT DISTINCT linkedin_id, cip2 FROM {edu_t} e
      WHERE degree_level = {C.BACHELOR_LEVEL} AND cip2 IS NOT NULL
        AND NOT coalesce(is_duplicate, FALSE)
    """)
    con.execute("""
      CREATE OR REPLACE TEMP TABLE ch_dm AS
      SELECT linkedin_id, count(*) AS k FROM ch_dm_fields GROUP BY 1
    """)

    # grad-school flag: launchboard grad-track definition on the y10 cohort
    levels = ", ".join(str(l) for l in GRAD_LEVELS)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE ch_grad AS
      SELECT DISTINCT c.group_key, c.linkedin_id
      FROM ch_cohort c
      JOIN {edu_raw} e ON e.linkedin_id = c.linkedin_id
      WHERE e.degree_level IN ({levels})
        AND e.start_year IS NOT NULL
        AND e.start_year BETWEEN {C.MIN_ANCHOR_YEAR} AND {C.SNAPSHOT_YEAR}
        AND e.start_year >= c.anchor
        AND e.start_year - c.anchor <= {GRAD_HORIZON}
    """)

    # year-10 endpoints (group grain + pooled grain)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE ch_ep AS
      SELECT c.group_key, c.linkedin_id, p.soc_major
      FROM ch_cohort c
      LEFT JOIN panel p ON p.linkedin_id = c.linkedin_id
                       AND p.cal_year = c.anchor + {C.FAN_YEAR}
    """)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE ch_pool_ep AS
      SELECT c.linkedin_id, p.soc_major
      FROM ch_pool c
      LEFT JOIN panel p ON p.linkedin_id = c.linkedin_id
                       AND p.cal_year = c.anchor + {C.FAN_YEAR}
    """)

    # first post-anchor self-employment step per POOLED person, classified at
    # SOC major-group grain with the same det-wins / jury-fills pooling as the
    # panel (build.build_panel); jury read directly from the calibrated parquet
    # because the substrate cache does not recreate the role_jury temp table.
    use_jury = "llm_jury" in C.SOC_SOURCES and C.ROLE_SOC_JURY.exists()
    if use_jury:
        con.execute(f"""
          CREATE OR REPLACE TEMP TABLE ch_role_jury AS
          SELECT role_canonical, soc_major AS jury_code
          FROM read_parquet('{C.q(C.ROLE_SOC_JURY)}')
        """)
    else:
        con.execute("CREATE OR REPLACE TEMP TABLE ch_role_jury "
                    "(role_canonical VARCHAR, jury_code VARCHAR)")
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE ch_first_se AS
      SELECT c.linkedin_id, s.sy - c.anchor AS yrs,
             CASE WHEN s.occupation_code IS NOT NULL
                    THEN {C.soc_major_case('s.occupation_code')}
                  ELSE {C.soc_major_label_case('rj.jury_code')}
             END AS soc_major
      FROM ch_pool c
      JOIN ch_steps s ON s.linkedin_id = c.linkedin_id
      LEFT JOIN ch_role_jury rj
        ON s.occupation_code IS NULL AND rj.role_canonical = s.role_canonical
      WHERE s.employment_type IN ({_se_list()}) AND s.sy >= c.anchor
      QUALIFY row_number() OVER (PARTITION BY c.linkedin_id
                                 ORDER BY s.sy, s.row_id) = 1
    """)


def _subset_fan(con, group: str, join_sql: str, base_share: dict):
    counts = con.execute(f"""
      SELECT ep.soc_major, count(*) FROM ch_ep ep {join_sql}
      WHERE ep.group_key = '{group}' GROUP BY 1
    """).fetchall()
    return _fan_cells([(s, int(n)) for s, n in counts], base_share)


def compute(con) -> dict:
    """Returns {"per_group": {...}, "pooled": {...}, "not_measured": {...},
    "notes": {...}}. Requires membership + panel on `con`."""
    _materialize(con)

    cohort_n = {g: int(n) for g, n in con.execute(
        "SELECT group_key, count(*) FROM ch_cohort GROUP BY 1").fetchall()}
    pool_n = int(con.execute("SELECT count(*) FROM ch_pool").fetchone()[0])

    # baseline y10 fan shares (rr denominator, same convention as the main fan)
    b_counts = con.execute(f"""
      SELECT soc_major, count(*) FROM ch_ep
      WHERE group_key = '{C.BASELINE_KEY}' GROUP BY 1""").fetchall()
    b_denom = sum(n for _s, n in b_counts)
    base_share = {s: n / b_denom for s, n in b_counts if s is not None}

    # participation counts per (group, choice)
    part = {g: dict(zip(("intern", "military", "service", "se"), r)) for g, *r in
            con.execute("""
              SELECT group_key,
                     count(*) FILTER (WHERE intern),
                     count(*) FILTER (WHERE military),
                     count(*) FILTER (WHERE service),
                     count(*) FILTER (WHERE se)
              FROM ch_flags GROUP BY 1""").fetchall()}
    se_med = {g: m for g, m in con.execute("""
      SELECT group_key, median(se_first_years) FROM ch_flags
      WHERE se GROUP BY 1""").fetchall()}
    dm_n = {g: int(n) for g, n in con.execute("""
      SELECT c.group_key, count(*) FROM ch_cohort c
      JOIN ch_dm d ON d.linkedin_id = c.linkedin_id AND d.k >= 2
      GROUP BY 1""").fetchall()}
    grad_n = {g: int(n) for g, n in con.execute(
        "SELECT group_key, count(*) FROM ch_grad GROUP BY 1").fetchall()}

    def share(n, d):
        return round(n / d, 4) if d else None

    per_group = {}
    for g in ALL_GROUPS:
        d = cohort_n.get(g, 0)
        p = part.get(g, {})
        ndm, ngr = dm_n.get(g, 0), grad_n.get(g, 0)
        n_int, n_mil = int(p.get("intern", 0)), int(p.get("military", 0))
        n_srv, n_se = int(p.get("service", 0)), int(p.get("se", 0))
        med = se_med.get(g)
        block = {
            "cohort": d,
            "double_major": {
                "n_windowed": ndm, "participation_share": share(ndm, d),
                "top_partners": None,
                "note": ("Partner-field detail is pooled across the five majors "
                         "-- see the pooled card in the Portal's Choices view; "
                         "per-major partner cells are too thin to name."),
            },
            "grad_school": {
                "n_grad": ngr, "n_nograd": d - ngr,
                "participation_share": share(ngr, d),
            },
            "internship": {
                "n_windowed": n_int, "participation_share": share(n_int, d),
                "window": list(INTERN_WINDOW),
            },
            "military": {
                "n_windowed": n_mil, "participation_share": share(n_mil, d),
                "window": list(MILITARY_WINDOW),
            },
            "service_year": (
                {"n_windowed": n_srv, "participation_share": share(n_srv, d),
                 "window": list(SERVICE_WINDOW)}
                if n_srv >= C.MIN_SUPPORT else None),
            "self_employment": {
                "n_windowed": n_se, "ever_share": share(n_se, d),
                "median_years_to_first":
                    round(float(med), 1) if med is not None else None,
            },
        }
        if g != C.BASELINE_KEY:
            # destination fans for the choice subsets (participation-only for
            # the baseline, per the plan)
            fan, sup, unc, _n = _subset_fan(
                con, g, "JOIN ch_dm d ON d.linkedin_id = ep.linkedin_id AND d.k >= 2",
                base_share)
            block["double_major"].update(
                fan=fan, fan_suppressed_cells=sup, unclassified_share=unc)
            fan, sup, unc, _n = _subset_fan(
                con, g, "SEMI JOIN ch_grad gr ON gr.group_key = ep.group_key "
                        "AND gr.linkedin_id = ep.linkedin_id", base_share)
            block["grad_school"].update(
                fan_grad=fan, fan_grad_suppressed_cells=sup,
                unclassified_share_grad=unc)
            fan, sup, unc, _n = _subset_fan(
                con, g, "ANTI JOIN ch_grad gr ON gr.group_key = ep.group_key "
                        "AND gr.linkedin_id = ep.linkedin_id", base_share)
            block["grad_school"].update(
                fan_nograd=fan, fan_nograd_suppressed_cells=sup,
                unclassified_share_nograd=unc)
            for key, flag in (("internship", "intern"), ("military", "military")):
                fan, sup, unc, _n = _subset_fan(
                    con, g, f"JOIN ch_flags f ON f.group_key = ep.group_key "
                            f"AND f.linkedin_id = ep.linkedin_id AND f.{flag}",
                    base_share)
                block[key].update(
                    fan=fan, fan_suppressed_cells=sup, unclassified_share=unc)
        per_group[g] = block

    # ---- pooled block ---------------------------------------------------------
    # double major: pooled fan + partner fields (per (major, person): every
    # OTHER bachelor family; deduped on (person, partner) across majors so an
    # English+History double major contributes History from the English side
    # and English from the History side, exactly once each).
    dm_pool_counts = con.execute("""
      SELECT ep.soc_major, count(*) FROM ch_pool_ep ep
      JOIN ch_dm d ON d.linkedin_id = ep.linkedin_id AND d.k >= 2
      GROUP BY 1""").fetchall()
    dm_fan, dm_sup, dm_unc, dm_pool_n = _fan_cells(
        [(s, int(n)) for s, n in dm_pool_counts], base_share)
    partner_selects = []
    for key, (_name, fams, _tier) in C.MAJORS.items():
        fam = ", ".join(f"'{f}'" for f in fams)
        partner_selects.append(f"""
          SELECT DISTINCT f.linkedin_id, f.cip2
          FROM ch_cohort c
          JOIN ch_dm d ON d.linkedin_id = c.linkedin_id AND d.k >= 2
          JOIN ch_dm_fields f ON f.linkedin_id = c.linkedin_id
          WHERE c.group_key = '{key}' AND f.cip2 NOT IN ({fam})""")
    partners = con.execute(
        "SELECT cip2, count(DISTINCT linkedin_id) AS n FROM ("
        + " UNION ".join(partner_selects)
        + ") GROUP BY 1 ORDER BY n DESC, cip2").fetchall()
    top_partners = [
        {"cip2": c, "label": cip_taxonomy.FAMILIES.get(c, c), "n": int(n)}
        for c, n in partners if n >= C.MIN_SUPPORT][:PARTNER_TOP]

    # service year: per-program n + pooled fan of any-program participants
    prog_rows = []
    s0, s1 = SERVICE_WINDOW
    for name, pat, exc in SERVICE_PROGRAMS:
        pred = f"regexp_matches(s.comp, '{pat}')"
        if exc:
            pred += f" AND NOT regexp_matches(s.comp, '{exc}')"
        n = con.execute(f"""
          SELECT count(DISTINCT c.linkedin_id) FROM ch_pool c
          JOIN ch_steps s ON s.linkedin_id = c.linkedin_id
          WHERE {pred} AND s.sy - c.anchor BETWEEN {s0} AND {s1}
        """).fetchone()[0]
        prog_rows.append((name, int(n)))
    programs = [{"name": nm, "n": n} for nm, n in prog_rows if n >= C.MIN_SUPPORT]
    programs_suppressed = sum(1 for _nm, n in prog_rows if 0 < n < C.MIN_SUPPORT)
    srv_any = int(con.execute(
        "SELECT count(*) FROM ch_pool_flags WHERE service").fetchone()[0])
    srv_counts = con.execute("""
      SELECT ep.soc_major, count(*) FROM ch_pool_ep ep
      JOIN ch_pool_flags f ON f.linkedin_id = ep.linkedin_id AND f.service
      GROUP BY 1""").fetchall()
    srv_fan, srv_sup, srv_unc, _srv_n = _fan_cells(
        [(s, int(n)) for s, n in srv_counts], base_share)

    # self-employment: pooled stats + top SOC groups of the first SE step
    se_pool_n = int(con.execute(
        "SELECT count(*) FROM ch_pool_flags WHERE se").fetchone()[0])
    se_pool_med = con.execute(
        "SELECT median(se_first_years) FROM ch_pool_flags WHERE se").fetchone()[0]
    se_soc = con.execute("""
      SELECT soc_major, count(*) FROM ch_first_se
      WHERE soc_major IS NOT NULL GROUP BY 1
      ORDER BY 2 DESC, 1""").fetchall()
    se_classified = sum(n for _s, n in se_soc)
    se_total = int(con.execute("SELECT count(*) FROM ch_first_se").fetchone()[0])
    top_groups = [
        {"group": s, "n": int(n), "share": round(n / se_classified, 4)}
        for s, n in se_soc if n >= C.MIN_SUPPORT][:SE_TOP_GROUPS]

    pooled = {
        "population_def": (
            "Union of the five majors' windowed year-10 cohorts, deduped by "
            "person (a multi-major person counts once, at their earliest "
            "anchor)."),
        "n_windowed": pool_n,
        "double_major": {
            "n": dm_pool_n, "participation_share": share(dm_pool_n, pool_n),
            "top_partners": top_partners,
            "fan": dm_fan, "fan_suppressed_cells": dm_sup,
            "unclassified_share": dm_unc,
        },
        "service_year": {
            "programs": programs, "programs_suppressed": programs_suppressed,
            "n_any": srv_any, "participation_share": share(srv_any, pool_n),
            "window": list(SERVICE_WINDOW),
            "fan": srv_fan, "fan_suppressed_cells": srv_sup,
            "unclassified_share": srv_unc,
            "pooled_only": True,
        },
        "self_employment": {
            "n": se_pool_n, "ever_share": share(se_pool_n, pool_n),
            "median_years_to_first":
                round(float(se_pool_med), 1) if se_pool_med is not None else None,
            "top_groups": top_groups,
            "first_se_classified_share":
                round(se_classified / se_total, 4) if se_total else None,
        },
    }

    # ---- not measured (free text only; honest counts, no parsing claimed) -----
    edu_raw = f"read_parquet('{C.q(C.EDUCATION)}')"
    minors = int(con.execute(f"""
      SELECT count(DISTINCT c.linkedin_id) FROM ch_pool c
      JOIN {edu_raw} e ON e.linkedin_id = c.linkedin_id
      WHERE regexp_matches(lower(coalesce(e.degree_raw, '') || ' ' ||
              coalesce(e.field_raw, '') || ' ' || coalesce(e.description, '')),
              '\\bminors?\\b')""").fetchone()[0])
    abroad = int(con.execute(f"""
      SELECT count(DISTINCT c.linkedin_id) FROM ch_pool c
      JOIN {edu_raw} e ON e.linkedin_id = c.linkedin_id
      WHERE regexp_matches(lower(coalesce(e.degree_raw, '') || ' ' ||
              coalesce(e.field_raw, '') || ' ' || coalesce(e.description, '')),
              '(study|studied|studying|semester|year) abroad')""").fetchone()[0])
    not_measured = {
        "minors": {
            "persons_mentioning": minors,
            "note": (
                "Free-text word match ('minor(s)') over degree/field/"
                "description rows of the pooled windowed cohort. Minors are "
                "NOT parsed into fields in this data -- this is a raw mention "
                "count (it can catch e.g. 'minority studies'), so no minor-"
                "based outcome claim is measurable yet."),
        },
        "study_abroad": {
            "persons_mentioning": abroad,
            "note": (
                "Free-text match ('study/studied/semester/year abroad') over "
                "degree/field/description rows of the pooled windowed cohort. "
                "Study abroad is unparsed free text -- an honest mention "
                "count only; no outcome claim is measurable yet."),
        },
    }

    notes = {
        "causal_caveat": (
            "Every number here is a description of people who chose these "
            "paths and stayed visible on LinkedIn -- not the effect of the "
            "choice. People pick double majors, grad school, internships, "
            "service, and self-employment for reasons the data cannot see."),
        "population": (
            "All outcomes are computed on the year-10 cohort: everyone "
            f"graduated by {C.SNAPSHOT_YEAR - C.FAN_YEAR}, so each person has "
            "a full ten-year window. Choice flags are matched person by "
            f"person. Named cells clear the {C.MIN_SUPPORT}-person reporting "
            "bar; a breakdown that cannot meet it is withheld and counted, "
            "never thinned."),
        "double_major": (
            "2+ distinct CIP2 families among a person's non-duplicate "
            "bachelor's rows (the same pooled det+jury field coding that "
            "builds membership). Partner fields are reported pooled across "
            "the five majors."),
        "grad_school": (
            "Reuses the launchboard grad-track definition: a graduate/"
            f"professional degree (levels {', '.join(map(str, GRAD_LEVELS))}) "
            f"STARTED within {GRAD_HORIZON} years of the bachelor anchor -- "
            "start-dated, so equal-window; enrollment, not completion."),
        "internship": (
            "A step whose title matches intern/internship as a whole word "
            "(word-boundary regex excludes international/internal/internist "
            "titles; probed: 5,070 LIKE-matches -> 4,678 kept), starting in "
            f"years [{INTERN_WINDOW[0]}, +{INTERN_WINDOW[1]}] of the anchor "
            "(degree years plus the first year out; probed start-year "
            "distribution peaks at -1/0). LinkedIn under-reports internships "
            "for older cohorts, so participation is a floor, not a rate."),
        "military": (
            "A step at a service-branch employer (army / navy / marine corps "
            "/ marines / air force / national guard / coast guard, word-"
            "boundary on company), excluding probed false positives "
            "(Salvation Army, Old Navy, Navy Federal, exchange services -- "
            "71 of 821 naive matches), starting in years "
            f"[{MILITARY_WINDOW[0]}, +{MILITARY_WINDOW[1]}] of the anchor. "
            "Pre-college service (veterans who enrolled after serving) falls "
            "outside the window by design. Civilian roles at military "
            "employers cannot be fully separated and are counted."),
        "service_year": (
            "A step at Peace Corps / AmeriCorps / Teach For America / "
            "Fulbright (law-firm 'Norton Rose Fulbright' excluded) / City "
            f"Year, starting in years [{SERVICE_WINDOW[0]}, "
            f"+{SERVICE_WINDOW[1]}] of the anchor. Program cells and fans are "
            "pooled across the five majors; per-major cells ship only where "
            "they clear the bar."),
        "self_employment": (
            "Any post-anchor step with employment_type in "
            f"{list(SE_TYPES)}. 'Ever' share and median years from anchor to "
            "the first such step; pooled top SOC groups classify each "
            "person's FIRST self-employed step with the same det-wins/"
            "jury-fills occupation pooling as the panel."),
    }

    return {"per_group": per_group, "pooled": pooled,
            "not_measured": not_measured, "notes": notes}
