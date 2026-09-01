"""Career Launchboard: the early-career module for the Stories layer.

Three empirically-gated components per major (+ baseline), all equal-window,
all n >= MIN_SUPPORT suppressed, pooled occupation sources:

  first_destinations   year-1 destination fan ("options at graduation":
                       the first observed classified occupation group).
  outlook              year-3 and year-5 destination fans.
  stability            the "strategic instability" evidence, probed 2026-07-09:
                       early-mover classes (0 / 1 / 2+ moves in years 0-3) with
                       (a) year-5 median seniority + median y0->y5 gain
                           [movers end at-or-above stayers everywhere; History
                            and Comm & Media mover premium exceeds baseline's;
                            Arts / Phil&Rel movers close a lower start = catch-up],
                       (b) continuity: gap-adjacent share of LATER moves
                           (years 4-10) [movers' moves are less gap-adjacent],
                       (c) exploration: mean distinct occupation groups and
                           industries touched in years 0-5.
                       HONEST NEGATIVE (measured, must ship with the feature):
                       early movers do NOT settle later -- their later moves
                       stay faster (median dwell 17-21mo vs stayers 26-33mo).
                       Mobility is a persistent style, not a phase.

Caveats carried into the JSON: mover classes are self-selected (descriptive,
never causal), seniority undercounts arts/self-employment careers, no wage
claims, revealed "down" is near-chance so no downward framing.
"""

from __future__ import annotations

from portal import analyses
from portal import common as C

HORIZONS = (1, 3, 5)          # first destinations + outlooks
MOVER_WINDOW = (0, 3)         # early moves counted in years 0..3
MOVER_OUTCOME_YEAR = 5        # outcome horizon for mover classes
LATE_WINDOW = (4, 10)         # "later moves" window (on the y10 cohort)
CLASSES = ("0", "1", "2+")

# --- Graduate & professional school as an early-career step ------------------
# Enrolling in a grad/professional degree is a real career step the job-only
# panel misses entirely (a full-time grad student with no job row otherwise
# falls into the fan's "unclassified" bucket). It is a START-DATED event -- ~95%
# of post-bachelor grad rows carry a usable start_year (vs ~20% end coverage on
# bachelors) -- so the equal-window rule applies cleanly: cohort = anchor <=
# SNAPSHOT_YEAR - GRAD_HORIZON, enrollment within [0, GRAD_HORIZON] of the
# bachelor anchor. All counts use count(DISTINCT linkedin_id) so a person's
# several grad degrees (MA then PhD; MA + MBA) never fan out.
GRAD_HORIZON = 5
GRAD_LEVELS = (5, 6, 7)       # 5 grad-unspecified, 6 master's, 7 doctorate
# The professional / field facet. degree_type is a degree KIND, so it must be
# read only on grad-level rows (business_admin@4 is a BBA; @6 is an MBA).
GRAD_TYPE_LABELS = {
    "law": "Law (JD)",
    "medicine": "Medicine (MD)",
    "dental": "Dentistry",
    "business_admin": "Business (MBA)",
    "public_health": "Public health (MPH)",
    "social_work": "Social work (MSW)",
    "nursing": "Nursing",
    "education": "Education",
    "fine_arts": "Fine arts (MFA)",
}
# Medicine (MD) is reported even where thin, per the advocacy brief: it is the
# rarest and most stereotype-breaking humanities->professional path, so it is
# shown down to a small privacy-safe floor and badged below the headline bar.
# Every other facet uses the drill-down's DETAIL_MIN_SUPPORT and is likewise
# badged when under MIN_SUPPORT. Headline (any / master's / doctorate) still
# clears MIN_SUPPORT the normal way.
GRAD_MEDICINE_FLOOR = 5

ALL_GROUPS = list(C.MAJORS.keys()) + [C.BASELINE_KEY]


