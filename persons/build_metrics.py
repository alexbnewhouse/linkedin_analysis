"""Metrics cube v0 over persons/person.parquet (spec P6).

    uv run python -m persons.build_metrics

Groups: all; tier:l1|l2|l3 (bachelor rung, pooled, ANY-row flags); group:<bachelor_field_group>;
cip2:<code> with n >= MIN_GROUP_N. Every categorical panel is suppressed below MIN_SUPPORT
persons with the two-cell secondary rule; a suppressed-cell count is reported only when at
least two cells were suppressed. Plus-k panels on BOTH axes, windowed: a person counts at
horizon k only when the anchor year <= LAST_COMPLETE_YEAR - k. Output persons/results/metrics.json
(+ tables/*.csv) with the same release stamp as the person table.
"""
from __future__ import annotations

import csv
import json
import time
from collections import defaultdict

import duckdb

from persons import common as C
from persons.build_person import release

TOP = {"cur_soc_major": 30, "first_soc_major": 30, "cur_title_family": 30, "cur_industry_l1": 20,
       "cur_us_state": 20, "top_employers": 20, "transitions": 60}


def _q(p) -> str:
    return str(p).replace("'", "''")


def _agg(con, sql) -> dict[str, list[tuple]]:
    d: dict[str, list[tuple]] = defaultdict(list)
    for r in con.execute(sql).fetchall():
        d[r[0]].append(tuple(r[1:]))
    return d


def panel(rows: list[tuple], top: int | None = None) -> dict:
    """rows: (key, n) -> suppressed, ordered, truncated panel."""
    cells = [(str(k), int(n)) for k, n in rows if k is not None]
    kept, n_sup = C.suppress(cells, C.MIN_SUPPORT)
    kept.sort(key=lambda kv: -kv[1])
    out = {"cells": [{"k": k, "n": n} for k, n in (kept[:top] if top else kept)],
           "n_total": sum(n for _, n in cells), "n_shown": sum(n for _, n in kept)}
    sc = C.suppressed_count_for_output(n_sup)
    if sc is not None:
        out["suppressed_cells"] = sc
    return out


