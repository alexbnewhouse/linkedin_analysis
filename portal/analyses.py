"""Per-major analyses over the shared substrate (membership + panel + spine).

All statistics obey equal-window discipline: a year-N number includes only
people whose anchor is <= SNAPSHOT_YEAR - N, so every subject has a full window.
Every reported cell with person-support < MIN_SUPPORT is suppressed.
"""

from __future__ import annotations

from portal import common as C

ALL_GROUPS = list(C.MAJORS.keys()) + [C.BASELINE_KEY]


def _win_cut(y: int) -> int:
    return C.SNAPSHOT_YEAR - y


def register_occ_nodes(con) -> None:
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE occ_nodes AS "
        f"SELECT node, label, soc_major FROM read_parquet('{C.q(C.OCC_NODES)}')")


def cohort_sizes(con, year: int) -> dict[str, int]:
    rows = con.execute(
        f"SELECT group_key, count(*) FROM membership WHERE anchor <= {_win_cut(year)} "
        f"GROUP BY 1").fetchall()
    return {g: int(n) for g, n in rows}


# --- 2. Destination fan (SOC major group at year 10, pooled sources) --------
def destination_fan(con) -> dict:
    cut = _win_cut(C.FAN_YEAR)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE fan_endpoint AS
      SELECT m.group_key, m.linkedin_id,
             p.soc_major,
             p.soc_source,
             p.occupation_code AS occ_code
      FROM membership m
      LEFT JOIN panel p
        ON p.linkedin_id = m.linkedin_id AND p.cal_year = m.anchor + {C.FAN_YEAR}
      WHERE m.anchor <= {cut}
    """)
    denom = {g: n for g, n in con.execute(
        "SELECT group_key, count(*) FROM fan_endpoint GROUP BY 1").fetchall()}
    counts = con.execute("""
      SELECT group_key, soc_major, count(*) AS n
      FROM fan_endpoint WHERE soc_major IS NOT NULL
      GROUP BY 1, 2""").fetchall()
    unclass = {g: n for g, n in con.execute("""
      SELECT group_key, count(*) FROM fan_endpoint WHERE soc_major IS NULL
      GROUP BY 1""").fetchall()}
    src_rows = con.execute("""
      SELECT group_key, soc_source, count(*) FROM fan_endpoint
      WHERE soc_major IS NOT NULL GROUP BY 1, 2""").fetchall()
    src_mix: dict[str, dict[str, int]] = {}
    for g, src, n in src_rows:
        src_mix.setdefault(g, {})[src] = int(n)

    # baseline shares for RR
    base_share = {}
    for g, soc, n in counts:
        if g == C.BASELINE_KEY:
            base_share[soc] = n / denom[g]

    out = {}
    for g in ALL_GROUPS:
        d = denom.get(g, 0)
        fan = []
        for gg, soc, n in counts:
            if gg != g or n < C.MIN_SUPPORT:
                continue
            share = n / d
            bs = base_share.get(soc)
            rr = round(share / bs, 3) if bs else None
            fan.append({"group": soc, "share": round(share, 4), "rr": rr, "n": int(n)})
        fan.sort(key=lambda r: (-r["share"], r["group"]))
        classified = sum(src_mix.get(g, {}).values())
        out[g] = {
            "fan": fan,
            "unclassified_share": round(unclass.get(g, 0) / d, 4) if d else None,
            "denom": d,
            "soc_source_mix": {
                src: round(n / classified, 4)
                for src, n in sorted(src_mix.get(g, {}).items())
            } if classified else {},
        }
    return out


# --- 2b. What a big destination *means*: within-group occupation drill-down --
# For every SOC major group in a cohort's fan, break the cell open into the
# specific 6-digit occupations behind it. This exists ONLY over the
# deterministic slice: an endpoint carries a 6-digit occupation_code (and hence
# a nameable role) only when the O*NET backbone coded it; the LLM jury resolves
# to the major group alone, so jury endpoints have no role to show. The payload
# reports that split honestly per cell so the drill-down never overclaims:
#   group_total   = people in this major-group cell (== the fan cell's n)
#   detail_coded  = of those, how many carry a 6-digit role (deterministic)
#   roles         = individual roles clearing DETAIL_MIN_SUPPORT, share OF CELL
#   roles_shown_n = people covered by the named roles
#   other_coded_n = coded to a role, but every remaining role is below the bar
#   no_detail_n   = classified to the group only (jury) -- no role to show
# Named roles clear DETAIL_MIN_SUPPORT (10; since the 2026-07-13 loosening this
# coincides with the MIN_SUPPORT headline bar): a descriptive composition of
# the coded subset, on the same footing as the breadth KPI's >=5-person
# occupation-node reach. See common.DETAIL_MIN_SUPPORT. Finer roles fold into
# other_coded_n rather than being listed, and the UI badges the whole panel as
# a coded-subset composition.
def destination_fan_detail(con, endpoint: str = "fan_endpoint") -> dict:
    """Requires `endpoint` -- a temp table of (group_key, soc_major, occ_code)
    endpoint rows: fan_endpoint (built by destination_fan, year 10) or the
    launchboard's lb_ep snapshot endpoints (years 1/3/5) -- plus occ_nodes
    (with label) registered on `con`. The semantics are horizon-agnostic: the
    drill-down describes the det-coded slice of whatever endpoint the table
    holds, under the same coverage-split honesty contract."""
    rows = con.execute(f"""
      SELECT fe.group_key, fe.soc_major, o.label AS role, count(*) AS n
      FROM {endpoint} fe
      JOIN occ_nodes o ON o.node = fe.occ_code
      WHERE fe.occ_code IS NOT NULL AND fe.soc_major IS NOT NULL
      GROUP BY 1, 2, 3
    """).fetchall()
    # deterministic (role-coded) totals per (group_key, soc_major)
    coded = {(gk, soc): n for gk, soc, n in con.execute(f"""
      SELECT group_key, soc_major, count(*)
      FROM {endpoint} WHERE occ_code IS NOT NULL AND soc_major IS NOT NULL
      GROUP BY 1, 2""").fetchall()}
    cell_total = {(gk, soc): n for gk, soc, n in con.execute(f"""
      SELECT group_key, soc_major, count(*)
      FROM {endpoint} WHERE soc_major IS NOT NULL
      GROUP BY 1, 2""").fetchall()}

    by_cell: dict[tuple, list] = {}
    for g, soc, role, n in rows:
        by_cell.setdefault((g, soc), []).append((role, int(n)))

    out: dict[str, dict] = {g: {} for g in ALL_GROUPS}
    for (g, soc), roles in by_cell.items():
        total = cell_total.get((g, soc), 0)
        det = coded.get((g, soc), 0)
        kept = sorted(((r, n) for r, n in roles if n >= C.DETAIL_MIN_SUPPORT),
                      key=lambda t: (-t[1], t[0]))
        shown = sum(n for _, n in kept)
        out[g][soc] = {
            "group_total": total,
            "detail_coded": det,
            "roles": [
                {"role": r, "n": n, "share_of_group": round(n / total, 4) if total else None}
                for r, n in kept
            ],
            "roles_shown_n": shown,
            "other_coded_n": det - shown,
            "no_detail_n": total - det,
        }
    return out


# --- 2c. Diversity of the possibility space ----------------------------------
# First-class diversity stats per major (and baseline) for the possibility-
# space stat band (PORTAL_REDESIGN_PLAN.md Part 1). effective_destinations and
# top3_classified_share are computed over the FULL classified endpoint
# distribution (every SOC major group with n >= 1), not just cells clearing
# MIN_SUPPORT: they are scalar aggregates that name no cell, so suppression
# does not apply -- same footing as unclassified_share, which also aggregates
# below-bar people. groups_reached and top_bucket_share, by contrast, restate
# the *published* fan (cells clearing MIN_SUPPORT).
SOC_GROUPS_OF = 23  # BLS SOC major groups (transition_network.common.SOC_MAJOR)


def diversity(con, fan: dict) -> dict:
    """Requires fan_endpoint (materialized by destination_fan) on `con`;
    `fan` is destination_fan's output (for the published-cell stats)."""
    counts_rows = con.execute("""
      SELECT group_key, soc_major, count(*) AS n
      FROM fan_endpoint WHERE soc_major IS NOT NULL
      GROUP BY 1, 2""").fetchall()
    by_g: dict[str, list[int]] = {}
    for g, _soc, n in counts_rows:
        by_g.setdefault(g, []).append(int(n))
    out = {}
    for g in ALL_GROUPS:
        ns = sorted(by_g.get(g, []), reverse=True)
        classified = sum(ns)
        f = fan[g]
        cells = f["fan"]
        if classified:
            simpson = sum((n / classified) ** 2 for n in ns)
            eff = round(1.0 / simpson, 2)
            top3 = round(sum(ns[:3]) / classified, 4)
        else:
            eff, top3 = None, None
        out[g] = {
            "classified_n": classified,
            "unclassified_share": f["unclassified_share"],
            "effective_destinations": eff,
            "groups_reached": len(cells),
            "groups_of": SOC_GROUPS_OF,
            "top_bucket_share": cells[0]["share"] if cells else None,
            "top3_classified_share": top3,
        }
    return out


