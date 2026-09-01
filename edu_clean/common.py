"""Shared utilities for the education-field cleaning approaches.

Cleaning is fundamentally a *value canonicalization* problem: we operate on the
distinct values of each field (weighted by frequency) and produce a mapping
value -> canonical_id. This module provides:

  * vocabulary export (cached to parquet) - distinct values + frequency, plus
    the modal LinkedIn school slug for institution titles
  * a shared text normalizer
  * the gold-standard evaluation pairs (same / distinct) live in gold.py
  * metrics: pairwise precision/recall/F1, reduction ratio, runtime
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
EDU = f"read_parquet('{ROOT}/parsed/education/*.parquet')"
CACHE = ROOT / "edu_clean" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
MANIFEST = ROOT / "parsed" / "_manifest.json"

FIELDS = ("field", "degree", "title")  # title == institution


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
    """Cache distinct values + frequency for a field to parquet. For `title`
    we also attach the modal school slug (best canonical institution key)."""
    out = CACHE / f"vocab_{name}.parquet"
    if not force and _cache_fresh(out):
        return out
    if out.exists():
        out.unlink()
    con = _con()
    if name == "title":
        con.sql(f"""
            COPY (
              WITH s AS (
                SELECT title AS value,
                       regexp_extract(url, 'linkedin\\.com/school/([^/?]+)', 1) AS slug
                FROM {EDU} WHERE title IS NOT NULL AND trim(title) <> ''
              ),
              slug_counts AS (
                SELECT value, slug, count(*) c FROM s
                WHERE slug <> '' GROUP BY 1, 2
              ),
              modal AS (
                SELECT value, arg_max(slug, c) AS modal_slug
                FROM slug_counts GROUP BY 1
              )
              SELECT v.value, count(*) AS freq, any_value(m.modal_slug) AS modal_slug
              FROM s v LEFT JOIN modal m USING (value)
              GROUP BY v.value
            ) TO '{out}' (FORMAT parquet)
        """)
    else:
        con.sql(f"""
            COPY (
              SELECT {name} AS value, count(*) AS freq
              FROM {EDU} WHERE {name} IS NOT NULL AND trim({name}) <> ''
              GROUP BY 1
            ) TO '{out}' (FORMAT parquet)
        """)
    return out


def load_vocab(name: str, force: bool = False) -> list[tuple]:
    """Return list of rows: (value, freq[, modal_slug]) sorted by freq desc."""
    path = export_vocab(name, force=force)
    con = _con()
    cols = "value, freq" + (", modal_slug" if name == "title" else "")
    return con.sql(
        f"SELECT {cols} FROM read_parquet('{path}') ORDER BY freq DESC, value ASC"
    ).fetchall()


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------
_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")
# soft fillers that rarely change meaning of a field/degree label
SOFT_STOP = {"general", "and", "or", "of", "the", "a", "an", "in", "to", "for", "with"}


def _ascii_fold(text: str) -> str:
    """NFKC + accent fold while preserving non-Latin fallback behavior.

    Latin diacritics should not split otherwise-identical names ("São" vs
    "Sao"). Non-Latin scripts are still removed by the ASCII matcher and are
    preserved later by safe_norm when no ASCII key remains.
    """
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


def normalize(text: str) -> str:
    """Aggressive-but-safe normalization for matching keys.

    NFKC fold, lowercase, unify '&'->'and', turn separators into spaces, drop
    remaining punctuation, collapse whitespace.
    """
    if text is None:
        return ""
    s = _ascii_fold(text)
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = s.lower()
    s = _protect_domain_tokens(s)
    s = s.replace("&", " and ")
    s = s.replace("/", " ").replace("-", " ").replace(".", " ")
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def token_key(text: str, drop_soft: bool = True) -> frozenset[str]:
    """Order-independent token set, optionally dropping soft fillers."""
    toks = normalize(text).split()
    if drop_soft:
        kept = [t for t in toks if t not in SOFT_STOP]
        toks = kept or toks  # never empty out completely
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
    """Evaluate same/distinct decisions against labeled pairs.

    Returns precision/recall/F1 for the 'should-merge' (same) decision, plus
    raw confusion counts and any pairs whose endpoints are missing from vocab.
    """
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
