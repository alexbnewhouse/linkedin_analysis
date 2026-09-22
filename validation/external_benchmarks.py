"""LinkedIn shares vs NCES Digest Table 322.10 / 325.92 and Humanities Indicators (spec P1).

    uv run python -m validation.external_benchmarks

Bachelor's rung = degree_level_pooled = 4, NOT is_duplicate, end_year present; field =
cip2_pooled (the pooled CIP layer is what is being benchmarked). Rows bucket to the
nearest Digest year within +-1. Writes validation/results/external_benchmarks.json
(committed). Reporting only: nothing is written to any table.

Stated biases (pre-review 2026-09-22): only ~19% of bachelor's-rung rows carry an
end_year and that subset skews toward CS and away from business; rows are not restricted
to US institutions while NCES is US-only; the advanced-degree comparison is a stock among
people who have had time to finish, so the primary line is restricted to cohorts at least
ten years past the bachelor's.
"""
from __future__ import annotations

import json
import subprocess
from datetime import date

import duckdb

from validation import common as C


def _sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=C.ROOT,
                                       text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _rung_sql() -> str:
    return (f"read_parquet('{C.EDUCATION}') WHERE NOT is_duplicate AND degree_level_pooled = 4 "
            f"AND cip2_pooled IS NOT NULL AND cip2_pooled <> '53'")


def build() -> dict:
    nces = C.load_nces()
    hi = C.load_hi()
    est = nces["history_estimate_share_of_socsci_history"]
    targets = sorted(int(y) for y in nces["years"])
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    con.create_function("bucket", lambda y: C.year_bucket(y, targets), ["INTEGER"], "INTEGER",
                        null_handling="special")
    rows = con.execute(f"""
        SELECT bucket(end_year) AS yb, cip2_pooled, count(*) AS n
        FROM {_rung_sql()} AND end_year IS NOT NULL
        GROUP BY 1, 2
    """).fetchall()
    by_year: dict[int, list[tuple[str, int]]] = {}
    for yb, cip2, n in rows:
        if yb is not None:
            by_year.setdefault(yb, []).append((cip2, n))

    out_years: dict[str, dict] = {}
    for y in targets:
        li = C.shares(by_year.get(y, []))
        n = sum(n for _, n in by_year.get(y, []))
        ny = nces["years"][str(y)]
        _, hist_est = C.nces_history(ny, est)
        entry: dict = {"linkedin_n": n, "history_estimated": hist_est}
        for name, cips, lines in (("core6", C.CORE6, C.CORE6_LINES),
                                  ("l1_proxy", C.L1_PROXY, C.L1_PROXY_LINES)):
            li_s = sum(li.get(c, 0.0) for c in cips)
            nc_s = C.nces_group_share(ny, lines, est)
            entry[name] = {"linkedin": li_s, "nces": nc_s, "ratio": li_s / nc_s if nc_s else None}
        for name, cip in C.NAMED.items():
            nc_s = C.nces_group_share(ny, (name,), est)
            li_s = li.get(cip, 0.0)
            entry[name] = {"linkedin": li_s, "nces": nc_s, "ratio": li_s / nc_s if nc_s else None}
        out_years[str(y)] = entry

    # representativeness of the years-present subset within the rung
    rep = con.execute(f"""
        SELECT end_year IS NOT NULL AS dated, count(*) AS n,
               avg((cip2_pooled IN {tuple(C.CORE6)})::INT) AS core6,
               avg((cip2_pooled IN {tuple(C.L1_PROXY)})::INT) AS l1_proxy,
               avg((cip2_pooled = '52')::INT) AS business,
               avg((cip2_pooled = '11')::INT) AS cs
        FROM {_rung_sql()} GROUP BY 1 ORDER BY 1
    """).fetchall()
    rung_subset = {("dated" if r[0] else "undated"): {"n": r[1], "core6": r[2], "l1_proxy": r[3],
                                                      "business": r[4], "cs": r[5]} for r in rep}

    adv = con.execute(f"""
        SELECT
          avg((highest_degree_level_pooled >= 6)::INT)
              FILTER (WHERE bachelor_end_year <= {C.ADVANCED_DEGREE_COHORT_MAX_YEAR}) AS rate_cohort,
          count(*) FILTER (WHERE bachelor_end_year <= {C.ADVANCED_DEGREE_COHORT_MAX_YEAR}) AS n_cohort,
          avg((highest_degree_level_pooled >= 6)::INT) AS rate_all,
          count(*) AS n_all
        FROM read_parquet('{C.EDU_PERSON}') WHERE hum_l1_bachelor_pooled_any
    """).fetchone()
    fp = con.execute(f"""
        SELECT count(*), bit_xor(hash(linkedin_id, idx, cip_code, cip2_pooled, degree_level_pooled))
        FROM read_parquet('{C.EDUCATION}')
    """).fetchone()
    con.close()

    hi_rate = hi["advanced_degree_rate_humanities_ba"]
    return {
        "release": {"built": date.today().isoformat(), "git": _sha(),
                    "snapshot_date": C.SNAPSHOT_DATE, "last_complete_year": C.LAST_COMPLETE_YEAR,
                    "education_rows": fp[0], "education_fingerprint": str(fp[1])},
        "sources": {"nces": nces["source"], "nces_history": nces["history_source"],
                    "nces_verified_on": nces.get("verified_on"),
                    "humanities_indicators": hi["advanced_degree_rate_source"]},
        "definitions": {
            "rung": "degree_level_pooled = 4, NOT is_duplicate, cip2_pooled real; field = cip2_pooled",
            "core6": list(C.CORE6), "l1_proxy": list(C.L1_PROXY),
            "year_bucket": f"nearest Digest year within +-{C.YEAR_TOLERANCE}",
            "advanced_degree": (f"highest_degree_level_pooled >= 6 among hum_l1_bachelor_pooled_any; "
                                f"primary line restricted to bachelor_end_year <= "
                                f"{C.ADVANCED_DEGREE_COHORT_MAX_YEAR}"),
        },
        "biases": [
            "years-present rows are a minority of the bachelor's rung and skew toward CS and away from business (see rung_subset)",
            "rows are not restricted to US institutions; NCES counts US institutions only",
            "the pooled CIP layer (det + jury + knn_head + degree_type) is what is benchmarked",
        ],
        "rung_subset": rung_subset,
        "years": out_years,
        "advanced_degree_rate": {
            "linkedin_hum_l1_bachelor_cohort": adv[0], "n_cohort": adv[1],
            "cohort_max_bachelor_year": C.ADVANCED_DEGREE_COHORT_MAX_YEAR,
            "linkedin_hum_l1_bachelor_all": adv[2], "n_all": adv[3],
            "humanities_indicators": hi_rate, "humanities_indicators_year": hi.get("advanced_degree_rate_year"),
            "ratio_cohort": adv[0] / hi_rate if adv[0] is not None else None,
            "ratio_all": adv[2] / hi_rate if adv[2] is not None else None,
        },
    }


