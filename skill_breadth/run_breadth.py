"""Task 3: breadth metrics.

Run order (each step reads the previous steps' outputs):
    1. uv run python -m skill_breadth.build_cohort
    2. uv run python -m skill_breadth.embed_roles
       uv run python -m skill_breadth.onet_skills
    3. uv run python -m skill_breadth.run_breadth  (this module)
    4. uv run python -m skill_breadth.build_figure

Reads Task 1/2 outputs (results/roles.parquet, results/role_soc.parquet,
results/onet_skill_matrix.parquet, cache/role_emb.npy + cache/role_keys.parquet)
and writes results/breadth.json: per group (4 headline + 2 sanity -- liberal_arts
had 0 people and was dropped, see Task 1) and per basis (text, onet_skills):
bootstrap Vendi score (median, 2.5/97.5 percentiles, n_people_available);
Spearman rank agreement between the two bases across group medians;
within-person spread (text basis only), stratified by role count; median
role description length per group; SOC source (pooled vs nearest) share per
group.

Two sensitivity runs go under "sensitivity":
  length_150_600 -- both bases, restricted to roles whose true description
      (career_steps.description, trimmed) is 150 to 600 characters, since
      shorter texts can spread out more in embedding space.
  onet_pooled_only -- O*NET basis only, restricted to roles whose SOC came
      from occupation_code_pooled (soc_source = 'pooled'), since the nearest
      SOC match reuses the same text embeddings as the text basis.

    uv run python -m skill_breadth.run_breadth
"""

from __future__ import annotations

import os

# BLAS oversubscription (32 OpenBLAS threads on many small eigendecompositions)
# made vendi() roughly 70x slower. Cap threads before numpy loads; threadpoolctl
# (below) enforces the same cap at runtime when it is installed.
BLAS_THREADS = 4
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, str(BLAS_THREADS))

import math
from contextlib import nullcontext

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import spearmanr

from . import common as C
from . import metrics as M

try:
    from threadpoolctl import threadpool_limits
except ImportError:  # env vars above still apply
    threadpool_limits = None

BASES = ("text", "onet_skills")
STRATA = ("3", "4", "5+")

LENGTH_MIN, LENGTH_MAX = 150, 600
POOLED_MIN_PEOPLE = 100


def _stratum(n_roles: int) -> str:
    return str(n_roles) if n_roles < 5 else "5+"


def load_role_matrices(con):
    """Row-aligned (role, text_emb, skill_emb) arrays plus group/person-id
    arrays, all indexed 0..n-1 in cache/role_keys.parquet's row order (the
    same order as cache/role_emb.npy)."""
    role_keys_tbl = pq.read_table(C.CACHE / "role_keys.parquet")
    n = role_keys_tbl.num_rows
    _check_role_keys_fresh(con, role_keys_tbl)
    row_idx = np.arange(n, dtype=np.int64)
    role_keys_tbl = role_keys_tbl.append_column("row_idx", pa.array(row_idx))

    text_emb = np.load(C.CACHE / "role_emb.npy")
    assert text_emb.shape[0] == n, f"role_emb rows ({text_emb.shape[0]}) != role_keys rows ({n})"

    # position_idx is frequently NULL (~77% of roles have no sub-position),
    # so the join must be NULL-safe (IS NOT DISTINCT FROM), not plain `=`,
    # or most rows silently fail to match (NULL = NULL is UNKNOWN in SQL).
    con.register("role_keys", role_keys_tbl)
    soc_map = con.sql(f"""
        SELECT rk.row_idx AS row_idx, rs.soc AS soc
        FROM role_keys rk
        JOIN read_parquet('{C.RESULTS / "role_soc.parquet"}') rs
          ON rk.linkedin_id = rs.linkedin_id
         AND rk.experience_idx = rs.experience_idx
         AND rk.position_idx IS NOT DISTINCT FROM rs.position_idx
        ORDER BY rk.row_idx
    """).arrow().read_all()
    assert soc_map.num_rows == n, (
        f"role_keys <-> role_soc join produced {soc_map.num_rows} rows, expected {n} "
        "(non-bijective key match)")
    assert (soc_map.column("row_idx").to_numpy() == row_idx).all(), \
        "role_keys <-> role_soc join is not a 1:1 row match"
    socs = soc_map.column("soc").to_pylist()

    skill_tbl = pq.read_table(C.RESULTS / "onet_skill_matrix.parquet")
    skill_cols = [c for c in skill_tbl.column_names if c != "soc"]
    skill_socs = skill_tbl.column("soc").to_pylist()
    skill_mat = np.column_stack([skill_tbl.column(c).to_numpy() for c in skill_cols]).astype(np.float64)
    soc_to_row = {s: i for i, s in enumerate(skill_socs)}

    missing = [s for s in socs if s not in soc_to_row]
    assert not missing, f"{len(missing)} roles map to a SOC absent from onet_skill_matrix.parquet"
    skill_idx = np.array([soc_to_row[s] for s in socs], dtype=np.int64)
    skill_emb = skill_mat[skill_idx]

    group_arr = np.array(role_keys_tbl.column("group").to_pylist())
    person_arr = np.array(role_keys_tbl.column("linkedin_id").to_pylist())

    return {"text": text_emb, "onet_skills": skill_emb}, group_arr, person_arr


