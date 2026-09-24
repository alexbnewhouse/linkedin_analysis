"""Task 2 (part 2): O*NET 29.3 skill matrix + role -> SOC mapping.

Downloads (if absent):
  reference/onet_skills.txt                  -- O*NET 29.3 Skills.txt
  reference/onet_occupation_data_29_3.txt     -- O*NET 29.3 Occupation Data.txt
  reference/onet_alternate_titles_29_3.txt    -- O*NET 29.3 Alternate Titles.txt
  reference/onet_skills_15_1252_imputed.txt   -- derived: O*NET 22.0 Skills.txt,
      filtered to the IM-scale rows for 15-1132.00 and 15-1133.00 only (see
      "15-1252 imputation" below). The full O*NET 22.0 Skills.txt is fetched
      over the network to build this but is not itself saved to disk.

Builds:
  results/onet_skill_matrix.parquet -- one row per 6-digit SOC in the 29.3
      skills table PLUS the imputed 15-1252 (764 SOCs total), columns soc +
      the 35 skill element names (Element Name, Scale ID='IM'), mean-
      aggregated from O*NET-SOC detail codes to 6-digit SOC, then z-scored
      per skill across the 764-SOC table, then L2-normalized per row. Wide
      format (not long) so Task 3 can join role_soc.soc -> this table
      directly and use the 35 columns as a vector.
  results/role_soc.parquet -- one row per role key (linkedin_id,
      experience_idx, position_idx): soc (6-digit, always one of the 764),
      soc_source in {'pooled','nearest'}, nearest_cos (the title term of the
      winning SOC's hybrid score), desc_cos (the description term). Both are
      NULL for soc_source='pooled' (no search was run for those).
  results/_embed_manifest.json

15-1252 imputation:
  O*NET 25.1 through 29.3 Skills.txt have no rows at all for SOC 15-1252
  ("Software Developers") -- confirmed by the Task 2 controller across every
  release in that range. 15-1252's IM-scale skill ratings are imputed as the
  mean of O*NET 22.0's 15-1132.00 and 15-1133.00 (the pre-split detail codes
  that both crosswalk to 15-1252), fetched once into
  reference/onet_skills_15_1252_imputed.txt. Its 29.3 Title/Alternate
  Titles/Description are present as normal (only the Skills.txt row was
  missing), so once inserted into the skill matrix, 15-1252 is a normal
  matching candidate like any other SOC.

Role -> SOC: hybrid title+description matching (2026-09-24 controller
  ruling, round 2). occupation_code_pooled, truncated to 6 digits, when
  present AND that 6-digit SOC is one of the 764 in the skill matrix ->
  soc_source='pooled'. Otherwise -> nearest by a HYBRID score per SOC:
      score(role, soc) = max_over_soc's_title_strings(cos(title_raw_emb, string_emb))
                        + cos(role_text_emb, soc_desc_emb)
  where "soc's title strings" are that SOC's O*NET 29.3 Title + Alternate
  Titles, and soc_desc_emb is that SOC's "Title. Description" embedding.
  Argmax SOC wins; ties broken toward the lowest SOC code. This replaced a
  round-1 title-only matcher (title_raw vs title strings only, no
  description term) that the controller found failed on generic titles that
  happen to collide with an unrelated occupation's alternate title --
  "Intern"/"Owner" -> Physicians All Other, "Founder" -> Metal-Refining
  Furnace Operators (Iron Founder), "Teacher" -> Business Teachers
  Postsecondary, "Project Manager" -> Construction Managers -- and which
  also produced observable near-tie flips from encoder batch noise (e.g.
  "Software Engineer" split across two SOCs at cosine 0.902374 both ways).
  The description term acts as a second, independent signal that breaks
  these generic-title collisions in favor of the SOC whose actual job
  description is closer to the role's.

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
ONET_22_SKILLS_URL = "https://www.onetcenter.org/dl_files/database/db_22_0_text/Skills.txt"

ONET_SKILLS_PATH = C.ROOT / "reference" / "onet_skills.txt"
ONET_OCC_PATH = C.ROOT / "reference" / "onet_occupation_data_29_3.txt"
ONET_ALT_PATH = C.ROOT / "reference" / "onet_alternate_titles_29_3.txt"
IMPUTED_15_1252_PATH = C.ROOT / "reference" / "onet_skills_15_1252_imputed.txt"

N_SKILLS = 35
NEAREST_BATCH = 4000  # query rows per GPU matmul batch against the candidate matrix

IMPUTED_SOC = "15-1252"
IMPUTE_SOURCE_CODES = ("15-1132.00", "15-1133.00")  # O*NET 22.0 pre-split codes -> 15-1252
IMPUTED_HEADER_COMMENT = (
    f"# Imputed for SOC {IMPUTED_SOC} (Software Developers): {ONET_22_SKILLS_URL} has no rows in "
    f"any O*NET release 25.1-29.3, so this file holds the Scale ID='IM' rows for its O*NET 22.0 "
    f"pre-split detail codes {' and '.join(IMPUTE_SOURCE_CODES)} (both crosswalk to {IMPUTED_SOC}). "
    f"skill_breadth/onet_skills.py averages these two codes' Data Value per skill and inserts the "
    f"result as {IMPUTED_SOC}'s row in the skill matrix before z-scoring. See reference/README.md."
)


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
    skill matrix; soc is None (caller must run nearest match) with
    soc_source='nearest' otherwise -- including when occupation_code_pooled
    is missing entirely."""
    if occupation_code_pooled is None:
        return None, "nearest"
    soc6 = truncate_soc(occupation_code_pooled)
    if soc6 in valid_socs:
        return soc6, "pooled"
    return None, "nearest"


