"""Deterministic tests for the industry classifier.

    uv run python -m industry.tests

Covers the taxonomy invariants, the precedence/fusion rules, partial-assignment
depth handling, the occupation-prior precision guard (agnostic occupations must
abstain), the name-rule precision guard (generic corporate words must not fire),
and the LLM cache-key / offline-determinism contract. No network, no big data.
"""

from __future__ import annotations

from . import classify, curated, jury, llm, local_llm, name_rules, occupation_prior
from . import taxonomy as T
from .common import level_scores
from .gold_residual import GOLD_RESIDUAL

_failures: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    if not cond:
        _failures.append(f"{name} {extra}")
    print(f"  [{status}] {name}{('  ' + extra) if (extra and not cond) else ''}")


# ----------------------------------------------------------------- taxonomy
def test_taxonomy() -> None:
    print("taxonomy")
    summary = T.validate()
    check("validates", summary["n_nodes"] > 100)
    check("levels 1-4 only", set(summary["by_level"]) == {1, 2, 3, 4})
    check("codes unique", len(T.all_codes()) == len(set(T.all_codes())))
    # ancestors / truncate
    code = "FIN.BNK.COM.RET"
    check("ancestors full chain", T.ancestors(code) == ["FIN", "FIN.BNK", "FIN.BNK.COM", code])
    check("truncate L2", T.truncate(code, 2) == "FIN.BNK")
    check("truncate beyond depth clamps", T.truncate("FIN", 4) == "FIN")
    check("partial code is valid target", T.is_valid("FIN.BNK"))
    check("naics falls back to ancestor", T.naics_of("FIN.BNK.COM.RET") != ())
    # structured-output schema
    sch = T.output_json_schema()
    check("schema enum = all codes", set(sch["properties"]["code"]["enum"]) == set(T.all_codes()))
    check("schema strict", sch["additionalProperties"] is False)
    # sector flags
    check("public sector flag", T.sector_of("PUB.GOV.FED") == "public")
    check("defense contractor overrides to private", T.sector_of("PUB.DEF.DCON") == "private")
    check("nonprofit flag", T.sector_of("NPO.RELG") == "nonprofit")


# ------------------------------------------------------------ code validity
def test_codes_resolve() -> None:
    print("curated + name-rule codes resolve")
    check("curated all valid", curated.validate() == [], str(curated.validate()))
    check("name rules all valid", name_rules.validate() == [], str(name_rules.validate()))


# ------------------------------------------------------- name-rule precision
def test_name_rule_precision() -> None:
    """Audit 2026-09-02 red C2: the ordered token list shadowed specific rules
    and fired on household names it should never touch. Every rule must be
    reachable on its own keyword, and these displays (all real, all measured
    misfires) must resolve to the right L1 or abstain."""
    print("name-rule precision (audit C2)")
    # reachability: a rule that can never be the first match is dead
    for kw, code in name_rules._RULES:  # noqa: SLF001
        probe = kw.lstrip("^")
        got_code, got_kw = name_rules.match(probe)
        check(f"rule reachable: {kw!r}", got_kw == kw and got_code == code,
              f"got {got_kw!r} -> {got_code}")

    def l1(display):
        code, _ = name_rules.match(display)
        return T.truncate(code, 1) if code else None

    def code_of(display):
        return name_rules.match(display)[0]

    # utilities and manufacturers are not construction trades
    check("PG&E -> ENR", l1("Pacific Gas and Electric Company") == "ENR")
    check("American Electric Power -> ENR", l1("American Electric Power") == "ENR")
    check("Schneider Electric not RE", l1("Schneider Electric") != "RE")
    check("Westinghouse Electric not RE", l1("Westinghouse Electric Company") != "RE")
    check("ABC Electrical Contractors still RE", l1("ABC Electrical Contractors") == "RE")
    # universities and professional schools
    check("Columbia in the City of New York -> EDU",
          l1("Columbia University in the City of New York") == "EDU")
    check("Museum of the City of New York not PUB", l1("Museum of the City of New York") != "PUB")
    check("City of Austin -> PUB.GOV.SLOC", code_of("City of Austin") == "PUB.GOV.SLOC")
    check("City of Hope -> HLT", l1("City of Hope") == "HLT")
    check("Harvard Business School -> EDU.HED", code_of("Harvard Business School") == "EDU.HED")
    check("Icahn School of Medicine -> EDU.HED",
          code_of("Icahn School of Medicine at Mount Sinai") == "EDU.HED")
    check("Lincoln High School -> EDU.K12", code_of("Lincoln High School") == "EDU.K12")
    check("Medical University of South Carolina -> EDU",
          l1("Medical University of South Carolina") == "EDU")
    check("U of Rochester Medical Center -> HLT.PROV.HOSP",
          code_of("University of Rochester Medical Center") == "HLT.PROV.HOSP")
    check("University Hospital -> HLT", l1("University Hospital") == "HLT")
    check("Capital University -> EDU", l1("Capital University") == "EDU")
    check("US Naval Academy -> EDU.HED", code_of("United States Naval Academy") == "EDU.HED")
    check("Christian Academy -> EDU.K12", code_of("Lincoln Christian Academy") == "EDU.K12")
    check("Academy Sports not EDU", l1("Academy Sports + Outdoors") != "EDU")
    # government
    check("Dept of Defense -> PUB.DEF", code_of("United States Department of Defense") == "PUB.DEF")
    check("Dept of Transportation -> PUB.GOV", code_of("Department of Transportation") == "PUB.GOV")
    check("NSF -> PUB", l1("National Science Foundation") == "PUB")
    check("TSA -> PUB", l1("Transportation Security Administration") == "PUB")
    check("Gates Foundation -> NPO.PHIL", code_of("Bill & Melinda Gates Foundation") == "NPO.PHIL")
    # banks that are not banks; industries that are not manufacturers
    check("Food Bank -> NPO", l1("Atlanta Community Food Bank") == "NPO")
    check("Blood Bank -> HLT", l1("Community Blood Bank") == "HLT")
    check("First National Bank -> FIN.BNK", code_of("First National Bank") == "FIN.BNK")
    check("Goodwill Industries -> NPO", l1("Goodwill Industries International") == "NPO")
    check("Acme Industries abstains", code_of("Acme Industries") is None)
    # brands caught by generic tokens
    check("State Farm not AGR", l1("State Farm") != "AGR")
    check("Family Farms -> AGR", l1("Smith Family Farms") == "AGR")
    check("Dairy Queen not AGR", l1("Dairy Queen") != "AGR")
    check("BAE Systems not TEC", l1("BAE Systems") != "TEC")
    check("Lucid Motors not CON", l1("Lucid Motors") != "CON")
    check("Equity Residential not FIN", l1("Equity Residential") != "FIN")
    check("Red Ventures not FIN", l1("Red Ventures") != "FIN")
    check("Capital One raw not FIN.ASM", code_of("Capital One") != "FIN.ASM")
    check("Capital Management -> FIN.ASM", code_of("Acme Capital Management") == "FIN.ASM")
    check("Records not MED", l1("National Archives and Records Administration") != "MED")
    check("Salon abstains", code_of("Bella Hair Salon") is None)
    # payers are not providers
    check("Health Plan -> HLT.PAYR", code_of("Blue Cross Health Plan") == "HLT.PAYR")
    check("St Mary's Hospital -> HLT.PROV.HOSP", code_of("St. Mary's Hospital") == "HLT.PROV.HOSP")


