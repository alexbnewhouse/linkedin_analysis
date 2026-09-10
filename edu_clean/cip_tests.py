"""Tests for the CIP jury pipeline (pure, no network, no LLM).

    uv run python -m edu_clean.cip_tests
"""

from __future__ import annotations

from edu_clean import cip_llm as L
from edu_clean import cip_taxonomy as T
from edu_clean.run_cip_jury import _non_field


def ok(name: str) -> None:
    print(f"  ok: {name}")


def test_taxonomy() -> None:
    codes = T.all_codes()
    assert len(T.FAMILIES) == 41, f"expected 41 families, got {len(T.FAMILIES)}"
    assert codes == sorted(T.FAMILIES) + [T.ABSTAIN]
    assert all(T.is_valid(c) for c in codes)
    assert not T.is_valid("99") and not T.is_valid(None) and not T.is_valid("")
    assert not T.is_valid("28"), "28 (Military Science) never occurs in the data"
    assert T.label(T.ABSTAIN)
    assert all(T.label(c) for c in T.FAMILIES), "every family must carry a CSV title"
    assert "GENERAL STUDIES" in T.label("24").upper(), "24 must be the General Studies family"
    ok("taxonomy: 41 data families + XUN, validity, reference labels")

    schema = T.output_json_schema()
    props = list(schema["properties"])
    assert props.index("rationale") < props.index("code"), "rationale must precede code"
    assert schema["properties"]["code"]["enum"] == codes
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"rationale", "code", "confidence"}
    ok("schema: reason-first property order, enum-constrained, strict")


def test_taxonomy_matches_data() -> None:
    """Every code is a REAL cip2 value found in the data, and vice versa."""
    edu = T.ROOT / "normalized" / "education.parquet"
    if not edu.exists():
        print("  -- skipped: education.parquet not found")
        return
    import duckdb
    con = duckdb.connect()
    data = {r[0] for r in con.execute(
        f"SELECT DISTINCT cip2 FROM read_parquet('{edu}') "
        f"WHERE cip2 IS NOT NULL").fetchall()}
    con.close()
    assert set(T.FAMILIES) == data, (
        f"taxonomy/data mismatch: extra={sorted(set(T.FAMILIES) - data)} "
        f"missing={sorted(data - set(T.FAMILIES))}")
    ok(f"taxonomy: exactly the {len(data)} cip2 values observed in education.parquet")


def test_cache_key() -> None:
    item = {"field_norm": "computer science", "top_raw_variants": "Computer Science | computer science",
            "modal_degree_text": "Bachelor of Science - BS", "n_rows": 100}
    k1 = L.cache_key(item, L.JURY[0])
    assert k1 == L.cache_key(dict(item), L.JURY[0]), "key must be stable"
    assert k1 != L.cache_key(item, L.JURY[1]), "key must vary by model"
    changed = dict(item, field_norm="data science")
    assert k1 != L.cache_key(changed, L.JURY[0]), "key must vary with evidence"
    orig = T.PROMPT_VERSION
    try:
        T.PROMPT_VERSION = orig + 1
        assert k1 != L.cache_key(item, L.JURY[0]), "key must vary with PROMPT_VERSION"
    finally:
        T.PROMPT_VERSION = orig
    ok("cache_key: stable, model/evidence/version sensitive")


def test_evidence_text_honesty() -> None:
    full = {"field_norm": "mechanical engineering",
            "top_raw_variants": "Mechanical Engineering | mechanical engineering",
            "modal_degree_text": "Bachelor of Engineering (B.E.)",
            "n_rows": 4200,
            "anchors": ["mechanical engineering technology -> 15 ENGINEERING TECHNOLOGIES/TECHNICIANS"]}
    txt = L.evidence_text(full)
    assert "mechanical engineering" in txt
    assert "Mechanical Engineering | mechanical engineering" in txt
    assert "Bachelor of Engineering (B.E.)" in txt and "4200" in txt
    assert "mechanical engineering technology -> 15" in txt

    bare = {"field_norm": "widget studies", "top_raw_variants": None,
            "modal_degree_text": None, "n_rows": None, "anchors": []}
    txt2 = L.evidence_text(bare)
    assert "degree" not in txt2.lower(), "absent degree must be omitted, not invented"
    assert "reference" not in txt2.lower(), "absent anchors must be omitted"
    assert txt2.splitlines() == ["Field of study: widget studies"], f"unexpected: {txt2!r}"
    # fabrication guard: every non-fixed line in the output must come from the item
    fixed_prefixes = ("Field of study:", "As written", "Typical degree line:",
                      "Occurrences in the dataset:", "Nearest reference fields", "- ")
    for line in L.evidence_text(full).splitlines():
        assert line.startswith(fixed_prefixes), f"unexpected line: {line!r}"
    ok("evidence_text: renders only provided fields, omits absent ones")


