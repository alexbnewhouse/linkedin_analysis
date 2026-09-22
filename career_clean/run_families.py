"""Occupation-family tier driver (spec P4, gate per the 2026-09-22 pre-review).

    uv run python -m career_clean.run_families classify   # -> normalized/mappings/title_family.parquet
    uv run python -m career_clean.run_families gate       # score anchors; stamp landable per (family, stratum)
    uv run python -m career_clean.run_families sample     # 100-row blind sample of landed steps (after rebuild)

classify runs the ported rules classifier over every distinct raw title value in
normalized/mappings/career_title.parquet and records family, nine-level seniority, flags,
confidence and the family's SOC-major anchor.

gate scores each family's anchor on TWO populations and TWO strata:
  populations  (a) det gold: career_clean/results/soc_gold.parquet minus the "mixed" roles
                   (any role_canonical that also has det-coded steps but is used by uncoded
                   raw variants -- the labels there are minorities, not the string's meaning);
               (b) jury: normalized/mappings/role_soc_jury.parquet (298,942 accepted roles),
                   the in-distribution set the family tier lands beside.
  strata       managerial (seniority9 in manager/director/vp/c_suite/owner) vs the rest,
               because functional families (marketing 13, sales 41, ...) are wrong on
               managers by SOC convention (managers are 11).
The string classified is role_display (soc_candidates.parquet). A (family, stratum) is
landable when precision >= BAR with n >= MIN_GOLD on BOTH populations at confidence 'high',
and the family is not in NEVER_LAND. Role-unweighted and step-weighted precision are both
written to career_clean/results/family_gate.json.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from career_clean.families.classify import classify_title
from career_clean.families.taxonomy import FAMILIES, NEVER_LAND

ROOT = Path(__file__).resolve().parent.parent
TITLES = ROOT / "normalized" / "mappings" / "career_title.parquet"
STEPS = ROOT / "normalized" / "career_steps.parquet"
OUT = ROOT / "normalized" / "mappings" / "title_family.parquet"
GOLD = ROOT / "career_clean" / "results" / "soc_gold.parquet"
CANDIDATES = ROOT / "career_clean" / "results" / "soc_candidates.parquet"
JURY = ROOT / "normalized" / "mappings" / "role_soc_jury.parquet"
GATE = ROOT / "career_clean" / "results" / "family_gate.json"
SAMPLE = ROOT / "career_clean" / "results" / "family_sample.jsonl"
BAR = 0.85
MIN_GOLD = 100
CHUNK = 40_000
MANAGERIAL = frozenset({"manager", "director", "vp", "c_suite", "owner"})
SALT = "p4-family-2026-09-22"
RUBRIC = ("pass = the assigned SOC major group is the right group for this job title at this "
          "employer (a marketing manager is Management 11, a marketing coordinator is Business "
          "13); fail = a different major group is clearly right; unsure = the title alone cannot "
          "place the job")


def stratum(seniority9: str) -> str:
    return "managerial" if seniority9 in MANAGERIAL else "staff"


def _work(vals: list[str]) -> list[tuple]:
    out = []
    for v in vals:
        r = classify_title(v or "")
        out.append((v, r["family"], r["seniority"], r["flags"], r["confidence"], FAMILIES[r["family"]][2]))
    return out


def _landable_map() -> dict[tuple[str, str], bool]:
    if not GATE.exists():
        return {}
    g = json.loads(GATE.read_text())
    return {(fam, st): v["landable"] for fam, d in g["families"].items() for st, v in d["strata"].items()}


def classify() -> None:
    con = duckdb.connect()
    vals = [r[0] for r in con.execute(f"SELECT value FROM read_parquet('{TITLES}')").fetchall()]
    chunks = [vals[i:i + CHUNK] for i in range(0, len(vals), CHUNK)]
    rows: list[tuple] = []
    with Pool(16) as pool:
        for part in pool.imap(_work, chunks, chunksize=1):
            rows.extend(part)
    land = _landable_map()
    t = pa.table({
        "value": [r[0] for r in rows],
        "family": [r[1] for r in rows],
        "seniority9": [r[2] for r in rows],
        "flags": pa.array([r[3] for r in rows], pa.list_(pa.string())),
        "confidence": [r[4] for r in rows],
        "soc_major_anchor": [r[5] for r in rows],
        "landable": [bool(land.get((r[1], stratum(r[2])), False)) and r[4] == "high"
                     and r[1] not in NEVER_LAND and r[5] is not None for r in rows],
    })
    pq.write_table(t, OUT, compression="zstd")
    n_land = sum(t.column("landable").to_pylist())
    print(f"wrote {OUT} ({t.num_rows:,} titles; {n_land:,} landable" +
          ("" if GATE.exists() else "; run `gate` to stamp landable") + ")")


def _score(rows: list[tuple[str, str, int]]) -> dict:
    """rows: (role_display, gold_major, n_steps) -> per (family, stratum) precision."""
    per: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for disp, major, n_steps in rows:
        r = classify_title(disp or "")
        if r["confidence"] != "high":
            continue
        anchor = FAMILIES[r["family"]][2]
        if anchor is None:
            continue
        per.setdefault((r["family"], stratum(r["seniority"])), []).append((int(anchor == major), n_steps or 0))
    out = {}
    for key, hits in per.items():
        n = len(hits)
        w = sum(s for _, s in hits)
        out[key] = {"n": n, "precision": round(sum(h for h, _ in hits) / n, 4),
                    "precision_step_weighted": round(sum(h * s for h, s in hits) / w, 4) if w else None}
    return out


def gate() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    mixed = {r[0] for r in con.execute(f"""
        SELECT DISTINCT role_canonical FROM read_parquet('{STEPS}')
        WHERE occupation_code IS NOT NULL AND role_canonical IS NOT NULL
          AND role_canonical IN (SELECT role_canonical FROM read_parquet('{STEPS}') WHERE occupation_code IS NULL)
    """).fetchall()}
    gold = con.execute(f"""
        SELECT role_display, gold_major, n_steps, role_canonical FROM read_parquet('{GOLD}')
        WHERE gold_major IS NOT NULL""").fetchall()
    gold_rows = [(d, m, n) for d, m, n, rc in gold if rc not in mixed]
    jury_rows = con.execute(f"""
        SELECT c.role_display, j.soc_major, c.n_steps
        FROM read_parquet('{JURY}') j JOIN read_parquet('{CANDIDATES}') c USING (role_canonical)
        WHERE j.soc_major IS NOT NULL AND j.soc_major <> 'XUN'""").fetchall()
    a = _score(gold_rows)
    b = _score(jury_rows)
    fams: dict[str, dict] = {}
    for fam in FAMILIES:
        strata = {}
        for st in ("managerial", "staff"):
            ga = a.get((fam, st), {"n": 0, "precision": None, "precision_step_weighted": None})
            gb = b.get((fam, st), {"n": 0, "precision": None, "precision_step_weighted": None})
            landable = (fam not in NEVER_LAND and FAMILIES[fam][2] is not None
                        and ga["n"] >= MIN_GOLD and gb["n"] >= MIN_GOLD
                        and ga["precision"] >= BAR and gb["precision"] >= BAR)
            strata[st] = {"det_gold": ga, "jury": gb, "landable": bool(landable)}
        fams[fam] = {"anchor": FAMILIES[fam][2], "never_land": fam in NEVER_LAND, "strata": strata}
    GATE.write_text(json.dumps({
        "generated": date.today().isoformat(), "bar": BAR, "min_gold": MIN_GOLD,
        "populations": {"det_gold_roles": len(gold_rows), "det_gold_mixed_excluded": len(gold) - len(gold_rows),
                        "jury_roles": len(jury_rows)},
        "families": fams}, indent=1) + "\n")
    print(f"{'family':24s} {'stratum':10s} {'gold n':>7s} {'gold p':>7s} {'jury n':>7s} {'jury p':>7s}  land")
    for fam, d in sorted(fams.items(), key=lambda kv: -sum(v["det_gold"]["n"] + v["jury"]["n"] for v in kv[1]["strata"].values())):
        for st, v in d["strata"].items():
            ga, gb = v["det_gold"], v["jury"]
            print(f"{fam:24s} {st:10s} {ga['n']:7d} {str(ga['precision']):>7s} {gb['n']:7d} {str(gb['precision']):>7s}  "
                  f"{'LAND' if v['landable'] else ('never' if d['never_land'] else '-')}")
    if OUT.exists():
        classify()


def sample(n: int = 100) -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    from transition_network.common import SOC_MAJOR
    con.execute(f"""
      CREATE TEMP VIEW s AS
      SELECT c.title_raw, c.company_raw, i.l1 AS industry_l1, c.title_family, c.title_seniority9,
             c.occupation_major_pooled AS soc_major, c.linkedin_id, c.experience_idx, c.position_idx, c.source_table
      FROM read_parquet('{STEPS}') c
      LEFT JOIN read_parquet('{ROOT / "industry" / "results" / "step_industry.parquet"}') i
        ON i.source_table = c.source_table AND i.linkedin_id = c.linkedin_id
       AND i.experience_idx = c.experience_idx AND i.position_idx IS NOT DISTINCT FROM c.position_idx
      WHERE c.occupation_source = 'family'
    """)
    rows = con.execute(f"""
      SELECT * FROM s ORDER BY hash(linkedin_id || '|' || experience_idx::VARCHAR || '|' ||
                                    coalesce(position_idx::VARCHAR, '') || '|{SALT}') LIMIT {int(n)}""").fetchall()
    cols = [d[0] for d in con.description]
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    with SAMPLE.open("w") as fh:
        fh.write(json.dumps({"_header": True, "sample": "family", "n": len(rows), "salt": SALT,
                             "rubric": RUBRIC, "labels": ["pass", "fail", "unsure"]}) + "\n")
        for i, r in enumerate(rows):
            d = dict(zip(cols, r))
            d["soc_major_label"] = SOC_MAJOR.get(d["soc_major"], "")
            d["id"] = f"family:{i:03d}"
            for k in ("linkedin_id", "experience_idx", "position_idx", "source_table"):
                d.pop(k, None)
            fh.write(json.dumps(d, default=str, ensure_ascii=False) + "\n")
    print(f"wrote {SAMPLE} ({len(rows)} rows)")


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"classify": classify, "gate": gate, "sample": sample}[cmd]()
