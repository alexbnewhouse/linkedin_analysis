"""Possibility-space ENRICHMENT: the parts of a humanities career the job-title
fan structurally misses -- civic/nonprofit engagement (volunteer causes),
knowledge/creative output (publications), professional multilingualism (for
language majors), and leadership/recognition (organizations, honors).

    uv run python -m enrichment.build_enrichment

All 13 parsed enrichment tables were previously unused. This driver joins the
five highest-value ones to the humanities population (any-degree L1, pooled) and
reports participation + composition per sub-field vs a non-humanities baseline.
Output: enrichment/results/enrichment.json + _manifest.json.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
EP = f"read_parquet('{ROOT / 'normalized' / 'education_person.parquet'}')"
P = lambda t: f"read_parquet('{ROOT / 'parsed' / t / '*.parquet'}')"  # noqa: E731
OUT = Path(__file__).resolve().parent / "results" / "enrichment.json"

# humanities sub-fields to report (terminal pooled group), + pooled + baseline
SUBFIELDS = ["Fine & Performing Arts", "English & Literature", "History",
             "Languages & Linguistics", "Philosophy & Religion", "Theology",
             "Area & Cultural Studies"]
PROF_LANG = ("Full professional proficiency", "Professional working proficiency",
             "Native or bilingual proficiency")


def _con():
    con = duckdb.connect(); con.execute("PRAGMA threads=8")
    # population table: one row per person with a humanities-group label
    con.execute(f"""
      CREATE TEMP TABLE pop AS
      SELECT linkedin_id, hum_l1_any,
             CASE WHEN hum_l1_any THEN humanities_field_group_pooled END AS subfield
      FROM {EP}
    """)
    # per-person enrichment flags (distinct-person existence + a few compositions)
    con.execute(f"""
      CREATE TEMP TABLE vol AS
      SELECT linkedin_id, count(*) n, mode(cause) top_cause
      FROM {P('volunteer_experience')} WHERE cause IS NOT NULL AND trim(cause) NOT IN ('','-')
      GROUP BY 1""")
    con.execute(f"""
      CREATE TEMP TABLE pub AS SELECT linkedin_id, count(*) n FROM {P('publications')} GROUP BY 1""")
    con.execute(f"""
      CREATE TEMP TABLE hon AS SELECT linkedin_id, count(*) n FROM {P('honors_and_awards')} GROUP BY 1""")
    con.execute(f"""
      CREATE TEMP TABLE lead AS
      SELECT linkedin_id, count(*) n FROM {P('organizations')}
      WHERE regexp_matches(lower(coalesce(membership_type,'')),
            'board|president|chair|director|officer|vice president|treasurer|secretary|founder')
      GROUP BY 1""")
    con.execute(f"""
      CREATE TEMP TABLE lang AS
      SELECT linkedin_id,
             count(*) FILTER (WHERE trim(subtitle) IN {PROF_LANG}) AS n_prof
      FROM {P('languages')} GROUP BY 1""")
    return con


def _group_stats(con, where: str, label: str) -> dict:
    n = con.execute(f"SELECT count(*) FROM pop WHERE {where}").fetchone()[0]
    if not n:
        return {"n_persons": 0}

    def pct(tbl, cond="TRUE"):
        c = con.execute(f"""
          SELECT count(DISTINCT p.linkedin_id) FROM pop p JOIN {tbl} t USING (linkedin_id)
          WHERE {where} AND {cond}""").fetchone()[0]
        return round(100.0 * c / n, 1)

    top_causes = con.execute(f"""
      SELECT t.top_cause, count(*) c FROM pop p JOIN vol t USING (linkedin_id)
      WHERE {where} GROUP BY 1 ORDER BY c DESC LIMIT 5""").fetchall()
    return {
        "n_persons": n,
        "volunteer_pct": pct("vol"),
        "top_volunteer_causes": [{"cause": c, "persons": n_} for c, n_ in top_causes],
        "publications_pct": pct("pub"),
        "honors_pct": pct("hon"),
        "org_leadership_pct": pct("lead"),
        "professional_multilingual_pct": pct("lang", "t.n_prof >= 1"),
    }


def build() -> dict:
    t0 = time.time()
    con = _con()
    out = {
        "humanities_pooled": _group_stats(con, "hum_l1_any", "humanities_pooled"),
        "non_humanities_baseline": _group_stats(con, "NOT hum_l1_any", "baseline"),
        "by_subfield": {},
    }
    for sf in SUBFIELDS:
        s = sf.replace("'", "''")
        out["by_subfield"][sf] = _group_stats(con, f"subfield = '{s}'", sf)
    con.close()
    out["notes"] = (
        "Participation = share of persons with >=1 record in the parsed enrichment "
        "table (a floor; LinkedIn under-reports). 'professional_multilingual' = >=1 "
        "language at Full/Professional-working/Native proficiency. These dimensions "
        "are OUTSIDE the paid job-title fan and are where humanities over-index. "
        "Population = any-degree L1 humanities (pooled); sub-field = terminal pooled "
        "field group.")
    out["generated"] = date.today().isoformat()
    out["runtime_s"] = round(time.time() - t0, 1)
    return out


def main() -> None:
    r = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(r, indent=2))
    h, b = r["humanities_pooled"], r["non_humanities_baseline"]
    print(f"humanities (n={h['n_persons']:,}) vs baseline (n={b['n_persons']:,}):")
    for k in ("volunteer_pct", "publications_pct", "honors_pct",
              "org_leadership_pct", "professional_multilingual_pct"):
        print(f"  {k:30} hum={h[k]:5}%  baseline={b[k]:5}%")
    print(f"  top humanities volunteer causes: "
          f"{[c['cause'] for c in h['top_volunteer_causes'][:4]]}")
    lang = r["by_subfield"]["Languages & Linguistics"]
    print(f"  Languages majors professional_multilingual: {lang['professional_multilingual_pct']}%")


if __name__ == "__main__":
    main()
