"""Score the blind gate sample for the frontier-labeled curated head.

    uv run python -m industry.head_gate industry/results/head_gate_review.jsonl

`industry/results/head_gate_blind.jsonl` is 100 head companies (50 drawn
row-weighted, 50 uniform) with the evidence the labeler saw and no code.  A
second reader (the owner, or a Gemini/Claude pass that was not shown the head
labels) writes `code` per row into a review file with the same `n` values;
`SKIP` or an empty code abstains.  This scorer joins the review to
`head_gate_key.jsonl`, reports L1 / L2 / exact agreement over the scored rows,
lists every disagreement, and enforces the bar the head tier's 0.95
confidence assumes: L1 agreement >= 0.90 (`L1_BAR`).  Anything under that is
a reason to retract the disagreeing codes into `curated.RETRACTED`, not to
ship the tier.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import taxonomy as T

L1_BAR = 0.90
KEY_PATH = Path(__file__).parent / "results" / "head_gate_key.jsonl"

_ABSTAIN = {"", "SKIP", None}


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def score(key: list[dict], review: list[dict]) -> dict:
    """Agreement between the head labels (`key`) and a reviewer (`review`),
    joined on `n`.  Raises KeyError for review rows with no key row."""
    by_n = {int(k["n"]): k for k in key}
    n_scored = l1_hit = l2_n = l2_hit = exact = 0
    invalid: list[tuple[int, str]] = []
    disagreements: list[dict] = []
    for r in review:
        n = int(r["n"])
        k = by_n[n]  # KeyError on purpose: an unmatched review row is a broken join
        code = (r.get("code") or "").strip().upper() or None
        if code in _ABSTAIN:
            continue
        if not T.is_valid(code):
            invalid.append((n, code))
            continue
        head = k["head_code"]
        n_scored += 1
        if T.truncate(head, 1) == T.truncate(code, 1):
            l1_hit += 1
        else:
            disagreements.append({"n": n, "company_id": k["company_id"], "display": k.get("display", ""),
                                  "head_code": head, "review_code": code, "level": 1})
            continue
        if T.level_of(head) >= 2 and T.level_of(code) >= 2:
            l2_n += 1
            if T.truncate(head, 2) == T.truncate(code, 2):
                l2_hit += 1
            else:
                disagreements.append({"n": n, "company_id": k["company_id"], "display": k.get("display", ""),
                                      "head_code": head, "review_code": code, "level": 2})
        if head == code:
            exact += 1
    return {
        "n_key": len(key),
        "n_review": len(review),
        "n_scored": n_scored,
        "invalid": invalid,
        "l1_agree": l1_hit / n_scored if n_scored else 0.0,
        "l2_n": l2_n,
        "l2_agree": l2_hit / l2_n if l2_n else 0.0,
        "exact_agree": exact / n_scored if n_scored else 0.0,
        "disagreements": disagreements,
    }


def passes(result: dict) -> bool:
    return result["l1_agree"] >= L1_BAR


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    result = score(_read_jsonl(KEY_PATH), _read_jsonl(Path(argv[0])))
    print(f"scored {result['n_scored']} of {result['n_review']} review rows "
          f"({len(result['invalid'])} invalid codes, "
          f"{result['n_review'] - result['n_scored'] - len(result['invalid'])} abstained)")
    print(f"L1 agreement {result['l1_agree']:.3f}   L2 agreement {result['l2_agree']:.3f} "
          f"(n={result['l2_n']})   exact {result['exact_agree']:.3f}   bar L1 >= {L1_BAR}")
    for n, code in result["invalid"]:
        print(f"  invalid code at n={n}: {code}")
    for d in result["disagreements"]:
        print(f"  L{d['level']} n={d['n']:>3} {d['company_id']:<45} head={d['head_code']:<18} review={d['review_code']}")
    ok = passes(result)
    print("GATE PASS" if ok else "GATE FAIL -- retract the L1 disagreements before shipping the head tier")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