def build(threads: int = 16) -> dict:
    t0 = time.time()
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    LC = C.LAST_COMPLETE_YEAR
    con.execute(f"CREATE TEMP VIEW P AS SELECT * FROM read_parquet('{_q(C.PERSON_OUT)}')")
    con.execute(f"CREATE TEMP VIEW S AS SELECT * FROM read_parquet('{_q(C.STEPS_OUT)}')")
    con.execute("""
      CREATE TEMP TABLE M AS
      SELECT linkedin_id, 'all' AS g FROM P WHERE has_bachelor
      UNION ALL SELECT linkedin_id, 'tier:l1' FROM P WHERE hum_l1_bachelor
      UNION ALL SELECT linkedin_id, 'tier:l2' FROM P WHERE hum_l2_bachelor
      UNION ALL SELECT linkedin_id, 'tier:l3' FROM P WHERE hum_l3_bachelor
      UNION ALL SELECT linkedin_id, 'group:' || bachelor_field_group FROM P WHERE bachelor_field_group IS NOT NULL
      UNION ALL SELECT linkedin_id, 'cip2:' || bachelor_cip2 FROM P WHERE bachelor_cip2 IS NOT NULL
    """)
    con.execute(f"""
      CREATE TEMP TABLE G AS SELECT g, count(*) AS n FROM M GROUP BY 1
      HAVING n >= {C.MIN_GROUP_N} OR g NOT LIKE 'cip2:%'
    """)
    con.execute("CREATE TEMP TABLE MP AS SELECT m.g, p.* FROM M m JOIN G USING (g) JOIN P p USING (linkedin_id)")
    groups = [r[0] for r in con.execute("SELECT g FROM G ORDER BY n DESC").fetchall()]

    basic = {r[0]: r[1:] for r in con.execute("""
      SELECT g, count(*) AS n,
             sum((bachelor_end_year IS NOT NULL)::INT) AS n_grad_axis, sum((entry_year IS NOT NULL)::INT) AS n_entry_axis,
             sum(has_current_step::INT) AS n_current, avg(has_grad_degree::INT) AS grad_any,
             avg(has_master::INT) AS master, avg(has_doctorate::INT) AS doctorate, avg(has_jd::INT) AS jd,
             avg(has_mba::INT) AS mba, avg(has_md_prof::INT) AS md_prof, avg(has_med::INT) AS med, avg(has_msw::INT) AS msw,
             avg(ever_manager_plus::INT) AS ever_manager, avg(ever_director_plus::INT) AS ever_director,
             avg(ever_vp_plus::INT) AS ever_vp, avg(ever_founder_owner::INT) AS ever_founder,
             avg(double_major_any::INT) AS double_major, avg(hum_l1_comajor_any::INT) AS l1_comajor,
             avg(bachelor_imputed_any::INT) AS bachelor_imputed, avg((bachelor_level_source = 'det')::INT) AS bachelor_det,
             avg(n_steps) AS avg_steps, avg(n_employers) AS avg_employers
      FROM MP GROUP BY g""").fetchall()}
    BASIC = ["n", "n_grad_axis", "n_entry_axis", "n_current", "grad_any", "master", "doctorate", "jd", "mba", "md_prof",
             "med", "msw", "ever_manager", "ever_director", "ever_vp", "ever_founder", "double_major", "l1_comajor",
             "bachelor_imputed", "bachelor_det", "avg_steps", "avg_employers"]

    cur_major = _agg(con, "SELECT g, cur_soc_major, count(*) FROM MP WHERE cur_soc_major IS NOT NULL GROUP BY 1, 2")
    first_major = _agg(con, "SELECT g, first_soc_major, count(*) FROM MP WHERE first_soc_major IS NOT NULL GROUP BY 1, 2")
    cur_family = _agg(con, "SELECT g, cur_title_family, count(*) FROM MP WHERE cur_title_family IS NOT NULL AND cur_title_family <> 'unclassified' GROUP BY 1, 2")
    cur_ind = _agg(con, "SELECT g, cur_industry_l1, count(*) FROM MP WHERE cur_industry_l1 IS NOT NULL GROUP BY 1, 2")
    cur_state = _agg(con, "SELECT g, cur_us_state, count(*) FROM MP WHERE cur_us_state IS NOT NULL GROUP BY 1, 2")
    employers = _agg(con, "SELECT g, cur_company_canonical_id, count(*) FROM MP WHERE cur_company_canonical_id IS NOT NULL AND cur_company_canonical_id NOT LIKE 'nonorg:%' GROUP BY 1, 2")
    trans = _agg(con, "SELECT g, first_soc_major || '>' || cur_soc_major, count(*) FROM MP WHERE first_soc_major IS NOT NULL AND cur_soc_major IS NOT NULL GROUP BY 1, 2")
    stage_dist = {}
    sen_stage = {}
    for axis in ("entry", "grad"):
        stage_dist[axis] = _agg(con, f"SELECT g, career_stage_{axis}, count(*) FROM MP WHERE career_stage_{axis} IS NOT NULL GROUP BY 1, 2")
        sen_stage[axis] = _agg(con, f"""
          SELECT g, career_stage_{axis},
                 avg((cur_seniority_ordinal >= {C.MANAGER_RANK})::INT), avg((cur_seniority_ordinal >= {C.DIRECTOR_RANK})::INT),
                 avg((cur_seniority_ordinal >= {C.VP_RANK})::INT), count(*)
          FROM MP WHERE career_stage_{axis} IS NOT NULL AND cur_seniority_ordinal IS NOT NULL GROUP BY 1, 2""")
    # plus-k panels on both axes, windowed
    atk: dict[str, dict[int, dict[str, list[tuple]]]] = {"entry": {}, "grad": {}}
    atk_n: dict[str, dict[int, dict[str, tuple]]] = {"entry": {}, "grad": {}}
    for axis, anchor in (("entry", "entry_year"), ("grad", "bachelor_end_year")):
        for k in C.HORIZONS:
            con.execute(f"""
              CREATE OR REPLACE TEMP TABLE atk AS
              SELECT mp.g, mp.linkedin_id, s.soc_major
              FROM MP mp JOIN S s USING (linkedin_id)
              WHERE mp.{anchor} BETWEEN 1950 AND {LC - k}
                AND s.y0 <= mp.{anchor} + {k} AND coalesce(s.y1, {C.SNAPSHOT_YEAR}) >= mp.{anchor} + {k}
              QUALIFY row_number() OVER (PARTITION BY mp.g, mp.linkedin_id
                                         ORDER BY s.seniority_score DESC NULLS LAST, s.tenure_months DESC NULLS LAST, s.row_id) = 1
            """)
            atk[axis][k] = _agg(con, "SELECT g, soc_major, count(*) FROM atk WHERE soc_major IS NOT NULL GROUP BY 1, 2")
            atk_n[axis][k] = {r[0]: r[1:] for r in con.execute(f"""
              SELECT mp.g, count(*) FILTER (WHERE mp.{anchor} BETWEEN 1950 AND {LC - k}) AS eligible,
                     count(DISTINCT a.linkedin_id) AS with_step
              FROM MP mp LEFT JOIN atk a ON a.g = mp.g AND a.linkedin_id = mp.linkedin_id
              GROUP BY 1""").fetchall()}
    ttf = _agg(con, f"SELECT g, least(6, greatest(-3, first_start_year - bachelor_end_year)), count(*) FROM MP WHERE bachelor_end_year BETWEEN 1950 AND {LC} AND first_start_year IS NOT NULL GROUP BY 1, 2")
    trend = con.execute(f"""
      SELECT bachelor_end_year, count(*), avg(hum_l1_bachelor::INT), avg(hum_l2_bachelor::INT), avg(hum_l3_bachelor::INT)
      FROM P WHERE has_bachelor AND bachelor_end_year BETWEEN 1985 AND {LC} GROUP BY 1 ORDER BY 1""").fetchall()
    con.close()

    out = {"release": release(), "floor": C.MIN_SUPPORT, "groups": {}}
    total_suppressed = 0

    def P_(rows, top=None):
        nonlocal total_suppressed
        p = panel(rows, top)
        total_suppressed += p.get("suppressed_cells", 0)
        return p

    for g in groups:
        b = dict(zip(BASIC, basic[g]))
        b = {k: (float(v) if v is not None else None) for k, v in b.items()}
        cm = cur_major.get(g, [])
        counts = [int(n) for _, n in cm]
        d = {"basic": b,
             "breadth": {"entropy": round(C.entropy(counts), 4), "majors_for_80pct": C.cover80(counts),
                         "top3_share": round(C.top3(counts), 4), "n": sum(counts)},
             "cur_soc_major": P_(cm, TOP["cur_soc_major"]),
             "first_soc_major": P_(first_major.get(g, []), TOP["first_soc_major"]),
             "cur_title_family": P_(cur_family.get(g, []), TOP["cur_title_family"]),
             "cur_industry_l1": P_(cur_ind.get(g, []), TOP["cur_industry_l1"]),
             "cur_us_state": P_(cur_state.get(g, []), TOP["cur_us_state"]),
             "top_employers": P_(employers.get(g, []), TOP["top_employers"]),
             "transitions_first_to_current": P_(trans.get(g, []), TOP["transitions"]),
             "stage": {ax: P_(stage_dist[ax].get(g, [])) for ax in ("entry", "grad")},
             "seniority_by_stage": {ax: {st: {"manager_plus": r[1], "director_plus": r[2], "vp_plus": r[3], "n": r[4]}
                                          for st, *r_ in [(x[0], x) for x in sen_stage[ax].get(g, [])]
                                          for r in [r_[0]] if r[4] >= C.MIN_SUPPORT}
                                    for ax in ("entry", "grad")},
             "at_k": {ax: {str(k): {"eligible": atk_n[ax][k].get(g, (0, 0))[0], "with_step": atk_n[ax][k].get(g, (0, 0))[1],
                                    "soc_major": P_(atk[ax][k].get(g, []), 30)}
                          for k in C.HORIZONS} for ax in ("entry", "grad")},
             "time_to_first_job_grad_axis": P_(ttf.get(g, []))}
        out["groups"][g] = d
    out["cohort_trend_grad_axis"] = [{"year": y, "n": n, "l1": a, "l2": b_, "l3": c_} for y, n, a, b_, c_ in trend if n >= C.MIN_SUPPORT]
    out["total_suppressed_cells"] = total_suppressed
    out["runtime_s"] = round(time.time() - t0, 1)
    return out


