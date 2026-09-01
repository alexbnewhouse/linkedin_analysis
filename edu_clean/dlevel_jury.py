"""LLM jury for degree-LEVEL coding of the ~720k rows where degree_level is NULL.
Two-model unanimity panel on the llamacpp lanes, mirroring edu_clean/cip_llm.py.
Context (100% computed, absent fields omitted): the degree cell as written, the
field cell, the modal school, and the typical program duration -- exactly the
evidence that lets a reader decide "business administration, 4 years, a
university" = bachelor, which duration ALONE cannot (that lever was rejected).

Propose-only: votes -> append-only JSONL cache; `run_dlevel_jury merge` writes a
NEW mappings parquet; nothing else is touched.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import duckdb

from edu_clean import dlevel_taxonomy as T

ROOT = Path(__file__).resolve().parent.parent
EDUCATION = ROOT / "normalized" / "education.parquet"
CACHE_FILE = Path(__file__).resolve().parent / "results" / "dlevel_votes.jsonl"

# Two disjoint jurors, BOTH served locally on the 5080 by the sm_120 build (the
# only build that serves the strict-JSON-schema grammar -- the Framework lanes
# return HTTP 000 on grammar requests, and the 30B bulk-moe won't fit alongside a
# second model in 16GB). qwen3-4b (Qwen) + llama3.1-8b (Llama) is a valid
# cross-architecture panel; the degree-level jury calibrates its own gate.
JURY = ("llamacpp/qwen3-4b-q4", "llamacpp/llama31-8b")
HOSTS_ENV = (
    "local5080=http://127.0.0.1:8090|8|llamacpp,"
    "local8b=http://127.0.0.1:8092|8|llamacpp"
)
_THINK_OFF_PREFIXES = ("qwen3", "bulk-moe", "deepseek-r1")
NUM_CTX = 4096


def _catalog() -> str:
    return "\n".join(f"  {c} - {T.LEVELS[c]}" for c in sorted(T.LEVELS))


_SYSTEM = f"""You determine the LEVEL of ONE academic credential from the evidence.

Valid codes:
{_catalog()}
  {T.ABSTAIN} - the text names no degree, or the level cannot be determined

