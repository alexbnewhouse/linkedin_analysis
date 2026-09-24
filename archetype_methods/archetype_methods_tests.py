"""Logic tests, no built parquet needed.

    uv run python -m archetype_methods.archetype_methods_tests
"""

from __future__ import annotations

from . import framework as F
from . import metrics as M


def test_framework_shape():
    assert len(F.ARCHETYPES) == 9
    assert sum(len(a.pathways) for a in F.ARCHETYPES) == 75
    assert len({t.lower() for t, _, _ in F.seeds()}) == 390
    amb = F.ambiguous_seed_titles()
    assert "public historian" in amb and amb["public historian"] == {"communicators", "researchers"}
    for a in F.ARCHETYPES:
        assert a.orientation.startswith("I ")
        assert len(a.skills) >= 12


def test_score_on_synthetic_gold():
    gold = [
        {"role_canonical": "a", "primary": "leaders", "secondary": "", "fit": "strong", "band": "A", "n_persons": 100},
        {"role_canonical": "b", "primary": "helpers", "secondary": "advocates", "fit": "weak", "band": "B", "n_persons": 10},
        {"role_canonical": "c", "primary": "none", "secondary": "", "fit": "none", "band": "C", "n_persons": 1},
        {"role_canonical": "d", "primary": "stewards", "secondary": "", "fit": "strong", "band": "D", "n_persons": 1},
    ]
    a = {"a": ("leaders", 1.0), "b": ("advocates", 0.5), "c": ("none", 0.9)}  # d abstains
    s = M.score(a, gold=gold, name="t")
    assert s["coverage"] == 0.75
    assert abs(s["acc_strict"] - 0.5) < 1e-9          # a, c right; b secondary only; d abstain
    assert abs(s["acc_lenient"] - 0.75) < 1e-9
    assert abs(s["acc_strict_assigned"] - 2 / 3) < 1e-9
    assert abs(s["acc_strict_w"] - 101 / 112) < 1e-9
    assert s["acc_by_fit"]["none"] == 1.0
    assert s["f1_by_label"]["stewards"] == 0.0 and s["f1_by_label"]["leaders"] == 1.0
    assert s["confusion"] == {"helpers->advocates": 1, "stewards->abstain": 1}


def test_agreement():
    a = {"x": ("leaders", 1), "y": ("helpers", 1), "z": ("abstain", 0)}
    b = {"x": ("leaders", 1), "y": ("leaders", 1), "z": ("none", 1)}
    r = M.agreement(a, b, ["x", "y", "z"])
    assert r["n"] == 2 and r["agree"] == 0.5


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
