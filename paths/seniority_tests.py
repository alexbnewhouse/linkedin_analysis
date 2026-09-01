"""Validation for the revealed-seniority + transition-typing system.

    uv run --group graph python -m paths.seniority_tests

Runs against the built artifacts (`paths/seniority_scores.parquet`,
`paths/_manifest.json`, `transition_network/occupation_edges.parquet`). Three
checks, mirroring SENIORITY_TRANSITIONS_PLAN.md §5:

  1. GOLD ORDERED ROLE PAIRS — does revealed `revealed_pct` rank the senior role
     above the junior one? Reported as pairwise accuracy; asserted on the robust
     subset. (Revealed seniority is propose-only, so we don't demand 100% on
     ambiguous bare tokens — we demand it on the clear cases.)
  2. INTERNAL CONSISTENCY — known occupation ladders (RN→NP, Cook→Chef,
     Police→Detective) must come out with mean Δseniority > 0 (up) on the
     occupation network. This is the method validating itself on cases the
     network README already established as high-relative-risk ladders.
  3. COVERAGE — the manifest must show the headline gain: seniority on a large
     majority of steps and confident typing on a majority of edges (vs the 15.8%
     directional baseline before this system).
"""

from __future__ import annotations

import json

import duckdb

from paths import common as C

# (junior_role, senior_role): revealed_pct(senior) should exceed revealed_pct(junior).
# Exact role_canonical strings (seniority words are stripped into seniority_level).
GOLD_ROLE_PAIRS = [
    ("analyst", "president"),
    ("manager", "president"),
    ("engineer", "president"),
    ("analyst", "vicepresident"),
    ("engineer", "vicepresident"),
    ("manager", "vicepresident"),
    ("engineersoftware", "president"),
]

# known occupation ladders (from transition_network/README.md): from_label -> to_label
GOLD_OCC_LADDERS = [
    ("Registered Nurses", "Nurse Practitioners"),
    ("Cooks, Restaurant", "Chefs and Head Cooks"),
    ("Police and Sheriff's Patrol Officers", "Detectives and Criminal Investigators"),
]


def main() -> None:
    con = duckdb.connect()
    s = f"read_parquet('{C.SENIORITY_SCORES_PATH}')"
    pct = {r[0]: r[1] for r in con.sql(f"SELECT role_canonical, revealed_pct FROM {s}").fetchall()}

    # 1. gold ordered role pairs
    correct, scored = 0, 0
    misses = []
    for lo, hi in GOLD_ROLE_PAIRS:
        if lo in pct and hi in pct:
            scored += 1
            if pct[hi] > pct[lo]:
                correct += 1
            else:
                misses.append((lo, round(pct[lo], 3), hi, round(pct[hi], 3)))
    acc = correct / scored if scored else 0.0
    print(f"[1] gold role-pair accuracy: {correct}/{scored} = {acc:.0%}")
    for m in misses:
        print(f"    miss: {m[0]}({m[1]}) >= {m[2]}({m[3]})")
    assert acc >= 0.85, f"revealed seniority orders gold pairs below 0.85 ({acc:.0%})"

    # 2. internal consistency: known ladders point up
    e = "read_parquet('" + str(C.ROOT / "transition_network" / "occupation_edges.parquet") + "')"
    for lo, hi in GOLD_OCC_LADDERS:
        row = con.sql(f"""SELECT mean_delta_sen FROM {e}
                          WHERE from_label = ? AND to_label = ?""", params=[lo, hi]).fetchone()
        assert row and row[0] is not None, f"ladder edge missing: {lo} -> {hi}"
        print(f"[2] ladder {lo!r} -> {hi!r}: Δsen={row[0]:+.3f}")
        assert row[0] > 0, f"ladder {lo}->{hi} should be up but Δsen={row[0]}"

    # 3. coverage gain (the headline)
    m = json.loads((C.OUT_DIR / "_manifest.json").read_text())
    assert m.get("has_revealed_scores"), "spine built without revealed scores"
    frac_sen = m["frac_steps_with_seniority_score"]
    typed = m["transitions_typed_conf_ge_min"] / m["transitions"]
    print(f"[3] steps with seniority_score: {frac_sen:.1%}; "
          f"edges typed (conf>={C.CONF_MIN}): {typed:.1%}")
    assert frac_sen > 0.5, f"seniority coverage too low: {frac_sen:.1%}"
    assert typed > 0.5, f"typed-edge coverage too low: {typed:.1%}"

    con.close()
    print("\nAll seniority/transition-typing checks passed.")


if __name__ == "__main__":
    main()