def main() -> None:
    r = build()
    C.OUT.parent.mkdir(parents=True, exist_ok=True)
    C.OUT.write_text(json.dumps(r, indent=1) + "\n")
    for y, e in r["years"].items():
        flag = " (history est.)" if e["history_estimated"] else ""
        print(f"{y}: n={e['linkedin_n']:,}  core6 {100*e['core6']['linkedin']:.2f}% vs NCES "
              f"{100*e['core6']['nces']:.2f}% (x{e['core6']['ratio']:.2f})  l1_proxy "
              f"{100*e['l1_proxy']['linkedin']:.2f}% vs {100*e['l1_proxy']['nces']:.2f}% "
              f"(x{e['l1_proxy']['ratio']:.2f}){flag}")
    a = r["advanced_degree_rate"]
    print(f"advanced-degree rate, L1 bachelor's <= {a['cohort_max_bachelor_year']}: "
          f"{100*a['linkedin_hum_l1_bachelor_cohort']:.1f}% (n={a['n_cohort']:,}) vs HI "
          f"{100*a['humanities_indicators']:.0f}% (x{a['ratio_cohort']:.2f}); all persons "
          f"{100*a['linkedin_hum_l1_bachelor_all']:.1f}% (n={a['n_all']:,})")
    rs = r["rung_subset"]
    print(f"rung subset: dated n={rs['dated']['n']:,} core6 {100*rs['dated']['core6']:.2f}%; "
          f"undated n={rs['undated']['n']:,} core6 {100*rs['undated']['core6']:.2f}%")
    print(f"wrote {C.OUT}")


if __name__ == "__main__":
    main()