def test_unanimous_accept() -> None:
    assert L.unanimous_accept(["51", "51"]) == "51"
    assert L.unanimous_accept(["51", "11"]) is None, "disagreement must reject"
    assert L.unanimous_accept([T.ABSTAIN, T.ABSTAIN]) is None, "XUN must never be accepted"
    assert L.unanimous_accept(["51", T.ABSTAIN]) is None
    assert L.unanimous_accept(["51"]) is None, "single vote must reject"
    assert L.unanimous_accept([]) is None
    assert L.unanimous_accept(["99", "99"]) is None, "invalid code must reject"
    assert L.unanimous_accept(["28", "28"]) is None, "off-data family must reject"
    ok("unanimous_accept: only complete, identical, valid, non-XUN panels pass")


def test_build_request_pure() -> None:
    item = {"field_norm": "nursing", "top_raw_variants": "Nursing", "n_rows": 9000}
    body = L.build_request(item, "llamacpp/qwen3-4b-q4")
    assert body["model"] == "qwen3-4b-q4"
    assert body["format"] == T.output_json_schema()
    assert body["options"]["temperature"] == 0 and body["options"]["seed"] == 7
    assert body["think"] is False, "qwen3 juror must request thinking off"
    body2 = L.build_request(item, "llamacpp/bulk-moe-q4")
    assert body2["think"] is False, "bulk-moe (Qwen3 MoE) must request thinking off"
    assert body["messages"][0]["content"] == L._SYSTEM
    ok("build_request: bare model name, schema, determinism opts, think-off")


def test_non_field_rule() -> None:
    for s in ("n/a", "none", "cum laude", "magna cum laude", "4.0", "3.8",
              "12", "a", "-", "undeclared", "minor", "", None):
        assert _non_field(s), f"{s!r} must be excluded by rule"
    for s in ("general studies", "general", "computer science", "informatica",
              "liberal arts", "art"):
        assert not _non_field(s), f"{s!r} must NOT be excluded by rule"
    ok("_non_field: literal non-answers/GPAs out; 'general studies' (CIP 24) stays in")


def test_gold_dominance() -> None:
    gold = L.CACHE_FILE.parent / "cip_gold.parquet"
    if not gold.exists():
        print("  -- skipped: cip_gold.parquet not built yet (run extract)")
        return
    import duckdb
    con = duckdb.connect()
    lo = con.execute(
        f"SELECT min(dominance), count(*) FROM read_parquet('{gold}')").fetchone()
    con.close()
    assert lo[0] >= 0.90, f"gold contains dominance < 0.9: {lo[0]}"
    ok(f"gold: dominance >= 0.9 enforced over {lo[1]:,} rows")


def test_gold_v1_floor() -> None:
    """Blind gold v1 (2026-09-01) regression gate: every landed CIP tier must
    keep >= 0.90 lenient and >= 0.90 humanities-level precision on the fixed
    held-out sample, and string-keyed tiers must not label placeholders beyond
    the recorded baseline (one string each in jury and frontier)."""
    from edu_clean import gold_v1 as G
    if not (G.OUT.exists() and G.EDU.exists()):
        print("  -- skipped: gold v1 or normalized/education.parquet not built")
        return
    out = G.score(verbose=False, write=False)
    for tier in G.LANDED:
        d = out["tiers"][tier]
        if d["graded"] < 30:
            continue
        assert d["lenient"] >= 0.90, f"gold v1: {tier} lenient {d['lenient']} < 0.90"
        assert d["level"] >= 0.90, f"gold v1: {tier} level {d['level']} < 0.90"
        assert len(d["xun_string_label_errors"]) <= 1, \
            f"gold v1: {tier} labels placeholders: {d['xun_string_label_errors']}"
    ok("gold v1: all landed tiers >= 0.90 lenient/level on the held-out sample")


def main() -> None:
    test_taxonomy()
    test_taxonomy_matches_data()
    test_cache_key()
    test_evidence_text_honesty()
    test_unanimous_accept()
    test_build_request_pure()
    test_non_field_rule()
    test_gold_dominance()
    test_gold_v1_floor()
    print("All CIP jury tests passed.")


if __name__ == "__main__":
    main()
