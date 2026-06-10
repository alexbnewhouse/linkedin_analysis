"""Final career-value canonicalizer (production-leaning hybrid).

Precedence per field (highest-precision layer that fires decides; weaker layers
only extend coverage on what's left):

  company: placeholder bucket  ->  company_id  ->  exact name->id crosswalk
           ->  guarded typo tail (to an id if possible)  ->  raw
  title:   seniority/role parse (level | compact base)  ->  guarded typo tail
           ->  raw
  description: normalization only (NFKC, control-char strip, whitespace) -- it
           is essentially unique free text, not an entity-resolution field.

Embeddings are deliberately not in the default path: the benchmark (run_eval)
showed they hold no usable precision margin on the seniority/role boundary
(titles) or sibling organizations (company), exactly as in education. Every
output carries a ``method`` tag and ``confidence`` so the low-confidence band can
feed a human review queue.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field as dc_field

from . import approach_a_rules as A
from . import approach_b_fuzzy as B
from . import occupation as O
from .common import Result, normalize, timer

_WS = re.compile(r"\s+")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class DetailedResult:
    name: str
    field: str
    mapping: dict[str, str]
    runtime_s: float
    method: dict[str, str] = dc_field(default_factory=dict)
    confidence: dict[str, float] = dc_field(default_factory=dict)
    extra: dict = dc_field(default_factory=dict)
    # auxiliary per-value output columns (column name -> {value: cell}), e.g.
    # title's seniority_rank_token / role_display. Written alongside the mapping
    # by build_normalized; absent for fields that have none.
    aux: dict[str, dict] = dc_field(default_factory=dict)

    def n_in(self) -> int:
        return len(self.mapping)

    def n_out(self) -> int:
        return len(set(self.mapping.values()))

    def reduction(self) -> float:
        return 1.0 - self.n_out() / self.n_in() if self.mapping else 0.0

    def as_result(self) -> Result:
        return Result(self.name, self.field, self.mapping, self.runtime_s, self.extra)


def safe_norm(text: str | None) -> str:
    """ASCII matching key with a Unicode-preserving fallback, so multilingual
    labels (~1% of companies, ~0.5% of titles) don't collapse to empty."""
    norm = normalize(text or "")
    if norm:
        return norm
    s = unicodedata.normalize("NFKC", text or "").strip().lower()
    return _WS.sub(" ", s)


def _row_pct_by_method(vocab: list[tuple], method: dict[str, str]) -> dict[str, float]:
    rows: dict[str, int] = defaultdict(int)
    total = 0
    for value, freq, *_ in vocab:
        total += freq
        rows[method[value]] += freq
    return {k: round(100 * v / total, 1) for k, v in sorted(rows.items(), key=lambda x: -x[1])}


# ------------------------------------------------------------ description
def normalize_description(text: str | None) -> str | None:
    """Clean a free-text description: NFKC, strip control chars, collapse
    whitespace, trim. Returns None for empty results. (Use the parsed
    ``description`` column, which is already HTML-stripped vs description_html.)"""
    if text is None:
        return None
    s = unicodedata.normalize("NFKC", text)
    s = s.replace("’", "'").replace("‘", "'").replace(" ", " ")
    s = _CTRL.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s or None


# ------------------------------------------------------------ company
def canon_company_value(
    value: str | None,
    *,
    company_id: str | None = None,
    name_crosswalk: dict[str, str] | None = None,
) -> tuple[str, str, float]:
    """Canonicalize one company row, preferring the row's actual company_id."""
    norm = normalize(value)
    bucket = A._placeholder_bucket(norm)  # noqa: SLF001
    if bucket:
        return f"nonorg:{bucket}", "placeholder", 1.0
    if company_id:
        return f"id:{A.canonical_company_id(company_id)}", "company_id", 1.0
    if norm and name_crosswalk and norm in name_crosswalk:
        recovered = A.canonical_company_id(name_crosswalk[norm])
        return f"id:{recovered}", "name_crosswalk", 0.97
    return f"raw:{safe_norm(value)}", "raw", 0.5


