"""Shared utilities for the career-field cleaning approaches.

Mirrors edu_clean/common.py. Cleaning is a *value canonicalization* problem: we
operate on the distinct values of each field (weighted by frequency) and produce
a mapping value -> canonical_id. This module provides:

  * vocabulary export (cached to parquet) - distinct values + frequency. For
    `company` we also attach the modal LinkedIn ``company_id`` (the in-data
    canonical organization key, analogous to the school slug in education).
  * a shared text normalizer (NFKC, case, &->and, separators, punctuation)
  * metrics: pairwise precision/recall/F1, reduction ratio, runtime
  * the gold-standard same/distinct pairs live in gold.py

KEY DATA-MODEL FACT (see PLAN.md / exploration/career_explore.py): LinkedIn uses
a grouped-position model. For a *single-role* experience, ``experience.title`` is
the job title; for a *multi-role* experience (one with ``positions`` children)
``experience.title`` is the COMPANY name and the real titles live in
``positions.title``. So the clean job-title vocabulary is
``single-role experience.title`` UNION ALL ``positions.title`` - encoded by the
JOB_TITLES SQL below.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
EXP = f"read_parquet('{ROOT}/parsed/experience/*.parquet')"
POS = f"read_parquet('{ROOT}/parsed/positions/*.parquet')"
CACHE = ROOT / "career_clean" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
MANIFEST = ROOT / "parsed" / "_manifest.json"

FIELDS = ("company", "title", "employment_type")  # description is normalization-only

# Unified job-title source (the data-model fact above, in SQL).
JOB_TITLES = f"""(
  SELECT title AS value FROM {EXP} t
    WHERE title IS NOT NULL AND trim(title) <> ''
      AND NOT EXISTS (SELECT 1 FROM {POS} p
                      WHERE p.linkedin_id=t.linkedin_id
                        AND p.experience_idx=t.experience_idx)
  UNION ALL
  SELECT title AS value FROM {POS} WHERE title IS NOT NULL AND trim(title) <> ''
)"""

# Row-level career-step source for axes that need both employer and role. For a
# multi-role experience, the employer/company_id live on experience and each
# child position carries its own title.
CAREER_STEPS = f"""(
  SELECT company, title, company_id FROM {EXP} t
    WHERE NOT EXISTS (SELECT 1 FROM {POS} p
                      WHERE p.linkedin_id=t.linkedin_id
                        AND p.experience_idx=t.experience_idx)
      AND ((company IS NOT NULL AND trim(company) <> '')
        OR (title IS NOT NULL AND trim(title) <> ''))
  UNION ALL
  SELECT e.company, p.title, e.company_id
  FROM {EXP} e
  JOIN {POS} p
    ON p.linkedin_id=e.linkedin_id
   AND p.experience_idx=e.experience_idx
  WHERE (e.company IS NOT NULL AND trim(e.company) <> '')
     OR (p.title IS NOT NULL AND trim(p.title) <> '')
)"""


# --------------------------------------------------------------------------
# Vocabulary export
# --------------------------------------------------------------------------
def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def _cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    if not MANIFEST.exists():
        return True
    return path.stat().st_mtime >= MANIFEST.stat().st_mtime


def export_vocab(name: str, force: bool = False) -> Path:
    """Cache distinct values + frequency for a field to parquet. For `company`
    we also attach the modal ``company_id`` (best canonical organization key)."""
    out = CACHE / f"vocab_{name}.parquet"
    if not force and _cache_fresh(out):
        return out
    if out.exists():
        out.unlink()
    con = _con()
    if name == "company":
        con.sql(f"""
            COPY (
              WITH base AS (
                SELECT company AS value, company_id
                FROM {EXP} WHERE company IS NOT NULL AND trim(company) <> ''
              ),
              idc AS (
                SELECT value, company_id, count(*) c FROM base
                WHERE company_id IS NOT NULL GROUP BY 1, 2
              ),
              modal AS (
                SELECT value, arg_max(company_id, c) AS modal_id FROM idc GROUP BY 1
              )
              SELECT b.value, count(*) AS freq, any_value(m.modal_id) AS modal_id
              FROM base b LEFT JOIN modal m USING (value)
              GROUP BY b.value
            ) TO '{out}' (FORMAT parquet)
        """)
    elif name == "title":
        con.sql(f"""
            COPY (
              SELECT value, count(*) AS freq FROM {JOB_TITLES} GROUP BY 1
            ) TO '{out}' (FORMAT parquet)
        """)
    elif name == "employment_type":
        con.sql(f"""
            COPY (
              WITH base AS (
                SELECT company, title, company_id FROM {CAREER_STEPS}
              ),
              idc AS (
                SELECT company, title, company_id, count(*) c FROM base
                WHERE company_id IS NOT NULL GROUP BY 1, 2, 3
              ),
              modal AS (
                SELECT company, title, arg_max(company_id, c) AS modal_id
                FROM idc GROUP BY 1, 2
              )
              SELECT b.company, b.title, count(*) AS freq, any_value(m.modal_id) AS modal_id
              FROM base b
              LEFT JOIN modal m
                ON b.company IS NOT DISTINCT FROM m.company
               AND b.title IS NOT DISTINCT FROM m.title
              GROUP BY b.company, b.title
            ) TO '{out}' (FORMAT parquet)
        """)
    else:
        raise ValueError(name)
    return out


def load_vocab(
    name: str, cap: int | None = None, include: tuple[str, ...] = (), force: bool = False
) -> list[tuple]:
    """Return rows ``(value, freq[, modal_id])`` sorted by freq desc.

    ``cap`` keeps only the top-N most frequent values (used by the GPU embedding
    approach, which is O(n^2) and cannot run on the full multi-million-value
    vocabulary). ``include`` force-adds specific values (e.g. gold-pair
    endpoints) even if they fall below the cap, so the benchmark stays honest.
    """
    path = export_vocab(name, force=force)
    con = _con()
    if name == "employment_type":
        cols = "company, title, freq, modal_id"
        src = f"read_parquet('{path}')"
        if cap is None:
            raw_rows = con.sql(
                f"SELECT {cols} FROM {src} ORDER BY freq DESC, company ASC, title ASC"
            ).fetchall()
        else:
            raw_rows = con.sql(
                f"SELECT {cols} FROM {src} ORDER BY freq DESC, company ASC, title ASC LIMIT {cap}"
            ).fetchall()
        return [((company, title), freq, modal_id) for company, title, freq, modal_id in raw_rows]

    cols = "value, freq" + (", modal_id" if name == "company" else "")
    src = f"read_parquet('{path}')"
    if cap is None:
        rows = con.sql(
            f"SELECT {cols} FROM {src} ORDER BY freq DESC, value ASC"
        ).fetchall()
        return rows
    rows = con.sql(
        f"SELECT {cols} FROM {src} ORDER BY freq DESC, value ASC LIMIT {cap}"
    ).fetchall()
    if include:
        have = {r[0] for r in rows}
        want = [v for v in include if v not in have]
        if want:
            qs = ",".join("?" for _ in want)
            extra = con.execute(
                f"SELECT {cols} FROM {src} WHERE value IN ({qs})", want
            ).fetchall()
            rows.extend(extra)
    return rows


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------
_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")
# Soft fillers that rarely change the identity of a company / job title.
SOFT_STOP = {"the", "a", "an", "of", "and", "or", "for", "to", "at", "in"}


def _ascii_fold(text: str) -> str:
    """NFKC + accent fold while preserving non-Latin fallback behavior."""
    s = unicodedata.normalize("NFKC", text)
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _protect_domain_tokens(text: str) -> str:
    """Protect meaningful punctuation before the generic punctuation pass."""
    s = re.sub(r"(?<![a-z0-9])c\s*\+\s*\+(?![a-z0-9])", " cplusplus ", text)
    s = re.sub(r"(?<![a-z0-9])c\s*#(?![a-z0-9])", " csharp ", s)
    s = re.sub(r"(?<![a-z0-9])f\s*#(?![a-z0-9])", " fsharp ", s)
    s = re.sub(r"(?<![a-z0-9])r\s*&\s*d(?![a-z0-9])", " research and development ", s)
    return s


def normalize(text: str | None) -> str:
    """Aggressive-but-safe normalization for matching keys.

    NFKC fold, lowercase, unify '&'->'and', turn separators into spaces, drop
    remaining punctuation, collapse whitespace. (Drops non-ASCII; use
    ``safe_norm`` in final_hybrid for raw canonical ids so multilingual labels
    don't collapse to empty.)
    """
    if text is None:
        return ""
    s = _ascii_fold(text)
    s = s.replace("’", "'").replace("‘", "'")
    s = s.lower()
    s = _protect_domain_tokens(s)
    s = s.replace("&", " and ")
    s = s.replace("/", " ").replace("-", " ").replace(".", " ")
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def token_key(text: str | None, drop_soft: bool = True) -> frozenset[str]:
    """Order-independent token set, optionally dropping soft fillers."""
    toks = normalize(text).split()
    if drop_soft:
        kept = [t for t in toks if t not in SOFT_STOP]
        toks = kept or toks
    return frozenset(toks)


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
@dataclass
class Result:
    name: str
    field: str
    mapping: dict  # raw value -> canonical id/string
    runtime_s: float
    extra: dict = dc_field(default_factory=dict)

    def n_in(self) -> int:
        return len(self.mapping)

    def n_out(self) -> int:
        return len(set(self.mapping.values()))

    def reduction(self) -> float:
        if not self.mapping:
            return 0.0
        return 1.0 - self.n_out() / self.n_in()


def pair_scores(mapping: dict, pairs: list[tuple[str, str, bool]]) -> dict:
    """Pairwise precision/recall/F1 for the 'should-merge' (same) decision."""
    tp = fp = tn = fn = 0
    missing = 0
    for a, b, same in pairs:
        if a not in mapping or b not in mapping:
            missing += 1
            continue
        pred_same = mapping[a] == mapping[b]
        if same and pred_same:
            tp += 1
        elif same and not pred_same:
            fn += 1
        elif (not same) and pred_same:
            fp += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    acc = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) else 0.0
    return {
        "precision": round(prec, 3),
        "recall": round(rec, 3),
        "f1": round(f1, 3),
        "accuracy": round(acc, 3),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "missing": missing,
    }


class timer:
    def __enter__(self):
        self._t = time.monotonic()
        return self

    def __exit__(self, *a):
        self.elapsed = time.monotonic() - self._t
