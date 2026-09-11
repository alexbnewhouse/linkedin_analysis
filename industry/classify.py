"""The fusion / arbitration engine (INDUSTRY_PLAN §3.8).

Each method emits a candidate ``(code, depth, confidence)``. This composes them,
highest precision first, and emits the DEEPEST node the corroborating evidence
supports -- a path truncated to the supported depth, with a per-level confidence,
NOT a forced L4 leaf. Precedence:

    M1 curated company_id        (P~=1.0, often L3/L4)   -> spine
    M3 company-name lexical rule (high, L2/L3)           -> spine if no M1
    M5 occupation prior          (weak, L1/L2)           -> corroborate, or
                                                            shallow fallback only
    nothing                      -> XOT (Other/Unknown) at L1, review queue

The LLM (M6) is deliberately NOT consulted here: it is propose-only and is merged
as a review-queue candidate by ``build_industry``, never overwriting this
deterministic answer (matches the repo's precision-first contract).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field

from . import curated, name_rules, occupation_prior
from . import taxonomy as T

# Per-method confidences for the deterministic spine.
_CONF_CURATED = 1.0
_CONF_PROMOTED = 0.95  # machine-promoted entries: jury agreement band, not 1.0
_CONF_NAME_MULTIWORD = 0.9
_CONF_NAME_TOKEN = 0.82
_AGREE_BONUS = 0.05  # weak prior corroborates the spine's L1


@dataclass
class IndustryAssignment:
    code: str            # deepest supported taxonomy node (may be partial / XOT)
    depth: int           # 1..4
    method: str          # curated | name_rule | occupation_prior | unresolved
    confidence: float    # overall
    sector: str | None   # private | public | nonprofit; None for XOT (no answer)
    per_level: dict[int, float] = dc_field(default_factory=dict)
    needs_review: bool = False
    matched: str | None = None  # the keyword / company_id that fired

    def truncated(self, depth: int) -> str | None:
        return T.truncate(self.code, depth)


def _unresolved() -> IndustryAssignment:
    # XOT is an explicit non-answer: it carries NO sector (audit 2026-09-02:
    # 47% of steps were "private" by default).
    return IndustryAssignment(
        code="XOT", depth=1, method="unresolved", confidence=0.0,
        sector=None, per_level={1: 0.0}, needs_review=True,
    )


def _from_spine(code: str, conf: float, method: str, matched: str | None,
                prior_code: str | None) -> IndustryAssignment:
    depth = T.level_of(code)
    per_level = {lvl: conf for lvl in range(1, depth + 1)}
    needs_review = False
    # weak prior corroboration: agree at L1 -> small boost; disagree -> flag (the
    # spine still wins, but the conflict is worth a human glance).
    if prior_code:
        if T.truncate(prior_code, 1) == T.truncate(code, 1):
            conf = min(1.0, conf + _AGREE_BONUS)
            per_level = {lvl: min(1.0, c + _AGREE_BONUS) for lvl, c in per_level.items()}
        elif method == "name_rule":
            needs_review = True
    return IndustryAssignment(
        code=code, depth=depth, method=method, confidence=round(conf, 3),
        sector=T.sector_of(code),
        per_level={k: round(v, 3) for k, v in per_level.items()},
        needs_review=needs_review, matched=matched,
    )


def classify_company(
    *, company_id: str | None, display: str | None,
    modal_occ: str | None = None, occ_coded_frac: float | None = None,
    freq: int | None = None, modal_share: float | None = None,
) -> IndustryAssignment:
    """Deterministic company-grain industry. Inputs come from the company vocab."""
    prior_code, prior_conf = occupation_prior.company_occupation_prior(
        modal_occ, occ_coded_frac, freq=freq, modal_share=modal_share)

    # M1 -- curated head crosswalk
    cur = curated.lookup(company_id)
    if cur:
        conf = curated.confidence_of(company_id) or _CONF_CURATED
        return _from_spine(cur, conf, "curated", company_id, prior_code)

    # M3 -- company-name lexical rules
    code, kw = name_rules.match(display)
    if code:
        conf = _CONF_NAME_MULTIWORD if (kw and " " in kw) else _CONF_NAME_TOKEN
        return _from_spine(code, conf, "name_rule", kw, prior_code)

    # M5 -- weak occupation prior as a shallow fallback only
    if prior_code:
        depth = T.level_of(prior_code)
        return IndustryAssignment(
            code=prior_code, depth=depth, method="occupation_prior",
            confidence=round(prior_conf, 3), sector=T.sector_of(prior_code),
            per_level={lvl: round(prior_conf, 3) for lvl in range(1, depth + 1)},
            needs_review=True, matched=modal_occ,
        )

    return _unresolved()


def classify_row(
    *, company_canonical_id: str | None, company_id: str | None,
    company_raw: str | None, occupation_code: str | None = None,
) -> IndustryAssignment:
    """Deterministic row-grain industry for one career step.

    Org rows (``id:`` / ``raw:``) get the company's industry; ``nonorg:`` rows
    (self-employed / retired / ...) have no employer, so industry comes from the
    row's own occupation prior. Description-based LLM inference for the
    text-bearing self-employed tail is merged separately (propose-only)."""
    key = company_canonical_id or ""
    if key.startswith("id:") or key.startswith("raw:"):
        return classify_company(
            company_id=company_id, display=company_raw,
            modal_occ=occupation_code, occ_coded_frac=1.0 if occupation_code else 0.0,
        )
    # nonorg / missing employer -> occupation prior only
    prior_code, prior_conf = occupation_prior.soc_to_industry(occupation_code)
    if prior_code:
        depth = T.level_of(prior_code)
        return IndustryAssignment(
            code=prior_code, depth=depth, method="occupation_prior",
            confidence=round(prior_conf, 3), sector=T.sector_of(prior_code),
            per_level={lvl: round(prior_conf, 3) for lvl in range(1, depth + 1)},
            needs_review=True, matched=occupation_code,
        )
    return _unresolved()


def classify_company_vocab(rows: list[dict]) -> dict[str, IndustryAssignment]:
    """Batch the company vocab -> {key: assignment}."""
    out: dict[str, IndustryAssignment] = {}
    for r in rows:
        out[r["key"]] = classify_company(
            company_id=r.get("company_id"), display=r.get("display"),
            modal_occ=r.get("modal_occ"), occ_coded_frac=r.get("occ_coded_frac"),
            freq=r.get("freq"), modal_share=r.get("modal_share"),
        )
    return out
