"""Human coding of gold / blind samples: registry, label-file format, scoring math.

Every blind sample drawn by a propose-only tier is a JSONL file: an optional first
line ``{"_header": true, "sample": ..., "rubric": ..., "labels": [...]}`` followed by one
row per item with an ``id`` and the display fields. Labels from any annotator (a person
in Label Studio, or a review subagent) live in ``coding/labels/<sample>.<annotator>.jsonl``
as ``{"id": ..., "label": ..., "note": ...}`` so precision and inter-annotator agreement
are computed the same way for everyone.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS_DIR = ROOT / "coding" / "labels"
LS_DIR = ROOT / "coding" / "label_studio"
DEFAULT_LABELS = ("pass", "fail", "unsure")


@dataclass(frozen=True)
class Sample:
    name: str
    path: Path
    question: str
    fields: tuple[str, ...]          # shown to the coder, in this order
    labels: tuple[str, ...] = DEFAULT_LABELS
    positive: str = "pass"           # the label that counts toward precision


SAMPLES: dict[str, Sample] = {
    "imputed_bachelor": Sample(
        "imputed_bachelor", ROOT / "edu_clean" / "results" / "imputed_bachelor_sample.jsonl",
        "Is this row plausibly a bachelor's degree (completed or in progress) at a "
        "bachelor's-granting institution?",
        ("school_raw", "degree_raw", "field_raw", "description", "start_year", "end_year",
         "cip2_pooled", "field_group")),
    "comajors": Sample(
        "comajors", ROOT / "edu_clean" / "results" / "comajors_sample.jsonl",
        "Does the field string name two distinct fields (major + major, or major + minor), "
        "and is each CIP code right for its component?",
        ("field_raw", "components", "primary_cip", "secondary_cip", "minor_cip", "cip2_pooled",
         "marker_class")),
    "family": Sample(
        "family", ROOT / "career_clean" / "results" / "family_sample.jsonl",
        "Is the assigned SOC major group right for this job title at this employer?",
        ("title_raw", "company_raw", "industry_l1", "title_family", "title_seniority9",
         "soc_major", "soc_major_label")),
    "overrides": Sample(
        "overrides", ROOT / "career_clean" / "results" / "override_sample.jsonl",
        "Is the override occupation code right for this title at this employer?",
        ("title_raw", "company_raw", "industry_l1", "industry_l2", "reason",
         "occupation_code_before", "occupation_code_override", "occupation_label")),
}


def label_path(sample: str, annotator: str) -> Path:
    return LABELS_DIR / f"{sample}.{annotator}.jsonl"


def read_sample(sample: Sample) -> tuple[dict, list[dict]]:
    header: dict = {}
    rows: list[dict] = []
    with sample.path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("_header"):
                header = d
            else:
                rows.append(d)
    return header, rows


def read_labels(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                d = json.loads(line)
                out[str(d["id"])] = d
    return out


def write_labels(path: Path, labels: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for d in labels:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")


def precision(labels: dict[str, dict], positive: str = "pass") -> dict:
    """strict = positive / all labeled (unsure counts against); lenient = positive /
    (positive + fail), unsure excluded."""
    vals = [d["label"] for d in labels.values()]
    n = len(vals)
    pos = sum(v == positive for v in vals)
    unsure = sum(v == "unsure" for v in vals)
    decided = n - unsure
    return {"n": n, "positive": pos, "unsure": unsure,
            "strict": pos / n if n else None,
            "lenient": pos / decided if decided else None}


def cohen_kappa(a: dict[str, dict], b: dict[str, dict]) -> dict:
    """Cohen's kappa on the ids both annotators labeled."""
    ids = sorted(set(a) & set(b))
    n = len(ids)
    if n == 0:
        return {"n": 0, "kappa": None, "agreement": None, "disagreements": []}
    la = [a[i]["label"] for i in ids]
    lb = [b[i]["label"] for i in ids]
    cats = sorted(set(la) | set(lb))
    po = sum(x == y for x, y in zip(la, lb)) / n
    pe = sum((la.count(c) / n) * (lb.count(c) / n) for c in cats)
    kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
    dis = [{"id": i, "a": a[i]["label"], "b": b[i]["label"]} for i in ids if a[i]["label"] != b[i]["label"]]
    return {"n": n, "kappa": kappa, "agreement": po, "disagreements": dis}
