"""Rec 4 - infer a functional cluster from the free-text ``description``.

The next lever for the ~59% self-employment residue that title+company cannot
cluster (bare "Owner"/"Founder"/"Consultant"). 47% of self-employment steps carry
a description, and self-employed people routinely name their trade there
("artisan letterpress shop", "professional pet sitting and dog walking", "create
Mac applications software").

Free text is far noisier than a title, so this is deliberately PROPOSE-ONLY
(review-queue grade, lowest confidence tier) and precision-first. Grounding
(exploration/se_description_explore.py) showed two failure modes of naive
bag-of-words voting and the fix for each:

  * generic business/function boilerplate ("manage operations", "marketing",
    "software expertise") appears in almost every description and over-fires
    clusters 11/13/15 -> those keywords are WEAK and may never DECIDE alone;
  * the trade is usually named in the FIRST sentence, while generic activity
    verbs follow in bullets -> read a lead window first.

Two stages, precision-first:
  1. desc_lead - first STRONG (non-generic) gazetteer keyword in the lead
                 window (first sentence/bullet, capped).            [conf 0.50]
  2. desc_vote - else a STRONG-keyword vote over the whole text, requiring >=2
                 DISTINCT strong keywords for the winning cluster and a clear
                 margin over the runner-up.                          [conf 0.40]
Otherwise nothing (the honest floor stays).
"""

from __future__ import annotations

import re
from collections import Counter

from . import se_cluster as C

# Generic business / function words that appear in nearly every self-employed
# description and so cannot, alone, identify the trade. They are excluded from
# both stages (a real designer/developer who is residue is rare; the recall lost
# is worth the precision gained, per the grounding sample).
WEAK_KEYWORDS = frozenset({
    "management", "operations", "marketing", "advertising", "data", "digital",
    "technology", "tech", "software", "web", "media", "design", "creative",
    "recruiting", "recruitment", "staffing", "finance", "financial",
    "network", "networking",
})
# Short gazetteer tokens that are safe in a title but collide with common
# English words in prose -- "it" (Information Technology) matches the pronoun
# "it" constantly. Excluded from description inference only.
_DESC_TOKEN_HAZARDS = frozenset({"it"})
_DESC_EXCLUDE = WEAK_KEYWORDS | _DESC_TOKEN_HAZARDS

_LEAD_SPLIT = re.compile(r"[.•●\n\r|;]")
_LEAD_CAP = 200
# The trade is named early; bound the vote scan so very long descriptions don't
# dominate runtime over millions of rows.
_VOTE_CAP = 600

_LEAD_CONF = 0.50
_VOTE_CONF = 0.40


def lead_window(text: str) -> str:
    """First sentence / bullet of a description, capped - where the trade is
    usually named, before the generic activity bullets."""
    first = _LEAD_SPLIT.split(text.strip(), 1)[0]
    return first[:_LEAD_CAP]


def infer_cluster(text: str | None) -> tuple[str | None, str, float, str | None]:
    """Return (cluster, method, confidence, evidence). cluster is a 2-digit major
    group or None. Propose-only."""
    if not text or not text.strip():
        return None, "desc_empty", 0.0, None

    # 1. strong keyword in the lead window
    cl, kw = C.ordered_keyword(lead_window(text), exclude=_DESC_EXCLUDE)
    if cl:
        return cl, "desc_lead", _LEAD_CONF, kw

    # 2. strong-keyword vote over the (capped) text (distinct keywords per cluster)
    hits = C.keyword_hits(text[:_VOTE_CAP], exclude=_DESC_EXCLUDE)
    if hits:
        per_cluster: Counter[str] = Counter(cl for _kw, cl in hits)
        (top, n), = per_cluster.most_common(1)
        second = per_cluster.most_common(2)[1][1] if len(per_cluster) > 1 else 0
        if n >= 2 and n > second:
            evidence = ",".join(sorted({kw for kw, c in hits if c == top}))
            return top, "desc_vote", _VOTE_CONF, evidence

    return None, "desc_none", 0.0, None