def _check_role_keys_fresh(con, role_keys_tbl) -> None:
    """cache/role_keys.parquet must hold exactly the role keys of
    results/roles.parquet. If build_cohort was rerun without rerunning the
    embedding and SOC steps, the cached arrays describe a stale role table."""
    con.register("rk_check", role_keys_tbl)
    n_keys, n_roles, n_match = con.sql(f"""
        SELECT (SELECT count(*) FROM rk_check),
               (SELECT count(*) FROM read_parquet('{C.RESULTS / "roles.parquet"}')),
               (SELECT count(*) FROM rk_check rk
                JOIN read_parquet('{C.RESULTS / "roles.parquet"}') r
                  ON rk.linkedin_id = r.linkedin_id
                 AND rk.experience_idx = r.experience_idx
                 AND rk.position_idx IS NOT DISTINCT FROM r.position_idx)
    """).fetchone()
    con.unregister("rk_check")
    if not (n_keys == n_roles == n_match):
        raise SystemExit(
            f"cache/role_keys.parquet ({n_keys} rows) does not match results/roles.parquet "
            f"({n_roles} rows, {n_match} shared keys). roles.parquet changed since the "
            "embeddings were built: rerun `uv run python -m skill_breadth.embed_roles` and "
            "`uv run python -m skill_breadth.onet_skills`, then run_breadth again.")


def role_metadata(con) -> dict[str, np.ndarray]:
    """Per-role metadata row-aligned to cache/role_keys.parquet: the true
    description length (length(trim(career_steps.description)), the same
    measure as the Task 1 filter) and soc_source. The description is re-joined
    from career_steps on the NULL-safe role key plus the exact role_text, so
    the de-duplicated row that Task 1 kept is the one measured."""
    rk = pq.read_table(C.CACHE / "role_keys.parquet")
    rk = rk.append_column("row_idx", pa.array(np.arange(rk.num_rows, dtype=np.int64)))
    con.register("rk_meta", rk)
    tbl = con.sql(f"""
        WITH d AS (
            SELECT r.linkedin_id, r.experience_idx, r.position_idx,
                   min(length(trim(cs.description))) AS dlen
            FROM read_parquet('{C.RESULTS / "roles.parquet"}') r
            JOIN read_parquet('{C.CAREER_STEPS}') cs
              ON cs.linkedin_id = r.linkedin_id
             AND cs.experience_idx = r.experience_idx
             AND cs.position_idx IS NOT DISTINCT FROM r.position_idx
             AND NOT cs.is_duplicate
             AND COALESCE(cs.title_raw, '') || '. ' || cs.description = r.role_text
            GROUP BY 1, 2, 3
        )
        SELECT rk.row_idx, d.dlen, rs.soc_source
        FROM rk_meta rk
        LEFT JOIN d
          ON d.linkedin_id = rk.linkedin_id
         AND d.experience_idx = rk.experience_idx
         AND d.position_idx IS NOT DISTINCT FROM rk.position_idx
        LEFT JOIN read_parquet('{C.RESULTS / "role_soc.parquet"}') rs
          ON rs.linkedin_id = rk.linkedin_id
         AND rs.experience_idx = rk.experience_idx
         AND rs.position_idx IS NOT DISTINCT FROM rk.position_idx
        ORDER BY rk.row_idx
    """).fetchnumpy()
    con.unregister("rk_meta")
    n = rk.num_rows
    assert len(tbl["row_idx"]) == n and (tbl["row_idx"] == np.arange(n)).all(), \
        "role metadata join is not 1:1 with role_keys"
    dlen = tbl["dlen"]
    n_missing = int(np.ma.count_masked(dlen)) if np.ma.isMaskedArray(dlen) else int(np.isnan(dlen.astype(float)).sum())
    assert n_missing == 0, f"{n_missing} roles found no matching career_steps description"
    return {"desc_len": np.asarray(dlen, dtype=np.int64),
            "soc_source": np.asarray(tbl["soc_source"], dtype=object)}


