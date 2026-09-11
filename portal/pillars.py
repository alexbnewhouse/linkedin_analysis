"""Four constructed pillars: Growth / Stability / Skill / Direction.

CONSTRUCTED FRAMEWORK -- NOT a validated one. Each pillar is a per-person
substrate scalar; a group's score is the percentile of the group's median
scalar within the BASELINE per-person distribution, x100, so 50 == baseline
parity by construction. Substrates:
  Growth    = seniority_score gain over the first 10 years (y10 - y0)
  Stability = mean primary dwell (months) * gap-freedom (1 - gapped-edge share)
  Skill     = mean O*NET job-zone-norm of occupations reached in the window
  Direction = (upward + deliberate-pivot) share of post-anchor moves
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right

from portal import common as C

PILLARS = ("growth", "stability", "skill", "direction")


def _percentile(sorted_vals: list[float], x: float) -> float:
    """Midpoint (mean) rank percentile: counts values below x plus half the ties
    at x. This maps the baseline's own median to ~50 even with heavy ties, so
    50 == baseline parity holds by construction."""
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    below = bisect_left(sorted_vals, x)
    ties = bisect_right(sorted_vals, x) - below
    return 100.0 * (below + 0.5 * ties) / n


def compute(con) -> dict:
    cut = C.LAST_COMPLETE_YEAR - C.FAN_YEAR
    trans = f"read_parquet('{C.q(C.TRANSITIONS)}')"
    dir_types = tuple(dict.fromkeys(C.UP_TYPES + C.PIVOT_TYPES))
    dir_list = ", ".join(f"'{t}'" for t in dir_types)
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE feat AS
      WITH coh AS (
        SELECT group_key, linkedin_id, anchor FROM membership WHERE anchor <= {cut}
      ),
      sen0 AS (
        SELECT c.group_key, c.linkedin_id, p.seniority_score AS s0
        FROM coh c JOIN panel p
          ON p.linkedin_id = c.linkedin_id AND p.cal_year = c.anchor
      ),
      sen10 AS (
        SELECT c.group_key, c.linkedin_id, p.seniority_score AS s10
        FROM coh c JOIN panel p
          ON p.linkedin_id = c.linkedin_id AND p.cal_year = c.anchor + {C.FAN_YEAR}
      ),
      skill AS (
        SELECT c.group_key, c.linkedin_id, avg(p.job_zone_norm) AS jz
        FROM coh c JOIN panel p
          ON p.linkedin_id = c.linkedin_id
         AND p.cal_year - c.anchor BETWEEN 0 AND {C.FAN_YEAR}
        GROUP BY 1, 2
      ),
      dwell AS (
        SELECT c.group_key, c.linkedin_id, avg(p.tenure_months) AS md
        FROM coh c JOIN panel p
          ON p.linkedin_id = c.linkedin_id
         AND p.cal_year - c.anchor BETWEEN 0 AND {C.FAN_YEAR}
        GROUP BY 1, 2
      ),
      edges AS (
        SELECT c.group_key, c.linkedin_id,
               count(*) AS tot,
               count(*) FILTER (WHERE t.has_gap) AS gaps,
               count(*) FILTER (WHERE t.transition_type IN ({dir_list})) AS dirn
        FROM coh c JOIN {trans} t
          ON t.linkedin_id = c.linkedin_id
         AND year(t.to_start_dt) - c.anchor BETWEEN 0 AND {C.FAN_YEAR}
        GROUP BY 1, 2
      )
      SELECT coh.group_key, coh.linkedin_id,
             (sen10.s10 - sen0.s0) AS growth,
             CASE WHEN dwell.md IS NOT NULL AND e.tot > 0
                  THEN dwell.md * (1 - e.gaps::double / e.tot) END AS stability,
             skill.jz AS skill,
             CASE WHEN e.tot > 0 THEN e.dirn::double / e.tot END AS direction
      FROM coh
      LEFT JOIN sen0  USING (group_key, linkedin_id)
      LEFT JOIN sen10 USING (group_key, linkedin_id)
      LEFT JOIN skill USING (group_key, linkedin_id)
      LEFT JOIN dwell USING (group_key, linkedin_id)
      LEFT JOIN edges e USING (group_key, linkedin_id)
    """)

    out = {g: {} for g in list(C.MAJORS) + [C.BASELINE_KEY]}
    for pillar in PILLARS:
        base = sorted(r[0] for r in con.execute(
            f"SELECT {pillar} FROM feat WHERE group_key = '{C.BASELINE_KEY}' "
            f"AND {pillar} IS NOT NULL").fetchall())
        meds = con.execute(
            f"SELECT group_key, median({pillar}) FROM feat "
            f"WHERE {pillar} IS NOT NULL GROUP BY 1").fetchall()
        med_by_g = {g: m for g, m in meds}
        for g in out:
            m = med_by_g.get(g)
            pct = _percentile(base, m) if m is not None else None
            out[g][pillar] = round(pct) if pct is not None else None
    return out
