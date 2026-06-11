"""Shared utilities for industry classification.

Industry is a property of the EMPLOYER, so we resolve it once per distinct
company and propagate to every career step that shares the company (the unit of
analysis, INDUSTRY_PLAN §2). The distinct-company grain is the production
``company_canonical_id`` already in ``normalized/career_steps.parquet`` (career_clean's
``id:<company_id>`` / ``raw:<norm>`` / ``nonorg:<bucket>``), so grouping on it is
consistent with the rest of the pipeline and guarantees "same company -> same
industry everywhere".

``export_company_vocab`` caches a per-company aggregate (display name, company_id,
frequency, person count, modal occupation, top titles, sample descriptions) that
the deterministic backbone and the LLM layer both consume. ``nonorg:`` keys
(self-employed / retired / ...) are NOT companies -- they get industry at the row
grain from the occupation/description signal (see ``occupation_prior`` and
SELF_EMPLOYED_PLAN), so they are excluded here.
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
STEPS = f"read_parquet('{ROOT}/normalized/career_steps.parquet')"
CACHE = Path(__file__).resolve().parent / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
STEPS_FILE = ROOT / "normalized" / "career_steps.parquet"

# How many sample titles / descriptions to attach per company for the LLM.
N_TITLES = 8
N_DESCRIPTIONS = 3
DESC_TRUNC = 600


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def _cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    if not STEPS_FILE.exists():
        return True
    return path.stat().st_mtime >= STEPS_FILE.stat().st_mtime


def export_company_vocab(force: bool = False) -> Path:
    """Cache the distinct-company-grain vocabulary to parquet.

    One row per ``company_canonical_id`` (org companies only). Columns:
      key, display, company_id, freq, n_persons, occ_coded_frac, modal_occ,
      titles (LIST<VARCHAR>), descriptions (LIST<VARCHAR>).
    """
    out = CACHE / "company_vocab.parquet"
    if not force and _cache_fresh(out):
        return out
    if out.exists():
        out.unlink()
    con = _con()
    con.sql(f"""
        COPY (
          WITH org AS (
            SELECT
              company_canonical_id AS key,
              company_raw, company_id_canonical, linkedin_id,
              occupation_code,
              coalesce(nullif(trim(role_canonical), ''), nullif(trim(title_raw), '')) AS title,
              description
            FROM {STEPS}
            WHERE company_canonical_id LIKE 'id:%' OR company_canonical_id LIKE 'raw:%'
          ),
          -- top-N titles per company by frequency
          tcount AS (
            SELECT key, title, count(*) c FROM org WHERE title IS NOT NULL GROUP BY 1, 2
          ),
          trank AS (
            SELECT key, title, row_number() OVER (PARTITION BY key ORDER BY c DESC, title) rn
            FROM tcount
          ),
          tagg AS (
            SELECT key, list(title ORDER BY rn) AS titles FROM trank WHERE rn <= {N_TITLES} GROUP BY 1
          ),
          -- up to N longest descriptions per company (longest = most informative).
          -- Every ORDER BY here carries a full tiebreak: the vocab feeds the LLM
          -- evidence text, whose hash is the frozen-cache key -- a re-export must
          -- be bit-identical or every cached vote is orphaned.
          drank AS (
            SELECT key, left(description, {DESC_TRUNC}) AS d,
                   row_number() OVER (PARTITION BY key ORDER BY length(description) DESC, d) rn
            FROM org WHERE description IS NOT NULL AND length(trim(description)) > 0
          ),
          dagg AS (
            SELECT key, list(d ORDER BY rn) AS descriptions FROM drank WHERE rn <= {N_DESCRIPTIONS} GROUP BY 1
          ),
          -- deterministic mode(): most frequent value, ties broken by the value
          dispmode AS (
            SELECT key, company_raw, row_number() OVER (
              PARTITION BY key ORDER BY count(*) DESC, company_raw) rn
            FROM org GROUP BY key, company_raw
          ),
          occmode AS (
            SELECT key, occupation_code, row_number() OVER (
              PARTITION BY key ORDER BY count(*) DESC, occupation_code) rn
            FROM org WHERE occupation_code IS NOT NULL GROUP BY key, occupation_code
          ),
          base AS (
            SELECT
              o.key,
              any_value(dm.company_raw) AS display,
              any_value(o.company_id_canonical) FILTER (WHERE o.key LIKE 'id:%') AS company_id,
              count(*) AS freq,
              count(DISTINCT o.linkedin_id) AS n_persons,
              round(avg(CASE WHEN o.occupation_code IS NOT NULL THEN 1.0 ELSE 0.0 END), 4) AS occ_coded_frac,
              any_value(om.occupation_code) AS modal_occ
            FROM org o
            LEFT JOIN (SELECT key, company_raw FROM dispmode WHERE rn = 1) dm USING (key)
            LEFT JOIN (SELECT key, occupation_code FROM occmode WHERE rn = 1) om USING (key)
            GROUP BY o.key
          )
          SELECT b.*,
                 coalesce(t.titles, []) AS titles,
                 coalesce(d.descriptions, []) AS descriptions
          FROM base b
          LEFT JOIN tagg t USING (key)
          LEFT JOIN dagg d USING (key)
        ) TO '{out}' (FORMAT parquet)
    """)
    return out


def load_company_vocab(cap: int | None = None, force: bool = False) -> list[dict]:
    """Return company-grain rows (dicts) sorted by freq desc.

    ``cap`` keeps only the top-N most frequent companies -- the head that covers
    most rows (top 50k company_ids cover ~54% of all id-bearing rows), used to
    bound the LLM head-curation pass and tests.
    """
    path = export_company_vocab(force=force)
    con = _con()
    limit = f"LIMIT {cap}" if cap is not None else ""
    rows = con.sql(f"""
        SELECT key, display, company_id, freq, n_persons, occ_coded_frac,
               modal_occ, titles, descriptions
        FROM read_parquet('{path}')
        ORDER BY freq DESC, key
        {limit}
    """).fetchall()
    cols = ["key", "display", "company_id", "freq", "n_persons", "occ_coded_frac",
            "modal_occ", "titles", "descriptions"]
    return [dict(zip(cols, r)) for r in rows]


# --------------------------------------------------------------------------
# Metrics -- per-level precision/recall + coverage by depth
# --------------------------------------------------------------------------
def level_scores(
    pred: dict[str, str | None], gold: dict[str, str], *, taxonomy
) -> dict:
    """Per-level (L1..L4) precision/recall against a gold ``key -> code`` set.

    A prediction is correct AT LEVEL k iff truncating both pred and gold to k
    levels agree (so you can be right at L1 but wrong at L4 -- reported per level,
    as the plan requires). ``pred`` may be None (abstain) or a partial code
    shallower than k (counts as no prediction at level k).
    """
    out = {}
    for lvl in (1, 2, 3, 4):
        tp = fp = fn = 0
        for key, g in gold.items():
            gt = taxonomy.truncate(g, lvl)
            if gt is None:
                continue  # gold itself shallower than this level -> not scored here
            p = pred.get(key)
            # a prediction shallower than this level is an ABSTAIN here, not a
            # wrong answer -- only score it where it actually reaches.
            if p and taxonomy.is_valid(p) and taxonomy.level_of(p) >= lvl:
                pt = taxonomy.truncate(p, lvl)
            else:
                pt = None
            if pt is None:
                fn += 1
            elif pt == gt:
                tp += 1
            else:
                fp += 1
                fn += 1
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        out[f"L{lvl}"] = {
            "precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(f1, 3), "tp": tp, "fp": fp, "fn": fn,
        }
    return out


def depth_coverage(
    rows: list[dict], pred: dict[str, str | None], *, taxonomy, weight: str = "freq"
) -> dict:
    """Share of rows (weighted by ``freq``) with a prediction reaching >= each
    depth. Answers "what % of career steps get an L1 / L2 / L3 / L4 industry"."""
    total = sum(r[weight] for r in rows) or 1
    hit = {1: 0, 2: 0, 3: 0, 4: 0}
    for r in rows:
        p = pred.get(r["key"])
        # XOT (Other/Unknown) is an explicit non-answer -> NOT coverage. XDV
        # (Diversified) is a real classification and does count.
        depth = taxonomy.level_of(p) if (p and taxonomy.is_valid(p) and p != "XOT") else 0
        for lvl in (1, 2, 3, 4):
            if depth >= lvl:
                hit[lvl] += r[weight]
    return {f"L{lvl}": round(100 * hit[lvl] / total, 1) for lvl in (1, 2, 3, 4)}


class timer:
    def __enter__(self):
        self._t = time.monotonic()
        return self

    def __exit__(self, *a):
        self.elapsed = time.monotonic() - self._t
