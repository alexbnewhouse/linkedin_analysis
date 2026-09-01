"""Phase 3b — archetype coherence validation (ARCHETYPES_PLAN.md §8).

Metrics that test whether the 15 buckets are internally coherent:
  - within-archetype SOC-major purity (person-weighted): among roles in an
    archetype that carry a SOC major, the share on the archetype's modal major.
  - within-archetype industry-L1 purity (context, not a target).
  - SOC-major -> archetype concentration (does each SOC major land mostly in
    one archetype, i.e. is the mapping near-functional?).
  - size distribution + OTHER decomposition (had-SOC vs no-signal).
Weighting uses n_steps (role occurrences) to avoid the cross-role person
double-count; reported as such.
"""

from __future__ import annotations

import json

from . import common as C


def build(con) -> dict:
    ra = f"read_parquet('{C.RESULTS / 'role_archetype.parquet'}')"
    rf = f"read_parquet('{C.RESULTS / 'role_features.parquet'}')"
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE j AS
      SELECT a.archetype_id, a.archetype_label, a.assign_method,
             f.soc_major, f.industry_l1, f.n_steps
      FROM {ra} a JOIN {rf} f USING (role_canonical)
    """)

    # within-archetype SOC-major purity (steps-weighted, roles with a soc_major)
    purity = con.execute("""
      WITH per AS (
        SELECT archetype_id, any_value(archetype_label) AS label,
               soc_major, sum(n_steps) AS w
        FROM j WHERE soc_major IS NOT NULL GROUP BY archetype_id, soc_major
      ),
      tot AS (SELECT archetype_id, sum(w) AS tw FROM per GROUP BY 1),
      top AS (SELECT archetype_id, max(w) AS mw FROM per GROUP BY 1)
      SELECT p.archetype_id, any_value(pe.label) AS label,
             round(t.mw::DOUBLE/o.tw, 3) AS soc_purity,
             o.tw AS soc_steps
      FROM (SELECT DISTINCT archetype_id FROM per) p
      JOIN tot o USING (archetype_id)
      JOIN top t USING (archetype_id)
      JOIN per pe ON pe.archetype_id = p.archetype_id
      GROUP BY p.archetype_id, t.mw, o.tw
      ORDER BY p.archetype_id
    """).fetchall()

    # SOC-major concentration: for each soc_major, share landing in its modal
    # archetype (how functional is the major->archetype map).
    soc_conc = con.execute("""
      WITH per AS (
        SELECT soc_major, archetype_id, sum(n_steps) AS w
        FROM j WHERE soc_major IS NOT NULL GROUP BY 1, 2
      ),
      tot AS (SELECT soc_major, sum(w) tw FROM per GROUP BY 1),
      top AS (SELECT soc_major, max(w) mw FROM per GROUP BY 1)
      SELECT per2.soc_major, round(top.mw::DOUBLE/tot.tw,3) AS concentration,
             tot.tw AS steps
      FROM (SELECT DISTINCT soc_major FROM per) per2
      JOIN tot USING (soc_major) JOIN top USING (soc_major)
      ORDER BY steps DESC
    """).fetchall()

    # within-archetype industry-L1 purity (context; industry is not a target)
    ind_purity = con.execute("""
      WITH per AS (
        SELECT archetype_id, industry_l1, sum(n_steps) AS w
        FROM j WHERE industry_l1 IS NOT NULL GROUP BY 1, 2),
      tot AS (SELECT archetype_id, sum(w) tw FROM per GROUP BY 1),
      top AS (SELECT archetype_id, max(w) mw, arg_max(industry_l1, w) top_l1
              FROM per GROUP BY 1)
      SELECT t.archetype_id, round(t.mw::DOUBLE/o.tw,3) AS ind_purity, t.top_l1
      FROM top t JOIN tot o USING (archetype_id) ORDER BY 1
    """).fetchall()

    # cross-signal agreement: for keyword-resolved roles, does the role's
    # soc_major (when present) imply the SAME archetype the keyword chose?
    from . import archetype_spec as S
    con.execute("""
      CREATE OR REPLACE TEMP TABLE kw AS
      SELECT a.archetype_id, f.soc_major, f.n_steps
      FROM read_parquet($ra) a JOIN read_parquet($rf) f USING (role_canonical)
      WHERE a.assign_method IN ('keyword','keyword_over_soc')
        AND f.soc_major IS NOT NULL
    """, {"ra": str(C.RESULTS / 'role_archetype.parquet'),
          "rf": str(C.RESULTS / 'role_features.parquet')})
    kw_rows = con.execute("SELECT archetype_id, soc_major, n_steps FROM kw").fetchall()
    agree = tot_w = 0
    for aid, major, w in kw_rows:
        implied = S.SOC_MAJOR_DEFAULT.get(major)
        if implied is not None and implied != "other":
            tot_w += w
            if S.ID_BY_KEY[implied] == aid:
                agree += w
    cross_agreement = round(agree / tot_w, 3) if tot_w else None

    # OTHER decomposition: uncoded tail vs out-of-scope (blue-collar/uniformed)
    other = con.execute("""
      SELECT
        round(100.0*sum(CASE WHEN soc_major IS NOT NULL THEN n_steps ELSE 0 END)
              /sum(n_steps),1) AS pct_had_soc,
        sum(n_steps) AS steps
      FROM j WHERE archetype_id = 0
    """).fetchone()
    other_majors = con.execute("""
      SELECT soc_major, sum(n_steps) AS steps
      FROM j WHERE archetype_id = 0 AND soc_major IS NOT NULL
      GROUP BY 1 ORDER BY steps DESC LIMIT 8
    """).fetchall()

    result = {
        "soc_major_purity": [
            {"id": a, "label": lab, "soc_purity": p, "soc_steps": int(s)}
            for a, lab, p, s in purity],
        "industry_l1_purity": [
            {"id": a, "ind_purity": p, "top_l1": t} for a, p, t in ind_purity],
        "soc_major_concentration": [
            {"soc_major": m, "concentration": c, "steps": int(s)}
            for m, c, s in soc_conc],
        "keyword_vs_soc_agreement": cross_agreement,
        "other_decomposition": {
            "pct_steps_with_soc_major": other[0],
            "total_steps": int(other[1]),
            "top_soc_majors_in_other": [
                {"soc_major": m, "steps": int(s)} for m, s in other_majors]},
        "mean_soc_purity_weighted": round(
            sum(p * s for _, _, p, s in purity) /
            sum(s for _, _, _, s in purity), 3),
    }
    (C.RESULTS / "validation.json").write_text(json.dumps(result, indent=2))
    return result


def unsupervised_crosscheck(con, top_n: int = 15000, k: int = 15) -> dict:
    """"Do the data back the anchors?" — embed the top-N roles by person
    support, KMeans(k), and report adjusted Rand vs the rule labels (excluding
    OTHER). High ARI = the unsupervised structure agrees with the hand anchors.
    """
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import KMeans
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

    ra = f"read_parquet('{C.RESULTS / 'role_archetype.parquet'}')"
    rf = f"read_parquet('{C.RESULTS / 'role_features.parquet'}')"
    rows = con.execute(f"""
      SELECT a.archetype_id, f.role_text
      FROM {ra} a JOIN {rf} f USING (role_canonical)
      WHERE a.archetype_id <> 0 AND f.role_text IS NOT NULL AND length(f.role_text) > 1
      ORDER BY a.n_persons DESC LIMIT {top_n}
    """).fetchall()
    labels = np.array([r[0] for r in rows])
    texts = [r[1] for r in rows]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer("all-MiniLM-L6-v2", device=device)
    vec = model.encode(texts, normalize_embeddings=True, batch_size=512,
                       convert_to_numpy=True, show_progress_bar=False)
    km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(vec)
    ari = adjusted_rand_score(labels, km.labels_)
    nmi = normalized_mutual_info_score(labels, km.labels_)
    res = {"top_n": len(rows), "k": k,
           "adjusted_rand": round(float(ari), 3),
           "normalized_mutual_info": round(float(nmi), 3)}
    (C.RESULTS / "unsupervised_crosscheck.json").write_text(json.dumps(res, indent=2))
    return res


def main() -> None:
    con = C.connect()
    r = build(con)
    print(f"mean SOC-major purity (steps-weighted): {r['mean_soc_purity_weighted']}")
    print("\nper-archetype SOC purity:")
    for x in r["soc_major_purity"]:
        print(f"  {x['soc_purity']:.3f}  [{x['id']:>2}] {x['label']}  (n_steps={x['soc_steps']:,})")
    print("\nSOC-major -> modal-archetype concentration (top by volume):")
    for x in r["soc_major_concentration"][:12]:
        print(f"  major {x['soc_major']}: {x['concentration']:.3f}  (n_steps={x['steps']:,})")
    print(f"\nkeyword-vs-SOC agreement: {r['keyword_vs_soc_agreement']}")
    print(f"OTHER: {r['other_decomposition']['pct_steps_with_soc_major']}% of OTHER steps had a SOC major")
    uc = unsupervised_crosscheck(con)
    print(f"\nunsupervised cross-check (top {uc['top_n']} roles, k={uc['k']}): "
          f"adjusted Rand = {uc['adjusted_rand']}, NMI = {uc['normalized_mutual_info']}")


if __name__ == "__main__":
    main()