def _boot_summary(scores: np.ndarray) -> dict:
    lo, hi = np.percentile(scores, [2.5, 97.5])
    return {"median": float(np.median(scores)), "lo": float(lo), "hi": float(hi)}


def person_rows_for_group(group_arr: np.ndarray, person_arr: np.ndarray, group: str) -> dict:
    idx = np.where(group_arr == group)[0]
    out: dict[str, list[int]] = {}
    for i in idx:
        out.setdefault(person_arr[i], []).append(int(i))
    return out


def run() -> dict:
    limit = threadpool_limits(BLAS_THREADS) if threadpool_limits else nullcontext()
    with limit:
        return _run()


def _run() -> dict:
    con = C.connect()
    bases, group_arr, person_arr = load_role_matrices(con)
    meta_rows = role_metadata(con)

    groups_present = sorted(set(group_arr.tolist()))
    headline = [g for g in C.HEADLINE_GROUPS if g in groups_present]
    sanity = [g for g in C.SANITY_GROUPS if g in groups_present]
    dropped_sanity = [g for g in C.SANITY_GROUPS if g not in groups_present]
    groups = headline + sanity
    print(f"groups: headline={headline} sanity={sanity} dropped(0 people)={dropped_sanity}", flush=True)

    vendi_out: dict[str, dict] = {}
    spread_out: dict[str, dict] = {}

    with C.Timer("bootstrap vendi + within-person spread, all groups"):
        for g in groups:
            person_rows = person_rows_for_group(group_arr, person_arr, g)
            n_people_available = len(person_rows)

            boot = M.bootstrap_vendi(
                person_rows, bases, seed=C.BOOT_SEED,
                n_people=C.N_PEOPLE, n_boot=C.N_BOOT,
            )
            entry = {"n_people_available": n_people_available}
            for basis in BASES:
                entry[basis] = _boot_summary(boot[basis])
            vendi_out[g] = entry

            spread = M.within_person_spread(person_rows, bases["text"], min_roles=3)
            by_stratum: dict[str, list[float]] = {s: [] for s in STRATA}
            for _pid, (n_roles, val) in spread.items():
                by_stratum[_stratum(n_roles)].append(val)
            spread_out[g] = {}
            for s in STRATA:
                vals = by_stratum[s]
                n = len(vals)
                spread_out[g][s] = {
                    "n_people": n,
                    "median_spread": float(np.median(vals)) if n >= 30 else None,
                }

    # Spearman rank agreement between the two bases, across group medians.
    med_text = [vendi_out[g]["text"]["median"] for g in groups]
    med_skills = [vendi_out[g]["onet_skills"]["median"] for g in groups]
    rho = float(spearmanr(med_text, med_skills).statistic)
    k = len(groups)
    spearman_out = {
        "groups_order": groups,
        "median_text": med_text,
        "median_onet_skills": med_skills,
        "rho": rho,
        # Exact permutation p-value, only meaningful at rho = 1 (the single
        # identical ordering out of k! equally likely ones). Six points and
        # two text-derived measures; see sensitivity.onet_pooled_only.
        "exact_permutation_p_if_rho_1": (1.0 / math.factorial(k)) if rho == 1.0 else None,
    }

    # Median true description length (chars) per group: length(trim(description))
    # from career_steps, re-joined on the NULL-safe role key (see role_metadata).
    median_desc_len = {
        g: float(np.median(meta_rows["desc_len"][group_arr == g])) for g in groups
    }

    sensitivity = _sensitivity(bases, group_arr, person_arr, meta_rows, groups, headline)

    # SOC source (pooled vs nearest) share per group.
    share_rows = con.sql(f"""
        SELECT "group", soc_source, count(*) AS c
        FROM read_parquet('{C.RESULTS / "role_soc.parquet"}')
        GROUP BY 1, 2
    """).fetchall()
    soc_share: dict[str, dict] = {}
    for g, source, c in share_rows:
        d = soc_share.setdefault(g, {"n_roles": 0, "pooled": 0, "nearest": 0})
        d["n_roles"] += c
        d[source] += c
    for g, d in soc_share.items():
        n = d["n_roles"]
        d["pooled"] = d["pooled"] / n if n else None
        d["nearest"] = d["nearest"] / n if n else None

    out = {
        "meta": {
            "seed": C.BOOT_SEED,
            "n_boot": C.N_BOOT,
            "n_people": C.N_PEOPLE,
            "headline_groups": headline,
            "sanity_groups": sanity,
            "dropped_sanity_groups_zero_people": dropped_sanity,
            "group_labels": {g: C.ALL_GROUP_LABELS[g] for g in groups},
            "bases": list(BASES),
            "role_count_strata": list(STRATA),
        },
        "vendi": vendi_out,
        "spearman_rank_agreement": spearman_out,
        "within_person_spread": spread_out,
        "median_description_length_chars": median_desc_len,
        "soc_source_share": soc_share,
        "sensitivity": sensitivity,
    }
    C.write_json(out, C.RESULTS / "breadth.json")

    _print_summary(groups, vendi_out, spread_out, median_desc_len, soc_share, spearman_out)
    _print_sensitivity(sensitivity)
    return out


