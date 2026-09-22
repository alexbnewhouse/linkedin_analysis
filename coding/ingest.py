"""Convert a Label Studio JSON export (or a two-column CSV) into a labels file.

    uv run python -m coding.ingest imputed_bachelor alex export.json
    uv run python -m coding.ingest imputed_bachelor alex labels.csv   # columns: id,label[,note]

Writes coding/labels/<sample>.<annotator>.jsonl. Label Studio export: the project's
"Export > JSON" file; the first non-cancelled annotation per task is used.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from coding import common as C


def parse_label_studio(path: Path) -> list[dict]:
    tasks = json.loads(path.read_text())
    out = []
    for t in tasks:
        tid = t.get("data", {}).get("id")
        anns = [a for a in t.get("annotations", []) if not a.get("was_cancelled")]
        if tid is None or not anns:
            continue
        label = None
        note = ""
        for r in anns[0].get("result", []):
            if r.get("from_name") == "label":
                ch = r.get("value", {}).get("choices") or []
                label = ch[0] if ch else None
            elif r.get("from_name") == "note":
                tx = r.get("value", {}).get("text") or []
                note = tx[0] if tx else ""
        if label:
            out.append({"id": str(tid), "label": label, "note": note})
    return out


def parse_csv(path: Path) -> list[dict]:
    out = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("id") and row.get("label"):
                out.append({"id": str(row["id"]), "label": row["label"].strip(),
                            "note": (row.get("note") or "").strip()})
    return out


def main() -> None:
    sample, annotator, src = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    labels = parse_csv(src) if src.suffix.lower() == ".csv" else parse_label_studio(src)
    allowed = set(C.SAMPLES[sample].labels)
    bad = [d for d in labels if d["label"] not in allowed]
    assert not bad, f"labels outside {sorted(allowed)}: {bad[:5]}"
    dest = C.label_path(sample, annotator)
    C.write_labels(dest, labels)
    print(f"wrote {dest.relative_to(C.ROOT)} ({len(labels)} labels)")


if __name__ == "__main__":
    main()