Rules:
1. Decide the credential LEVEL, not the field. "Bachelor of Science in Nursing" is 4 (bachelor); "psychology" with a 4-year duration at a university is most likely 4 (bachelor).
2. Use ALL evidence together. Program duration is a strong cue: ~4 years => bachelor (4), ~2 years => associate (3) or master's (6) depending on the credential words, ~1 year or less => certificate (2), 5+ years with doctoral words => doctorate (7). Duration alone is NOT decisive -- weigh it with the degree/field words and the institution.
3. Abbreviations: MBA/MFA/MSW/MA/MS => 6; PhD/JD/MD/EdD/DBA => 7; BA/BS/BFA => 4; AA/AS => 3.
4. Answer {T.ABSTAIN} when the text names NO credential ("study abroad", "exchange program", "minor", "continuing education", a bare GPA or honor) or when master's vs doctorate genuinely cannot be told -- prefer 5 only if it is clearly graduate but the tier is unclear.
5. Do not invent a level from the field name alone: "biology" with no duration and no degree words is {T.ABSTAIN}, not a guess.
6. Answer in the fixed JSON schema: a rationale of at most two short sentences, then the code, then your confidence.
"""


def evidence_text(item: dict) -> str:
    parts = []
    if item.get("degree_text"):
        parts.append(f"Degree line as written: {item['degree_text'][:120]}")
    if item.get("field_text"):
        parts.append(f"Field of study line: {item['field_text'][:120]}")
    if item.get("modal_school"):
        parts.append(f"Institution: {item['modal_school'][:80]}")
    if item.get("median_years") is not None:
        parts.append(f"Typical program duration: about {item['median_years']} year(s).")
    if item.get("n_rows"):
        parts.append(f"Occurrences in the dataset: {item['n_rows']} education rows.")
    if not parts:
        parts.append("(no evidence)")
    return "\n".join(parts)


def cache_key(item: dict, model: str) -> str:
    payload = json.dumps({
        "evidence": evidence_text(item), "model": model,
        "prompt_version": T.PROMPT_VERSION, "schema_version": T.SCHEMA_VERSION,
        "n_codes": len(T.all_codes()),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class Proposal:
    key: str
    code: str
    confidence: str
    rationale: str
    model: str
    input_hash: str

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


def load_cache() -> dict[str, Proposal]:
    out: dict[str, Proposal] = {}
    if not CACHE_FILE.exists():
        return out
    for line in CACHE_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            p = Proposal(**json.loads(line))
        except (json.JSONDecodeError, TypeError):
            continue
        out[p.input_hash] = p
    return out


def append_cache(proposals: list[Proposal]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_FILE.open("a", encoding="utf-8") as fh:
        for p in proposals:
            fh.write(p.to_json() + "\n")


def votes_by_key(items, jurors=JURY) -> dict[str, dict[str, str]]:
    cache = load_cache()
    out: dict[str, dict[str, str]] = {}
    for it in items:
        for m in jurors:
            p = cache.get(cache_key(it, m))
            if p is not None:
                out.setdefault(it["key"], {})[m] = p.code
    return out


def unanimous_accept(codes: list[str]) -> str | None:
    if len(codes) != len(JURY):
        return None
    first = codes[0]
    if first == T.ABSTAIN or not T.is_valid(first):
        return None
    return first if all(c == first for c in codes) else None


# --- candidate / gold construction ----------------------------------------
_KEY = "lower(trim(coalesce(degree_raw,''))) || '||' || lower(trim(coalesce(field_raw,'')))"


def _rows(where: str, limit: int | None):
    con = duckdb.connect(); con.execute("PRAGMA threads=8")
    lim = f"LIMIT {limit}" if limit else ""
    rows = con.execute(f"""
      SELECT {_KEY} AS key,
             any_value(degree_raw) AS degree_text,
             any_value(field_raw) AS field_text,
             mode(school_raw) AS modal_school,
             median(CASE WHEN end_year BETWEEN start_year AND start_year+12
                         THEN end_year - start_year END) AS median_years,
             count(*) AS n_rows
      FROM read_parquet('{EDUCATION}')
      WHERE {where} AND NOT is_duplicate
        AND (degree_raw IS NOT NULL OR field_raw IS NOT NULL)
      GROUP BY 1 ORDER BY n_rows DESC, key ASC {lim}
    """).fetchall()
    con.close()
    cols = ("key", "degree_text", "field_text", "modal_school", "median_years", "n_rows")
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        if d["median_years"] is not None:
            d["median_years"] = round(float(d["median_years"]), 1)
        out.append(d)
    return out


def candidates(limit: int) -> list[dict]:
    return _rows("degree_level IS NULL", limit)


def gold(sample: int, dominance: float = 0.9) -> list[dict]:
    """Known-level keys with >= `dominance` share on one level -> the true label.
    Frequency-stratified by taking the top `sample` by row count."""
    con = duckdb.connect(); con.execute("PRAGMA threads=8")
    rows = con.execute(f"""
      WITH k AS (
        SELECT {_KEY} AS key, degree_level AS lvl, count(*) c
        FROM read_parquet('{EDUCATION}')
        WHERE degree_level IS NOT NULL AND NOT is_duplicate
          AND (degree_raw IS NOT NULL OR field_raw IS NOT NULL)
        GROUP BY 1, 2
      ),
      tot AS (SELECT key, sum(c) n, max(c) top FROM k GROUP BY 1),
      dom AS (
        SELECT k.key, k.lvl AS gold_lvl, tot.n
        FROM k JOIN tot USING (key)
        WHERE k.c = tot.top AND tot.top >= {dominance} * tot.n
      )
      SELECT d.key, d.gold_lvl, d.n,
             any_value(e.degree_raw) degree_text, any_value(e.field_raw) field_text,
             mode(e.school_raw) modal_school,
             median(CASE WHEN e.end_year BETWEEN e.start_year AND e.start_year+12
                         THEN e.end_year - e.start_year END) median_years
      FROM dom d JOIN read_parquet('{EDUCATION}') e
        ON {_KEY.replace('degree_raw','e.degree_raw').replace('field_raw','e.field_raw')} = d.key
      WHERE NOT e.is_duplicate
      GROUP BY 1, 2, 3 ORDER BY d.n DESC LIMIT {sample}
    """).fetchall()
    con.close()
    cols = ("key", "gold_lvl", "n_rows", "degree_text", "field_text",
            "modal_school", "median_years")
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d["gold_code"] = str(int(d["gold_lvl"]))
        if d["median_years"] is not None:
            d["median_years"] = round(float(d["median_years"]), 1)
        out.append(d)
    return out


# --- firing (copied mechanics from cip_llm) --------------------------------
def _model_name(model: str) -> str:
    return model.split("/", 1)[1] if "/" in model else model


def build_request(item: dict, model: str, *, schema: dict | None = None) -> dict:
    bare = _model_name(model)
    body = {
        "model": bare,
        "messages": [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": evidence_text(item)}],
        "stream": False,
        "format": schema if schema is not None else T.output_json_schema(),
        "keep_alive": "10m",
        "options": {"temperature": 0, "seed": 7, "num_ctx": NUM_CTX},
    }
    if bare.startswith(_THINK_OFF_PREFIXES):
        body["think"] = False
    return body


def make_pool():
    os.environ["OLLAMA_HOSTS"] = HOSTS_ENV
    from industry import llm_pool
    return llm_pool.HostPool()


def fire(items, jurors=JURY, *, execute: bool = False) -> dict:
    cache = load_cache()
    pending = [(it, m) for m in jurors for it in items
               if cache_key(it, m) not in cache]
    plan = {"items": len(items), "jurors": len(jurors), "pending_units": len(pending),
            "cached_units": len(items) * len(jurors) - len(pending)}
    if not execute or not pending:
        return {**plan, "done": 0, "failed": 0, "skipped": 0}

    from industry import llm_pool
    pool = make_pool()
    if not pool.hosts:
        print("[dlevel] no llamacpp lane reachable -- nothing fired")
        return {**plan, "done": 0, "failed": 0, "skipped": len(pending)}
    print(f"[dlevel] firing {len(pending):,} units across {[h.name for h in pool.hosts]}")
    schema = T.output_json_schema()
    units = [llm_pool.WorkUnit(model=_model_name(m), body=build_request(it, m, schema=schema),
                               meta=(it, m)) for it, m in pending]
    buf: list[Proposal] = []
    pf = [0]

    def on_result(meta, resp):
        it, m = meta
        try:
            d = json.loads((resp.get("message") or {}).get("content", ""))
        except (json.JSONDecodeError, TypeError):
            pf[0] += 1; return
        code = d.get("code")
        if not T.is_valid(code):
            pf[0] += 1; return
        buf.append(Proposal(key=it["key"], code=code, confidence=d.get("confidence", "low"),
                            rationale=str(d.get("rationale", ""))[:400], model=m,
                            input_hash=cache_key(it, m)))
        if len(buf) >= 50:
            append_cache(buf); buf.clear()

    stats = pool.run(units, on_result)
    if buf:
        append_cache(buf)
    print(f"[dlevel] pool: {stats['done']:,} ok, {stats['failed']:,} failed; parse_fail {pf[0]}")
    return {**plan, **stats, "parse_failures": pf[0]}