# ----------------------------------------------------------------- fusion
def test_precedence() -> None:
    print("precedence / fusion")
    a = classify.classify_company(company_id="wellsfargo", display="Wells Fargo")
    check("M1 curated wins", a.code == "FIN.BNK.COM.RET" and a.method == "curated")
    check("M1 confidence 1.0", a.confidence == 1.0)
    check("M1 per-level depth 4", set(a.per_level) == {1, 2, 3, 4})

    # curated beats a misleading name token (id present)
    a = classify.classify_company(company_id="goldman-sachs", display="Goldman Sachs Bank")
    check("curated beats name token", a.code == "FIN.BNK.INV")

    a = classify.classify_company(company_id=None, display="St Mary's Hospital")
    check("M3 name rule fires", a.code == "HLT.PROV.HOSP" and a.method == "name_rule")

    a = classify.classify_company(company_id=None, display="Riverside Real Estate Group")
    check("M3 multiword priority", T.truncate(a.code, 2) == "RE.REST" and a.confidence >= 0.9)

    a = classify.classify_company(company_id=None, display="Global Solutions Group")
    check("M3 abstains on generic words", a.method in ("unresolved", "occupation_prior"))

    a = classify.classify_company(
        company_id=None, display="Acme Co", modal_occ="51-4041", occ_coded_frac=0.9)
    check("M5 weak fallback + review", a.method == "occupation_prior" and a.needs_review)

    a = classify.classify_company(company_id=None, display="Zzxq Q")
    check("unresolved -> XOT review", a.code == "XOT" and a.needs_review)


def test_rows() -> None:
    print("row grain")
    a = classify.classify_row(
        company_canonical_id="nonorg:self_employed", company_id=None,
        company_raw=None, occupation_code="29-1141")
    check("self-employed RN -> Healthcare", T.truncate(a.code, 1) == "HLT")
    a = classify.classify_row(
        company_canonical_id="nonorg:self_employed", company_id=None,
        company_raw=None, occupation_code="15-1252")
    check("agnostic SOC abstains -> XOT", a.code == "XOT")
    a = classify.classify_row(
        company_canonical_id="id:wellsfargo", company_id="wellsfargo",
        company_raw="Wells Fargo", occupation_code=None)
    check("org row propagates company industry", a.code == "FIN.BNK.COM.RET")


# ----------------------------------------------------- occupation precision
def test_occupation_prior() -> None:
    print("occupation prior precision")
    for agnostic in ("11-1021", "13-2011", "15-1252", "41-3091", "43-4051"):
        code, conf = occupation_prior.soc_to_industry(agnostic)
        check(f"agnostic {agnostic} abstains", code is None)
    for bound, l1 in (("29-1141", "HLT"), ("25-2021", "EDU"), ("47-2111", "RE"),
                      ("35-1011", "HOS")):
        code, conf = occupation_prior.soc_to_industry(bound)
        check(f"bound {bound} -> {l1}", code is not None and T.truncate(code, 1) == l1)


