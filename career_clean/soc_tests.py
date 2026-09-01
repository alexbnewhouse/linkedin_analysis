"""Tests for the SOC jury pipeline (pure, no network, no LLM).

    uv run python -m career_clean.soc_tests
"""

from __future__ import annotations

from career_clean import soc_llm as L
from career_clean import soc_taxonomy as T


def ok(name: str) -> None:
    print(f"  ok: {name}")


def test_taxonomy() -> None:
    codes = T.all_codes()
    assert len(T.MAJOR_GROUPS) == 23, f"expected 23 major groups, got {len(T.MAJOR_GROUPS)}"
    assert codes == sorted(T.MAJOR_GROUPS) + [T.ABSTAIN]
    assert all(T.is_valid(c) for c in codes)
    assert not T.is_valid("99") and not T.is_valid(None) and not T.is_valid("")
    assert T.label(T.ABSTAIN)
    ok("taxonomy: 23 groups + XUN, validity, labels")

    schema = T.output_json_schema()
    props = list(schema["properties"])
    assert props.index("rationale") < props.index("code"), "rationale must precede code"
    assert schema["properties"]["code"]["enum"] == codes
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"rationale", "code", "confidence"}
    ok("schema: reason-first property order, enum-constrained, strict")


def test_cache_key() -> None:
    item = {"role_canonical": "engineersoftware", "role_display": "software engineer",
            "top_titles": "Software Engineer | Sr Software Engineer", "n_steps": 100}
    k1 = L.cache_key(item, L.JURY[0])
    assert k1 == L.cache_key(dict(item), L.JURY[0]), "key must be stable"
    assert k1 != L.cache_key(item, L.JURY[1]), "key must vary by model"
    changed = dict(item, role_display="data engineer")
    assert k1 != L.cache_key(changed, L.JURY[0]), "key must vary with evidence"
    orig = T.PROMPT_VERSION
    try:
        T.PROMPT_VERSION = orig + 1
        assert k1 != L.cache_key(item, L.JURY[0]), "key must vary with PROMPT_VERSION"
    finally:
        T.PROMPT_VERSION = orig
    ok("cache_key: stable, model/evidence/version sensitive")


def test_evidence_text_honesty() -> None:
    full = {"role_canonical": "nurseregistered", "role_display": "registered nurse",
            "top_titles": "Registered Nurse | RN", "industry_l1_label": "Healthcare",
            "modal_seniority": "senior", "n_steps": 4200}
    txt = L.evidence_text(full)
    assert "registered nurse" in txt and "Registered Nurse | RN" in txt
    assert "Healthcare" in txt and "senior" in txt and "4200" in txt

    bare = {"role_canonical": "x", "role_display": "widget wrangler",
            "top_titles": None, "industry_l1_label": None,
            "modal_seniority": None, "n_steps": None}
    txt2 = L.evidence_text(bare)
    assert "industry" not in txt2.lower(), "absent industry must be omitted, not invented"
    assert "seniority" not in txt2.lower()
    assert txt2.splitlines() == ["Role: widget wrangler"], f"unexpected: {txt2!r}"
    # fabrication guard: every non-fixed token in the output must come from the item
    fixed_prefixes = ("Role:", "As written", "Typical seniority:",
                      "Most common employer industry", "Occurrences in the dataset:")
    for line in L.evidence_text(full).splitlines():
        assert line.startswith(fixed_prefixes), f"unexpected line: {line!r}"
    ok("evidence_text: renders only provided fields, omits absent ones")


def test_unanimous_accept() -> None:
    assert L.unanimous_accept(["29", "29"]) == "29"
    assert L.unanimous_accept(["29", "11"]) is None, "disagreement must reject"
    assert L.unanimous_accept([T.ABSTAIN, T.ABSTAIN]) is None, "XUN must never be accepted"
    assert L.unanimous_accept(["29", T.ABSTAIN]) is None
    assert L.unanimous_accept(["29"]) is None, "single vote must reject"
    assert L.unanimous_accept([]) is None
    assert L.unanimous_accept(["99", "99"]) is None, "invalid code must reject"
    ok("unanimous_accept: only complete, identical, valid, non-XUN panels pass")


def test_build_request_pure() -> None:
    item = {"role_canonical": "teacher", "role_display": "teacher",
            "top_titles": "Teacher", "n_steps": 9000}
    body = L.build_request(item, "llamacpp/qwen3-4b-q4")
    assert body["model"] == "qwen3-4b-q4"
    assert body["format"] == T.output_json_schema()
    assert body["options"]["temperature"] == 0 and body["options"]["seed"] == 7
    assert body["think"] is False, "qwen3 juror must request thinking off"
    body2 = L.build_request(item, "llamacpp/bulk-moe-q4")
    assert body2["think"] is False, "bulk-moe (Qwen3 MoE) must request thinking off"
    assert body["messages"][0]["content"] == L._SYSTEM
    ok("build_request: bare model name, schema, determinism opts, think-off")


def test_gold_dominance() -> None:
    if not L.CACHE_FILE.parent.joinpath("soc_gold.parquet").exists():
        print("  -- skipped: soc_gold.parquet not built yet (run extract)")
        return
    import duckdb
    con = duckdb.connect()
    lo = con.execute(
        f"SELECT min(dominance), count(*) FROM "
        f"read_parquet('{L.CACHE_FILE.parent / 'soc_gold.parquet'}')").fetchone()
    con.close()
    assert lo[0] >= 0.90, f"gold contains dominance < 0.9: {lo[0]}"
    ok(f"gold: dominance >= 0.9 enforced over {lo[1]:,} rows")


def main() -> None:
    test_taxonomy()
    test_cache_key()
    test_evidence_text_honesty()
    test_unanimous_accept()
    test_build_request_pure()
    test_gold_dominance()
    print("All SOC jury tests passed.")


if __name__ == "__main__":
    main()