# --- 3/4. Breadth + distinctive destinations --------------------------------
def breadth_and_distinctive(con) -> dict:
    cut = _win_cut(C.FAN_YEAR)
    # Breadth: distinct occupation-network nodes reached as a primary occupation
    # within the first 10 years post-anchor, with >=5 person-support per node.
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE reach AS
      SELECT m.group_key, p.occupation_code AS node,
             count(DISTINCT m.linkedin_id) AS n_persons
      FROM membership m
      JOIN panel p ON p.linkedin_id = m.linkedin_id
      SEMI JOIN occ_nodes o ON o.node = p.occupation_code
      WHERE m.anchor <= {cut}
        AND p.cal_year - m.anchor BETWEEN 0 AND {C.FAN_YEAR}
        AND p.occupation_code IS NOT NULL
      GROUP BY 1, 2
    """)
    breadth = {g: int(n) for g, n in con.execute(
        f"SELECT group_key, count(*) FROM reach WHERE n_persons >= "
        f"{C.BREADTH_MIN_PERSONS} GROUP BY 1").fetchall()}

    # Distinctive: year-10 endpoint occupation node with RR >= DISTINCTIVE_RR
    # and n >= DISTINCTIVE_MIN (== MIN_SUPPORT) vs baseline.
    endpoint = con.execute("""
      SELECT group_key, occ_code AS node, count(*) AS n
      FROM fan_endpoint WHERE occ_code IS NOT NULL
      GROUP BY 1, 2""").fetchall()
    denom = {g: n for g, n in con.execute(
        "SELECT group_key, count(*) FROM fan_endpoint GROUP BY 1").fetchall()}
    base_share = {node: n / denom[C.BASELINE_KEY]
                  for g, node, n in endpoint if g == C.BASELINE_KEY}
    distinctive = {g: 0 for g in ALL_GROUPS}
    for g, node, n in endpoint:
        if n < C.DISTINCTIVE_MIN:
            continue
        bs = base_share.get(node)
        if not bs:
            continue
        rr = (n / denom[g]) / bs
        if rr >= C.DISTINCTIVE_RR:
            distinctive[g] += 1
    return {g: {"breadth": breadth.get(g, 0), "breadth_of": 824,
                "distinctive": distinctive.get(g, 0)} for g in ALL_GROUPS}


# --- 5/6. Upward-move share + median dwell ----------------------------------
def moves(con) -> dict:
    cut = _win_cut(C.FAN_YEAR)
    up_list = ", ".join(f"'{t}'" for t in C.UP_TYPES)
    trans = f"read_parquet('{C.q(C.TRANSITIONS)}')"
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE moveset AS
      SELECT m.group_key, t.transition_type, t.dwell_months
      FROM membership m
      JOIN {trans} t ON t.linkedin_id = m.linkedin_id
      WHERE m.anchor <= {cut}
        AND year(t.to_start_dt) - m.anchor BETWEEN 0 AND {C.FAN_YEAR}
    """)
    rows = con.execute(f"""
      SELECT group_key,
             count(*) AS total,
             count(*) FILTER (WHERE transition_type IN ({up_list})) AS up,
             median(dwell_months) AS dwell_med
      FROM moveset GROUP BY 1""").fetchall()
    out = {}
    for g, total, up, dwell in rows:
        out[g] = {
            "up_share": round(up / total, 4) if total else None,
            "dwell_median_mo": int(dwell) if dwell is not None else None,
            "n_edges": int(total),
        }
    return out