# ------------------------------------------------ audit 2026-09-02 guards
def test_audit_guards() -> None:
    """Red-team H1/H3/M4 + green I1/I5: XOT carries no sector; the company-grain
    occupation prior needs real support; machine-promoted curated keys are not
    precision 1.0; the contaminated promotions are corrected or retracted."""
    print("audit guards (sector, prior support, curated provenance)")
    check("XOT has no sector", classify._unresolved().sector is None)  # noqa: SLF001
    # major group 27 (designers / PR / producers) spans every sector -> abstain
    check("27-1024 abstains", occupation_prior.soc_to_industry("27-1024")[0] is None)
    check("27-2012 abstains", occupation_prior.soc_to_industry("27-2012")[0] is None)
    # company-grain prior: one person's title is not a workforce
    code, _ = occupation_prior.company_occupation_prior("29-1141", 1.0, freq=1)
    check("freq 1 abstains", code is None)
    code, _ = occupation_prior.company_occupation_prior("29-1141", 1.0, freq=3)
    check("freq 3 fires", code is not None)
    code, _ = occupation_prior.company_occupation_prior("29", 0.9, freq=10, modal_share=0.5)
    check("modal share 0.5 abstains", code is None)
    code, _ = occupation_prior.company_occupation_prior("29", 0.9, freq=10, modal_share=0.6)
    check("2-digit pooled major fires at share 0.6", code is not None and T.truncate(code, 1) == "HLT")
    a = classify.classify_company(company_id=None, display="Acme Co",
                                  modal_occ="29", occ_coded_frac=0.9, freq=2)
    check("classify_company passes freq to the prior", a.method != "occupation_prior")
    # curated provenance
    a = classify.classify_company(company_id="wellsfargo", display="Wells Fargo")
    check("hand-curated confidence 1.0", a.confidence == 1.0)
    a = classify.classify_company(company_id="upmc", display="UPMC")
    check("promoted confidence < 1.0", a.method == "curated" and a.confidence == 0.95)
    check("consultant_66 retracted", curated.lookup("consultant_66") is None)
    check("thebeach2 retracted", curated.lookup("thebeach2") is None)
    check("integris-for-banks retracted", curated.lookup("integris-for-banks") is None)
    check("berkeley-rha retracted", curated.lookup("berkeley-rha") is None)
    check("ucsdhealth is a health system", curated.lookup("ucsdhealth") == "HLT.PROV.HOSP")
    check("uc-irvine-medical-center is a hospital",
          curated.lookup("uc-irvine-medical-center") == "HLT.PROV.HOSP")
    check("kpn is a telecom", curated.lookup("kpn") == "TEC.TELE")
    check("kentucky dept of education is state government",
          curated.lookup("kentucky-department-of-education") == "PUB.GOV.SLOC")
    # scoring: an XOT prediction is an abstention, never a false positive
    s = level_scores({"a": "XOT"}, {"a": "FIN.BNK"}, taxonomy=T)
    check("XOT scored as abstain", s["L1"]["fp"] == 0 and s["L1"]["fn"] == 1)
    # curated provenance tiers: hand > head (frontier-labeled, blind-gated) >
    # promoted (machine); every landed key reports which tier it came from
    check("hand provenance", curated.provenance("wellsfargo") == "hand")
    check("promoted provenance", curated.provenance("upmc") == "promoted")
    check("unknown provenance", curated.provenance("no-such-company") is None)
    from . import curated_head
    check("head module exports HEAD + METHOD", isinstance(curated_head.HEAD, dict)
          and isinstance(curated_head.METHOD, str))
    check("head codes valid", all(T.is_valid(c) for c in curated_head.HEAD.values()))
    for cid in curated_head.HEAD:
        check(f"head key {cid} not retracted/hand", cid not in curated.RETRACTED)
        break


def test_propagation() -> None:
    """Red-team H1/H2: propagate_to_steps must emit one row per career step
    (NULL keys and companies missing from the table included), never leak a
    dotted code into l1, and carry the prior's sector."""
    print("propagation (temp dir)")
    import tempfile
    from pathlib import Path as _Path

    import duckdb

    from . import build_industry

    with tempfile.TemporaryDirectory() as d:
        d = _Path(d)
        con = duckdb.connect()
        con.execute("""
          CREATE TABLE steps AS SELECT * FROM (VALUES
            ('p1', 0, NULL, 'experience', 'id:wellsfargo', NULL, NULL),
            ('p2', 0, NULL, 'experience', NULL, '29-1141', '29'),
            ('p3', 0, NULL, 'experience', 'nonorg:self_employed', '11-1021', '11'),
            ('p4', 0, NULL, 'experience', 'nonorg:self_employed', '55-1011', '55'),
            ('p5', 0, NULL, 'experience', 'id:missing-from-table', NULL, NULL)
          ) t(linkedin_id, experience_idx, position_idx, source_table,
              company_canonical_id, occupation_code, occupation_major_pooled)
        """)
        con.execute(f"COPY steps TO '{d / 'steps.parquet'}' (FORMAT parquet)")
        con.execute("""
          CREATE TABLE comp AS SELECT * FROM (VALUES
            ('id:wellsfargo', 'FIN.BNK.COM.RET', 'FIN', 'FIN.BNK', 'FIN.BNK.COM',
             'FIN.BNK.COM.RET', 4, 'curated', 1.0, 'private', FALSE)
          ) t(key, industry_code, l1, l2, l3, l4, depth, method, confidence,
              sector, needs_review)
        """)
        con.execute(f"COPY comp TO '{d / 'comp.parquet'}' (FORMAT parquet)")
        out = d / "step_industry.parquet"
        _path, m = build_industry.propagate_to_steps(
            steps_path=d / "steps.parquet", company_path=d / "comp.parquet", out_path=out)
        rows = {r[0]: r for r in con.execute(f"""
            SELECT linkedin_id, industry_code, l1, l2, l3, depth, method, sector
            FROM read_parquet('{out}') ORDER BY 1""").fetchall()}
        check("one output row per step", len(rows) == 5 and m["step_rows"] == 5)
        check("NULL key kept as unresolved",
              rows.get("p2") is not None and rows["p2"][2] == "HLT")
        check("nonorg prior l1 has no dot", rows["p2"][2] == "HLT" and rows["p2"][3] == "HLT.PROV")
        check("nonorg prior depth is code depth", rows["p2"][5] == 2)
        check("agnostic nonorg -> XOT, no sector",
              rows["p3"][1] == "XOT" and rows["p3"][7] is None)
        check("military prior carries public sector",
              rows["p4"][2] == "PUB" and rows["p4"][4] == "PUB.DEF.AF" and rows["p4"][7] == "public")
        check("company missing from table -> unresolved, not dropped",
              rows["p5"][1] == "XOT" and rows["p5"][6] == "unresolved")
        check("manifest counts null keys", m.get("null_key_rows") == 1)
        check("manifest counts nonorg rows", m.get("nonorg_rows") == 2)


