"""LLM-as-jury: hierarchical consensus over a panel of diverse Claude jurors.

This is the centerpiece of the LLM_JUDGE_JURY_REPORT recommendations. Instead of
trusting one model's single call (and its near-constant self-reported "high"
confidence), we poll a small panel of *diverse* jurors and aggregate their
taxonomy paths by **walking the tree top-down and stopping at the deepest level a
majority of jurors agree on** (Verga et al. "Replacing Judges with Juries" / PoLL,
adapted to our hierarchical, partial-assignment schema in INDUSTRY_PLAN §3.8).

Why this fits the schema exactly:
  * Juror AGREEMENT sets the depth. Jurors that all say "Finance/Banking" but
    split on the L3/L4 leaf yield ``FIN.BNK`` -- a correct SHALLOW answer, never a
    guessed deep one. This is the precision/recall-by-depth trade the plan wants,
    now driven by measurable consensus rather than one model's nerve.
  * The per-level support fraction is a real, EMPIRICALLY CALIBRATABLE confidence
    (e.g. "3/3 at L1, 2/3 at L2, 1/3 at L3"), far better than verbalized high/med/low.
  * Total disagreement (no L1 majority) -> ``XOT`` + review: principled,
    externally-grounded abstention feeding the existing curation ratchet.

The panel is intra-vendor by design (Haiku / Sonnet / Opus tiers) so no scraped
profile PII leaves Anthropic -- the governance constraint in INDUSTRY_PLAN §7.9.
A local open-weight juror can be added later (juror specs are just model strings).

This module is PURE (no network, no SDK): it aggregates already-resolved juror
proposals, so it is fully unit-testable offline. The firing lives in ``llm.py`` /
``fire_llm.py``; merging into the company table lives in ``build_industry.py``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import taxonomy as T

# Default consensus threshold: a label must be supported by STRICTLY MORE than
# this fraction of ALL jurors (abstainers count against depth) to be accepted at a
# level. 0.5 = simple majority: 2/3 jurors descend, a 1/1/1 split stops. Ties
# (2/4) do not exceed 0.5, so they stop -- the conservative choice.
DEFAULT_TAU = 0.5


@dataclass(frozen=True)
class JuryVerdict:
    code: str                      # deepest consensus node (partial path, or XOT)
    depth: int                     # 1..4 (1 for XOT/abstain)
    agreement: float               # support fraction at the accepted depth (0..1)
    n_jurors: int                  # how many valid juror votes went in
    per_level: dict[int, float] = field(default_factory=dict)  # support per level
    jurors: dict[str, str] = field(default_factory=dict)       # model -> its code

    @property
    def is_abstention(self) -> bool:
        return self.code == "XOT"


def consensus(paths: list[str], *, tau: float = DEFAULT_TAU) -> tuple[str, dict[int, float]]:
    """Hierarchical majority consensus over juror taxonomy ``paths``.

    Each path is a (possibly partial) taxonomy code. Walk L1->L4; at each level
    take the modal label among jurors whose path reaches that level AND is
    consistent with the already-accepted parent. Accept it (descend) iff its
    support, as a fraction of ALL jurors, strictly exceeds ``tau``; otherwise stop
    and emit the accepted prefix. No L1 majority -> ``XOT``.

    Returns ``(code, per_level_support)``. Invalid/empty paths are dropped.
    """
    valid = [p for p in paths if T.is_valid(p)]
    n = len(valid)
    if n == 0:
        return "XOT", {}
    accepted: str | None = None
    support: dict[int, float] = {}
    for level in (1, 2, 3, 4):
        votes: Counter[str] = Counter()
        for p in valid:
            trunc = T.truncate(p, level)
            if trunc is None:
                continue  # this juror is shallower than `level` -> abstains here
            if accepted is not None and T.truncate(p, level - 1) != accepted:
                continue  # inconsistent with the accepted parent -> excluded
            votes[trunc] += 1
        if not votes:
            break
        label, cnt = votes.most_common(1)[0]
        frac = cnt / n  # denominator is ALL jurors: abstention counts against depth
        if frac > tau:
            accepted = label
            support[level] = round(frac, 3)
        else:
            break
    if accepted is None:
        return "XOT", {1: 0.0}
    return accepted, support


def aggregate(proposals_by_model: dict[str, str], *, tau: float = DEFAULT_TAU) -> JuryVerdict:
    """Aggregate ``{model -> code}`` (one vote per juror) into a JuryVerdict.

    ``proposals_by_model`` maps each juror model to the single code it proposed
    for one company. Degrades gracefully: a single juror yields that juror's path
    at agreement 1.0 (so the existing one-model cache still works), and an empty
    panel yields an XOT abstention.
    """
    jurors = {m: c for m, c in proposals_by_model.items() if T.is_valid(c)}
    code, per_level = consensus(list(jurors.values()), tau=tau)
    depth = T.level_of(code)
    agreement = per_level.get(depth, 0.0)
    return JuryVerdict(
        code=code, depth=depth, agreement=agreement, n_jurors=len(jurors),
        per_level=per_level, jurors=dict(jurors),
    )