def insert_imputed_soc(
    socs: list[str], mat: np.ndarray, skills: list[str], soc: str, skill_values: dict[str, float]
) -> tuple[list[str], np.ndarray]:
    """Pure insertion of one additional SOC row into the skill matrix,
    keeping SOC order ascending (so downstream tie-breaks that rely on
    sorted-ascending SOC order still hold). skill_values must name exactly
    the skills in `skills` (order-independent). Used to fold the imputed
    15-1252 row into the matrix before z-scoring, so it participates in the
    same z-score population as every other SOC."""
    if set(skill_values) != set(skills):
        missing = set(skills) - set(skill_values)
        extra = set(skill_values) - set(skills)
        raise ValueError(f"imputed skill set mismatch for {soc}: missing={missing}, extra={extra}")
    if soc in socs:
        raise ValueError(f"{soc} is already in the skill matrix -- no imputation needed")
    row = np.array([skill_values[s] for s in skills], dtype=mat.dtype)
    socs2 = list(socs) + [soc]
    mat2 = np.vstack([mat, row[None, :]])
    order = np.argsort(socs2)
    return [socs2[i] for i in order], mat2[order]


def hybrid_nearest_soc(
    title_vec: np.ndarray,
    desc_vec: np.ndarray,
    cand_vecs: np.ndarray,
    cand_socs: Sequence[str],
    soc_desc_vecs: np.ndarray,
    socs: Sequence[str],
) -> tuple[str, float, float]:
    """Pure single-query hybrid lookup (socs must be sorted ascending, same
    order as soc_desc_vecs' rows). For every soc in `socs`: title term = max
    cosine of title_vec against that soc's rows in (cand_vecs, cand_socs);
    desc term = cosine of desc_vec (role_text embedding) against
    soc_desc_vecs[soc's index] (that soc's Title. Description embedding).
    Assigns argmax(title term + desc term); ties broken toward the lowest
    SOC code via np.argmax's documented first-occurrence-on-ties behavior
    (relies on `socs` being sorted ascending). Returns (soc, title_term,
    desc_term) for the winner -- the same two numbers the bulk path records
    as nearest_cos and desc_cos."""
    title_sims = cand_vecs @ title_vec
    title_max = np.full(len(socs), -np.inf)
    soc_pos = {s: i for i, s in enumerate(socs)}
    for cand_soc, sim in zip(cand_socs, title_sims):
        i = soc_pos[cand_soc]
        if sim > title_max[i]:
            title_max[i] = sim
    desc_sims = soc_desc_vecs @ desc_vec
    scores = title_max + desc_sims
    best = int(np.argmax(scores))
    return socs[best], float(title_max[best]), float(desc_sims[best])


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

    if IMPUTED_15_1252_PATH.exists():
        return
    print(f"downloading {ONET_22_SKILLS_URL} to build {IMPUTED_15_1252_PATH.name}", flush=True)
    req = urllib.request.Request(ONET_22_SKILLS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        raw = resp.read().decode("utf-8")
    lines = raw.splitlines()
    header, rows = lines[0], lines[1:]
    cols = header.split("\t")
    soc_i, scale_i = cols.index("O*NET-SOC Code"), cols.index("Scale ID")
    keep = [r for r in rows if r.split("\t")[soc_i] in IMPUTE_SOURCE_CODES and r.split("\t")[scale_i] == "IM"]
    if len(keep) != len(IMPUTE_SOURCE_CODES) * N_SKILLS:
        raise ValueError(
            f"expected {len(IMPUTE_SOURCE_CODES) * N_SKILLS} IM rows for {IMPUTE_SOURCE_CODES}, found {len(keep)}"
        )
    IMPUTED_15_1252_PATH.write_text(IMPUTED_HEADER_COMMENT + "\n" + header + "\n" + "\n".join(keep) + "\n")


def load_imputed_15_1252_mean(con: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """Mean Data Value per skill from reference/onet_skills_15_1252_imputed.txt
    (the O*NET 22.0 IM-scale rows for 15-1132.00 and 15-1133.00), keyed to
    the 29.3 skill names via Element ID -- O*NET Element IDs are stable
    across releases but a couple of Element Names drifted (22.0's
    "Operation Monitoring" is 29.3's "Operations Monitoring", same
    2.B.3.g), so joining on name would silently miss a skill."""
    id_to_name = con.sql(f"""
        SELECT DISTINCT "Element ID" AS element_id, "Element Name" AS skill
        FROM read_csv('{ONET_SKILLS_PATH}', delim='\t', header=true, quote='')
        WHERE "Scale ID" = 'IM'
    """).arrow().read_all()
    id_to_name = dict(zip(id_to_name.column("element_id").to_pylist(), id_to_name.column("skill").to_pylist()))

    rows = con.sql(f"""
        SELECT "Element ID" AS element_id, avg("Data Value") AS value
        FROM read_csv('{IMPUTED_15_1252_PATH}', delim='\t', header=true, quote='', skip=1)
        WHERE "Scale ID" = 'IM'
        GROUP BY element_id
    """).arrow().read_all()
    out = {}
    for element_id, value in zip(rows.column("element_id").to_pylist(), rows.column("value").to_pylist()):
        if element_id not in id_to_name:
            raise ValueError(f"imputed Element ID {element_id!r} has no match in the 29.3 skills table")
        out[id_to_name[element_id]] = value
    if len(out) != N_SKILLS:
        raise ValueError(f"expected {N_SKILLS} imputed skills for {IMPUTED_SOC}, found {len(out)}")
    return out


def build_skill_matrix(con: duckdb.DuckDBPyConnection) -> tuple[list[str], np.ndarray, list[str]]:
    """Returns (soc_list, matrix, skill_cols) -- matrix is [n_soc, 35]
    z-scored then L2-normalized, including the imputed 15-1252 row. soc_list
    order matches matrix row order (ascending SOC code)."""
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

    imputed_values = load_imputed_15_1252_mean(con)
    socs, mat = insert_imputed_soc(socs, mat, skills, IMPUTED_SOC, imputed_values)

    unit = zscore_l2_normalize(mat)

    return socs, unit.astype(np.float32), skills


def build_candidate_titles(con: duckdb.DuckDBPyConnection, valid_socs: set[str]) -> tuple[list[str], list[str]]:
    """Candidate (soc, title) pairs for the title term: for every 6-digit
    SOC in valid_socs, its O*NET 29.3 occupation Title(s) (one per O*NET-SOC
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
        raise ValueError(f"{len(missing)} skill-matrix SOCs have no candidate title at all: {sorted(missing)[:10]}")
    return cand_socs, cand_texts


def build_soc_desc_texts(con: duckdb.DuckDBPyConnection, socs: list[str]) -> list[str]:
    """One `Title. Description` string per soc in `socs`, same order: the
    '.00' detail row if present, else the first detail row (by O*NET-SOC
    Code) for that 6-digit prefix. Used as the description term's SOC side."""
    valid_socs = set(socs)
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
        raise ValueError(f"{len(missing)} skill-matrix SOCs have no Occupation Data row: {sorted(missing)[:10]}")

    texts_out = []
    for soc in socs:
        rows = by_soc[soc]
        chosen = next((r for r in rows if r[0].endswith(".00")), rows[0])
        _, title, desc = chosen
        texts_out.append(f"{title}. {desc}")
    return texts_out


def batched_hybrid_nearest(
    title_emb: np.ndarray,
    desc_emb: np.ndarray,
    cand_emb: np.ndarray,
    cand_soc_idx: np.ndarray,
    soc_desc_emb: np.ndarray,
    socs: Sequence[str],
    batch_size: int = NEAREST_BATCH,
) -> tuple[list[str], list[float], list[float]]:
    """Vectorized/batched form of hybrid_nearest_soc over many queries at
    once (GPU). Per batch: title_chunk @ cand_emb.T gives [b, n_cand]
    title-candidate cosines; a scatter-reduce (amax) collapses that to
    [b, n_soc] by taking, for each soc, the max over its own candidate
    columns (cand_soc_idx maps each candidate column to its soc's index in
    `socs`) -- this is the "per-SOC max over strings" as a single vectorized
    op, no Python loop over roles or SOCs. desc_chunk @ soc_desc_emb.T gives
    [b, n_soc] description cosines directly (soc_desc_emb is already row-
    aligned to `socs`). The two are summed and argmax'd per row on the CPU
    (numpy.argmax's documented first-occurrence-on-ties behavior gives the
    lowest-SOC-code tie-break, since `socs` is sorted ascending)."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    cand_t = torch.from_numpy(cand_emb).to(device)
    soc_desc_t = torch.from_numpy(soc_desc_emb).to(device)
    idx_t = torch.from_numpy(cand_soc_idx.astype(np.int64)).to(device)
    n_soc = len(socs)

    socs_out: list[str] = []
    title_cos_out: list[float] = []
    desc_cos_out: list[float] = []

    with torch.no_grad():
        for start in range(0, title_emb.shape[0], batch_size):
            title_chunk = torch.from_numpy(title_emb[start:start + batch_size]).to(device)
            desc_chunk = torch.from_numpy(desc_emb[start:start + batch_size]).to(device)
            b = title_chunk.shape[0]

            title_sims = title_chunk @ cand_t.T  # [b, n_cand]
            index = idx_t.unsqueeze(0).expand(b, -1)
            title_max = torch.full((b, n_soc), float("-inf"), device=device, dtype=title_sims.dtype)
            title_max.scatter_reduce_(1, index, title_sims, reduce="amax", include_self=True)

            desc_sims = desc_chunk @ soc_desc_t.T  # [b, n_soc]
            scores = (title_max + desc_sims).cpu().numpy()
            title_max_np = title_max.cpu().numpy()
            desc_sims_np = desc_sims.cpu().numpy()

            best = np.argmax(scores, axis=1)
            rows = np.arange(b)
            socs_out.extend(socs[i] for i in best)
            title_cos_out.extend(title_max_np[rows, best].tolist())
            desc_cos_out.extend(desc_sims_np[rows, best].tolist())
    return socs_out, title_cos_out, desc_cos_out


def run() -> dict:
    download_if_absent()
    con = C.connect()

    with C.Timer("skill matrix"):
        socs, skill_mat, skill_cols = build_skill_matrix(con)
    valid_socs = set(socs)
    print(f"skill matrix: {len(socs)} SOCs x {len(skill_cols)} skills (incl. imputed {IMPUTED_SOC})", flush=True)

    C.RESULTS.mkdir(parents=True, exist_ok=True)
    matrix_table = pa.table(
        {"soc": socs, **{col: skill_mat[:, i] for i, col in enumerate(skill_cols)}}
    )
    pq.write_table(matrix_table, str(C.RESULTS / "onet_skill_matrix.parquet"))

    with C.Timer("candidate titles"):
        cand_socs, cand_texts = build_candidate_titles(con, valid_socs)
    print(f"candidate titles: {len(cand_texts)} (soc, title) pairs over {len(set(cand_socs))} SOCs", flush=True)
    cand_emb = C.encode(cand_texts, name="onet_title_candidates_29_3")
    soc_pos = {s: i for i, s in enumerate(socs)}
    cand_soc_idx = np.array([soc_pos[s] for s in cand_socs], dtype=np.int64)

    with C.Timer("soc description texts"):
        soc_desc_texts = build_soc_desc_texts(con, socs)
    soc_desc_emb = C.encode(soc_desc_texts, name="onet_soc_desc_29_3")

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

    role_key_cache = pq.read_table(str(C.CACHE / "role_keys.parquet"))
    role_emb = np.load(C.CACHE / "role_emb.npy")  # role_text embeddings, from embed_roles.py
    assert role_emb.shape[0] == n_roles == role_key_cache.num_rows
    assert role_key_cache.column("linkedin_id").to_pylist() == role_keys.column("linkedin_id").to_pylist()
    assert role_key_cache.column("experience_idx").to_pylist() == role_keys.column("experience_idx").to_pylist()
    assert role_key_cache.column("position_idx").to_pylist() == role_keys.column("position_idx").to_pylist(), \
        "role_emb.npy row order doesn't match roles_df -- desc_emb would be misaligned"
    desc_emb = role_emb

    assignments = [pooled_soc_assignment(c, valid_socs) for c in pooled_codes]
    is_pooled = np.array([source == "pooled" for _, source in assignments])

    with C.Timer("hybrid nearest-SOC search"):
        soc_out: list[str | None] = [None] * n_roles
        source_out: list[str] = [None] * n_roles
        title_cos_out: list[float | None] = [None] * n_roles
        desc_cos_out: list[float | None] = [None] * n_roles

        for i in range(n_roles):
            if is_pooled[i]:
                soc_out[i] = assignments[i][0]
                source_out[i] = "pooled"

        nearest_idx = np.where(~is_pooled)[0]
        if len(nearest_idx):
            n_socs_out, n_title_cos, n_desc_cos = batched_hybrid_nearest(
                title_emb[nearest_idx], desc_emb[nearest_idx], cand_emb, cand_soc_idx, soc_desc_emb, socs
            )
            for j, i in enumerate(nearest_idx):
                soc_out[i] = n_socs_out[j]
                source_out[i] = "nearest"
                title_cos_out[i] = float(n_title_cos[j])
                desc_cos_out[i] = float(n_desc_cos[j])

    out_table = role_keys.append_column("soc", pa.array(soc_out)) \
        .append_column("soc_source", pa.array(source_out)) \
        .append_column("nearest_cos", pa.array(title_cos_out, type=pa.float32())) \
        .append_column("desc_cos", pa.array(desc_cos_out, type=pa.float32()))
    pq.write_table(out_table, str(C.RESULTS / "role_soc.parquet"))

    groups = role_keys.column("group").to_pylist()
    share_by_group: dict[str, dict[str, float]] = {}
    median_nearest_cos_by_group: dict[str, float | None] = {}
    median_desc_cos_by_group: dict[str, float | None] = {}
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
        title_vals = [title_cos_out[i] for i in idx if title_cos_out[i] is not None]
        desc_vals = [desc_cos_out[i] for i in idx if desc_cos_out[i] is not None]
        median_nearest_cos_by_group[g] = float(np.median(title_vals)) if title_vals else None
        median_desc_cos_by_group[g] = float(np.median(desc_vals)) if desc_vals else None

    manifest = {
        "n_roles_embedded": n_roles,
        "onet_release": "29.3",
        "n_onet_soc_in_skills_table": len(socs),
        "imputed_socs": [IMPUTED_SOC],
        "nearest_match_method": (
            "hybrid: max title_raw-vs-(Title+AlternateTitle) cosine per SOC, "
            "plus role_text-vs-(Title. Description) cosine; argmax over SOCs"
        ),
        "n_candidate_titles": len(cand_texts),
        "skill_columns": skill_cols,
        "soc_source_share_by_group": share_by_group,
        "median_nearest_cos_by_group": median_nearest_cos_by_group,
        "median_desc_cos_by_group": median_desc_cos_by_group,
    }
    C.write_json(manifest, C.RESULTS / "_embed_manifest.json")
    print(f"soc_source_share_by_group={share_by_group}", flush=True)
    print(f"median_nearest_cos_by_group={median_nearest_cos_by_group}", flush=True)
    print(f"median_desc_cos_by_group={median_desc_cos_by_group}", flush=True)
    return manifest


if __name__ == "__main__":
    run()
