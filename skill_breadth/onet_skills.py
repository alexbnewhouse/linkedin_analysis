"""Task 2 (part 2): O*NET 29.3 skill matrix + role -> SOC mapping.

Downloads (if absent):
  reference/onet_skills.txt              -- O*NET 29.3 Skills.txt
  reference/onet_occupation_data_29_3.txt -- O*NET 29.3 Occupation Data.txt

Builds:
  results/onet_skill_matrix.parquet -- one row per 6-digit SOC present in the
      29.3 skills table (763 SOCs), columns soc + the 35 skill element names
      (Element Name, Scale ID='IM'), mean-aggregated from O*NET-SOC detail
      codes to 6-digit SOC, then z-scored per skill across the 763-SOC table,
      then L2-normalized per row. Wide format (not long) so Task 3 can join
      role_soc.soc -> this table directly and use the 35 columns as a vector.
  results/role_soc.parquet -- one row per role key (linkedin_id,
      experience_idx, position_idx): soc (6-digit, always a SOC present in
      the skills table), soc_source in {'pooled','nearest'}, nearest_cos
      (cosine to the matched SOC's O*NET Title+Description text; NULL for
      soc_source='pooled', where no nearest search was run).
  results/_embed_manifest.json

Role -> SOC:
  occupation_code_pooled, truncated to 6 digits, when present AND that 6-digit
  SOC is one of the 763 in the skills table -> soc_source='pooled'.
  Otherwise (no pooled code, or pooled code not in the 29.3 skills table --
  taxonomy drift) -> nearest O*NET occupation by cosine between the role-text
  embedding (cache/role_emb.npy, from embed_roles.py) and the O*NET
  `Title. Description` embedding, restricted to the 763 skills-table SOCs.
  For the occupation text of an aggregated 6-digit SOC, the 29.3 Occupation
  Data ".00" detail row is used if present, else the first row (by
  O*NET-SOC Code) for that 6-digit prefix.

    uv run python -m skill_breadth.onet_skills
"""

from __future__ import annotations

import urllib.request

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from . import common as C

ONET_SKILLS_URL = "https://www.onetcenter.org/dl_files/database/db_29_3_text/Skills.txt"
ONET_OCC_URL = "https://www.onetcenter.org/dl_files/database/db_29_3_text/Occupation%20Data.txt"

ONET_SKILLS_PATH = C.ROOT / "reference" / "onet_skills.txt"
ONET_OCC_PATH = C.ROOT / "reference" / "onet_occupation_data_29_3.txt"

N_SKILLS = 35


def truncate_soc(onet_soc_code: str) -> str:
    """'15-1252.00' -> '15-1252' (6-digit SOC from an 8-digit O*NET-SOC code)."""
    return onet_soc_code[:7]


def zscore_l2_normalize(mat: np.ndarray) -> np.ndarray:
    """Per-column z-score, then per-row L2 normalize. mat: [n, d] float."""
    mu = mat.mean(axis=0, keepdims=True)
    sigma = mat.std(axis=0, ddof=0, keepdims=True)
    z = (mat - mu) / sigma
    norms = np.linalg.norm(z, axis=1, keepdims=True)
    return z / norms


def pooled_soc_assignment(occupation_code_pooled: str | None, valid_socs: set[str]) -> tuple[str | None, str]:
    """(soc, soc_source) if occupation_code_pooled resolves to a SOC in the
    29.3 skills table; soc is None (caller must run nearest match) with
    soc_source='nearest' otherwise -- including when occupation_code_pooled
    is missing entirely."""
    if occupation_code_pooled is None:
        return None, "nearest"
    soc6 = truncate_soc(occupation_code_pooled)
    if soc6 in valid_socs:
        return soc6, "pooled"
    return None, "nearest"