def _sensitivity(bases, group_arr, person_arr, meta_rows, groups, headline) -> dict:
    """Two restricted re-runs of the headline bootstrap (same seed, N_BOOT)."""
    dlen, src = meta_rows["desc_len"], meta_rows["soc_source"]

    def pools(mask):
        return {g: person_rows_for_group(np.where(mask, group_arr, ""), person_arr, g) for g in groups}

    # 1. Length-matched: both bases, roles with 150-600 char descriptions.
    length_mask = (dlen >= LENGTH_MIN) & (dlen <= LENGTH_MAX)
    length_out = {"description_chars": [LENGTH_MIN, LENGTH_MAX], "n_boot": C.N_BOOT, "groups": {}}
    with C.Timer("sensitivity: length 150-600"):
        for g, pr in pools(length_mask).items():
            n_use = min(C.N_PEOPLE, len(pr))
            e = {"n_people_available": len(pr), "n_people": n_use,
                 "n_roles": int((length_mask & (group_arr == g)).sum())}
            boot = M.bootstrap_vendi(pr, bases, seed=C.BOOT_SEED, n_people=n_use, n_boot=C.N_BOOT)
            for basis in BASES:
                e[basis] = _boot_summary(boot[basis])
            length_out["groups"][g] = e

    # 2. O*NET basis on pooled-SOC roles only (codes from occupation_code_pooled,
    #    not from this module's embedding match). One common n across groups,
    #    set by the smallest pooled pool among the headline groups.
    pooled_mask = src == "pooled"
    pooled_pools = pools(pooled_mask)
    n_common = min(C.N_PEOPLE, min(len(pooled_pools[g]) for g in headline))
    pooled_out = {"n_people": n_common, "n_boot": C.N_BOOT, "min_pool": POOLED_MIN_PEOPLE,
                  "basis": "onet_skills", "groups": {}}
    with C.Timer("sensitivity: pooled-SOC only"):
        for g, pr in pooled_pools.items():
            e = {"n_people_available": len(pr),
                 "n_roles": int((pooled_mask & (group_arr == g)).sum())}
            if len(pr) < POOLED_MIN_PEOPLE or len(pr) < n_common:
                e["onet_skills"] = None
            else:
                boot = M.bootstrap_vendi(pr, {"onet_skills": bases["onet_skills"]},
                                         seed=C.BOOT_SEED, n_people=n_common, n_boot=C.N_BOOT)
                e["onet_skills"] = _boot_summary(boot["onet_skills"])
            pooled_out["groups"][g] = e
    return {"length_150_600": length_out, "onet_pooled_only": pooled_out}