# --------------------------------------------------------------- metrics
def test_level_scores() -> None:
    print("per-level scoring")
    gold = {"a": "FIN.BNK.COM.RET", "b": "HLT.PROV.HOSP"}
    pred = {"a": "FIN.BNK.COM.RET", "b": "FIN"}  # b right nowhere
    s = level_scores(pred, gold, taxonomy=T)
    check("L1 precision 0.5", s["L1"]["precision"] == 0.5)
    check("L1 recall 0.5", s["L1"]["recall"] == 0.5)
    # partial pred counts at the level it reaches, abstains below
    pred2 = {"a": "FIN.BNK", "b": "HLT.PROV.HOSP"}
    s2 = level_scores(pred2, gold, taxonomy=T)
    check("both correct at L2", s2["L2"]["tp"] == 2)
    check("partial a abstains at L3 (fn, not fp)", s2["L3"]["fn"] == 1 and s2["L3"]["fp"] == 0)


# --------------------------------------------------------------- llm layer
def test_llm() -> None:
    print("llm layer (offline)")
    item = {"key": "id:acme", "display": "Acme Corp",
            "titles": ["Engineer"], "descriptions": ["We build things."]}
    k1 = llm.cache_key(item, llm.MODEL_BULK)
    k2 = llm.cache_key(item, llm.MODEL_BULK)
    k3 = llm.cache_key(item, llm.MODEL_HEAD)
    check("cache_key deterministic", k1 == k2)
    check("cache_key model-sensitive", k1 != k3)
    item2 = dict(item, display="Acme Inc")
    check("cache_key evidence-sensitive", llm.cache_key(item2, llm.MODEL_BULK) != k1)
    check("invalid code rejected", llm._parse_result_text('{"code":"NOPE"}') is None)  # noqa: SLF001
    check("valid code parsed",
          (llm._parse_result_text('{"code":"FIN","confidence":"low","rationale":"x"}')  # noqa: SLF001
           or {}).get("code") == "FIN")
    # offline propose with no cache -> empty, deterministic, no network
    check("offline propose returns only cache", isinstance(llm.propose([item], dry_run=True), dict))
    params = llm._params(item, llm.MODEL_BULK)  # noqa: SLF001
    enum = params["output_config"]["format"]["schema"]["properties"]["code"]["enum"]
    check("request enum constrained", "FIN" in enum and len(enum) == len(T.all_codes()))
    check("system prompt cached", params["system"][0]["cache_control"]["type"] == "ephemeral")
    # REASON BEFORE VERDICT: rationale must be the first generated field.
    sch = T.output_json_schema()
    check("schema reason-first", sch["required"][0] == "rationale"
          and list(sch["properties"])[0] == "rationale")
    # torn trailing line (crash mid-flush) must not poison the cache load
    import tempfile
    import os as _os
    from pathlib import Path as _Path
    _orig_cache = llm.CACHE_FILE
    try:
        fd, tmp = tempfile.mkstemp(suffix=".jsonl")
        _os.close(fd)
        llm.CACHE_FILE = _Path(tmp)
        good = llm.Proposal(key="id:x", code="FIN", confidence="low",
                            rationale="r", model="m", input_hash="h1")
        llm.append_cache([good])
        llm.CACHE_FILE.write_text(llm.CACHE_FILE.read_text() + '{"key": "id:y", "co')
        loaded = llm.load_cache()
        check("torn cache line skipped", list(loaded) == ["h1"])
    finally:
        llm.CACHE_FILE.unlink(missing_ok=True)
        llm.CACHE_FILE = _orig_cache


