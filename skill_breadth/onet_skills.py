"""Task 2 (part 2): O*NET 29.3 skill matrix + role -> SOC mapping.

Downloads (if absent):
  reference/onet_skills.txt                  -- O*NET 29.3 Skills.txt
  reference/onet_occupation_data_29_3.txt     -- O*NET 29.3 Occupation Data.txt
  reference/onet_alternate_titles_29_3.txt    -- O*NET 29.3 Alternate Titles.txt

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
      (cosine to the matched candidate title; NULL for soc_source='pooled',
      where no nearest search was run).
  results/_embed_manifest.json

Role -> SOC:
  occupation_code_pooled, truncated to 6 digits, when present AND that 6-digit
  SOC is one of the 763 in the skills table -> soc_source='pooled'.
  Otherwise (no pooled code, or pooled code not in the 29.3 skills table --
  taxonomy drift) -> nearest O*NET occupation by title-to-title cosine:
  the role's title_raw, embedded alone, against a candidate pool of every
  O*NET 29.3 occupation Title and Alternate Title belonging to the 763
  skills-table SOCs (deduped on (soc, lowercased title)). This replaced an
  earlier description-vs-description matcher (role_text vs Title.
  Description) that the Task 2 controller ruling on 2026-09-24 found too
  noisy for the ~80% of roles that go through nearest match (e.g. "Senior
  R&D manager" -> Skincare Specialists, driven by unrelated description
  text) -- title-to-title matching is the fix, on the theory that titles are
  a cleaner, more literal signal than free-text descriptions for occupation
  identity.

    uv run python -m skill_breadth.onet_skills
"""

from __future__ import annotations

import urllib.request
from typing import Sequence

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch

from . import common as C

ONET_SKILLS_URL = "https://www.onetcenter.org/dl_files/database/db_29_3_text/Skills.txt"
ONET_OCC_URL = "https://www.onetcenter.org/dl_files/database/db_29_3_text/Occupation%20Data.txt"
ONET_ALT_URL = "https://www.onetcenter.org/dl_files/database/db_29_3_text/Alternate%20Titles.txt"

ONET_SKILLS_PATH = C.ROOT / "reference" / "onet_skills.txt"
ONET_OCC_PATH = C.ROOT / "reference" / "onet_occupation_data_29_3.txt"
ONET_ALT_PATH = C.ROOT / "reference" / "onet_alternate_titles_29_3.txt"

N_SKILLS = 35
NEAREST_BATCH = 4000  # query rows per GPU matmul batch against the candidate matrix


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


def nearest_soc(
    query_vec: np.ndarray, candidate_vecs: np.ndarray, candidate_socs: Sequence[str]
) -> tuple[str, float]:
    """Pure single-query nearest-candidate lookup: cosine (dot product, both
    inputs assumed L2-normalized) between query_vec and every row of
    candidate_vecs; returns the SOC and cosine of the single best match.
    candidate_socs[i] is the SOC that candidate_vecs[i] (one Title or
    Alternate Title string) belongs to -- the same SOC may own many rows."""
    sims = candidate_vecs @ query_vec
    best = int(np.argmax(sims))
    return candidate_socs[best], float(sims[best])