# --- 7. Long-view seniority curve -------------------------------------------
def curve(con) -> dict:
    frames = {g: {"years": [], "median_seniority": [], "n": []} for g in ALL_GROUPS}
    for y in C.CURVE_YEARS:
        cut = _win_cut(y)
        rows = con.execute(f"""
          SELECT m.group_key, median(p.seniority_score) AS med, count(*) AS n
          FROM membership m
          JOIN panel p ON p.linkedin_id = m.linkedin_id
                      AND p.cal_year = m.anchor + {y}
          WHERE m.anchor <= {cut} AND p.seniority_score IS NOT NULL
          GROUP BY 1""").fetchall()
        by_g = {g: (med, n) for g, med, n in rows}
        for g in ALL_GROUPS:
            med, n = by_g.get(g, (None, 0))
            frames[g]["years"].append(y)
            frames[g]["n"].append(int(n))
            frames[g]["median_seniority"].append(
                round(med, 4) if (n and n >= C.MIN_SUPPORT and med is not None) else None)
    return frames


# --- 8. Sectors reached (industry L1 at year 10) ----------------------------
def sectors(con) -> dict:
    labels = C.load_industry_l1_labels()
    counts = con.execute(f"""
      SELECT m.group_key,
             CASE WHEN p.industry_l1 IS NULL OR p.industry_l1 = '{C.INDUSTRY_UNRESOLVED_CODE}'
                  THEN NULL ELSE p.industry_l1 END AS l1,
             count(*) AS n
      FROM membership m
      LEFT JOIN panel p ON p.linkedin_id = m.linkedin_id
                       AND p.cal_year = m.anchor + {C.FAN_YEAR}
      WHERE m.anchor <= {_win_cut(C.FAN_YEAR)}
      GROUP BY 1, 2""").fetchall()
    denom = {g: n for g, n in con.execute(
        f"SELECT group_key, count(*) FROM membership WHERE anchor <= "
        f"{_win_cut(C.FAN_YEAR)} GROUP BY 1").fetchall()}
    out = {}
    for g in ALL_GROUPS:
        d = denom.get(g, 0)
        resolved, unresolved = [], 0
        for gg, l1, n in counts:
            if gg != g:
                continue
            if l1 is None:
                unresolved += n
            else:
                resolved.append((l1, n))
        resolved.sort(key=lambda r: (-r[1], r[0]))
        top = resolved[:C.SECTOR_TOP]
        rest = sum(n for _, n in resolved[C.SECTOR_TOP:])
        sec = [{"sector": labels.get(l1, l1), "share": round(n / d, 4), "n": int(n)}
               for l1, n in top if n >= C.MIN_SUPPORT]
        if rest >= C.MIN_SUPPORT:
            sec.append({"sector": "Other", "share": round(rest / d, 4), "n": int(rest)})
        out[g] = {"sectors": sec,
                  "industry_unresolved_share": round(unresolved / d, 4) if d else None}
    return out



