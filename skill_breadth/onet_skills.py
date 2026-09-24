"""Task 2 (part 2): O*NET 29.3 skill matrix + role -> SOC mapping.

Run order (each step reads the previous steps' outputs):
    1. uv run python -m skill_breadth.build_cohort
    2. uv run python -m skill_breadth.embed_roles
       uv run python -m skill_breadth.onet_skills   (this module)
    3. uv run python -m skill_breadth.run_breadth
    4. uv run python -m skill_breadth.build_figure

Downloads (if absent):
  reference/onet_skills.txt                  -- O*NET 29.3 Skills.txt
  reference/onet_occupation_data_29_3.txt     -- O*NET 29.3 Occupation Data.txt
  reference/onet_alternate_titles_29_3.txt    -- O*NET 29.3 Alternate Titles.txt
  reference/onet_2010_to_2019_crosswalk.csv   -- O*NET-SOC 2010 -> 2019 crosswalk
  reference/onet_skills_29_3_backfill_source.txt -- derived: O*NET 22.0
      Skills.txt, filtered to just the IM-scale rows for the O*NET-SOC 2010
      codes needed to backfill 2019-taxonomy SOCs missing from 29.3
      Skills.txt (see "Skill-row backfill" below). The full O*NET 22.0
      Skills.txt is fetched over the network to build this but is not
      itself saved to disk.

Builds:
  results/onet_skill_matrix.parquet -- one row per 6-digit SOC in the 29.3
      skills table PLUS every crosswalk-backfilled SOC, columns soc + the 35
      skill element names (Element Name, Scale ID='IM'), mean-aggregated
      from O*NET-SOC detail codes to 6-digit SOC, then z-scored per skill
      across the full SOC table, then L2-normalized per row. Wide format
      (not long) so Task 3 can join role_soc.soc -> this table directly and
      use the 35 columns as a vector.
  results/role_soc.parquet -- one row per role key (linkedin_id,
      experience_idx, position_idx): soc, soc_source in {'pooled','nearest'},
      nearest_cos (the title cosine of the winning SOC: max cosine of the
      role's title_raw against that SOC's title strings; stored for every
      nearest-matched role, including generic-status titles whose title term
      was left out of the score -- see "Generic-status titles" below),
      desc_cos (the description term). Both NULL for soc_source='pooled'.
  results/_embed_manifest.json

Skill-row backfill (generalizes a 2026-09-24 round-2 fix that only handled
  15-1252): many 2019-taxonomy SOCs present in 29.3 Occupation Data have no
  rows at all in 29.3 Skills.txt -- 104 of them, confirmed by a direct
  count. For each, this module finds every O*NET-SOC 2010 code that the
  O*NET 2010->2019 crosswalk maps to it, and if any of those 2010 codes has
  IM-scale skill rows in O*NET 22.0 (the last release built on the 2010
  taxonomy), backfills the missing SOC's 35 ratings as the mean across all
  such source rows, joined to 29.3 skill names by Element ID (Element Names
  drift slightly between releases -- e.g. 22.0's "Operation Monitoring" is
  29.3's "Operations Monitoring"). 15-1252 ("Software Developers") comes out
  of this general mechanism the same way round 2 special-cased it: its two
  2010 predecessors, 15-1132.00 and 15-1133.00, both crosswalk to it. Not
  every missing SOC is backfillable this way -- see run()'s manifest output
  for the current backfilled/unbackfillable split. The crosswalk CSV URL
  actually used here (see CROSSWALK_URL below) differs from
  .../taxonomy/2019/soc/2010_to_2019_Crosswalk.csv (which serves an HTML
  page, or with ?fmt=csv a DIFFERENT crosswalk -- O*NET-SOC 2019 to 2018
  SOC, not 2010 O*NET-SOC to 2019) -- the real 2010->2019 O*NET-SOC
  crosswalk lives at .../taxonomy/2019/walk/2010_to_2019_Crosswalk.csv.

Role -> SOC: hybrid title+description matching (2026-09-24 controller
  ruling, round 2, refined round 3). occupation_code_pooled, truncated to 6
  digits, when present AND that 6-digit SOC is in the skill matrix ->
  soc_source='pooled'. Otherwise -> nearest by a HYBRID score per SOC:
      score(role, soc) = max_over_soc's_title_strings(cos(title_raw_emb, string_emb))
                        + cos(role_text_emb, soc_desc_emb)
  where "soc's title strings" are that SOC's O*NET 29.3 Title + Alternate
  Titles, and soc_desc_emb is that SOC's "Title. Description" embedding.
  Argmax SOC wins; ties broken toward the lowest SOC code. Round 1 was
  title-only (no description term); round 2 added the description term but
  still let "Owner"/"Intern"/"Founder"-style generic-status titles get
  hijacked by an unrelated occupation's identically-worded alternate title,
  since an exact (cosine ~1.0) title match is hard for any description term
  to outweigh in an unweighted sum. Round 3's fix (below) removes the title
  term outright for known generic-status titles rather than trying to
  out-weigh it.

Generic-status titles: for roles whose normalized title_raw is a member of
  GENERIC_TITLES (career_clean.occupation._GENERIC_STATUS_TITLES -- "owner",
  "founder", "consultant", "contractor", etc., titles that describe
  someone's *employment status* rather than a specific occupation -- unioned
  locally with {"intern", "internship", "summer intern", "volunteer"}), the
  title term is dropped entirely: score(role, soc) = description term only.
  These titles' surface form carries no real occupational signal (an
  "Owner" could own any kind of business), so the title term for them is
  pure noise that happens to spike to ~1.0 against whichever unrelated
  occupation's alt-title lexicon contains that exact word.

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

from career_clean.occupation import _GENERIC_STATUS_TITLES, normalize

from . import common as C

ONET_SKILLS_URL = "https://www.onetcenter.org/dl_files/database/db_29_3_text/Skills.txt"
ONET_OCC_URL = "https://www.onetcenter.org/dl_files/database/db_29_3_text/Occupation%20Data.txt"
ONET_ALT_URL = "https://www.onetcenter.org/dl_files/database/db_29_3_text/Alternate%20Titles.txt"
ONET_22_SKILLS_URL = "https://www.onetcenter.org/dl_files/database/db_22_0_text/Skills.txt"
# The controller-specified .../taxonomy/2019/soc/2010_to_2019_Crosswalk.csv serves an
# HTML page (or, with ?fmt=csv, a DIFFERENT crosswalk: O*NET-SOC 2019 -> 2018 SOC).
# The real O*NET-SOC 2010 -> 2019 crosswalk is at this path instead (verified by content:
# header "O*NET-SOC 2010 Code,O*NET-SOC 2010 Title,O*NET-SOC 2019 Code,O*NET-SOC 2019 Title").
CROSSWALK_URL = "https://www.onetcenter.org/taxonomy/2019/walk/2010_to_2019_Crosswalk.csv?fmt=csv"

ONET_SKILLS_PATH = C.ROOT / "reference" / "onet_skills.txt"
ONET_OCC_PATH = C.ROOT / "reference" / "onet_occupation_data_29_3.txt"
ONET_ALT_PATH = C.ROOT / "reference" / "onet_alternate_titles_29_3.txt"
CROSSWALK_PATH = C.ROOT / "reference" / "onet_2010_to_2019_crosswalk.csv"
BACKFILL_SOURCE_PATH = C.ROOT / "reference" / "onet_skills_29_3_backfill_source.txt"

N_SKILLS = 35
NEAREST_BATCH = 4000  # query rows per GPU matmul batch against the candidate matrix

# Titles whose surface form is an employment-status label, not an occupation --
# career_clean.occupation's curated set (owner/founder/consultant/...), unioned with
# internship- and volunteer-flavored titles per the 2026-09-24 round-3 controller ruling.
GENERIC_TITLES: frozenset[str] = _GENERIC_STATUS_TITLES | {"intern", "internship", "summer intern", "volunteer"}


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


def insert_backfilled_socs(
    socs: list[str], mat: np.ndarray, skills: list[str], backfill: dict[str, dict[str, float]]
) -> tuple[list[str], np.ndarray]:
    """Pure insertion of N additional SOC rows into the skill matrix,
    keeping SOC order ascending (so downstream tie-breaks that rely on
    sorted-ascending SOC order still hold). Each backfill[soc] must name
    exactly the skills in `skills` (order-independent); backfill may be
    empty (no-op). Generalizes round 2's single-SOC insert_imputed_soc to
    every crosswalk-backfilled SOC at once, so they all participate in the
    same z-score population as every other SOC."""
    if not backfill:
        return list(socs), mat
    overlap = set(backfill) & set(socs)
    if overlap:
        raise ValueError(f"SOCs already in the skill matrix: {sorted(overlap)}")
    new_socs = sorted(backfill)
    rows = []
    for soc in new_socs:
        values = backfill[soc]
        if set(values) != set(skills):
            missing = set(skills) - set(values)
            extra = set(values) - set(skills)
            raise ValueError(f"backfill skill set mismatch for {soc}: missing={missing}, extra={extra}")
        rows.append([values[s] for s in skills])
    socs2 = list(socs) + new_socs
    mat2 = np.vstack([mat, np.array(rows, dtype=mat.dtype)])
    order = np.argsort(socs2)
    return [socs2[i] for i in order], mat2[order]


def hybrid_nearest_soc(
    title_vec: np.ndarray,
    desc_vec: np.ndarray,
    cand_vecs: np.ndarray,
    cand_socs: Sequence[str],
    soc_desc_vecs: np.ndarray,
    socs: Sequence[str],
    drop_title_term: bool = False,
) -> tuple[str, float, float]:
    """Pure single-query hybrid lookup (socs must be sorted ascending, same
    order as soc_desc_vecs' rows). For every soc in `socs`: title term = max
    cosine of title_vec against that soc's rows in (cand_vecs, cand_socs);
    desc term = cosine of desc_vec (role_text embedding) against
    soc_desc_vecs[soc's index] (that soc's Title. Description embedding).
    Assigns argmax(title term + desc term) -- or argmax(desc term) alone
    when drop_title_term is True, for generic-status titles whose title
    term carries no real signal. Ties broken toward the lowest SOC code via
    np.argmax's documented first-occurrence-on-ties behavior (relies on
    `socs` being sorted ascending). Returns (soc, title_term, desc_term) for
    the winner -- the title term is always computed and returned (for
    diagnostics) even when drop_title_term excludes it from the score."""
    title_sims = cand_vecs @ title_vec
    title_max = np.full(len(socs), -np.inf)
    soc_pos = {s: i for i, s in enumerate(socs)}
    for cand_soc, sim in zip(cand_socs, title_sims):
        i = soc_pos[cand_soc]
        if sim > title_max[i]:
            title_max[i] = sim
    desc_sims = soc_desc_vecs @ desc_vec
    scores = desc_sims if drop_title_term else title_max + desc_sims
    best = int(np.argmax(scores))
    return socs[best], float(title_max[best]), float(desc_sims[best])


def download_if_absent() -> None:
    for path, url in (
        (ONET_SKILLS_PATH, ONET_SKILLS_URL),
        (ONET_OCC_PATH, ONET_OCC_URL),
        (ONET_ALT_PATH, ONET_ALT_URL),
        (CROSSWALK_PATH, CROSSWALK_URL),
    ):
        if path.exists():
            continue
        print(f"downloading {url} -> {path}", flush=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            path.write_bytes(resp.read())


def ensure_backfill_source_file(needed_2010_codes: list[str]) -> None:
    """Fetches O*NET 22.0 Skills.txt in full (not saved raw) and writes just
    the Scale ID='IM' rows for `needed_2010_codes` to BACKFILL_SOURCE_PATH,
    with a header comment explaining provenance. No-op if the file already
    exists (idempotent, same pattern as download_if_absent, but the content
    depends on which SOCs are missing from 29.3 Skills.txt, computed by the
    caller, so it can't be a fixed-URL download)."""
    if BACKFILL_SOURCE_PATH.exists():
        return
    print(f"downloading {ONET_22_SKILLS_URL} to build {BACKFILL_SOURCE_PATH.name}", flush=True)
    req = urllib.request.Request(ONET_22_SKILLS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        raw = resp.read().decode("utf-8")
    lines = raw.splitlines()
    header, rows = lines[0], lines[1:]
    cols = header.split("\t")
    soc_i, scale_i = cols.index("O*NET-SOC Code"), cols.index("Scale ID")
    needed = set(needed_2010_codes)
    keep = [r for r in rows if r.split("\t")[soc_i] in needed and r.split("\t")[scale_i] == "IM"]
    comment = (
        f"# O*NET 22.0 Skills.txt Scale ID='IM' rows for the {len(needed)} O*NET-SOC 2010 codes "
        f"needed to backfill 2019-taxonomy SOCs with no rows in O*NET 29.3 Skills.txt (crosswalk: "
        f"{CROSSWALK_URL}). skill_breadth/onet_skills.py averages, per missing SOC, all of its "
        f"crosswalk-mapped 2010 codes' Data Value per skill (joined to 29.3 skill names by Element "
        f"ID) and inserts the result as that SOC's row before z-scoring. See reference/README.md."
    )
    BACKFILL_SOURCE_PATH.write_text(comment + "\n" + header + "\n" + "\n".join(keep) + "\n")


def _load_29_3_element_id_to_name(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Element ID -> 29.3 skill name, Scale ID='IM'. O*NET Element IDs are
    stable across releases but a couple of Element Names drifted (22.0's
    "Operation Monitoring" is 29.3's "Operations Monitoring", same
    2.B.3.g), so joining backfill sources on name would silently miss a
    skill -- always join on Element ID instead."""
    rows = con.sql(f"""
        SELECT DISTINCT "Element ID" AS element_id, "Element Name" AS skill
        FROM read_csv('{ONET_SKILLS_PATH}', delim='\t', header=true, quote='')
        WHERE "Scale ID" = 'IM'
    """).arrow().read_all()
    return dict(zip(rows.column("element_id").to_pylist(), rows.column("skill").to_pylist()))


def build_crosswalk_backfill(
    con: duckdb.DuckDBPyConnection, occ_socs: set[str], skill_socs: set[str]
) -> tuple[dict[str, dict[str, float]], list[str]]:
    """Returns (backfill_values, unbackfillable_socs) for every 6-digit SOC
    in occ_socs (29.3 Occupation Data) that has no rows in skill_socs (29.3
    Skills.txt). backfill_values[soc] is a full 35-skill dict, the mean IM
    rating across the O*NET 22.0 rows of soc's O*NET-SOC 2010 crosswalk
    sources; unbackfillable_socs are missing SOCs where none of their
    crosswalk-mapped 2010 codes have any IM rows in O*NET 22.0 (a real,
    expected outcome for many 2019-only "All Other"/newly split categories
    and the military SOCs, not an error)."""
    missing = sorted(occ_socs - skill_socs)
    if not missing:
        return {}, []

    con.sql(f"""
        CREATE OR REPLACE TEMP TABLE missing_socs_tbl AS
        SELECT * FROM (VALUES {", ".join(f"('{s}')" for s in missing)}) AS t(soc)
    """)
    con.sql(f"""
        CREATE OR REPLACE TEMP TABLE crosswalk_missing AS
        SELECT "O*NET-SOC 2010 Code" AS soc2010, left("O*NET-SOC 2019 Code", 7) AS soc2019
        FROM read_csv('{CROSSWALK_PATH}', header=true)
        WHERE left("O*NET-SOC 2019 Code", 7) IN (SELECT soc FROM missing_socs_tbl)
    """)
    needed_2010 = con.sql("SELECT DISTINCT soc2010 FROM crosswalk_missing ORDER BY 1") \
        .arrow().read_all().column("soc2010").to_pylist()

    ensure_backfill_source_file(needed_2010)
    id_to_name = _load_29_3_element_id_to_name(con)

    con.sql(f"""
        CREATE OR REPLACE TEMP TABLE backfill_src AS
        SELECT "O*NET-SOC Code" AS soc2010, "Element ID" AS element_id, avg("Data Value") AS value
        FROM read_csv('{BACKFILL_SOURCE_PATH}', delim='\t', header=true, quote='', skip=1)
        WHERE "Scale ID" = 'IM'
        GROUP BY soc2010, element_id
    """)
    agg = con.sql("""
        SELECT cm.soc2019 AS soc, bs.element_id, avg(bs.value) AS value
        FROM crosswalk_missing cm
        JOIN backfill_src bs ON bs.soc2010 = cm.soc2010
        GROUP BY cm.soc2019, bs.element_id
    """).arrow().read_all()

    backfill_values: dict[str, dict[str, float]] = {}
    for soc, element_id, value in zip(
        agg.column("soc").to_pylist(), agg.column("element_id").to_pylist(), agg.column("value").to_pylist()
    ):
        if element_id in id_to_name:
            backfill_values.setdefault(soc, {})[id_to_name[element_id]] = value

    complete = {soc: vals for soc, vals in backfill_values.items() if len(vals) == N_SKILLS}
    unbackfillable = sorted(set(missing) - set(complete))
    return complete, unbackfillable


def build_skill_matrix(
    con: duckdb.DuckDBPyConnection,
) -> tuple[list[str], np.ndarray, list[str], list[str], list[str]]:
    """Returns (soc_list, matrix, skill_cols, backfilled_socs,
    unbackfillable_socs) -- matrix is [n_soc, 35] z-scored then
    L2-normalized, including every crosswalk-backfilled SOC. soc_list order
    matches matrix row order (ascending SOC code)."""
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

    occ_socs = set(con.sql(f"""
        SELECT DISTINCT left("O*NET-SOC Code", 7)
        FROM read_csv('{ONET_OCC_PATH}', delim='\t', header=true, quote='')
    """).arrow().read_all().column(0).to_pylist())
    backfill_values, unbackfillable = build_crosswalk_backfill(con, occ_socs, set(socs))
    socs, mat = insert_backfilled_socs(socs, mat, skills, backfill_values)

    unit = zscore_l2_normalize(mat)

    return socs, unit.astype(np.float32), skills, sorted(backfill_values), unbackfillable


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
    drop_title_mask: np.ndarray,
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
    aligned to `socs`). drop_title_mask (bool, one per query row) zeroes out
    the title term's contribution to the SCORE (via torch.where) for
    generic-status-title roles, without discarding the title term itself --
    it's still returned for diagnostics. The two are summed (or not) and
    argmax'd per row on the CPU (numpy.argmax's documented
    first-occurrence-on-ties behavior gives the lowest-SOC-code tie-break,
    since `socs` is sorted ascending)."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    cand_t = torch.from_numpy(cand_emb).to(device)
    soc_desc_t = torch.from_numpy(soc_desc_emb).to(device)
    idx_t = torch.from_numpy(cand_soc_idx.astype(np.int64)).to(device)
    drop_t = torch.from_numpy(drop_title_mask.astype(bool)).to(device)
    n_soc = len(socs)

    socs_out: list[str] = []
    title_cos_out: list[float] = []
    desc_cos_out: list[float] = []

    with torch.no_grad():
        for start in range(0, title_emb.shape[0], batch_size):
            title_chunk = torch.from_numpy(title_emb[start:start + batch_size]).to(device)
            desc_chunk = torch.from_numpy(desc_emb[start:start + batch_size]).to(device)
            drop_chunk = drop_t[start:start + batch_size]
            b = title_chunk.shape[0]

            title_sims = title_chunk @ cand_t.T  # [b, n_cand]
            index = idx_t.unsqueeze(0).expand(b, -1)
            title_max = torch.full((b, n_soc), float("-inf"), device=device, dtype=title_sims.dtype)
            title_max.scatter_reduce_(1, index, title_sims, reduce="amax", include_self=True)

            desc_sims = desc_chunk @ soc_desc_t.T  # [b, n_soc]
            combined = title_max + desc_sims
            scores = torch.where(drop_chunk.unsqueeze(1), desc_sims, combined).cpu().numpy()
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
        socs, skill_mat, skill_cols, backfilled_socs, unbackfillable_socs = build_skill_matrix(con)
    valid_socs = set(socs)
    print(
        f"skill matrix: {len(socs)} SOCs x {len(skill_cols)} skills "
        f"({len(backfilled_socs)} crosswalk-backfilled, {len(unbackfillable_socs)} still unbackfillable)",
        flush=True,
    )

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

    generic_mask = np.array([normalize(t) in GENERIC_TITLES for t in title_texts])
    print(f"generic-status titles (title term dropped): {int(generic_mask.sum())}/{n_roles} roles", flush=True)

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
                title_emb[nearest_idx], desc_emb[nearest_idx], cand_emb, cand_soc_idx,
                soc_desc_emb, socs, generic_mask[nearest_idx],
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
        "n_onet_soc_in_skill_matrix": len(socs),
        "n_soc_crosswalk_backfilled": len(backfilled_socs),
        "crosswalk_backfilled_socs": backfilled_socs,
        "n_soc_unbackfillable": len(unbackfillable_socs),
        "unbackfillable_socs": unbackfillable_socs,
        "n_generic_status_title_roles": int(generic_mask.sum()),
        "nearest_match_method": (
            "hybrid: max title_raw-vs-(Title+AlternateTitle) cosine per SOC, "
            "plus role_text-vs-(Title. Description) cosine; argmax over SOCs; "
            "title term dropped entirely for generic-status titles (GENERIC_TITLES)"
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