def canon_company(vocab: list[tuple]) -> DetailedResult:
    with timer() as t:
        crosswalk = A._name_to_id_crosswalk(vocab)  # noqa: SLF001 (reuse benchmarked)
        mapping: dict[str, str] = {}
        method: dict[str, str] = {}
        conf: dict[str, float] = {}
        for value, _freq, modal_id in vocab:
            cid, m, c = canon_company_value(
                value, company_id=modal_id, name_crosswalk=crosswalk
            )
            mapping[value] = cid
            method[value] = m
            conf[value] = c

        # guarded typo tail: merge a no-id raw spelling onto an id-bearing twin
        b_map = B.run("company", vocab).mapping
        for value, *_ in vocab:
            if method[value] != "raw":
                continue
            rep = b_map[value]
            if rep != value and mapping.get(rep, "").startswith("id:"):
                mapping[value] = mapping[rep]
                method[value], conf[value] = "typo_to_id", 0.9
            elif rep != value:
                mapping[value] = f"raw:{safe_norm(rep)}"
                method[value], conf[value] = "typo", 0.85

    return DetailedResult(
        "final_hybrid", "company", mapping, t.elapsed, method, conf,
        extra={"row_pct_by_method": _row_pct_by_method(vocab, method)},
    )


# ------------------------------------------------------- functional cluster
def canon_functional_cluster_value(
    *,
    company: str | None,
    title: str | None,
    company_id: str | None = None,
    description: str | None = None,
    onet_index: tuple[dict, dict] | None = None,
) -> tuple[str, str, float]:
    """Resolve the row-level functional/industry cluster (SOC major group).

    This is the axis the self-employment population is clustered on. It composes
    the SOC backbone with the four meaning-extraction recs (qualifier recovery,
    title-keyword, personal-brand company trade, and free-text description
    inference); see ``se_cluster`` / ``se_description`` and the ``run_self_employed``
    + ``run_se_description`` evaluators. Pass ``onet_index = occupation.load_onet()[:2]``
    once and reuse it across rows -- building it per call is wasteful.
    """
    from . import se_cluster as C

    if onet_index is None:
        by_norm, by_tokens, _ = O.load_onet()
    else:
        by_norm, by_tokens = onet_index
    emp, _m, _c = A.resolve_employment_type(company=company, title=title, company_id=company_id)
    return C.resolve_functional_cluster(
        company=company, title=title, by_norm=by_norm, by_tokens=by_tokens,
        company_id=company_id, employment_type=emp, description=description,
    )


# ------------------------------------------------------------ employment type
def canon_employment_type_value(
    *,
    company: str | None,
    title: str | None,
    company_id: str | None = None,
) -> tuple[str, str, float]:
    """Resolve the row-level employment-status axis.

    This deliberately does not replace ``canon_company_value``. The company axis
    answers "which organization, if any?"; this axis answers "what class of work
    relationship?" and is computed from both company and title.
    """
    return A.resolve_employment_type(
        company=company,
        title=title,
        company_id=company_id,
    )


def canon_employment_type(rows: list[tuple]) -> DetailedResult:
    """Canonicalize row-shaped inputs.

    Expected row forms are ``((company, title), freq[, company_id])`` or
    ``(company, title, freq[, company_id])``. The tuple key form lets callers use
    this with the existing ``DetailedResult`` mapping contract without inventing
    synthetic strings.
    """
    with timer() as t:
        mapping: dict[tuple[str | None, str | None], str] = {}
        method: dict[tuple[str | None, str | None], str] = {}
        conf: dict[tuple[str | None, str | None], float] = {}
        method_rows: dict[str, int] = defaultdict(int)
        total = 0
        for row in rows:
            if row and isinstance(row[0], tuple):
                key = row[0]
                company, title = key
                freq = row[1] if len(row) > 1 else 1
                company_id = row[2] if len(row) > 2 else None
            else:
                company, title = row[0], row[1]
                key = (company, title)
                freq = row[2] if len(row) > 2 else 1
                company_id = row[3] if len(row) > 3 else None
            emp, m, c = canon_employment_type_value(
                company=company,
                title=title,
                company_id=company_id,
            )
            mapping[key] = emp
            method[key] = m
            conf[key] = c
            method_rows[m] += freq
            total += freq
    row_pct = {
        k: round(100 * v / total, 1)
        for k, v in sorted(method_rows.items(), key=lambda x: -x[1])
    } if total else {}
    return DetailedResult(
        "final_hybrid", "employment_type", mapping, t.elapsed, method, conf,
        extra={"row_pct_by_method": row_pct},
    )