# --- 9. The employer field (dispersion, not a top-employers list) -----------
# 2026-07-09 review replaced an "employer lens" that (a) quietly relaxed the
# suppression bar for NAMED-employer cells -- the most identifying cell type
# the portal could publish -- and (b) counted raw company strings. The honest
# probe at the then-40 bar (canonical ids, major x employer, years 0-5) found
# 1-3 cells per major, almost all self-employment markers: NO real employer
# concentrates a humanities cohort. That dispersion IS the finding, so the
# shipped feature reports it: aggregate SIZE BUCKETS (how many employers hired
# 1 / 2 / 3-5 / ... graduates) plus names ONLY at n >= MIN_SUPPORT (the single
# global bar -- 10 since the 2026-07-13 loosening; the bucket edges derive from
# it so the top bucket is exactly the named-eligible set). Nothing below the
# bar leaves the pipeline, even anonymously.
EMPLOYER_WINDOW_YEARS = 5
EMPLOYER_BUCKETS = ((1, 1), (2, 2), (3, 5),
                    (6, C.MIN_SUPPORT - 1), (C.MIN_SUPPORT, None))


def employer_field(con) -> dict:
    steps = f"read_parquet('{C.q(C.STEPS)}')"
    cut = _win_cut(EMPLOYER_WINDOW_YEARS)
    # NOTE on determinism (byte-reproducibility bug found 2026-07-14): the
    # display name used to be any_value(company_raw), which is thread-order-
    # dependent in DuckDB, and `labeled` ordered by n DESC with no tie-break --
    # both flipped between identical runs once the loosened bar surfaced many
    # more named employers. The name is now the employer's MODAL raw string
    # (ties broken lexicographically) and every ordering carries a total
    # tie-break.
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE emp_rel AS
      SELECT m.group_key,
             coalesce(s.company_canonical_id,
                      'raw:' || lower(trim(s.company_raw))) AS emp_id,
             s.company_raw AS raw_name,
             m.linkedin_id
      FROM membership m
      JOIN {steps} s ON s.linkedin_id = m.linkedin_id
      WHERE m.anchor <= {cut}
        AND s.datable AND NOT s.bad_negative_duration AND NOT s.bad_future_start
        AND year(s.start_dt) - m.anchor BETWEEN 0 AND {EMPLOYER_WINDOW_YEARS}
        AND (s.company_canonical_id IS NOT NULL
             OR (s.company_raw IS NOT NULL AND trim(s.company_raw) <> ''))
    """)
    con.execute("""
      CREATE OR REPLACE TEMP TABLE emp_field AS
      WITH agg AS (
        SELECT group_key, emp_id, count(DISTINCT linkedin_id) AS n
        FROM emp_rel GROUP BY 1, 2
      ),
      names AS (
        SELECT group_key, emp_id, raw_name AS emp_name
        FROM (
          SELECT group_key, emp_id, raw_name, count(*) AS c
          FROM emp_rel
          WHERE raw_name IS NOT NULL AND trim(raw_name) <> ''
          GROUP BY 1, 2, 3)
        QUALIFY row_number() OVER (PARTITION BY group_key, emp_id
                                   ORDER BY c DESC, raw_name) = 1
      )
      SELECT a.group_key, a.emp_id, nm.emp_name, a.n
      FROM agg a LEFT JOIN names nm USING (group_key, emp_id)
    """)
    stats = {g: dict(zip(("n_employers", "persons", "singletons"), r)) for g, *r in
             con.execute("""
               SELECT group_key, count(*), sum(n), sum(CASE WHEN n = 1 THEN 1 ELSE 0 END)
               FROM emp_field GROUP BY 1""").fetchall()}
    top10 = {g: t for g, t in con.execute("""
      SELECT group_key, sum(n) FROM (
        SELECT group_key, n, row_number() OVER (
          PARTITION BY group_key ORDER BY n DESC, emp_id) AS rk
        FROM emp_field) WHERE rk <= 10 GROUP BY 1""").fetchall()}
    labeled = {}
    # "Various ..." profile strings are aggregation junk, not employers -- they
    # stay in the size buckets but are never named (Self-Employed/Freelance
    # markers are real signals and stay).
    for g, name, n in con.execute(f"""
      SELECT group_key, emp_name, n FROM emp_field WHERE n >= {C.MIN_SUPPORT}
      ORDER BY group_key, n DESC, emp_name, emp_id""").fetchall():
        if name and name.strip().lower().startswith("various"):
            continue
        labeled.setdefault(g, []).append({"name": name, "n": int(n)})
    bucket_rows = con.execute("""
      SELECT group_key, n, count(*) FROM emp_field GROUP BY 1, 2""").fetchall()

    out = {}
    for g in ALL_GROUPS:
        st = stats.get(g)
        if not st:
            out[g] = None
            continue
        buckets = []
        for lo, hi in EMPLOYER_BUCKETS:
            cnt = sum(c for gg, n, c in bucket_rows
                      if gg == g and n >= lo and (hi is None or n <= hi))
            buckets.append({"size_min": lo, "size_max": hi, "employers": int(cnt)})
        persons = int(st["persons"])
        out[g] = {
            "window_years": EMPLOYER_WINDOW_YEARS,
            "employer_relationships": persons,
            "n_employers": int(st["n_employers"]),
            "singleton_employer_share": round(st["singletons"] / st["n_employers"], 4),
            "top10_share_of_cohort": round((top10.get(g, 0) or 0) / persons, 4),
            "size_buckets": buckets,
            "labeled": labeled.get(g, []),
        }
    return out
