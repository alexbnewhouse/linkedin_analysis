"""The gold set: a stratified, person-weighted sample of real roles, hand-labeled.

    uv run python -m archetype_methods.gold sample   # draw + write gold/sample.csv
    uv run python -m archetype_methods.gold stats    # after labeling

Strata are person-support bands so the benchmark reports both what the head
looks like (where the population lives) and whether a method survives the
tail. Labels: primary archetype key, optional secondary, and a `fit` grade:
  strong  the framework has an obvious home for this work
  weak    placeable only by stretching an orientation statement
  none    outside all nine orientations (trades, clinical, production, transport,
          uniformed service, placeholders such as 'retired')
Labeling rules are in EVALUATION.md.
"""

from __future__ import annotations

import csv
import sys

import numpy as np
import pyarrow.compute as pc

from . import common as C

BANDS = (("A", 1000, 10**9), ("B", 100, 999), ("C", 20, 99), ("D", 5, 19))
PER_BAND = 100
SEED = 20260917

FIELDS = ("role_canonical", "band", "n_persons", "role_display", "role_text",
          "soc_detail", "soc_major", "industry_l1", "owner_share", "mean_seniority")


def sample():
    t = C.load_roles()
    rng = np.random.default_rng(SEED)
    rows = []
    for band, lo, hi in BANDS:
        mask = pc.and_(pc.greater_equal(t["n_persons"], lo), pc.less_equal(t["n_persons"], hi))
        sub = t.filter(mask)
        idx = rng.choice(sub.num_rows, size=min(PER_BAND, sub.num_rows), replace=False)
        for i in sorted(idx):
            r = {k: sub[k][int(i)].as_py() for k in FIELDS if k in sub.column_names}
            r["band"] = band
            rows.append(r)
    C.GOLD.mkdir(exist_ok=True)
    with (C.GOLD / "sample.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(FIELDS))
        w.writeheader()
        w.writerows(rows)
    print(len(rows), "roles sampled ->", C.GOLD / "sample.csv")


def load():
    """Labeled gold rows: list of dicts with primary/secondary/fit merged in."""
    sample_rows = {r["role_canonical"]: r for r in csv.DictReader((C.GOLD / "sample.csv").open())}
    out = []
    for r in csv.DictReader((C.GOLD / "labels.csv").open()):
        base = dict(sample_rows[r["role_canonical"]])
        base.update({"primary": r["primary"], "secondary": r.get("secondary") or "",
                     "fit": r["fit"], "note": r.get("note", "")})
        base["n_persons"] = int(base["n_persons"])
        out.append(base)
    return out


def stats():
    g = load()
    from collections import Counter
    print(len(g), "labeled")
    print("primary:", Counter(r["primary"] for r in g).most_common())
    print("fit:", Counter(r["fit"] for r in g).most_common())
    print("secondary set:", sum(1 for r in g if r["secondary"]))
    w = sum(r["n_persons"] for r in g)
    print("person-weighted fit:", {k: round(sum(r["n_persons"] for r in g if r["fit"] == k) / w, 3)
                                   for k in ("strong", "weak", "none")})


if __name__ == "__main__":
    {"sample": sample, "stats": stats}[sys.argv[1]]()
