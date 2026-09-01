"""Crosswalk LinkedIn school slugs -> IPEDS UNITID, and emit institution metadata
(control, Carnegie classification, level, region, metro). High-precision,
propose-only (never touches normalized/education.parquet).

    uv run python -m reference.build_ipeds_crosswalk            # dry-run: coverage + gold sample
    uv run python -m reference.build_ipeds_crosswalk --execute  # write the parquets + manifest

Matching (precision-first):
  1. exact  -- slug's modal name, normalized, == a UNIQUE IPEDS name (INSTNM or IALIAS)
  2. core   -- normalized name == a UNIQUE IPEDS "core" (INSTNM minus campus suffix
               after '-' or ' at '); ambiguous cores (multi-campus) are NOT matched
  3. curate -- a small hand-verified flagship map for high-volume bare names that
               are ambiguous by rule (University of Washington -> Seattle, etc.)
Everything else stays UNMATCHED (IPEDS is US Title-IV only; a low slug-match rate
is expected -- person-weighted coverage is the metric that matters).

Sources: IPEDS HD2023 (institution directory), NCES, US Gov public domain.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
HD = ROOT / "reference" / "ipeds" / "HD2023.csv"
EDU = ROOT / "normalized" / "education.parquet"
META_OUT = ROOT / "reference" / "institution_meta.parquet"
XWALK_OUT = ROOT / "normalized" / "mappings" / "school_ipeds.parquet"
MANIFEST = ROOT / "reference" / "ipeds" / "_crosswalk_manifest.json"

# --- documented IPEDS code -> label decodes (HD2023 dictionary) ---------------
CONTROL_LABEL = {"1": "public", "2": "private_nonprofit", "3": "private_forprofit",
                 "-3": "unknown"}
ICLEVEL_LABEL = {"1": "4yr+", "2": "2yr", "3": "<2yr", "-3": "unknown"}
# Carnegie 2021 Basic (C21BASIC) -> compact label. Full scheme has many codes;
# we bucket the ones that matter for an outcomes moderator and pass the raw code
# through for anything finer.
C21_LABEL = {
    # associate's colleges (1-9) and special-focus two-year (10-13)
    "1": "assoc_high_transfer_high_trad", "2": "assoc_high_transfer_mixed",
    "3": "assoc_high_transfer_high_nontrad", "4": "assoc_mixed_high_trad",
    "5": "assoc_mixed_mixed", "6": "assoc_mixed_high_nontrad",
    "7": "assoc_high_cte_high_trad", "8": "assoc_high_cte_mixed",
    "9": "assoc_high_cte_high_nontrad",
    "10": "special_focus_2yr_health", "11": "special_focus_2yr_technical",
    "12": "special_focus_2yr_arts_design", "13": "special_focus_2yr_other",
    "14": "bacc_associates_dominant",
    # doctoral (15-17), master's (18-20), baccalaureate (21-23)
    "15": "R1_doctoral_very_high", "16": "R2_doctoral_high",
    "17": "doctoral_professional",
    "18": "masters_larger", "19": "masters_medium", "20": "masters_small",
    "21": "bacc_arts_sciences", "22": "bacc_diverse", "23": "bacc_associates_mixed",
    # special-focus four-year (24-32) and tribal (33)
    "24": "special_focus_4yr_faith", "25": "special_focus_4yr_medical",
    "26": "special_focus_4yr_health", "27": "special_focus_4yr_engineering",
    "28": "special_focus_4yr_tech", "29": "special_focus_4yr_business",
    "30": "special_focus_4yr_arts", "31": "special_focus_4yr_law",
    "32": "special_focus_4yr_other", "33": "tribal",
    "-2": "not_applicable", "-3": "unknown", "0": "not_classified",
}

# Hand-verified flagship UNITIDs for high-volume bare-name slugs that rule 2
# leaves ambiguous (multi-campus). UNITIDs verified against HD2023 INSTNM.
CURATED_FLAGSHIP = {
    "university-of-washington": 236948,       # UW-Seattle Campus
    "university-of-maryland": 163286,         # UMD-College Park
    "university-of-michigan": 170976,         # UM-Ann Arbor
    "penn-state-university": 214777,          # Penn State-Main Campus
    "indiana-university": 151351,             # IU-Bloomington
    "university-of-wisconsin": 240444,        # UW-Madison
    "university-of-colorado": 126614,         # CU-Boulder
    "university-of-pittsburgh": 215293,       # Pitt-main campus (Pittsburgh)
    "university-of-massachusetts": 166629,    # UMass Amherst
    "rutgers-university": 186380,             # Rutgers-New Brunswick
    "university-of-minnesota": 174066,        # UMN-Twin Cities
    "university-of-missouri": 178396,         # Mizzou (Columbia)
    "university-of-nebraska": 181464,         # UNL (Lincoln)
    "purdue-university": 243780,              # Purdue-Main Campus
}

_STOP = re.compile(r"\b(the|of|at|a|and)\b")
_ABBR = [("univ.", "university"), ("univ ", "university "), ("&", "and"),
         ("st.", "saint")]


def norm(name: str | None) -> str:
    if not name:
        return ""
    s = name.lower().strip()
    for a, b in _ABBR:
        s = s.replace(a, b)
    s = re.sub(r"[,\-–—/().']", " ", s)     # separators -> space
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = _STOP.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def core(instnm: str) -> str:
    """INSTNM minus its campus suffix: drop everything after the first '-' or
    ' at '. 'University of Michigan-Ann Arbor' -> 'University of Michigan'."""
    s = re.split(r"\s*-\s*|\s+at\s+", instnm, maxsplit=1)[0]
    return norm(s)


def _ipeds_indexes(con):
    rows = con.execute(
        f"SELECT UNITID, INSTNM, IALIAS FROM read_csv('{HD}', ignore_errors=true, "
        f"all_varchar=true)").fetchall()
    exact: dict[str, set] = {}
    core_ix: dict[str, set] = {}
    for uid, instnm, ialias in rows:
        uid = int(uid)
        keys = {norm(instnm)}
        if ialias:
            for al in re.split(r"\s{2,}|\|", ialias):   # aliases: 2+ spaces or '|'
                if al.strip():
                    keys.add(norm(al))
        for k in keys:
            if k:
                exact.setdefault(k, set()).add(uid)
        c = core(instnm)
        if c:
            core_ix.setdefault(c, set()).add(uid)
    return exact, core_ix


def _slug_names(con):
    return con.execute(f"""
      WITH s AS (SELECT school_slug, linkedin_id, school_raw FROM read_parquet('{EDU}')
                 WHERE school_slug IS NOT NULL AND NOT is_duplicate AND school_raw IS NOT NULL)
      SELECT school_slug, mode(school_raw) AS nm, count(DISTINCT linkedin_id) AS np
      FROM s GROUP BY 1""").fetchall()


def build_crosswalk(con):
    exact, core_ix = _ipeds_indexes(con)
    matches = []
    for slug, nm, np in _slug_names(con):
        if slug in CURATED_FLAGSHIP:
            matches.append((slug, CURATED_FLAGSHIP[slug], "curated_flagship", 1.0, np))
            continue
        k = norm(nm)
        if not k:
            continue
        if k in exact and len(exact[k]) == 1:
            matches.append((slug, next(iter(exact[k])), "exact", 1.0, np))
        elif (k in core_ix and len(core_ix[k]) == 1 and len(k.split()) >= 3):
            # >=3 tokens: short cores ("university east") collide across schools
            # (e.g. "University of the East" [PH] vs "University of East-West
            # Medicine"). Require a distinctive multi-token core.
            matches.append((slug, next(iter(core_ix[k])), "core", 0.9, np))
        # else: unmatched (ambiguous or absent) -- precision over coverage
    return matches


def run(execute: bool) -> dict:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    matches = build_crosswalk(con)

    con.execute("CREATE TEMP TABLE xw (school_slug VARCHAR, unitid INTEGER, "
                "match_method VARCHAR, match_confidence DOUBLE, n_persons BIGINT)")
    con.executemany("INSERT INTO xw VALUES (?, ?, ?, ?, ?)", matches)
    dup = con.execute("SELECT count(*)-count(DISTINCT school_slug) FROM xw").fetchone()[0]
    assert dup == 0, f"{dup} slugs matched twice"

    # coverage: person-weighted is the metric that matters
    tot_slugs, tot_persons = con.execute(f"""
      WITH s AS (SELECT school_slug, count(DISTINCT linkedin_id) np FROM read_parquet('{EDU}')
                 WHERE school_slug IS NOT NULL AND NOT is_duplicate GROUP BY 1)
      SELECT count(*), sum(np) FROM s""").fetchone()
    m_slugs = con.execute("SELECT count(*) FROM xw").fetchone()[0]
    m_persons = con.execute("SELECT sum(n_persons) FROM xw").fetchone()[0]

    # institution metadata table (all IPEDS institutions; decoded)
    con.execute(f"CREATE OR REPLACE TEMP TABLE hd AS SELECT * FROM "
                f"read_csv('{HD}', ignore_errors=true, all_varchar=true)")
    con.execute("CREATE TEMP TABLE lut_control (k VARCHAR, v VARCHAR)")
    con.executemany("INSERT INTO lut_control VALUES (?,?)", list(CONTROL_LABEL.items()))
    con.execute("CREATE TEMP TABLE lut_ic (k VARCHAR, v VARCHAR)")
    con.executemany("INSERT INTO lut_ic VALUES (?,?)", list(ICLEVEL_LABEL.items()))
    con.execute("CREATE TEMP TABLE lut_c21 (k VARCHAR, v VARCHAR)")
    con.executemany("INSERT INTO lut_c21 VALUES (?,?)", list(C21_LABEL.items()))

    con.execute("""
      CREATE OR REPLACE TEMP TABLE meta AS
      SELECT CAST(hd.UNITID AS INTEGER) AS unitid, hd.INSTNM AS instnm,
             hd.CONTROL AS control, lc.v AS control_label,
             hd.ICLEVEL AS iclevel, li.v AS iclevel_label,
             hd.C21BASIC AS carnegie_c21basic, lca.v AS carnegie_label,
             hd.STABBR AS state, hd.OBEREG AS region, hd.CBSA AS cbsa_metro, hd.CITY AS city
      FROM hd
      LEFT JOIN lut_control lc ON lc.k = hd.CONTROL
      LEFT JOIN lut_ic li ON li.k = hd.ICLEVEL
      LEFT JOIN lut_c21 lca ON lca.k = hd.C21BASIC
    """)

    # gold sample: frequency-stratified matched pairs, slug name vs INSTNM
    gold = con.execute("""
      SELECT x.school_slug, x.n_persons, x.match_method, m.instnm, m.control_label, m.carnegie_label
      FROM xw x JOIN meta m USING (unitid)
      ORDER BY x.n_persons DESC LIMIT 40""").fetchall()

    by_method = dict(con.execute("SELECT match_method, count(*) FROM xw GROUP BY 1").fetchall())

    report = {
        "generated": date.today().isoformat(),
        "matched_slugs": m_slugs, "total_slugs": tot_slugs,
        "slug_coverage_pct": round(100.0 * m_slugs / tot_slugs, 1),
        "matched_persons": int(m_persons), "total_persons": int(tot_persons),
        "person_coverage_pct": round(100.0 * m_persons / tot_persons, 1),
        "by_method": {k: int(v) for k, v in by_method.items()},
        "top40_matches": [
            {"slug": g[0], "persons": g[1], "method": g[2], "instnm": g[3],
             "control": g[4], "carnegie": g[5]} for g in gold],
        "executed": execute,
    }
    if execute:
        XWALK_OUT.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY (SELECT school_slug, unitid, match_method, match_confidence "
                    f"FROM xw ORDER BY school_slug) TO '{XWALK_OUT}' (FORMAT parquet, COMPRESSION zstd)")
        con.execute(f"COPY (SELECT * FROM meta ORDER BY unitid) TO '{META_OUT}' "
                    f"(FORMAT parquet, COMPRESSION zstd)")
        MANIFEST.write_text(json.dumps(report, indent=2) + "\n")
    con.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    r = run(ap.parse_args().execute)
    print(f"matched {r['matched_slugs']:,}/{r['total_slugs']:,} slugs "
          f"({r['slug_coverage_pct']}%), {r['matched_persons']:,}/{r['total_persons']:,} "
          f"persons ({r['person_coverage_pct']}% person-weighted)")
    print(f"by method: {r['by_method']}")
    print("top matches (eyeball for precision):")
    for g in r["top40_matches"][:20]:
        print(f"  {g['persons']:>7,} {g['method']:16} {g['slug']:34} -> {g['instnm']} "
              f"[{g['control']}/{g['carnegie']}]")
    if not r["executed"]:
        print("(dry-run -- pass --execute to write parquets)")


if __name__ == "__main__":
    main()
