"""Score a sample's labels: precision per annotator, Cohen's kappa between annotators.

    uv run python -m coding.score imputed_bachelor              # every labels file for the sample
    uv run python -m coding.score imputed_bachelor alex reviewer

Prints strict and lenient precision (the gate reads the STRICT number against the bar
recorded in the notes) and, for every pair of annotators, kappa plus the disagreements.
"""
from __future__ import annotations

import json
import sys

from coding import common as C


def score(sample: str, annotators: list[str] | None = None) -> dict:
    s = C.SAMPLES[sample]
    if not annotators:
        annotators = sorted(p.name.split(".")[1] for p in C.LABELS_DIR.glob(f"{sample}.*.jsonl"))
    labels = {a: C.read_labels(C.label_path(sample, a)) for a in annotators}
    out = {"sample": sample, "annotators": {}, "pairs": []}
    for a, lab in labels.items():
        out["annotators"][a] = C.precision(lab, s.positive)
    for i, a in enumerate(annotators):
        for b in annotators[i + 1:]:
            k = C.cohen_kappa(labels[a], labels[b])
            out["pairs"].append({"a": a, "b": b, **k})
    return out


def main() -> None:
    r = score(sys.argv[1], sys.argv[2:] or None)
    for a, p in r["annotators"].items():
        st = f"{p['strict']:.3f}" if p["strict"] is not None else "n/a"
        le = f"{p['lenient']:.3f}" if p["lenient"] is not None else "n/a"
        print(f"{r['sample']} / {a}: n={p['n']} pass={p['positive']} unsure={p['unsure']} "
              f"strict={st} lenient={le}")
    for pr in r["pairs"]:
        kp = f"{pr['kappa']:.3f}" if pr["kappa"] is not None else "n/a"
        print(f"  {pr['a']} vs {pr['b']}: n={pr['n']} agreement={pr['agreement']} kappa={kp}")
        for d in pr["disagreements"][:40]:
            print(f"    {d['id']}: {pr['a']}={d['a']} {pr['b']}={d['b']}")
    print(json.dumps({k: v for k, v in r.items() if k != "pairs"}, indent=1))


if __name__ == "__main__":
    main()
