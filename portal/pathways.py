"""Named-pathway mining on the role axis.

Within each major's windowed year-10 cohort, reconstruct each person's ordered
post-anchor primary-role path (from the primary-timeline transition edges),
mine contiguous 3-4 role_canonical n-grams, rank by distinct-person support,
and emit routes clearing MIN_PERSONS. A route is flagged `unexpected` when its
terminal occupation group is NOT among the major's top-5 fan destinations yet it
still clears support.
"""

from __future__ import annotations

from collections import defaultdict

from portal import common as C


def _role_soc_major(con) -> dict[str, str]:
    """role_canonical -> modal SOC major group among the population panel."""
    soc_case = C.soc_major_case("occupation_code")
    rows = con.execute(f"""
      WITH r AS (
        SELECT role_canonical, {soc_case} AS soc_major, count(*) AS n
        FROM panel WHERE role_canonical IS NOT NULL AND occupation_code IS NOT NULL
        GROUP BY 1, 2
      )
      SELECT role_canonical, soc_major FROM r
      QUALIFY row_number() OVER (PARTITION BY role_canonical ORDER BY n DESC) = 1
    """).fetchall()
    return {r: s for r, s in rows if s is not None}


def _role_dwell(con) -> dict[str, float]:
    """role_canonical -> median primary tenure (months) among the population."""
    rows = con.execute("""
      SELECT role_canonical, median(tenure_months) AS m
      FROM panel WHERE role_canonical IS NOT NULL AND tenure_months IS NOT NULL
      GROUP BY 1""").fetchall()
    return {r: float(m) for r, m in rows if m is not None}


