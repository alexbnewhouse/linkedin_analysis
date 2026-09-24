"""Task 3: breadth metrics.

Reads Task 1/2 outputs (results/roles.parquet, results/role_soc.parquet,
results/onet_skill_matrix.parquet, cache/role_emb.npy + cache/role_keys.parquet)
and writes results/breadth.json: per group (4 headline + 2 sanity -- liberal_arts
had 0 people and was dropped, see Task 1) and per basis (text, onet_skills):
bootstrap Vendi score (median, 2.5/97.5 percentiles, n_people_available);
Spearman rank agreement between the two bases across group medians;
within-person spread (text basis only), stratified by role count; median
role description length per group; SOC source (pooled vs nearest) share per
group.

    uv run python -m skill_breadth.run_breadth
"""

from __future__ import annotations

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import spearmanr

from . import common as C
from . import metrics as M

BASES = ("text", "onet_skills")
STRATA = ("3", "4", "5+")


def _stratum(n_roles: int) -> str:
    return str(n_roles) if n_roles < 5 else "5+"


def load_role_matrices(con):
    """Row-aligned (role, text_emb, skill_emb) arrays plus group/person-id
    arrays, all indexed 0..n-1 in cache/role_keys.parquet's row order (the
    same order as cache/role_emb.npy)."""
    role_keys_tbl = pq.read_table(C.CACHE / "role_keys.parquet")
    n = role_keys_tbl.num_rows
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


def person_rows_for_group(group_arr: np.ndarray, person_arr: np.ndarray, group: str) -> dict:
    idx = np.where(group_arr == group)[0]
    out: dict[str, list[int]] = {}
    for i in idx:
        out.setdefault(person_arr[i], []).append(int(i))
    return out


def run() -> dict:
    con = C.connect()
    bases, group_arr, person_arr = load_role_matrices(con)

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
                scores = boot[basis]
                lo, hi = np.percentile(scores, [2.5, 97.5])
                entry[basis] = {
                    "median": float(np.median(scores)),
                    "lo": float(lo),
                    "hi": float(hi),
                }
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
    rho_res = spearmanr(med_text, med_skills)
    spearman_out = {
        "groups_order": groups,
        "median_text": med_text,
        "median_onet_skills": med_skills,
        "rho": float(rho_res.statistic),
        "pvalue": float(rho_res.pvalue),
    }

    # Median description length (chars) per group -- description = role_text
    # minus its "title_raw. " prefix (role_text = title_raw || '. ' || description,
    # see common.py docstring); untrimmed, so a close but not byte-exact proxy
    # for length(trim(description)) used at the Task 1 filter stage.
    desc_len_rows = con.sql(f"""
        SELECT "group", median(length(role_text) - length(title_raw) - 2) AS median_len
        FROM read_parquet('{C.RESULTS / "roles.parquet"}')
        GROUP BY 1
    """).fetchall()
    median_desc_len = {g: float(v) for g, v in desc_len_rows}

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
    }
    C.write_json(out, C.RESULTS / "breadth.json")

    _print_summary(groups, vendi_out, spread_out, median_desc_len, soc_share, spearman_out)
    return out


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
          f"rho={spearman_out['rho']:.3f} p={spearman_out['pvalue']:.4f} "
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
