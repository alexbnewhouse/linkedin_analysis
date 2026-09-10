"""Benchmark the headless Claude Code jury on the SOC role tail.

    uv run python -m career_clean.headless_bench run      # ~40 calls, writes results
    uv run python -m career_clean.headless_bench report   # extrapolate to N strings

Design under test: Haiku 4.5 + Sonnet 5 as voters (batched B strings per
call), Opus on their disagreements, every vote cached per string in
results/headless_votes.jsonl (append-only, keyed by evidence + model snapshot
+ prompt version), every call logged with tokens, USD and wall time.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import duckdb

from career_clean import run_soc_jury as J
from career_clean import soc_anchors as A
from career_clean import soc_candidates as SC
from career_clean import soc_llm as L
from career_clean import soc_taxonomy as T
from cleanlib.headless_claude import HeadlessError, call

VOTES = SC.RESULTS / "headless_votes.jsonl"
CALLS = SC.RESULTS / "headless_bench_calls.jsonl"
OUT = SC.RESULTS / "headless_bench.json"
BATCH_VERSION = "batched_v1"
MODELS = {"haiku": "haiku", "sonnet": "sonnet", "opus": "opus"}

_SYSTEM = L._SYSTEM.replace(
    "You classify ONE job role into exactly one US SOC 2018 major group.",
    "You classify EACH job role below into exactly one US SOC 2018 major group. "
    "Items are independent; judge each on its own evidence.") + (
    "\n7. Return one vote per item, in order, with the item number i copied exactly.\n"
    "8. Deliver the votes ONLY through the structured output; never write them as prose "
    "or a code block first.\n")


def schema(n: int) -> dict:
    return {"type": "object",
            "properties": {"votes": {"type": "array", "minItems": n, "maxItems": n,
                "items": {"type": "object", "properties": {
                    "i": {"type": "integer"},
                    "rationale": {"type": "string", "maxLength": 160},
                    "code": {"type": "string", "enum": T.all_codes()},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]}},
                    "required": ["i", "rationale", "code", "confidence"],
                    "additionalProperties": False}}},
            "required": ["votes"], "additionalProperties": False}


def user_text(items: list[dict]) -> str:
    return "\n\n".join(f"### Item {k + 1}\n{L.evidence_text(it)}" for k, it in enumerate(items))


def vote_key(item: dict, model_alias: str) -> str:
    payload = json.dumps({"evidence": L.evidence_text(item), "model": model_alias,
                          "prompt_version": T.PROMPT_VERSION, "batch": BATCH_VERSION,
                          "n_codes": len(T.all_codes())}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def fire_batch(model_alias: str, items: list[dict], run: str) -> dict:
    try:
        r = call(MODELS[model_alias], _SYSTEM, user_text(items), schema(len(items)))
    except HeadlessError as e:
        print(f"   retry ({e})", flush=True)
        try:
            r = call(MODELS[model_alias], _SYSTEM, user_text(items), schema(len(items)), max_turns=6)
        except HeadlessError as e2:
            rec = {"run": run, "model": None, "alias": model_alias, "n_items": len(items), "parsed": 0,
                   "duration_s": 0, "cost_usd": 0, "failed": str(e2)[:200], "ts": time.time()}
            with CALLS.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            return {"votes": {}, "call": {**rec, "tok_input": 0, "tok_output": 0}}
    votes = {}
    for v in (r["output"] or {}).get("votes", []):
        i = v.get("i")
        if isinstance(i, int) and 1 <= i <= len(items) and T.is_valid(v.get("code")):
            votes[i - 1] = v
    with VOTES.open("a") as f:
        for k, it in enumerate(items):
            v = votes.get(k)
            if v:
                f.write(json.dumps({"key": it["role_canonical"], "code": v["code"],
                                    "confidence": v["confidence"], "rationale": v["rationale"][:160],
                                    "model": r["model"], "alias": model_alias,
                                    "input_hash": vote_key(it, model_alias), "run": run},
                                   ensure_ascii=False) + "\n")
    rec = {"run": run, "model": r["model"], "alias": model_alias, "n_items": len(items),
           "parsed": len(votes), "duration_s": r["duration_s"], "cost_usd": r["cost_usd"],
           **{f"tok_{k}": v for k, v in r["usage"].items()},
           "side_calls": r["side_calls"], "num_turns": r["num_turns"], "ts": time.time()}
    with CALLS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return {"votes": {items[k]["role_canonical"]: v["code"] for k, v in votes.items()}, "call": rec}


def fire(model_alias: str, items: list[dict], batch: int, conc: int, run: str) -> dict:
    batches = [items[i:i + batch] for i in range(0, len(items), batch)]
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=conc) as ex:
        results = list(ex.map(lambda b: fire_batch(model_alias, b, run), batches))
    wall = time.monotonic() - t0
    votes, calls = {}, []
    for res in results:
        votes.update(res["votes"]); calls.append(res["call"])
    n = len(items)
    calls = [c for c in calls if not c.get("failed")] or calls
    stats = {"run": run, "model": calls[0]["model"] if calls else None, "alias": model_alias,
             "strings": n, "batch": batch, "concurrency": conc, "calls": len(calls),
             "parsed": sum(c["parsed"] for c in calls),
             "wall_s": round(wall, 1), "call_s_mean": round(sum(c["duration_s"] for c in calls) / len(calls), 1),
             "tok_in": sum(c["tok_input"] or 0 for c in calls), "tok_out": sum(c["tok_output"] or 0 for c in calls),
             "cost_usd": round(sum(c["cost_usd"] or 0 for c in calls), 4)}
    stats["per_string"] = {"tok_in": round(stats["tok_in"] / n, 1), "tok_out": round(stats["tok_out"] / n, 1),
                           "cost_usd": round(stats["cost_usd"] / n, 5), "wall_s": round(wall / n, 3)}
    print(f"[{run}] {model_alias} n={n} B={batch} c={conc}: {len(calls)} calls, wall {wall:.0f}s, "
          f"${stats['cost_usd']:.3f}, {stats['per_string']['tok_in']:.0f}/{stats['per_string']['tok_out']:.0f} tok/str, "
          f"parsed {stats['parsed']}/{n}", flush=True)
    return {"stats": stats, "votes": votes}


def load_tail(offset: int, n: int) -> list[dict]:
    con = duckdb.connect()
    rows = con.execute(f"""
      SELECT {', '.join(J._ITEM_COLS)} FROM read_parquet('{SC.CANDIDATES}') c
      WHERE role_canonical NOT IN (SELECT role_canonical FROM read_parquet('{J.MERGE_OUT}'))
      ORDER BY n_steps DESC, role_canonical ASC LIMIT {n * 2} OFFSET {offset}""").fetchall()
    items = [it for it in J._rows_to_items(rows) if not J._non_occupation(it["role_display"])][:n]
    A.attach_anchors(items)
    return items


def load_gold(n: int) -> list[dict]:
    con = duckdb.connect()
    rows = con.execute(f"""
      SELECT {', '.join(J._ITEM_COLS)}, gold_major, tercile FROM read_parquet('{SC.GOLD}')
      WHERE in_sample ORDER BY hash(role_canonical || 'hb1') LIMIT {n}""").fetchall()
    items = J._rows_to_items(rows, J._ITEM_COLS + ("gold_major", "tercile"))
    A.attach_anchors(items)
    return items


def cmd_run() -> None:
    out = {"generated": date.today().isoformat(), "runs": [], "band": {}, "gold": {}}
    a = load_tail(0, 200); b = load_tail(400, 200); c = load_tail(800, 200)
    print(f"tail slices: {len(a)}/{len(b)}/{len(c)} strings", flush=True)
    r1 = fire("haiku", a, 25, 1, "R1 haiku A B25 c1"); out["runs"].append(r1["stats"])
    r3 = fire("sonnet", a, 25, 1, "R3 sonnet A B25 c1"); out["runs"].append(r3["stats"])
    # disagreement band on A
    hv, sv = r1["votes"], r3["votes"]
    band, unan, abst, miss = [], 0, 0, 0
    for it in a:
        k = it["role_canonical"]; h, s = hv.get(k), sv.get(k)
        if h is None or s is None:
            miss += 1; continue
        if h == s and h != T.ABSTAIN:
            unan += 1
        elif h == T.ABSTAIN and s == T.ABSTAIN:
            abst += 1
        else:
            band.append(it)
    out["band"] = {"n": len(a), "unanimous": unan, "both_abstain": abst, "band": len(band),
                   "unparsed": miss, "band_share": round(len(band) / len(a), 3)}
    print(f"band on A: {out['band']}", flush=True)
    if band:
        r4 = fire("opus", band, 25, 1, "R4 opus band(A) B25 c1"); out["runs"].append(r4["stats"])
        ov = r4["votes"]
        resolved = sum(1 for it in band if ov.get(it["role_canonical"]) not in (None, T.ABSTAIN)
                       and ov[it["role_canonical"]] in (hv.get(it["role_canonical"]), sv.get(it["role_canonical"])))
        out["band"]["opus_resolved_2of3"] = resolved
    r5 = fire("haiku", c, 25, 4, "R5 haiku C B25 c4"); out["runs"].append(r5["stats"])
    r8 = fire("sonnet", b, 25, 4, "R8 sonnet B B25 c4"); out["runs"].append(r8["stats"])
    g = load_gold(100)
    r6 = fire("haiku", g, 25, 2, "R6 haiku gold B25 c2"); out["runs"].append(r6["stats"])
    r7 = fire("sonnet", g, 25, 2, "R7 sonnet gold B25 c2"); out["runs"].append(r7["stats"])
    for name, votes in (("haiku", r6["votes"]), ("sonnet", r7["votes"])):
        voted = [(votes.get(it["role_canonical"]), it["gold_major"]) for it in g
                 if votes.get(it["role_canonical"]) not in (None, T.ABSTAIN)]
        out["gold"][name] = {"n": len(g), "voted": len(voted),
                             "accuracy": round(sum(1 for v, gm in voted if v == gm) / len(voted), 3) if voted else None}
    both = [(r6["votes"].get(it["role_canonical"]), r7["votes"].get(it["role_canonical"]), it["gold_major"]) for it in g]
    un = [(h, gm) for h, s, gm in both if h and s and h == s and h != T.ABSTAIN]
    out["gold"]["unanimous"] = {"n": len(un), "accuracy": round(sum(1 for h, gm in un if h == gm) / len(un), 3) if un else None,
                                "share": round(len(un) / len(g), 3)}
    print(f"gold: {out['gold']}", flush=True)
    OUT.write_text(json.dumps(out, indent=1))
    print(f"wrote {OUT}", flush=True)


def cmd_report() -> None:
    out = json.loads(OUT.read_text())
    runs = {r["run"]: r for r in out["runs"]}
    band = out["band"]["band_share"]
    con = duckdb.connect()
    tail_strings = con.execute(f"""SELECT count(*) FROM read_parquet('{SC.CANDIDATES}')
      WHERE role_canonical NOT IN (SELECT role_canonical FROM read_parquet('{J.MERGE_OUT}'))""").fetchone()[0]
    def per(alias, prefer=None):
        rs = [r for r in out["runs"] if r["alias"] == alias and (prefer is None or prefer in r["run"])]
        n = sum(r["strings"] for r in rs)
        return {"cost": sum(r["cost_usd"] for r in rs) / n, "call_s": sum(r["call_s_mean"] * r["calls"] for r in rs) / sum(r["calls"] for r in rs),
                "batch": rs[0]["batch"], "tok_in": sum(r["tok_in"] for r in rs) / n, "tok_out": sum(r["tok_out"] for r in rs) / n}
    h, s, o = per("haiku", "B25"), per("sonnet"), per("opus") if any(r["alias"] == "opus" for r in out["runs"]) else None
    c4 = runs.get("R5 haiku C B25 c4"); c1 = runs.get("R1 haiku A B25 c1")
    speedup = (c1["wall_s"] / c4["wall_s"]) if c1 and c4 else 1.0
    print(f"tail strings now uncoded: {tail_strings:,}; band share {band:.1%}; c4 speedup {speedup:.2f}x")
    print(f"{'N strings':>10} {'cost voters':>12} {'cost opus':>10} {'total $':>9} {'hours c=1':>10} {'hours c=4':>10} {'tokens':>12}")
    rep = {"tail_strings": tail_strings, "band_share": band, "speedup_c4": round(speedup, 2), "rows": []}
    for N in (5000, 25000, 100000, tail_strings):
        cv = N * (h["cost"] + s["cost"]); co = N * band * (o["cost"] if o else 0)
        calls = N / h["batch"] * 2 + N * band / (o["batch"] if o else 25)
        secs = N / h["batch"] * h["call_s"] + N / s["batch"] * s["call_s"] + (N * band / o["batch"] * o["call_s"] if o else 0)
        toks = N * (h["tok_in"] + h["tok_out"] + s["tok_in"] + s["tok_out"]) + (N * band * (o["tok_in"] + o["tok_out"]) if o else 0)
        row = {"N": N, "cost_voters": round(cv, 2), "cost_opus": round(co, 2), "total_usd": round(cv + co, 2),
               "calls": int(calls), "hours_c1": round(secs / 3600, 2), "hours_c4": round(secs / 3600 / speedup, 2), "tokens": int(toks)}
        rep["rows"].append(row)
        print(f"{N:>10,} {cv:>12.2f} {co:>10.2f} {cv+co:>9.2f} {row['hours_c1']:>10.2f} {row['hours_c4']:>10.2f} {int(toks):>12,}")
    out["extrapolation"] = rep
    OUT.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    {"run": cmd_run, "report": cmd_report}[sys.argv[1] if len(sys.argv) > 1 else "run"]()