def write_tables(out: dict) -> None:
    C.TABLES.mkdir(parents=True, exist_ok=True)
    with (C.TABLES / "group_summary.csv").open("w", newline="") as fh:
        w = None
        for g, d in out["groups"].items():
            row = {"group": g, **d["basic"], **{f"breadth_{k}": v for k, v in d["breadth"].items()}}
            if w is None:
                w = csv.DictWriter(fh, fieldnames=list(row))
                w.writeheader()
            w.writerow(row)
    with (C.TABLES / "cur_soc_major_by_group.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["group", "soc_major", "n", "share_of_shown"])
        for g, d in out["groups"].items():
            p = d["cur_soc_major"]
            for c in p["cells"]:
                w.writerow([g, c["k"], c["n"], round(c["n"] / p["n_shown"], 4) if p["n_shown"] else None])


def main() -> None:
    out = build()
    C.RESULTS.mkdir(parents=True, exist_ok=True)
    C.METRICS_OUT.write_text(json.dumps(out, indent=1, default=str) + "\n")
    write_tables(out)
    print(f"wrote {C.METRICS_OUT} ({len(out['groups'])} groups, {out['total_suppressed_cells']} suppressed cells, "
          f"{out['runtime_s']}s)")
    for g in ("all", "tier:l1", "tier:l2", "tier:l3"):
        d = out["groups"][g]
        b = d["basic"]
        top = ", ".join(f"{c['k']} {c['n']:,}" for c in d["cur_soc_major"]["cells"][:5])
        print(f"  {g:8s} n={b['n']:,.0f} grad-degree {100*b['grad_any']:.1f}% director+ {100*b['ever_director']:.1f}% "
              f"double-major {100*b['double_major']:.1f}% | current major: {top}")
        for ax in ("entry", "grad"):
            a = d["at_k"][ax]["10"]
            print(f"           +10 {ax}: eligible {a['eligible']:,}, with step {a['with_step']:,}")


if __name__ == "__main__":
    main()