def _grad_track(con) -> dict:
    """Per group: share enrolling in a graduate or professional degree within
    GRAD_HORIZON years of the bachelor anchor, split by level (master's /
    doctorate) and by professional/field type (Law, Medicine, ...). Reads
    membership + education only (no panel). Distinct-person counts throughout."""
    edu = f"read_parquet('{C.q(C.EDUCATION)}')"
    cut = C.SNAPSHOT_YEAR - GRAD_HORIZON
    levels = ", ".join(str(l) for l in GRAD_LEVELS)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE lb_grad AS
      SELECT m.group_key, m.linkedin_id, e.degree_level, e.degree_type
      FROM membership m
      JOIN {edu} e ON e.linkedin_id = m.linkedin_id
      WHERE m.anchor <= {cut}
        AND e.degree_level IN ({levels})
        AND e.start_year IS NOT NULL
        AND e.start_year BETWEEN {C.MIN_ANCHOR_YEAR} AND {C.SNAPSHOT_YEAR}
        AND e.start_year >= m.anchor
        AND e.start_year - m.anchor <= {GRAD_HORIZON}
    """)
    denom = {g: n for g, n in con.execute(
        f"SELECT group_key, count(*) FROM membership WHERE anchor <= {cut} "
        f"GROUP BY 1").fetchall()}
    anyg = {g: n for g, n in con.execute(
        "SELECT group_key, count(DISTINCT linkedin_id) FROM lb_grad "
        "GROUP BY 1").fetchall()}
    lvl_rows = con.execute("""
      SELECT group_key,
             CASE WHEN degree_level = 7 THEN 'Doctorate' ELSE 'Master''s' END AS cls,
             count(DISTINCT linkedin_id) AS n
      FROM lb_grad GROUP BY 1, 2""").fetchall()
    typ_rows = con.execute("""
      SELECT group_key, degree_type, count(DISTINCT linkedin_id) AS n
      FROM lb_grad WHERE degree_type IS NOT NULL GROUP BY 1, 2""").fetchall()

    bkey, bd = C.BASELINE_KEY, denom.get(C.BASELINE_KEY, 0)
    base_any = anyg.get(bkey, 0) / bd if bd else None
    base_lvl = {c: n / bd for g, c, n in lvl_rows if g == bkey and bd}
    base_typ = {t: n / bd for g, t, n in typ_rows if g == bkey and bd}

    def rr(share, base):
        return round(share / base, 3) if base else None

    out = {}
    for g in ALL_GROUPS:
        d = denom.get(g, 0)
        if not d:
            out[g] = None
            continue
        a = anyg.get(g, 0)
        by_level = []
        for cls in ("Master's", "Doctorate"):
            n = next((nn for gg, cc, nn in lvl_rows if gg == g and cc == cls), 0)
            if n >= C.MIN_SUPPORT:
                s = n / d
                by_level.append({"level": cls, "n": int(n), "share": round(s, 4),
                                 "rr": rr(s, base_lvl.get(cls))})
        by_type = []
        for t, label in GRAD_TYPE_LABELS.items():
            n = next((nn for gg, tt, nn in typ_rows if gg == g and tt == t), 0)
            floor = GRAD_MEDICINE_FLOOR if t == "medicine" else C.DETAIL_MIN_SUPPORT
            if n >= floor:
                s = n / d
                by_type.append({"type": label, "n": int(n), "share": round(s, 4),
                                "rr": rr(s, base_typ.get(t)),
                                "below_bar": n < C.MIN_SUPPORT})
        by_type.sort(key=lambda r: -r["n"])
        out[g] = {
            "horizon": GRAD_HORIZON,
            "cohort": int(d),
            "any": ({"n": int(a), "share": round(a / d, 4), "rr": rr(a / d, base_any)}
                    if a >= C.MIN_SUPPORT else None),
            "by_level": by_level,
            "by_type": by_type,
            "detail_bar": C.DETAIL_MIN_SUPPORT,
            "min_support": C.MIN_SUPPORT,
        }
    return out


def _fan_at(con, horizon: int) -> dict:
    """Destination fan at `horizon` years post-anchor (same rules as the
    year-10 fan: share of the full windowed cohort, RR vs baseline at the
    SAME horizon, cells under MIN_SUPPORT suppressed). Each emitted cell
    carries the same `detail` occupation drill-down as the year-10 fan
    (analyses.destination_fan_detail over this horizon's endpoint: det-coded
    subset only, roles clearing DETAIL_MIN_SUPPORT, honest coverage split).
    Requires occ_nodes registered on `con` (analyses.register_occ_nodes)."""
    cut = C.SNAPSHOT_YEAR - horizon
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE lb_ep AS
      SELECT m.group_key, m.linkedin_id, p.soc_major,
             p.occupation_code AS occ_code
      FROM membership m
      LEFT JOIN panel p ON p.linkedin_id = m.linkedin_id
                       AND p.cal_year = m.anchor + {horizon}
      WHERE m.anchor <= {cut}
    """)
    denom = {g: n for g, n in con.execute(
        "SELECT group_key, count(*) FROM lb_ep GROUP BY 1").fetchall()}
    counts = con.execute("""
      SELECT group_key, soc_major, count(*) FROM lb_ep
      WHERE soc_major IS NOT NULL GROUP BY 1, 2""").fetchall()
    base_share = {soc: n / denom[C.BASELINE_KEY]
                  for g, soc, n in counts if g == C.BASELINE_KEY}
    unclass = {g: n for g, n in con.execute(
        "SELECT group_key, count(*) FROM lb_ep WHERE soc_major IS NULL "
        "GROUP BY 1").fetchall()}
    out = {}
    for g in ALL_GROUPS:
        d = denom.get(g, 0)
        fan = []
        for gg, soc, n in counts:
            if gg != g or n < C.MIN_SUPPORT:
                continue
            share = n / d
            bs = base_share.get(soc)
            fan.append({"group": soc, "share": round(share, 4),
                        "rr": round(share / bs, 3) if bs else None, "n": int(n)})
        fan.sort(key=lambda r: (-r["share"], r["group"]))
        out[g] = {"cohort": d, "fan": fan,
                  "unclassified_share": round(unclass.get(g, 0) / d, 4) if d else None}
    # attach the within-cell occupation drill-down (same machinery and honesty
    # contract as the year-10 fan; a cell without any coded role ships null)
    detail = analyses.destination_fan_detail(con, endpoint="lb_ep")
    for g in ALL_GROUPS:
        for cell in out[g]["fan"]:
            cell["detail"] = detail[g].get(cell["group"])
    return out