def _print_sensitivity(sens: dict) -> None:
    L = sens["length_150_600"]
    print(f"\n=== Sensitivity: descriptions {L['description_chars'][0]}-{L['description_chars'][1]} chars ===",
          flush=True)
    for g, e in L["groups"].items():
        t, s = e["text"], e["onet_skills"]
        print(f"{g:<28} pool={e['n_people_available']:>6} n={e['n_people']:>4}  "
              f"text={t['median']:6.2f} [{t['lo']:5.2f},{t['hi']:5.2f}]  "
              f"skills={s['median']:5.2f} [{s['lo']:5.2f},{s['hi']:5.2f}]", flush=True)
    P = sens["onet_pooled_only"]
    print(f"\n=== Sensitivity: O*NET basis, pooled-SOC roles only (n={P['n_people']}) ===", flush=True)
    for g, e in P["groups"].items():
        s = e["onet_skills"]
        cell = "null (pool too small)" if s is None else f"{s['median']:5.2f} [{s['lo']:5.2f},{s['hi']:5.2f}]"
        print(f"{g:<28} pool={e['n_people_available']:>6}  skills={cell}", flush=True)


def _print_summary(groups, vendi_out, spread_out, median_desc_len, soc_share, spearman_out) -> None:
    print("\n=== Breadth summary (Vendi score, median [2.5%, 97.5%]) ===", flush=True)
    header = f"{'group':<28}{'n':>7}  {'text':>26}  {'onet_skills':>26}  {'desc_len':>9}  {'soc_nearest%':>12}"
    print(header, flush=True)
    for g in groups:
        e = vendi_out[g]
        t = e["text"]
        s = e["onet_skills"]
        t_str = f"{t['median']:6.2f} [{t['lo']:5.2f},{t['hi']:5.2f}]"
        s_str = f"{s['median']:6.2f} [{s['lo']:5.2f},{s['hi']:5.2f}]"
        dl = median_desc_len.get(g)
        dl_str = f"{dl:.0f}" if dl is not None else "n/a"
        share = soc_share.get(g, {})
        nearest_pct = share.get("nearest")
        nearest_str = f"{nearest_pct * 100:.1f}" if nearest_pct is not None else "n/a"
        print(f"{g:<28}{e['n_people_available']:>7}  {t_str:>26}  {s_str:>26}  {dl_str:>9}  {nearest_str:>12}",
              flush=True)
    print(f"\nSpearman rank agreement (text vs onet_skills, group medians): "
          f"rho={spearman_out['rho']:.3f} exact perm p (if rho=1)={spearman_out['exact_permutation_p_if_rho_1']} "
          f"(groups={spearman_out['groups_order']})", flush=True)

    print("\n=== Within-person spread (text basis, mean pairwise cosine distance), median by role-count stratum ===",
          flush=True)
    strata_header = f"{'group':<28}" + "".join(f"{('n=' + s):>18}" for s in STRATA)
    print(strata_header, flush=True)
    for g in groups:
        row = f"{g:<28}"
        for s in STRATA:
            d = spread_out[g][s]
            if d["median_spread"] is None:
                cell = f"null (n={d['n_people']})"
            else:
                cell = f"{d['median_spread']:.3f} (n={d['n_people']})"
            row += f"{cell:>18}"
        print(row, flush=True)


if __name__ == "__main__":
    run()
