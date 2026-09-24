"""D3 (LLM zero-shot) and M4 (cluster-then-map) need a language model. Both
run through the local `local_delegate` MCP tool from the orchestrating session,
so this module only prepares the prompts and ingests the answers.

    uv run python -m archetype_methods.bench_llm prepare-d3      -> results/llm/d3_batch_*.txt
    uv run python -m archetype_methods.bench_llm ingest-d3 TIER  -> reads results/llm/d3_TIER_batch_*.json
    uv run python -m archetype_methods.bench_llm prepare-m4 NAME -> results/llm/m4_NAME.txt
    uv run python -m archetype_methods.bench_llm ingest-m4 NAME  -> reads results/llm/m4_NAME.json
"""

from __future__ import annotations

import csv
import json
import sys

import numpy as np

from . import common as C
from . import framework as F
from . import gold as G

LLM = C.RESULTS / "llm"
BATCH = 50


def framework_prompt() -> str:
    lines = ["You classify job titles into a framework of nine career skill archetypes.",
             "Archetypes (key: label. orientation. representative roles):"]
    for a in F.ARCHETYPES:
        roles = sorted({r for rs in a.pathways.values() for r in rs})
        lines.append(f"- {a.key}: {a.label}. {a.orientation} Roles: {'; '.join(roles[:40])}.")
    lines.append("- none: work outside all nine orientations (skilled trades, transportation, "
                 "production, clinical healthcare practice, uniformed service) or a placeholder "
                 "title that names no work (owner, founder, unemployed, intern, member).")
    lines.append("Classify the WORK the title names, not the industry. A functional manager "
                 "belongs to the function (a sales manager is connectors, an accounting manager "
                 "is stewards); a general manager, project manager or administrator is leaders.")
    return "\n".join(lines)


def prepare_d3():
    LLM.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader((C.GOLD / "sample.csv").open()))
    head = framework_prompt()
    for b in range(0, len(rows), BATCH):
        chunk = rows[b:b + BATCH]
        items = "\n".join(f"{i + b}\t{r['role_display']}\t(raw title: {r['role_text'].split(' ', 1)[-1][:60]}; "
                          f"SOC {r['soc_detail'] or r['soc_major'] or 'unknown'})"
                          for i, r in enumerate(chunk))
        (LLM / f"d3_batch_{b // BATCH}.txt").write_text(
            head + "\n\nFor each line (index, title, hints) return primary archetype key and an "
            "optional secondary key when the role is genuinely hybrid, else null.\n\n" + items)
    print("wrote", (len(rows) + BATCH - 1) // BATCH, "batches")


def ingest_d3(tier: str):
    from . import metrics as M
    rows = list(csv.DictReader((C.GOLD / "sample.csv").open()))
    out = {}
    for p in sorted(LLM.glob(f"d3_{tier}_batch_*.json")):
        for item in json.loads(p.read_text()):
            i = int(item["index"])
            lab = (item.get("primary") or "abstain").strip().lower()
            if lab not in F.KEYS and lab != F.NONE_KEY:
                lab = "abstain"
            out[rows[i]["role_canonical"]] = (lab, 1.0)
    s = M.score(out, name=f"D3_llm_{tier}")
    print(f"D3_llm_{tier}: n={len(out)} cov={s['coverage']:.2f} strict={s['acc_strict']:.3f} "
          f"lenient={s['acc_lenient']:.3f} F1={s['macro_f1']:.3f} by_fit={s['acc_by_fit']}")
    path = C.RESULTS / "llm.json"
    cur = json.loads(path.read_text()) if path.exists() else {}
    cur[f"D3_llm_{tier}"] = s
    C.write_json(cur, path)
    np.save(LLM / f"d3_{tier}_assignment.npy", out, allow_pickle=True)


def prepare_m4(name: str):
    ind = json.loads((C.RESULTS / "inductive.json").read_text())
    ev = ind[name]
    head = framework_prompt()
    t = C.load_roles()
    disp = dict(zip(t["role_canonical"].to_pylist(), t["role_display"].to_pylist()))
    items = "\n".join(f"{c}\t{'; '.join(disp.get(r, r) for r in v['top'])}" for c, v in ev["clusters"].items())
    (LLM / f"m4_{name}.txt").write_text(
        head + "\n\nEach line is a CLUSTER of job titles found by unsupervised clustering "
        "(cluster id, then its most common titles). Give each cluster the single archetype "
        "key that best describes the shared work, or 'none' if the cluster's work is outside "
        "the framework, or 'mixed' if the cluster mixes two or more archetypes so badly that "
        "no single key is honest.\n\n" + items)
    print("wrote", LLM / f"m4_{name}.txt")


def ingest_m4(name: str):
    from . import metrics as M
    assign = np.load(C.RESULTS / "inductive_assignments.npy", allow_pickle=True).item()[name]
    cmap = {int(item["cluster"]): (item["archetype"] or "").strip().lower()
            for item in json.loads((LLM / f"m4_{name}.json").read_text())}
    out = {}
    for rc, c in assign.items():
        lab = cmap.get(int(c), "abstain")
        if lab not in F.KEYS and lab != F.NONE_KEY:
            lab = "abstain"
        out[rc] = (lab, 0.5)
    s = M.score(out, name=f"M4_cluster_map_{name}")
    from collections import Counter
    s["cluster_labels"] = dict(Counter(cmap.values()))
    print(f"M4 {name}: cov={s['coverage']:.2f} strict={s['acc_strict']:.3f} lenient={s['acc_lenient']:.3f} "
          f"assigned={s['acc_strict_assigned']:.3f} F1={s['macro_f1']:.3f} labels={s['cluster_labels']}")
    path = C.RESULTS / "llm.json"
    cur = json.loads(path.read_text()) if path.exists() else {}
    cur[f"M4_cluster_map_{name}"] = s
    C.write_json(cur, path)
    np.save(LLM / f"m4_{name}_assignment.npy", out, allow_pickle=True)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "prepare-d3":
        prepare_d3()
    elif cmd == "ingest-d3":
        ingest_d3(sys.argv[2])
    elif cmd == "prepare-m4":
        prepare_m4(sys.argv[2])
    elif cmd == "ingest-m4":
        ingest_m4(sys.argv[2])
