"""Industry/sector classification (Layer 6a).

A 4-level hierarchical industry schema (``taxonomy``) plus a multi-method,
precision-first classifier that *infers* industry at the distinct-company grain
and propagates to career steps. The in-data industry field is unusable
(``cc_industry`` populated on 0.005% of profiles), so this is ~100% an inference
problem; see INDUSTRY_PLAN.md.

Method precedence (highest precision first; weaker layers only extend coverage):

    M1 curated company_id -> industry crosswalk        (backbone, P~=1.0)   curated.py
    M3 company-name lexical rules                        (self-describing names) name_rules.py
    M4/M5 occupation (SOC) -> industry prior             (weak prior/tiebreak) occupation_prior.py
    M6 LLM on name+title+description                     (propose-only, last)   llm.py

The fusion engine (classify.py) emits the DEEPEST node all corroborating
evidence agrees on, with a per-level confidence + method + depth, so the output
is a path truncated to the supported depth -- not a forced L4 leaf.
"""