def _mover_class_sql() -> str:
    return ("CASE WHEN moves = 0 THEN '0' WHEN moves = 1 THEN '1' "
            "ELSE '2+' END")


def _stability(con) -> dict:
    trans = f"read_parquet('{C.q(C.TRANSITIONS)}')"
    w0, w1 = MOVER_WINDOW
    l0, l1 = LATE_WINDOW
    y5cut = C.SNAPSHOT_YEAR - MOVER_OUTCOME_YEAR
    y10cut = C.SNAPSHOT_YEAR - C.FAN_YEAR

    # early-move counts for BOTH windows in one pass
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE lb_moves AS
      SELECT m.group_key, m.linkedin_id, m.anchor,
             count(t.linkedin_id) FILTER (
               WHERE year(t.to_start_dt) - m.anchor BETWEEN {w0} AND {w1}) AS moves
      FROM membership m
      LEFT JOIN {trans} t ON t.linkedin_id = m.linkedin_id
      WHERE m.anchor <= {y5cut}
      GROUP BY 1, 2, 3
    """)
    cls = _mover_class_sql()

    # (a) year-5 outcome by mover class
    outcome = con.execute(f"""
      SELECT l.group_key, {cls} AS cls,
             count(*) FILTER (WHERE p5.seniority_score IS NOT NULL) AS n,
             round(median(p5.seniority_score), 4) AS med_s5,
             round(median(p5.seniority_score) - median(p0.seniority_score), 4) AS med_gain
      FROM lb_moves l
      LEFT JOIN panel p0 ON p0.linkedin_id = l.linkedin_id AND p0.cal_year = l.anchor
      LEFT JOIN panel p5 ON p5.linkedin_id = l.linkedin_id
                        AND p5.cal_year = l.anchor + {MOVER_OUTCOME_YEAR}
      GROUP BY 1, 2
    """).fetchall()

    # (b) continuity + pace of LATER moves (full y10 window so late window fits)
    late = con.execute(f"""
      SELECT l.group_key, {cls} AS cls,
             count(*) AS n_moves,
             round(median(t.dwell_months), 1) AS med_dwell,
             round(avg(CASE WHEN t.has_gap THEN 1 ELSE 0 END), 4) AS gap_share
      FROM lb_moves l
      JOIN {trans} t ON t.linkedin_id = l.linkedin_id
      WHERE l.anchor <= {y10cut}
        AND year(t.to_start_dt) - l.anchor BETWEEN {l0} AND {l1}
      GROUP BY 1, 2
    """).fetchall()

    # (c) exploration breadth in years 0-5 (y10 cohort, consistent with (b))
    explore = con.execute(f"""
      WITH touch AS (
        SELECT l.group_key, l.linkedin_id, {cls} AS cls,
               count(DISTINCT p.soc_major) FILTER (WHERE p.soc_major IS NOT NULL) AS gr,
               count(DISTINCT p.industry_l1) FILTER (
                 WHERE p.industry_l1 IS NOT NULL
                   AND p.industry_l1 != '{C.INDUSTRY_UNRESOLVED_CODE}') AS ind
        FROM lb_moves l
        JOIN panel p ON p.linkedin_id = l.linkedin_id
                    AND p.cal_year - l.anchor BETWEEN 0 AND {MOVER_OUTCOME_YEAR}
        WHERE l.anchor <= {y10cut}
        GROUP BY 1, 2, 3
      )
      SELECT group_key, cls, count(*) AS n,
             round(avg(gr), 2) AS avg_groups, round(avg(ind), 2) AS avg_industries
      FROM touch GROUP BY 1, 2
    """).fetchall()

    out = {g: {c: {} for c in CLASSES} for g in ALL_GROUPS}
    for g, c, n, s5, gain in outcome:
        if g in out and n >= C.MIN_SUPPORT:
            out[g][c].update({"n_y5": int(n), "median_seniority_y5": s5,
                              "median_gain_y0_y5": gain})
    for g, c, n, dwell, gap in late:
        if g in out and n >= C.MIN_SUPPORT:
            out[g][c].update({"n_late_moves": int(n), "late_move_median_dwell_mo": dwell,
                              "late_move_gap_share": gap})
    for g, c, n, gr, ind in explore:
        if g in out and n >= C.MIN_SUPPORT:
            out[g][c].update({"n_explore": int(n), "avg_occupation_groups_y0_5": gr,
                              "avg_industries_y0_5": ind})
    return out


def compute(con) -> dict:
    fans = {h: _fan_at(con, h) for h in HORIZONS}
    stability = _stability(con)
    grad = _grad_track(con)
    out = {}
    for g in ALL_GROUPS:
        out[g] = {
            "first_destinations": fans[1][g],
            "outlook": {f"y{h}": fans[h][g] for h in HORIZONS if h != 1},
            "stability": stability[g],
            "grad_track": grad[g],
        }
    return out


NOTES = (
    "Launchboard evidence rules: mover classes (0/1/2+ moves in years 0-3) are "
    "self-selected -- every comparison is descriptive, never causal. Measured "
    "2026-07-09: movers end year 5 at or above stayers in every group "
    "(History and Communication & Media mover premiums exceed the all-graduate "
    "premium; Arts and Philosophy & Religion movers start lower and close the "
    "gap); movers' later moves are LESS gap-adjacent than stayers'; movers "
    "touch more occupation groups and industries by year 5. HONEST NEGATIVE, "
    "shipped with the feature: early movers do not settle later -- their later "
    "moves remain faster (median dwell 17-21 months vs stayers' 26-33). "
    "Seniority undercounts arts/self-employment careers; no wage claims; "
    "revealed downward moves are near-chance and are never framed. "
    "Graduate-school step: enrollment in a graduate/professional degree within "
    "5 years of the bachelor anchor (a start-dated event, so equal-window; "
    "distinct-person counts, no multi-degree fan-out). 'Any', master's and "
    f"doctorate cells clear the {C.MIN_SUPPORT}-person suppression bar; the "
    "professional/field facet (Law, Medicine, Business, ...) is a coded "
    f"breakdown shown at the {C.DETAIL_MIN_SUPPORT}-person drill-down bar and "
    "badged when under the headline bar -- Medicine (MD) is reported down to a "
    "small floor even where thin, the rarest humanities->professional path. "
    "Enrollment only, not completion: a recent bachelor mid-degree at the "
    "snapshot is still counted as enrolled, never as a failure to finish. "
    "Snapshot fans (year-1 first destinations, year-3/5 outlook) carry the "
    "same per-cell `detail` occupation drill-down as the year-10 fan: it "
    "describes only the deterministically role-coded slice of the cell, "
    f"named roles clear the {C.DETAIL_MIN_SUPPORT}-person drill-down bar, and "
    "the coverage split (detail_coded / no_detail_n) ships with every cell."
)