# ----------------------------------------------------------------- jury
def test_jury() -> None:
    print("jury (hierarchical consensus)")
    # unanimous deep agreement -> full depth, agreement 1.0
    v = jury.aggregate({"a": "FIN.BNK.COM.RET", "b": "FIN.BNK.COM.RET", "c": "FIN.BNK.COM.RET"})
    check("unanimous -> full depth", v.code == "FIN.BNK.COM.RET" and v.agreement == 1.0)
    # agree at L2, split at L3 -> stop at the consensus depth (L2)
    v = jury.aggregate({"a": "FIN.BNK.COM", "b": "FIN.BNK.INV", "c": "FIN.BNK.CU"})
    check("split below L2 -> truncate to FIN.BNK", v.code == "FIN.BNK" and v.depth == 2)
    check("FIN.BNK support 3/3", v.per_level.get(2) == 1.0)
    # majority (2/3) at L1 only, third juror elsewhere -> L1 consensus
    v = jury.aggregate({"a": "FIN.BNK", "b": "FIN.ASM", "c": "TEC.SOF"})
    check("2/3 at L1 -> FIN", v.code == "FIN" and v.depth == 1 and round(v.per_level[1], 2) == 0.67)
    # total L1 disagreement -> abstain (XOT) for the review queue
    v = jury.aggregate({"a": "FIN.BNK", "b": "TEC.SOF", "c": "HLT.PROV"})
    check("3-way L1 split -> XOT abstain", v.code == "XOT" and v.is_abstention)
    # single juror degrades gracefully to that juror's path at agreement 1.0
    v = jury.aggregate({"a": "HLT.PROV.HOSP"})
    check("single juror -> its path", v.code == "HLT.PROV.HOSP" and v.n_jurors == 1)
    # empty / all-invalid panel -> abstain
    check("empty panel -> XOT", jury.aggregate({}).code == "XOT")
    check("invalid votes dropped", jury.aggregate({"a": "NOPE"}).code == "XOT")
    # tie does not descend (2/4 is not a majority)
    v = jury.aggregate({"a": "FIN.BNK", "b": "FIN.BNK", "c": "FIN.ASM", "d": "FIN.ASM"})
    check("tie at L2 stops at FIN", v.code == "FIN" and v.depth == 1)


# --------------------------------------------------- local (Ollama) backend
def test_local_llm() -> None:
    print("local jury backend (offline)")
    item = {"key": "id:acme", "display": "Acme Corp",
            "titles": ["Engineer"], "descriptions": ["We build things."]}
    # local model strings are namespaced and map to bare Ollama names
    check("local jury namespaced", all(m.startswith("ollama/") for m in local_llm.LOCAL_JURY))
    check("model-name strip", local_llm._model_name("ollama/llama3.1:8b") == "llama3.1:8b")  # noqa: SLF001
    req = local_llm.build_request(item, "ollama/llama3.1:8b")
    check("request bare model", req["model"] == "llama3.1:8b")
    check("request reason-first enum-constrained",
          req["format"]["required"][0] == "rationale"
          and len(req["format"]["properties"]["code"]["enum"]) == len(T.all_codes()))
    check("request has system+user", [m["role"] for m in req["messages"]] == ["system", "user"])
    # local + cloud jurors COEXIST: distinct cache keys, shared Proposal schema
    check("local cache_key != cloud",
          llm.cache_key(item, "ollama/llama3.1:8b") != llm.cache_key(item, llm.MODEL_BULK))
    # offline (daemon may be down OR dry_run) -> pure cache read, no exception
    check("offline local propose safe", isinstance(local_llm.propose_local([item], dry_run=True), dict))
    # cached_panel is backend-agnostic: tolerates an empty/foreign panel
    check("cached_panel returns dict", isinstance(llm.cached_panel([item]), dict))
    # upgraded panel: 3 disjoint families sized to where they run
    check("jury is 3 disjoint big families",
          local_llm.LOCAL_JURY == ("ollama/gemma3:27b", "ollama/qwen3:32b",
                                   "ollama/phi4:14b"))
    check("head curator defined", local_llm.LOCAL_HEAD == "ollama/gpt-oss:120b")
    # think flags: hybrid-thinking families get think=false (clean fast JSON);
    # everything else omits the key (Ollama rejects it on non-thinking models).
    check("qwen3 think off",
          local_llm.build_request(item, "ollama/qwen3:32b").get("think") is False)
    check("deepseek think off",
          local_llm.build_request(item, "ollama/deepseek-r1:8b").get("think") is False)
    check("gemma has no think key",
          "think" not in local_llm.build_request(item, "ollama/gemma3:27b"))
    check("gpt-oss keeps default thinking",
          "think" not in local_llm.build_request(item, "ollama/gpt-oss:120b"))

    # pool-backed firing: a fake transport proves items x models fan out across
    # hosts in ONE pool run and land in the cache via the normal Proposal path.
    from . import llm_pool as P
    import json as _json
    import tempfile as _tempfile
    import os as _os2
    from pathlib import Path as _Path2
    _orig_cache2 = llm.CACHE_FILE
    try:
        fd2, tmp2 = _tempfile.mkstemp(suffix=".jsonl")
        _os2.close(fd2)
        llm.CACHE_FILE = _Path2(tmp2)
        fired: list[tuple[str, str]] = []
        def fake_chat(h, body):
            fired.append((h.name, body["model"]))
            return {"message": {"content": _json.dumps(
                {"rationale": "test", "code": "FIN", "confidence": "low"})}}
        fake_pool = P.HostPool(
            [P.OllamaHost("a", "http://a", 1), P.OllamaHost("b", "http://b", 1)],
            fetch_tags=lambda u: (["gemma3:27b", "qwen3:32b"] if u == "http://b"
                                  else ["phi4:14b"]),
            transport=fake_chat)
        items = [{"key": "id:pooltest", "display": "Pool Test Co"}]
        out = local_llm.propose_local_panel(items, models=local_llm.LOCAL_JURY,
                                            dry_run=False, pool=fake_pool)
        check("panel fans out across hosts",
              sorted(fired) == [("a", "phi4:14b"), ("b", "gemma3:27b"), ("b", "qwen3:32b")])
        check("panel returns all jurors",
              set(out.get("id:pooltest", {})) == set(local_llm.LOCAL_JURY))
        check("votes are valid Proposals",
              all(p.code == "FIN" for p in out.get("id:pooltest", {}).values()))
    finally:
        llm.CACHE_FILE.unlink(missing_ok=True)
        llm.CACHE_FILE = _orig_cache2