# ------------------------------------------------------------ title
def canon_title(vocab: list[tuple]) -> DetailedResult:
    with timer() as t:
        mapping: dict[str, str] = {}
        method: dict[str, str] = {}
        conf: dict[str, float] = {}
        # aux axes (finding 2/5): rank tokens + per-base display candidates
        rank_tok: dict[str, str] = {}
        best_plain: dict[str, tuple[int, str]] = {}  # compact base -> (freq, level-free value)
        best_any: dict[str, tuple[int, str]] = {}    # compact base -> (freq, any value)
        for row in vocab:
            value = row[0]
            freq = row[1] if len(row) > 1 else 1
            rank_tok[value] = A.seniority_rank_tokens(value)
            lvl, base = A.parse_title(value)
            if base:
                # compact the sorted base so "Co-Founder" == "Cofounder" while
                # the level signature keeps seniorities distinct.
                compact = base.replace(" ", "")
                mapping[value] = f"title:{lvl}|{compact}"
                method[value], conf[value] = ("title_leveled" if lvl else "title_base"), 1.0
                if compact not in best_any or freq > best_any[compact][0]:
                    best_any[compact] = (freq, value)
                if not lvl and (compact not in best_plain or freq > best_plain[compact][0]):
                    best_plain[compact] = (freq, value)
            else:
                mapping[value] = f"raw:{safe_norm(value)}"
                method[value], conf[value] = "raw", 0.5

        # guarded typo tail for the residual raw values
        b_map = B.run("title", vocab).mapping
        for value, *_ in vocab:
            if method[value] != "raw":
                continue
            rep = b_map[value]
            if rep != value and mapping.get(rep, "").startswith("title:"):
                mapping[value] = mapping[rep]
                method[value], conf[value] = "typo_to_title", 0.9
            elif rep != value:
                mapping[value] = f"raw:{safe_norm(rep)}"
                method[value], conf[value] = "typo", 0.85

        # role_display (finding 5): one human-readable label per compact base --
        # the modal LEVEL-FREE raw spelling ("Software Engineer" for base
        # 'engineersoftware'), else the original-order de-leveled base of the
        # modal spelling. NULL for raw canonicals (no parsed role identity).
        display: dict[str, str | None] = {}
        for value, cid in mapping.items():
            if not cid.startswith("title:"):
                display[value] = None
                continue
            compact = cid.split("|", 1)[1]
            pick = best_plain.get(compact)
            if pick is not None:
                display[value] = pick[1]
            else:
                fallback = best_any.get(compact)
                display[value] = A.title_display_base(fallback[1] if fallback else value)

    return DetailedResult(
        "final_hybrid", "title", mapping, t.elapsed, method, conf,
        extra={"row_pct_by_method": _row_pct_by_method(vocab, method)},
        aux={"seniority_rank_token": rank_tok, "role_display": display},
    )


# ------------------------------------------------------------ occupation
def canon_occupation(vocab: list[tuple]) -> DetailedResult:
    """Deterministic O*NET-SOC axis (precision backbone). The embedding-anchored
    proposer (approach_c.run_anchored_occupation) extends coverage into the
    review queue but is intentionally NOT in the default production path."""
    with timer() as t:
        mapping, method = O.canon_occupation(vocab)
        conf = {v: (1.0 if m.startswith("onet") else 0.5) for v, m in method.items()}
    return DetailedResult(
        "final_hybrid", "occupation", mapping, t.elapsed, method, conf,
        extra={"row_pct_by_method": _row_pct_by_method(vocab, method)},
    )


def run(field_name: str, vocab: list[tuple]) -> DetailedResult:
    if field_name == "company":
        return canon_company(vocab)
    if field_name == "employment_type":
        return canon_employment_type(vocab)
    if field_name == "title":
        return canon_title(vocab)
    if field_name == "occupation":
        return canon_occupation(vocab)
    raise ValueError(field_name)