def mine_soc(con, top5_fan: dict[str, list[str]]) -> dict:
    """Named-pathway mining at pooled SOC-MAJOR-GROUP grain (23 labels).

    Per windowed person: the year-0..FAN_YEAR sequence of pooled ``soc_major``
    panel labels, consecutive duplicates collapsed. HONESTY RULE: any
    unclassified year BREAKS the sequence -- we never bridge X -> (unknown) -> Y
    into an X -> Y adjacency, because the unknown year may hide a different
    occupation. Chains are therefore contiguously-classified spans only, and
    coverage grows exactly as occupation coding grows. Emits 3-4-stage chains
    with >= PATH_MIN_PERSONS distinct persons; ``unexpected`` = terminal group
    outside the major's top-5 fan destinations."""
    cut = C.LAST_COMPLETE_YEAR - C.FAN_YEAR
    rows_by_group: dict[str, list] = {g: [] for g in C.MAJORS}
    data = con.execute(f"""
      SELECT m.group_key, m.linkedin_id, p.cal_year - m.anchor AS rel_year,
             p.soc_major
      FROM membership m
      JOIN panel p ON p.linkedin_id = m.linkedin_id
                  AND p.cal_year BETWEEN m.anchor AND m.anchor + {C.FAN_YEAR}
      WHERE m.anchor <= {cut} AND m.group_key != '{C.BASELINE_KEY}'
      ORDER BY m.group_key, m.linkedin_id, rel_year
    """).fetchall()
    for row in data:
        if row[0] in rows_by_group:
            rows_by_group[row[0]].append(row[1:])

    out = {}
    for g in C.MAJORS:
        # person -> {rel_year: soc_major} (rows with soc_major NULL are kept
        # as explicit Nones so they break chains, same as absent years)
        person_years: dict[str, dict[int, str | None]] = defaultdict(dict)
        for lid, rel_year, soc in rows_by_group[g]:
            person_years[lid][int(rel_year)] = soc

        ngram_persons: dict[tuple, set] = defaultdict(set)
        for lid, years in person_years.items():
            seq: list[str] = []
            segments: list[list[str]] = []
            for y in range(0, C.FAN_YEAR + 1):
                soc = years.get(y)          # None = no panel row OR unclassified
                if soc is None:
                    if len(seq) >= C.PATH_MIN_STAGES:
                        segments.append(seq)
                    seq = []
                elif not seq or seq[-1] != soc:
                    seq.append(soc)
            if len(seq) >= C.PATH_MIN_STAGES:
                segments.append(seq)
            for seg in segments:
                for L in range(C.PATH_MIN_STAGES, C.PATH_MAX_STAGES + 1):
                    for i in range(len(seg) - L + 1):
                        ngram_persons[tuple(seg[i:i + L])].add(lid)

        top5 = set(top5_fan.get(g, []))
        ranked = sorted(ngram_persons.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        emitted, suppressed = [], 0
        for ngram, persons in ranked:
            n = len(persons)
            if n >= C.PATH_MIN_PERSONS:
                if len(emitted) >= C.PATH_TOP:
                    continue
                terminal = ngram[-1]
                emitted.append({
                    "stages": [{"group": s} for s in ngram],
                    "n_persons": int(n),
                    "terminal_group": terminal,
                    "unexpected": bool(terminal not in top5),
                })
            elif n >= C.PATH_SUPPRESS_FLOOR:
                suppressed += 1
        out[g] = {"paths": emitted, "paths_suppressed_count": int(suppressed),
                  "paths_grain": "soc_major_pooled"}
    return out


def mine(con, top5_fan: dict[str, list[str]]) -> dict:
    """top5_fan: group_key -> list of that group's top-5 fan SOC major labels."""
    cut = C.LAST_COMPLETE_YEAR - C.FAN_YEAR
    trans = f"read_parquet('{C.q(C.TRANSITIONS)}')"
    role_soc = _role_soc_major(con)
    role_dwell = _role_dwell(con)

    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE path_edges AS
      SELECT m.group_key, m.linkedin_id, t.to_start_dt, t.from_row_id,
             t.from_role, t.to_role
      FROM membership m
      JOIN {trans} t ON t.linkedin_id = m.linkedin_id
      WHERE m.anchor <= {cut}
        AND year(t.to_start_dt) - m.anchor BETWEEN 0 AND {C.FAN_YEAR}
        AND t.from_role IS NOT NULL AND t.to_role IS NOT NULL
      ORDER BY m.group_key, m.linkedin_id, t.to_start_dt, t.from_row_id
    """)

    out = {}
    for g in C.MAJORS:
        rows = con.execute(
            "SELECT linkedin_id, from_role, to_role FROM path_edges "
            "WHERE group_key = ? ORDER BY linkedin_id, to_start_dt, from_row_id",
            [g]).fetchall()
        # reconstruct per-person ordered role sequence (collapse consecutive dups)
        seqs: dict[str, list[str]] = defaultdict(list)
        for lid, fr, tr in rows:
            s = seqs[lid]
            if not s:
                s.append(fr)
            if s[-1] != fr:
                s.append(fr)
            if s[-1] != tr:
                s.append(tr)
        # n-grams -> set of persons
        ngram_persons: dict[tuple, set] = defaultdict(set)
        for lid, seq in seqs.items():
            for L in range(C.PATH_MIN_STAGES, C.PATH_MAX_STAGES + 1):
                for i in range(len(seq) - L + 1):
                    ngram_persons[tuple(seq[i:i + L])].add(lid)

        top5 = set(top5_fan.get(g, []))
        ranked = sorted(ngram_persons.items(),
                        key=lambda kv: (-len(kv[1]), kv[0]))
        emitted, suppressed = [], 0
        for ngram, persons in ranked:
            n = len(persons)
            if n >= C.PATH_MIN_PERSONS:
                if len(emitted) >= C.PATH_TOP:
                    continue
                terminal_soc = role_soc.get(ngram[-1])
                unexpected = terminal_soc is not None and terminal_soc not in top5
                emitted.append({
                    "name": None,
                    "stages": [{"role": r,
                                "median_dwell_mo": int(role_dwell.get(r, 0))}
                               for r in ngram],
                    "n_persons": int(n),
                    "terminal_group": terminal_soc,
                    "unexpected": bool(unexpected),
                })
            elif n >= C.PATH_SUPPRESS_FLOOR:
                suppressed += 1
        out[g] = {"paths": emitted, "paths_suppressed_count": int(suppressed)}
    return out
