"""Data for the interactive archetype map demo.

    uv run --group embed python -m archetype_methods.demo_data layout   -> results/demo/layout.json + LLM batches
    uv run python -m archetype_methods.demo_data ingest                 -> results/demo/roles.json

Takes the N most-held titles in the universe, lays them out in 2-D with t-SNE
on [title embedding | description-document embedding], and labels them with
the 27B zero-shot reader (D3) via the same batch files as bench_llm. Only
titles, holder counts, coordinates, and labels leave the machine; no profile
text is included in the output.
"""

from __future__ import annotations

import json
import sys

import numpy as np
from sklearn.manifold import TSNE
from sklearn.preprocessing import normalize

from . import common as C
from . import framework as F
from . import m_inductive as I
from .bench_llm import framework_prompt

N = 2000
DEMO = C.RESULTS / "demo"
LLM = C.RESULTS / "llm"
BATCH = 50


def layout():
    t = C.load_roles()
    roles_all = t["role_canonical"].to_pylist()
    X = I.role_text_embeddings(t)
    # skip bare placeholders so the map is about work
    skip = {"retired", "unemployed", "student", "intern", "volunteer", "member", "various", "temporarypositions"}
    keep = [i for i, r in enumerate(roles_all) if r not in skip][:N]
    droles, Xt = [roles_all[i] for i in keep], X[keep]
    dr, Xd = I.build_role_docs(t)
    dpos = {r: i for i, r in enumerate(dr)}
    Xdoc = np.stack([Xd[dpos[r]] if r in dpos else Xt[j] for j, r in enumerate(droles)])
    Z = normalize(np.hstack([Xt, Xdoc]))
    with C.Timer("tsne"):
        Y = TSNE(2, perplexity=30, init="pca", random_state=0, metric="cosine").fit_transform(Z)
    Y = (Y - Y.min(0)) / (Y.max(0) - Y.min(0))
    disp = dict(zip(roles_all, t["role_display"].to_pylist()))
    npers = dict(zip(roles_all, t["n_persons"].to_pylist()))
    soc = dict(zip(roles_all, t["soc_major"].to_pylist()))
    rows = [{"id": r, "title": disp[r], "n": int(npers[r]), "x": round(float(Y[j, 0]), 4),
             "y": round(float(Y[j, 1]), 4), "soc": C.SOC_MAJOR_LABEL.get(soc[r] or "", "")}
            for j, r in enumerate(droles)]
    DEMO.mkdir(parents=True, exist_ok=True)
    (DEMO / "layout.json").write_text(json.dumps(rows))
    head = framework_prompt()
    for b in range(0, len(rows), BATCH):
        chunk = rows[b:b + BATCH]
        items = "\n".join(f"{b + i}\t{r['title']}\t(SOC group: {r['soc'] or 'unknown'})" for i, r in enumerate(chunk))
        (LLM / f"demo_batch_{b // BATCH}.txt").write_text(
            head + "\n\nFor each line (index, title, hint) return primary archetype key and an optional "
            "secondary key when the role is genuinely hybrid, else null.\n\n" + items)
    print(len(rows), "roles;", (len(rows) + BATCH - 1) // BATCH, "batches")


def ingest():
    rows = json.loads((DEMO / "layout.json").read_text())
    for p in sorted(LLM.glob("demo_deep_batch_*.json")):
        for item in json.loads(p.read_text()):
            r = rows[int(item["index"])]
            r["a"] = item["primary"] if item["primary"] in F.KEYS or item["primary"] == F.NONE_KEY else F.NONE_KEY
            r["b"] = item.get("secondary") or None
    missing = [r["title"] for r in rows if "a" not in r]
    print("labeled by the reader", len(rows) - len(missing), "; filled from M3 classifier", len(missing))
    m3 = np.load(C.RESULTS / "mixed_assignments.npy", allow_pickle=True).item()["M3_classifier"]
    for r in rows:
        if "a" not in r:
            r["a"] = m3.get(r["id"], (F.NONE_KEY, 0))[0]
            r["b"] = None
            r["src"] = "m3"
    (DEMO / "roles.json").write_text(json.dumps(rows, separators=(",", ":")))
    from collections import Counter
    print(Counter(r["a"] for r in rows).most_common())


if __name__ == "__main__":
    {"layout": layout, "ingest": ingest}[sys.argv[1]]()
