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
    import tempfile, os as _os
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
    # no env -> the two default hosts
    hs = P.hosts_from_env({})
    check("default hosts", [h.name for h in hs] == ["local", "framework"])

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


def main() -> None:
    for t in (test_taxonomy, test_codes_resolve, test_precedence, test_rows,
              test_occupation_prior, test_level_scores, test_llm, test_jury,
              test_local_llm, test_llm_pool, test_gold_residual):
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