# ------------------------------------------------------------ llm host pool
def test_llm_pool() -> None:
    print("llm host pool")
    from . import llm_pool as P

    # OLLAMA_HOSTS env spec: "name=url|slots,..." (slots default 1, urls rstripped)
    hs = P.hosts_from_env({"OLLAMA_HOSTS": "a=http://a:1/|3, b=http://b:2"})
    check("OLLAMA_HOSTS parsed",
          [(h.name, h.base_url, h.parallel) for h in hs]
          == [("a", "http://a:1", 3), ("b", "http://b:2", 1)])
    # legacy OLLAMA_HOST replaces the local default entry only
    hs = P.hosts_from_env({"OLLAMA_HOST": "http://gpu:11434"})
    check("OLLAMA_HOST overrides local entry",
          hs[0].name == "local" and hs[0].base_url == "http://gpu:11434"
          and hs[1].name == "framework")
    # no env -> two Ollama daemons + two batched llama-server lanes
    hs = P.hosts_from_env({})
    check("default hosts", [(h.name, h.api) for h in hs]
          == [("local", "ollama"), ("framework", "ollama"),
              ("local-srv", "llamacpp"), ("fw-srv", "llamacpp")])

    # malformed env: trailing comma ignored; missing '=' fails loudly
    hs = P.hosts_from_env({"OLLAMA_HOSTS": "a=http://a:1,"})
    check("trailing comma ignored", [h.name for h in hs] == ["a"])
    try:
        P.hosts_from_env({"OLLAMA_HOSTS": "http://a:1"})
        check("missing '=' raises", False)
    except ValueError:
        check("missing '=' raises", True)
    # scheme-less urls (Ollama's own OLLAMA_HOST convention) get http:// prefixed
    hs = P.hosts_from_env({"OLLAMA_HOST": "127.0.0.1:9999"})
    check("scheme-less OLLAMA_HOST normalized", hs[0].base_url == "http://127.0.0.1:9999")
    hs = P.hosts_from_env({"OLLAMA_HOSTS": "a=box:11434|2"})
    check("scheme-less OLLAMA_HOSTS normalized",
          hs[0].base_url == "http://box:11434" and hs[0].parallel == 2)

    # discovery: unreachable host (fetch_tags -> None) is dropped; models recorded
    tags = {"http://a:1": ["m1", "m2"], "http://b:2": None}
    pool = P.HostPool(
        [P.OllamaHost("a", "http://a:1", 1), P.OllamaHost("b", "http://b:2", 2)],
        fetch_tags=lambda u: tags[u], transport=lambda h, b: {})
    check("unreachable host dropped", [h.name for h in pool.hosts] == ["a"])
    check("serves() uses discovered tags",
          [h.name for h in pool.serves("m1")] == ["a"] and pool.serves("zzz") == [])

    # ---- llama-server (llama.cpp) hosts: api segment, discovery, body adapters
    hs = P.hosts_from_env({"OLLAMA_HOSTS": "fast=http://gpu:8080|16|llamacpp, x=http://o:11434|2"})
    check("api segment parsed",
          (hs[0].api, hs[0].parallel) == ("llamacpp", 16) and hs[1].api == "ollama")
    pool = P.HostPool(
        [P.OllamaHost("srv", "http://s:8080", 4, api="llamacpp"),
         P.OllamaHost("oll", "http://o:11434", 1)],
        fetch_tags=lambda u: ["m-ollama"],
        fetch_openai=lambda u: ["bulk-q4"],
        transport=lambda h, b: {})
    check("llamacpp discovery via /v1/models",
          [h.name for h in pool.serves("bulk-q4")] == ["srv"]
          and [h.name for h in pool.serves("m-ollama")] == ["oll"])
    # body adapter: Ollama-format request -> OpenAI chat completions
    body = {"model": "bulk-q4", "messages": [{"role": "system", "content": "s"},
                                             {"role": "user", "content": "u"}],
            "stream": False, "format": {"type": "object"},
            "options": {"temperature": 0, "seed": 7, "num_ctx": 8192},
            "think": False}
    ob = P._openai_body(body)  # noqa: SLF001
    check("openai body adapted",
          ob["model"] == "bulk-q4" and ob["messages"] == body["messages"]
          and ob["temperature"] == 0 and ob["seed"] == 7
          and ob["response_format"]["json_schema"]["schema"] == {"type": "object"}
          and ob["cache_prompt"] is True and "think" not in ob and "format" not in ob)
    # response adapter: OpenAI shape -> the Ollama shape callers parse
    oresp = {"choices": [{"message": {"content": '{"code":"FIN"}'}}],
             "usage": {"completion_tokens": 42, "prompt_tokens": 3000},
             "timings": {"predicted_ms": 500.0, "prompt_ms": 120.0}}
    ar = P._from_openai(oresp)  # noqa: SLF001
    check("openai response adapted",
          ar["message"]["content"] == '{"code":"FIN"}' and ar["eval_count"] == 42
          and ar["eval_duration"] == 500_000_000)

    import time as _time

    # affinity + work stealing: "big" only on b; "small" on both. Host a is
    # slowed so b provably steals "small" after draining "big".
    runs: list[tuple[str, str]] = []   # (host, model) per executed unit
    def rec(h, body):
        runs.append((h.name, body["model"]))
        _time.sleep(0.005 if h.name == "a" else 0)
        return {"message": {"content": "ok"}}
    tag2 = {"http://a": ["small"], "http://b": ["small", "big"]}
    pool = P.HostPool([P.OllamaHost("a", "http://a", 1), P.OllamaHost("b", "http://b", 1)],
                      fetch_tags=lambda u: tag2[u], transport=rec)
    got: list[object] = []
    units = [P.WorkUnit("big", {"model": "big"}, meta=i) for i in range(5)] \
          + [P.WorkUnit("small", {"model": "small"}, meta=5 + i) for i in range(40)]
    res = pool.run(units, lambda meta, r: got.append(meta), progress_every=10**9)
    check("pool: all units done", res == {"done": 45, "failed": 0, "skipped": 0}
          and sorted(got) == list(range(45)))
    check("pool: big pinned to b", {h for h, m in runs if m == "big"} == {"b"})
    check("pool: small stolen by both", {h for h, m in runs if m == "small"} == {"a", "b"})

    # unit for a model no live host serves -> skipped, not hung
    res = pool.run([P.WorkUnit("nowhere", {"model": "nowhere"})], lambda m, r: None)
    check("pool: unservable skipped", res == {"done": 0, "failed": 0, "skipped": 1})

    # same-host retry: first call raises, second succeeds
    calls = {"n": 0}
    def flaky(h, body):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient")
        return {"message": {"content": "ok"}}
    pool = P.HostPool([P.OllamaHost("a", "http://a", 1)],
                      fetch_tags=lambda u: ["m"], transport=flaky)
    res = pool.run([P.WorkUnit("m", {"model": "m"})], lambda m, r: None)
    check("pool: same-host retry", res["done"] == 1 and calls["n"] == 2)

    # cross-host rescue + mark-down: a always fails, b always works. All 10
    # units must finish on b, and a must be marked down after 5 consecutive
    # failures (bounding its wasted calls to <= 2 attempts x 5 units).
    a_calls = {"n": 0}
    def ab(h, body):
        if h.name == "a":
            a_calls["n"] += 1
            raise OSError("a is broken")
        return {"message": {"content": "ok"}}
    tag3 = {"http://a": ["m"], "http://b": ["m"]}
    pool = P.HostPool([P.OllamaHost("a", "http://a", 1), P.OllamaHost("b", "http://b", 1)],
                      fetch_tags=lambda u: tag3[u], transport=ab)
    res = pool.run([P.WorkUnit("m", {"model": "m"}, meta=i) for i in range(10)],
                   lambda m, r: None)
    check("pool: failing host's work rescued", res["done"] == 10 and res["failed"] == 0)
    check("pool: host marked down bounds damage", a_calls["n"] <= 10)

    # every host fails -> all units fail, run still terminates
    def dead(h, body):
        raise OSError("all dead")
    pool = P.HostPool([P.OllamaHost("a", "http://a", 1)],
                      fetch_tags=lambda u: ["m"], transport=dead)
    res = pool.run([P.WorkUnit("m", {"model": "m"}, meta=i) for i in range(3)],
                   lambda m, r: None)
    check("pool: total failure terminates", res["done"] == 0 and res["failed"] == 3)

    # a raising on_result must not hang the run or lose accounting
    boom = {"n": 0}
    def bad_cb(meta, r):
        boom["n"] += 1
        raise OSError("disk full")
    pool = P.HostPool([P.OllamaHost("a", "http://a", 1)],
                      fetch_tags=lambda u: ["m"],
                      transport=lambda h, b: {"message": {"content": "ok"}})
    res = pool.run([P.WorkUnit("m", {"model": "m"}, meta=i) for i in range(3)],
                   bad_cb)
    check("pool: raising callback terminates", res["done"] == 3 and boom["n"] == 3)

    # a failed unit must NOT be re-taken by the host that failed it: a is broken
    # and sticky on "m"; b is healthy but busy on "other" first. The unit must
    # end up done (on b), not burned by a.
    def ab2(h, body):
        if h.name == "a":
            raise OSError("a is broken")
        _time.sleep(0.002)
        return {"message": {"content": "ok"}}
    tag4 = {"http://a": ["m"], "http://b": ["m", "other"]}
    pool = P.HostPool([P.OllamaHost("a", "http://a", 1), P.OllamaHost("b", "http://b", 1)],
                      fetch_tags=lambda u: tag4[u], transport=ab2)
    units = [P.WorkUnit("other", {"model": "other"}, meta=i) for i in range(5)] \
          + [P.WorkUnit("m", {"model": "m"}, meta=100 + i) for i in range(2)]
    res = pool.run(units, lambda m, r: None)
    check("pool: tried host never re-takes", res["done"] == 7 and res["failed"] == 0)


