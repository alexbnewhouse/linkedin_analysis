"""Reproducible probes for self-employed / freelance career steps.

Run with:

    uv run python exploration/self_employed_explore.py

This mirrors the measurements summarized in career_clean/SELF_EMPLOYED_PLAN.md:
placeholder-company scale, title marker scale, row signal coverage, and
raw-vs-status-stripped occupation recovery examples.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from career_clean import approach_a_rules as A
from career_clean import occupation as O
from career_clean.common import EXP, JOB_TITLES, ROOT, load_vocab, normalize

OUT = ROOT / "career_clean" / "results" / "self_employed_explore.json"


def company_placeholder_profile() -> dict:
    vocab = load_vocab("company")
    total_rows = sum(freq for _value, freq, _modal_id in vocab)
    rows: Counter[str] = Counter()
    spellings: Counter[str] = Counter()
    for value, freq, _modal_id in vocab:
        bucket = A._placeholder_bucket(normalize(value))  # noqa: SLF001
        if not bucket:
            continue
        rows[bucket] += freq
        spellings[bucket] += 1
    return {
        bucket: {
            "rows": count,
            "pct_company_rows": round(100 * count / total_rows, 3),
            "distinct_spellings": spellings[bucket],
        }
        for bucket, count in rows.most_common()
    }


def title_marker_profile() -> dict:
    vocab = load_vocab("title")
    total_rows = sum(freq for _value, freq in vocab)
    rows: Counter[str] = Counter()
    for value, freq in vocab:
        norm = normalize(value)
        toks = set(norm.split())
        if "consultant" in toks:
            rows["consultant"] += freq
        if "owner" in toks:
            rows["owner"] += freq
        if "founder" in toks or "cofounder" in toks or "co founder" in norm:
            rows["founder_cofounder"] += freq
        if any(tok.startswith("freelanc") for tok in toks):
            rows["freelance"] += freq
        if "independent" in toks:
            rows["independent"] += freq
        if "contractor" in toks:
            rows["contractor"] += freq
        if norm.startswith("self employed") or norm.startswith("selfemployed"):
            rows["self_employed_in_title"] += freq
        if A.title_has_solo_marker(value):
            rows["strong_solo_markers_union"] += freq
    return {
        marker: {"rows": count, "pct_title_rows": round(100 * count / total_rows, 3)}
        for marker, count in rows.most_common()
    }


def self_employed_row_coverage() -> dict:
    con = duckdb.connect()
    # SQL-side approximation of the exact Python placeholder dictionary, used
    # only for exploration scale/coverage counts.
    base = f"""
      FROM {EXP} experience
      WHERE company IS NOT NULL
        AND (
          regexp_matches(lower(company), '^self.?employ')
          OR regexp_matches(lower(company), '^freelanc')
          OR regexp_matches(lower(company), '^independent (contractor|consultant)')
          OR regexp_matches(lower(company), '^sole proprietor')
          OR regexp_matches(lower(company), '^private practice')
        )
    """
    total = con.sql(f"SELECT count(*) {base}").fetchone()[0]
    if not total:
        return {}
    title_present, dated, description, company_id, multi_role = con.sql(f"""
      SELECT
        count(*) FILTER (WHERE title IS NOT NULL AND trim(title) <> ''),
        count(*) FILTER (WHERE start_date IS NOT NULL AND end_date IS NOT NULL),
        count(*) FILTER (WHERE description IS NOT NULL AND trim(description) <> ''),
        count(*) FILTER (WHERE company_id IS NOT NULL AND trim(company_id) <> ''),
        count(*) FILTER (
          WHERE EXISTS (
            SELECT 1
            FROM read_parquet('{ROOT}/parsed/positions/*.parquet') p
            WHERE p.linkedin_id=experience.linkedin_id
              AND p.experience_idx=experience.experience_idx
          )
        )
      {base}
    """).fetchone()
    return {
        "rows": total,
        "pct_title_present": round(100 * title_present / total, 1),
        "pct_start_and_end_dates": round(100 * dated / total, 1),
        "pct_description": round(100 * description / total, 1),
        "pct_company_id": round(100 * company_id / total, 1),
        "pct_multi_role": round(100 * multi_role / total, 1),
    }


def occupation_recovery_examples() -> dict:
    by_norm, by_tokens, _code_to_title = O.load_onet()
    examples = [
        "Freelance Graphic Designer",
        "Freelance Writer",
        "Freelance Artist",
        "Private Tutor",
        "Owner",
        "Independent Consultant",
    ]
    out = {}
    for title in examples:
        raw_code, raw_method = O._match_surface(title, by_norm, by_tokens)  # noqa: SLF001
        stripped = A.strip_employment_status_prefix(title)
        stripped_code, stripped_method = (
            O._match_surface(stripped, by_norm, by_tokens) if stripped else (None, "empty")  # noqa: SLF001
        )
        final_code, final_method = O.match(title, by_norm, by_tokens)
        out[title] = {
            "raw": f"soc:{raw_code}" if raw_code else None,
            "raw_method": raw_method,
            "stripped_title": stripped,
            "stripped": f"soc:{stripped_code}" if stripped_code else None,
            "stripped_method": stripped_method,
            "final": f"soc:{final_code}" if final_code else None,
            "final_method": final_method,
        }
    return out


def main() -> None:
    report = {
        "company_placeholders": company_placeholder_profile(),
        "title_markers": title_marker_profile(),
        "self_employed_row_coverage": self_employed_row_coverage(),
        "occupation_recovery_examples": occupation_recovery_examples(),
        "job_title_source": JOB_TITLES,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