def download_if_absent() -> None:
    for path, url in ((ONET_SKILLS_PATH, ONET_SKILLS_URL), (ONET_OCC_PATH, ONET_OCC_URL)):
        if path.exists():
            continue
        print(f"downloading {url} -> {path}", flush=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            path.write_bytes(resp.read())


def build_skill_matrix(con) -> tuple[list[str], np.ndarray]:
    """Returns (soc_list, matrix) -- matrix is [n_soc, 35] z-scored then
    L2-normalized. soc_list order matches matrix row order."""
    con.sql(f"""
        CREATE OR REPLACE TEMP TABLE skills_raw AS
        SELECT
            left("O*NET-SOC Code", 7) AS soc,
            "Element Name" AS skill,
            "Data Value" AS value
        FROM read_csv('{ONET_SKILLS_PATH}', delim='\t', header=true, quote='')
        WHERE "Scale ID" = 'IM'
    """)
    n_skills = con.sql("SELECT count(DISTINCT skill) FROM skills_raw").fetchone()[0]
    if n_skills != N_SKILLS:
        raise ValueError(f"expected {N_SKILLS} IM-scale skills, found {n_skills}")

    agg = con.sql("""
        SELECT soc, skill, avg(value) AS value
        FROM skills_raw
        GROUP BY soc, skill
        ORDER BY soc, skill
    """).arrow().read_all()

    socs = sorted(set(agg.column("soc").to_pylist()))
    skills = sorted(set(agg.column("skill").to_pylist()))
    soc_idx = {s: i for i, s in enumerate(socs)}
    skill_idx = {s: i for i, s in enumerate(skills)}

    mat = np.full((len(socs), len(skills)), np.nan, dtype=np.float64)
    for soc, skill, value in zip(
        agg.column("soc").to_pylist(), agg.column("skill").to_pylist(), agg.column("value").to_pylist()
    ):
        mat[soc_idx[soc], skill_idx[skill]] = value
    if np.isnan(mat).any():
        raise ValueError("skill matrix has missing (soc, skill) cells -- not every SOC has all 35 skills")

    unit = zscore_l2_normalize(mat)

    return socs, unit.astype(np.float32), skills


def build_occupation_texts(con, valid_socs: set[str]) -> tuple[list[str], list[str]]:
    """One (soc, text) per 6-digit SOC in valid_socs: the '.00' detail row's
    Title. Description if present, else the first detail row for that SOC
    (by O*NET-SOC Code)."""
    occ = con.sql(f"""
        SELECT "O*NET-SOC Code" AS onet_soc, left("O*NET-SOC Code", 7) AS soc,
               "Title" AS title, "Description" AS description
        FROM read_csv('{ONET_OCC_PATH}', delim='\t', header=true, quote='')
        ORDER BY soc, onet_soc
    """).arrow().read_all()

    by_soc: dict[str, list[tuple[str, str, str]]] = {}
    for onet_soc, soc, title, desc in zip(
        occ.column("onet_soc").to_pylist(), occ.column("soc").to_pylist(),
        occ.column("title").to_pylist(), occ.column("description").to_pylist(),
    ):
        if soc in valid_socs:
            by_soc.setdefault(soc, []).append((onet_soc, title, desc))

    missing = valid_socs - set(by_soc)
    if missing:
        raise ValueError(f"{len(missing)} skills-table SOCs have no Occupation Data row: {sorted(missing)[:10]}")

    socs_out, texts_out = [], []
    for soc in sorted(valid_socs):
        rows = by_soc[soc]
        chosen = next((r for r in rows if r[0].endswith(".00")), rows[0])
        _, title, desc = chosen
        socs_out.append(soc)
        texts_out.append(f"{title}. {desc}")
    return socs_out, texts_out


def run() -> dict:
    download_if_absent()
    con = C.connect()

    with C.Timer("skill matrix"):
        socs, skill_mat, skill_cols = build_skill_matrix(con)
    valid_socs = set(socs)
    print(f"skill matrix: {len(socs)} SOCs x {len(skill_cols)} skills", flush=True)

    C.RESULTS.mkdir(parents=True, exist_ok=True)
    matrix_table = pa.table(
        {"soc": socs, **{col: skill_mat[:, i] for i, col in enumerate(skill_cols)}}
    )
    pq.write_table(matrix_table, str(C.RESULTS / "onet_skill_matrix.parquet"))

    with C.Timer("occupation texts"):
        occ_socs, occ_texts = build_occupation_texts(con, valid_socs)
    occ_emb = C.encode(occ_texts, name="onet_occ_text_29_3")
    soc_order = {s: i for i, s in enumerate(occ_socs)}

    role_keys = pq.read_table(str(C.CACHE / "role_keys.parquet"))
    role_emb = np.load(C.CACHE / "role_emb.npy")
    n_roles = role_keys.num_rows
    assert role_emb.shape[0] == n_roles, "role_emb.npy / role_keys.parquet row-count mismatch"

    roles_df = con.sql(f"""
        SELECT rk.*, r.occupation_code_pooled
        FROM read_parquet('{C.CACHE / "role_keys.parquet"}') rk
        JOIN read_parquet('{C.RESULTS / "roles.parquet"}') r
          ON rk.linkedin_id = r.linkedin_id
         AND rk.experience_idx = r.experience_idx
         AND rk.position_idx IS NOT DISTINCT FROM r.position_idx
        ORDER BY rk.linkedin_id, rk.experience_idx, rk.position_idx
    """).arrow().read_all()
    pooled_codes = roles_df.column("occupation_code_pooled").to_pylist()
    assert len(pooled_codes) == n_roles

    assignments = [pooled_soc_assignment(c, valid_socs) for c in pooled_codes]
    is_pooled = np.array([source == "pooled" for _, source in assignments])

    with C.Timer("nearest-SOC search"):
        soc_out = [None] * n_roles
        source_out = [None] * n_roles
        cos_out = [None] * n_roles

        for i in range(n_roles):
            if is_pooled[i]:
                soc_out[i] = assignments[i][0]
                source_out[i] = "pooled"
                cos_out[i] = None

        nearest_idx = np.where(~is_pooled)[0]
        if len(nearest_idx):
            sims = role_emb[nearest_idx] @ occ_emb.T  # cosine, both L2-normalized
            best = np.argmax(sims, axis=1)
            best_cos = sims[np.arange(len(nearest_idx)), best]
            for j, i in enumerate(nearest_idx):
                soc_out[i] = occ_socs[best[j]]
                source_out[i] = "nearest"
                cos_out[i] = float(best_cos[j])

    out_table = role_keys.append_column("soc", pa.array(soc_out)) \
        .append_column("soc_source", pa.array(source_out)) \
        .append_column("nearest_cos", pa.array(cos_out, type=pa.float32()))
    pq.write_table(out_table, str(C.RESULTS / "role_soc.parquet"))

    groups = role_keys.column("group").to_pylist()
    share_by_group: dict[str, dict[str, float]] = {}
    median_nearest_cos_by_group: dict[str, float | None] = {}
    for g in sorted(set(groups)):
        idx = [i for i, gg in enumerate(groups) if gg == g]
        n = len(idx)
        n_pooled = sum(1 for i in idx if source_out[i] == "pooled")
        n_nearest = n - n_pooled
        share_by_group[g] = {
            "n": n,
            "pooled": n_pooled / n if n else None,
            "nearest": n_nearest / n if n else None,
        }
        cos_vals = [cos_out[i] for i in idx if cos_out[i] is not None]
        median_nearest_cos_by_group[g] = float(np.median(cos_vals)) if cos_vals else None

    manifest = {
        "n_roles_embedded": n_roles,
        "onet_release": "29.3",
        "n_onet_soc_in_skills_table": len(socs),
        "skill_columns": skill_cols,
        "soc_source_share_by_group": share_by_group,
        "median_nearest_cos_by_group": median_nearest_cos_by_group,
    }
    C.write_json(manifest, C.RESULTS / "_embed_manifest.json")
    print(f"soc_source_share_by_group={share_by_group}", flush=True)
    print(f"median_nearest_cos_by_group={median_nearest_cos_by_group}", flush=True)
    return manifest


if __name__ == "__main__":
    run()
