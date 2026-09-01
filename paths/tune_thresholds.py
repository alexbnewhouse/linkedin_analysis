"""Calibrate the transition-typing threshold τ (SENIORITY_TRANSITIONS_PLAN §5).

    uv run --group graph python -m paths.tune_thresholds

τ_up/τ_down decide when a Δseniority is large enough to call a move directional.
We tune them WITHOUT hand labels by using the **lexical layer as silver truth**:
on edges where both endpoints carry a named seniority token, sign(Δordinal) is a
trustworthy up/down. We then ask how well the *independent* revealed signal
(SpringRank role rank, which never sees the lexical word) agrees, as a function of
the threshold on the revealed-score gap. This is non-circular (the predictor
excludes the lexical layer) and calibrates exactly the regime where τ matters —
the no-lexical-word majority that only the revealed layer can type.

Reports an accuracy/coverage curve and a recommended τ; does not edit config.
"""

from __future__ import annotations

import argparse

import duckdb
import numpy as np

from paths import common as C

TAUS = [0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25, 0.30]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target-accuracy", type=float, default=0.72)
    args = ap.parse_args()
    con = duckdb.connect()
    s = f"read_parquet('{C.SENIORITY_SCORES_PATH}')"
    t = f"read_parquet('{C.TRANSITIONS_OUT}')"

    # both-lexical edges (silver truth) with an independent revealed gap on each side
    df = con.sql(f"""
      SELECT
        sign(e.to_seniority_ordinal - e.from_seniority_ordinal) AS lex_dir,
        (tr.revealed_pct - fr.revealed_pct) AS rev_delta
      FROM {t} e
      JOIN {s} fr ON fr.role_canonical = e.from_role
      JOIN {s} tr ON tr.role_canonical = e.to_role
      WHERE e.from_seniority_ordinal IS NOT NULL
        AND e.to_seniority_ordinal IS NOT NULL
        AND e.from_role <> e.to_role          -- need a real role change to compare
    """).df()
    nonflat = df[df["lex_dir"] != 0]
    lex = nonflat["lex_dir"].to_numpy()
    rev = nonflat["rev_delta"].to_numpy()
    print(f"silver edges (both lexical, non-flat, distinct roles): {len(nonflat):,}\n")
    print(f"{'tau':>6} {'coverage':>9} {'dir_accuracy':>13} {'up_prec':>8} {'down_prec':>10}")
    rec = []
    for tau in TAUS:
        fire = np.abs(rev) > tau
        cov = fire.mean()
        if fire.sum() == 0:
            continue
        pred = np.sign(rev[fire])
        truth = lex[fire]
        acc = (pred == truth).mean()
        up = pred > 0
        down = pred < 0
        up_p = (truth[up] > 0).mean() if up.any() else float("nan")
        dn_p = (truth[down] < 0).mean() if down.any() else float("nan")
        rec.append((tau, cov, acc))
        print(f"{tau:>6.2f} {cov:>8.1%} {acc:>12.1%} {up_p:>8.1%} {dn_p:>9.1%}")

    # recommend the largest-coverage tau meeting the target directional accuracy
    ok = [r for r in rec if r[2] >= args.target_accuracy]
    best = min(ok, key=lambda r: r[0]) if ok else max(rec, key=lambda r: r[2])
    print(f"\nRecommended τ ≈ {best[0]:.2f} "
          f"(directional accuracy {best[2]:.1%} at {best[1]:.1%} coverage, "
          f"target {args.target_accuracy:.0%}). Current default TAU_UP/DOWN="
          f"{C.TAU_UP}/{C.TAU_DOWN}.")
    print("Interpretation: the revealed signal agrees with the lexical truth on a "
          "clear majority of role-change directions; τ trades coverage for "
          "precision. Revealed typing stays propose-only with confidence attached.")
    con.close()


if __name__ == "__main__":
    main()