# ------------------------------------------------------- residual gold set
def test_gold_residual() -> None:
    print("residual gold set")
    check("non-empty", len(GOLD_RESIDUAL) >= 40)
    bad = [g.key for g in GOLD_RESIDUAL if not T.is_valid(g.expected)]
    check("all expected codes valid", bad == [], str(bad))
    keys = [g.key for g in GOLD_RESIDUAL]
    check("keys unique", len(keys) == len(set(keys)))
    check("keys are canonical-id shaped",
          all(g.key.startswith(("id:", "raw:", "nonorg:")) for g in GOLD_RESIDUAL))


# ---------------------------------------------------------------- head gate
def test_head_gate() -> None:
    """The blind-gate scorer: L1/L2/exact agreement between the frontier head
    labels and an independent reviewer, abstentions excluded, invalid reviewer
    codes reported, and the 0.90 L1 bar enforced by `passes`."""
    from . import head_gate
    key = [
        {"n": 1, "company_id": "a", "display": "A", "head_code": "HLT.PROV.HOSP"},
        {"n": 2, "company_id": "b", "display": "B", "head_code": "FIN.BNK"},
        {"n": 3, "company_id": "c", "display": "C", "head_code": "MED.PUBL"},
        {"n": 4, "company_id": "d", "display": "D", "head_code": "NPO"},
        {"n": 5, "company_id": "e", "display": "E", "head_code": "TEC.SOF"},
    ]
    review = [
        {"n": 1, "code": "HLT.PROV.HOSP"},   # exact
        {"n": 2, "code": "FIN.INS"},         # L1 agree, L2 disagree
        {"n": 3, "code": "NPO"},             # L1 disagree
        {"n": 4, "code": "SKIP"},            # abstain -> not scored
        {"n": 5, "code": "TEC.NOPE"},        # invalid reviewer code
    ]
    r = head_gate.score(key, review)
    check("gate: abstentions excluded", r["n_scored"] == 3, str(r))
    check("gate: invalid reviewer codes reported", r["invalid"] == [(5, "TEC.NOPE")], str(r["invalid"]))
    check("gate: L1 agreement", abs(r["l1_agree"] - 2 / 3) < 1e-9, str(r["l1_agree"]))
    check("gate: L2 agreement counts only pairs with depth >= 2 on both sides",
          r["l2_n"] == 2 and r["l2_agree"] == 0.5, f"{r['l2_n']} {r['l2_agree']}")
    check("gate: exact agreement", abs(r["exact_agree"] - 1 / 3) < 1e-9, str(r["exact_agree"]))
    check("gate: disagreements listed with both codes",
          [(d["n"], d["head_code"], d["review_code"]) for d in r["disagreements"]]
          == [(2, "FIN.BNK", "FIN.INS"), (3, "MED.PUBL", "NPO")], str(r["disagreements"]))
    check("gate: bar is 0.90 L1", not head_gate.passes(r) and head_gate.passes({**r, "l1_agree": 0.9}))
    check("gate: unmatched review rows are an error",
          _raises(lambda: head_gate.score(key, [{"n": 99, "code": "NPO"}])))


