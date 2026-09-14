"""Extract the archetype-tracking slice the journey prototype shows.

Reads archetypes/results/{person_year_archetype,role_archetype,role_features}.parquet
and portal/results/portal_data.json; writes prototype/journey_site/journey_data.json.
Fields of study are the NHA level-1 field groups with >= 2,000 people followed to
career year ten. Time axis is career-entry (years since first datable job), the
archetypes module's axis. Every named cell clears the ten-person bar.
"""
import json, sys
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[2]
P = f"'{ROOT}/archetypes/results/person_year_archetype.parquet'"
RA = f"'{ROOT}/archetypes/results/role_archetype.parquet'"
RF = f"'{ROOT}/archetypes/results/role_features.parquet'"
OUT = Path(__file__).with_name("journey_data.json")
BAR = 10
# generic one-word titles that name a rank or a season rather than a job
GENERIC = "('assistant','associate','research','summer','account','art','creative','manager','director','officer','member','student','intern','specialist','coordinator','representative','various','professional','staff','employee','worker','contractor','volunteer','analyst','sales','senior','junior','lead','president','vice president','executive','partner','principal','fellow','graduate','trainee','apprentice','freelance','self employed','self-employed','owner','founder','co-founder','independent','consultant','administrator','supervisor','operations','marketing','finance','legal','design','writer','editor','producer','teacher','managing','production','human resources','board member','general')"
YEARS = [1, 3, 5, 10]
EXCLUDE = {"Other", "Psychology"}
PORTAL_KEY = {"Fine & Performing Arts": "arts", "English & Literature": "english", "History": "history",
              "Philosophy & Religion": "philrel", "Communication & Media": "commmedia"}

con = duckdb.connect()
con.execute(f"CREATE TEMP TABLE py AS SELECT linkedin_id, career_year, archetype_id, humanities_field_group AS fg FROM {P} WHERE in_window AND nha_level = 1 AND career_year <= 10")
fields = [r[0] for r in con.execute(f"""
  SELECT fg FROM py WHERE career_year = 10 GROUP BY fg HAVING count(DISTINCT linkedin_id) >= 2000 ORDER BY count(DISTINCT linkedin_id) DESC""").fetchall() if r[0] not in EXCLUDE]
print("fields:", fields, file=sys.stderr)

def slug(s):
    import re
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")

def one(where, key):
    d = {"key": key}
    d["persons"] = con.execute(f"SELECT count(DISTINCT linkedin_id) FROM py WHERE {where}").fetchone()[0]
    occ = {}
    for y in YEARS:
        rows = con.execute(f"SELECT archetype_id, count(DISTINCT linkedin_id) FROM py WHERE {where} AND career_year={y} GROUP BY 1").fetchall()
        tot = sum(n for _, n in rows)
        occ[y] = {"n": tot, "mix": {int(a): n for a, n in rows if n >= BAR}}
    d["occ"] = occ
    # y1 -> y10 flows per person
    con.execute(f"""CREATE OR REPLACE TEMP TABLE fl AS
      SELECT a.linkedin_id, a.archetype_id AS a1, b.archetype_id AS a10
      FROM (SELECT linkedin_id, archetype_id FROM py WHERE {where} AND career_year=1) a
      JOIN (SELECT linkedin_id, archetype_id FROM py WHERE {where} AND career_year=10) b USING (linkedin_id)""")
    rows = con.execute("SELECT a1, a10, count(*) FROM fl GROUP BY 1,2").fetchall()
    d["flows_n"] = sum(n for *_, n in rows)
    d["flows"] = [[int(a), int(b), n] for a, b, n in rows if n >= BAR]
    d["flows_suppressed"] = sum(1 for *_, n in rows if n < BAR)
    # y5 waypoint for named cells
    rows = con.execute(f"""SELECT f.a1, f.a10, p.archetype_id, count(*) FROM fl f
      JOIN (SELECT linkedin_id, archetype_id FROM py WHERE {where} AND career_year=5) p USING (linkedin_id)
      GROUP BY 1,2,3 HAVING count(*) >= {BAR}""").fetchall()
    d["via5"] = [[int(a), int(b), int(c), n] for a, b, c, n in rows]
    # how long it took: median career year of first entry into the year-10 kind
    rows = con.execute(f"""SELECT b.archetype_id, median(f.first_y), count(*) FROM
      (SELECT linkedin_id, archetype_id FROM py WHERE {where} AND career_year=10) b
      JOIN (SELECT linkedin_id, archetype_id, min(career_year) AS first_y FROM py WHERE {where} GROUP BY 1,2) f USING (linkedin_id, archetype_id)
      GROUP BY 1 HAVING count(*) >= {BAR}""").fetchall()
    d["first_entry"] = {int(a): float(m) for a, m, n in rows}
    return d

data = {"bar": BAR, "years": YEARS, "axis": "career-entry", "fields": {}, "all": None}
for f in fields:
    k = slug(f)
    data["fields"][k] = one(f"fg = '{f}'", k) | {"name": f, "portal": PORTAL_KEY.get(f)}
    print(k, data["fields"][k]["persons"], file=sys.stderr)
data["all"] = one("TRUE", "all") | {"name": "all humanities fields"}

# named roles per archetype, and a search index
cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM {RF}").fetchall()]
print("role_features cols:", cols, file=sys.stderr)
textcol = next((c for c in ("role_display", "role_text", "title", "role") if c in cols), None)
if textcol:
    con.execute(f"""CREATE TEMP TABLE roles AS SELECT r.role_canonical, r.archetype_id, r.n_persons, f.{textcol} AS txt
      FROM {RA} r JOIN {RF} f USING (role_canonical) WHERE r.archetype_id > 0""")
else:
    con.execute(f"CREATE TEMP TABLE roles AS SELECT role_canonical, archetype_id, n_persons, role_canonical AS txt FROM {RA} WHERE archetype_id > 0")
data["roles"] = {}
for a, in con.execute("SELECT DISTINCT archetype_id FROM roles ORDER BY 1").fetchall():
    rows = con.execute(f"SELECT txt, n_persons FROM roles WHERE archetype_id={a} AND length(txt) BETWEEN 3 AND 40 AND lower(txt) NOT IN {GENERIC} AND txt NOT LIKE '%and Officer%' ORDER BY n_persons DESC LIMIT 14").fetchall()
    data["roles"][int(a)] = [[t, n] for t, n in rows]
data["search"] = [[t, int(a)] for t, a, n in con.execute(f"SELECT txt, archetype_id, n_persons FROM roles WHERE n_persons >= 25 AND length(txt) BETWEEN 3 AND 40 AND lower(txt) NOT IN {GENERIC} ORDER BY n_persons DESC LIMIT 4000").fetchall()]

# portal extras for the five majors: employers and graduate steps
pd = json.load(open(ROOT / "portal/results/portal_data.json"))
data["portal"] = {}
for k, m in pd["majors"].items():
    gt = m["launchboard"]["grad_track"]
    data["portal"][k] = {"employers": [e for e in m["employer_field"]["labeled"] if e["n"] >= BAR][:12],
                         "grad": {"cohort": gt["cohort"], "any": gt["any"], "by_type": [t for t in gt["by_type"] if not t["below_bar"]]}}
data["generated"] = pd["generated"]
OUT.write_text(json.dumps(data, separators=(",", ":")))
print("wrote", OUT, OUT.stat().st_size, file=sys.stderr)