def download_if_absent() -> None:
    for path, url in (
        (ONET_SKILLS_PATH, ONET_SKILLS_URL),
        (ONET_OCC_PATH, ONET_OCC_URL),
        (ONET_ALT_PATH, ONET_ALT_URL),
    ):
        if path.exists():
            continue
        print(f"downloading {url} -> {path}", flush=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            path.write_bytes(resp.read())


def build_skill_matrix(con: duckdb.DuckDBPyConnection) -> tuple[list[str], np.ndarray, list[str]]:
    """Returns (soc_list, matrix, skill_cols) -- matrix is [n_soc, 35]
    z-scored then L2-normalized. soc_list order matches matrix row order."""
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


def build_candidate_titles(con: duckdb.DuckDBPyConnection, valid_socs: set[str]) -> tuple[list[str], list[str]]:
    """Candidate (soc, title) pairs for nearest-match: for every 6-digit SOC
    in valid_socs, its O*NET 29.3 occupation Title(s) (one per O*NET-SOC
    detail code under that 6-digit SOC) plus every Alternate Title for those
    same detail codes. Deduped on (soc, lowercased title). Returns
    (cand_socs, cand_texts), same order, row-aligned."""
    con.sql(f"""
        CREATE OR REPLACE TEMP TABLE valid_socs_tbl AS
        SELECT * FROM (VALUES {", ".join(f"('{s}')" for s in sorted(valid_socs))}) AS t(soc)
    """)
    combined = con.sql(f"""
        WITH occ_titles AS (
            SELECT left("O*NET-SOC Code", 7) AS soc, "Title" AS title
            FROM read_csv('{ONET_OCC_PATH}', delim='\t', header=true, quote='')
        ),
        alt_titles AS (
            SELECT left("O*NET-SOC Code", 7) AS soc, "Alternate Title" AS title
            FROM read_csv('{ONET_ALT_PATH}', delim='\t', header=true, quote='')
        ),
        all_titles AS (
            SELECT soc, title FROM occ_titles
            UNION ALL
            SELECT soc, title FROM alt_titles
        ),
        deduped AS (
            SELECT soc, any_value(title) AS title
            FROM all_titles
            WHERE soc IN (SELECT soc FROM valid_socs_tbl)
            GROUP BY soc, lower(title)
        )
        SELECT soc, title FROM deduped ORDER BY soc, title
    """).arrow().read_all()

    cand_socs = combined.column("soc").to_pylist()
    cand_texts = combined.column("title").to_pylist()
    missing = valid_socs - set(cand_socs)
    if missing:
        raise ValueError(f"{len(missing)} skills-table SOCs have no candidate title at all: {sorted(missing)[:10]}")
    return cand_socs, cand_texts


def batched_nearest(
    query_emb: np.ndarray, cand_emb: np.ndarray, cand_socs: Sequence[str], batch_size: int = NEAREST_BATCH
) -> tuple[list[str], list[float]]:
    """Vectorized form of nearest_soc over many queries at once (GPU, batched
    so the [batch, n_candidates] similarity matrix stays small). Same
    argmax-of-cosine logic as nearest_soc, just batched for throughput --
    71k queries x 49k candidates is too big to do as a single matmul."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    cand_t = torch.from_numpy(cand_emb).to(device)
    socs_out: list[str] = []
    cos_out: list[float] = []
    with torch.no_grad():
        for start in range(0, query_emb.shape[0], batch_size):
            chunk = torch.from_numpy(query_emb[start:start + batch_size]).to(device)
            sims = chunk @ cand_t.T
            best = torch.argmax(sims, dim=1)
            best_cos = sims[torch.arange(sims.shape[0]), best]
            socs_out.extend(cand_socs[i] for i in best.tolist())
            cos_out.extend(best_cos.tolist())
    return socs_out, cos_out


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

    with C.Timer("candidate titles"):
        cand_socs, cand_texts = build_candidate_titles(con, valid_socs)
    print(f"candidate titles: {len(cand_texts)} (soc, title) pairs over {len(set(cand_socs))} SOCs", flush=True)
    cand_emb = C.encode(cand_texts, name="onet_title_candidates_29_3")

    roles_df = con.sql(f"""
        SELECT linkedin_id, "group", experience_idx, position_idx,
               title_raw, occupation_code_pooled
        FROM read_parquet('{C.RESULTS / "roles.parquet"}')
        ORDER BY linkedin_id, experience_idx, position_idx
    """).arrow().read_all()
    n_roles = roles_df.num_rows
    role_keys = roles_df.select(["linkedin_id", "group", "experience_idx", "position_idx"])
    pooled_codes = roles_df.column("occupation_code_pooled").to_pylist()
    title_texts = roles_df.column("title_raw").to_pylist()

    title_emb = C.encode(title_texts, name="role_titles")
    assert title_emb.shape[0] == n_roles

    assignments = [pooled_soc_assignment(c, valid_socs) for c in pooled_codes]
    is_pooled = np.array([source == "pooled" for _, source in assignments])

    with C.Timer("nearest-SOC search (title vs title)"):
        soc_out: list[str | None] = [None] * n_roles
        source_out: list[str] = [None] * n_roles
        cos_out: list[float | None] = [None] * n_roles

        for i in range(n_roles):
            if is_pooled[i]:
                soc_out[i] = assignments[i][0]
                source_out[i] = "pooled"
                cos_out[i] = None

        nearest_idx = np.where(~is_pooled)[0]
        if len(nearest_idx):
            nearest_socs, nearest_cos = batched_nearest(title_emb[nearest_idx], cand_emb, cand_socs)
            for j, i in enumerate(nearest_idx):
                soc_out[i] = nearest_socs[j]
                source_out[i] = "nearest"
                cos_out[i] = float(nearest_cos[j])

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
        "nearest_match_method": "title_raw vs O*NET Title + Alternate Title candidates (title-to-title)",
        "n_candidate_titles": len(cand_texts),
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
