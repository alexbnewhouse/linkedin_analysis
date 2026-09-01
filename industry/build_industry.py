"""Assemble the company -> industry_path table (the production artifact).

    uv run python -m industry.build_industry            # full company vocab
    uv run python -m industry.build_industry --cap 50000
    uv run python -m industry.build_industry --propagate # also join onto career steps

Pipeline:
  1. company vocab (distinct ``company_canonical_id``)  -> common.export_company_vocab
  2. deterministic backbone (M1/M3/M5)                  -> classify.classify_company_vocab
  3. merge the FROZEN LLM proposals (M6) as PROPOSE-ONLY review-queue candidates
     -- they are written to separate ``llm_*`` columns and NEVER overwrite a
     deterministic answer (precision-first contract).
  4. write industry/results/company_industry.parquet (one row per company, with
     industry_code + truncated l1..l4 + depth + method + confidence + sector +
     needs_review + the llm candidate) and a build manifest.

``--propagate`` joins that onto ``normalized/career_steps.parquet`` to emit a
row-level ``step_industry.parquet`` (the org axis the flow diagrams are drawn on);
``nonorg`` self-employed rows get their row-level occupation prior here too.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from . import classify, jury, llm
from . import taxonomy as T
from .common import STEPS, depth_coverage, export_company_vocab, load_company_vocab

RESULTS = Path(__file__).resolve().parent / "results"
COMPANY_OUT = RESULTS / "company_industry.parquet"
STEP_OUT = RESULTS / "step_industry.parquet"


def build_company_table(cap: int | None, *, use_llm: bool) -> tuple[Path, dict]:
    vocab = load_company_vocab(cap=cap)
    assign = classify.classify_company_vocab(vocab)

    # M6 propose-only: read the frozen jury cache (no API call) for companies the
    # deterministic stack left unresolved or shallow (L1). Each company's juror
    # votes are collapsed by jury.aggregate into a hierarchical-consensus verdict;
    # the AGREEMENT fraction is the (calibratable) confidence, not the model's
    # self-reported high/med/low. These are review-queue candidates and NEVER
    # overwrite a deterministic answer (precision-first contract).
    panel: dict[str, dict[str, llm.Proposal]] = {}
    if use_llm:
        needy = [r for r in vocab
                 if assign[r["key"]].method in ("unresolved", "occupation_prior")]
        # backend-agnostic: picks up cloud (claude-*) AND local (ollama/*) jurors.
        panel = llm.cached_panel(needy)  # offline: cached jurors only, no API call

    rows = []
    for r in vocab:
        a = assign[r["key"]]
        votes = panel.get(r["key"]) or {}
        verdict = jury.aggregate({m: p.code for m, p in votes.items()}) if votes else None
        # carry a representative rationale: a juror whose code matches the verdict.
        lead = next((p for p in votes.values() if verdict and p.code == verdict.code),
                    next(iter(votes.values()), None))
        rows.append({
            "key": r["key"],
            "company_id": r["company_id"],
            "display": r["display"],
            "freq": r["freq"],
            "n_persons": r["n_persons"],
            "industry_code": a.code,
            "l1": T.truncate(a.code, 1),
            "l2": T.truncate(a.code, 2),
            "l3": T.truncate(a.code, 3),
            "l4": T.truncate(a.code, 4),
            "depth": a.depth,
            "method": a.method,
            "confidence": a.confidence,
            "sector": a.sector,
            "needs_review": a.needs_review,
            "matched": a.matched,
            # propose-only jury candidate (agreement-gated, not verbalized-conf):
            "llm_code": verdict.code if verdict else None,
            "llm_depth": verdict.depth if verdict else None,
            "llm_agreement": verdict.agreement if verdict else None,
            "llm_n_jurors": verdict.n_jurors if verdict else None,
            # does the jury's L1 corroborate the deterministic L1 (when both exist)?
            "llm_agrees_det": (
                None if (verdict is None or a.method == "unresolved")
                else T.truncate(verdict.code, 1) == T.truncate(a.code, 1)
            ),
            "llm_confidence": lead.confidence if lead else None,  # advisory only
            "llm_rationale": lead.rationale if lead else None,
        })

    RESULTS.mkdir(exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, COMPANY_OUT)

    pred = {r["key"]: r["industry_code"] for r in rows}
    llm_rows = [r for r in rows if r["llm_code"]]
    multi_juror = [r for r in llm_rows if (r["llm_n_jurors"] or 0) >= 2]
    disagreements = sum(1 for r in llm_rows if r["llm_agrees_det"] is False)
    manifest = {
        "n_companies": len(rows),
        "total_rows": sum(r["freq"] for r in vocab),
        "coverage_by_depth_row_pct": depth_coverage(vocab, pred, taxonomy=T, weight="freq"),
        "review_queue_companies": sum(1 for r in rows if r["needs_review"]),
        "llm_candidates": len(llm_rows),
        "llm_multi_juror_candidates": len(multi_juror),
        "llm_abstentions_XOT": sum(1 for r in llm_rows if r["llm_code"] == "XOT"),
        "llm_disagrees_with_deterministic_L1": disagreements,
        "cap": cap,
    }
    return COMPANY_OUT, manifest


def propagate_to_steps() -> tuple[Path, dict]:
    """Join the company industry onto career steps; nonorg rows get their own
    row-level occupation prior. Heavy (full career_steps)."""
    if not COMPANY_OUT.exists():
        raise SystemExit("run build_company_table first (company_industry.parquet missing)")
    con = duckdb.connect()
    # Build a tiny SOC-major -> industry prior table in SQL for the nonorg rows,
    # mirroring occupation_prior (kept in sync via the test suite).
    from .occupation_prior import _MAJOR_TO_INDUSTRY, _SOC_OVERRIDE  # noqa: SLF001
    major_vals = ", ".join(f"('{k}', '{v[0]}', {v[1]})" for k, v in _MAJOR_TO_INDUSTRY.items())
    over_vals = ", ".join(f"('{k}', '{v[0]}', {v[1]})" for k, v in _SOC_OVERRIDE.items())
    con.sql(f"CREATE TEMP TABLE major_prior AS SELECT * FROM (VALUES {major_vals}) t(maj, code, conf)")
    con.sql(f"CREATE TEMP TABLE soc_prior AS SELECT * FROM (VALUES {over_vals}) t(soc, code, conf)")
    con.sql(f"""
        COPY (
          WITH steps AS (
            SELECT linkedin_id, experience_idx, position_idx, source_table,
                   company_canonical_id AS key, occupation_code
            FROM {STEPS}
          ),
          org AS (
            SELECT s.*, c.industry_code, c.l1, c.l2, c.l3, c.l4, c.depth,
                   c.method, c.confidence, c.sector, c.needs_review
            FROM steps s JOIN read_parquet('{COMPANY_OUT}') c USING (key)
          ),
          nonorg AS (
            SELECT s.*,
                   coalesce(o.code, m.code, 'XOT') AS industry_code,
                   coalesce(o.code, m.code, 'XOT') AS l1,
                   NULL AS l2, NULL AS l3, NULL AS l4,
                   1 AS depth,
                   CASE WHEN o.code IS NOT NULL OR m.code IS NOT NULL
                        THEN 'occupation_prior' ELSE 'unresolved' END AS method,
                   coalesce(o.conf, m.conf, 0.0) AS confidence,
                   'private' AS sector,
                   TRUE AS needs_review
            FROM steps s
            LEFT JOIN soc_prior  o ON o.soc = replace(s.occupation_code, 'soc:', '')
            LEFT JOIN major_prior m ON m.maj = substr(replace(s.occupation_code, 'soc:', ''), 1, 2)
            WHERE s.key NOT LIKE 'id:%' AND s.key NOT LIKE 'raw:%'
          )
          SELECT linkedin_id, experience_idx, position_idx, source_table, key,
                 industry_code, l1, l2, l3, l4, depth, method, confidence, sector, needs_review
          FROM org
          UNION ALL BY NAME
          SELECT linkedin_id, experience_idx, position_idx, source_table, key,
                 industry_code, l1, l2, l3, l4, depth, method, confidence, sector, needs_review
          FROM nonorg
        ) TO '{STEP_OUT}' (FORMAT parquet)
    """)
    n, l1cov = con.sql(f"""
        SELECT count(*), round(100.0 * avg(CASE WHEN l1 <> 'XOT' THEN 1 ELSE 0 END), 1)
        FROM read_parquet('{STEP_OUT}')
    """).fetchone()
    return STEP_OUT, {"step_rows": n, "L1_coverage_pct": l1cov}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--no-llm", action="store_true", help="skip merging the frozen LLM proposals")
    ap.add_argument("--propagate", action="store_true", help="also emit row-level step_industry.parquet")
    ap.add_argument("--force-vocab", action="store_true", help="rebuild the company vocab cache")
    args = ap.parse_args()

    if args.force_vocab:
        export_company_vocab(force=True)

    path, manifest = build_company_table(args.cap, use_llm=not args.no_llm)
    print(f"wrote {path}")
    print(json.dumps(manifest, indent=2))

    # Transparency: a committed cache that yields 0 candidates almost always means
    # its proposals were fired under an OLDER prompt/schema version than the current
    # one (cache_key embeds llm.PROMPT_VERSION), so they are deliberately not reused.
    if not args.no_llm and manifest["llm_candidates"] == 0 and llm.CACHE_FILE.exists() \
            and llm.CACHE_FILE.stat().st_size > 0:
        print(f"\nnote: {llm.CACHE_FILE.name} exists but 0 candidates merged -- its "
              f"proposals were fired under an older prompt/schema version (current "
              f"PROMPT_VERSION={llm.PROMPT_VERSION}, reason-first jury). Re-fire with "
              f"`uv run python -m industry.fire_llm jury --limit N --execute`.")

    if args.propagate:
        spath, smanifest = propagate_to_steps()
        print(f"wrote {spath}")
        print(json.dumps(smanifest, indent=2))
        manifest["propagation"] = smanifest

    (RESULTS / "build_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {RESULTS / 'build_manifest.json'}")


if __name__ == "__main__":
    main()