def test_head_tools() -> None:
    """The head writer: SKIP dropped, hand wins silently, invalid codes and
    retracted keys rejected, module text carries provenance comments."""
    from collections import OrderedDict
    from . import head_tools
    rows = [
        {"company_id": "a", "code": "HLT.PROV.HOSP", "display": 'A "Corp"', "freq": 10},
        {"company_id": "b", "code": "SKIP", "display": "B", "freq": 9},
        {"company_id": "c", "code": "NOPE.X", "display": "C", "freq": 8},
        {"company_id": "d", "code": "NPO", "display": "D", "freq": 7},
        {"company_id": "e", "code": "FIN.BNK", "display": "E", "freq": 6},
    ]
    entries, bad = head_tools.build_entries(rows, hand={"e"}, retracted=frozenset({"d"}))
    check("head_tools: keeps only valid, non-hand, non-retracted, non-SKIP", list(entries) == ["a"], str(list(entries)))
    check("head_tools: rejects invalid code and retracted key",
          bad == [("c", "NOPE.X", "invalid code"), ("d", "NPO", "retracted")], str(bad))
    text = head_tools.render(OrderedDict(entries), "HEADER\n")
    check("head_tools: rendered module has provenance comment with escaped display",
          text == 'HEADER\nHEAD: dict[str, str] = {\n    "a": "HLT.PROV.HOSP",  # A \\"Corp\\" (rows=10)\n}\n', repr(text))
    ns: dict = {}
    exec(text.replace("HEADER\n", ""), ns)  # noqa: S102 -- the rendered table must be importable Python
    check("head_tools: rendered table round-trips", ns["HEAD"] == {"a": "HLT.PROV.HOSP"})


def _raises(fn) -> bool:
    try:
        fn()
    except (KeyError, ValueError):
        return True
    return False


def main() -> None:
    for t in (test_taxonomy, test_codes_resolve, test_name_rule_precision,
              test_precedence, test_rows,
              test_occupation_prior, test_audit_guards, test_propagation,
              test_level_scores, test_llm, test_jury,
              test_local_llm, test_llm_pool, test_gold_residual, test_head_gate, test_head_tools):
        t()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}):")
        for f in _failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print("all industry tests passed")


if __name__ == "__main__":
    main()
