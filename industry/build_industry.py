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
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from . import classify, jury, llm
from . import taxonomy as T
from .common import STEPS_FILE, depth_coverage, export_company_vocab, load_company_vocab

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
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "career_steps": str(STEPS_FILE),
            "career_steps_mtime": STEPS_FILE.stat().st_mtime if STEPS_FILE.exists() else None,
        },
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


def propagate_to_steps(
    steps_path: Path | None = None, company_path: Path | None = None,
    out_path: Path | None = None,
) -> tuple[Path, dict]:
    """Join the company industry onto career steps; nonorg rows get their own
    row-level occupation prior. Heavy (full career_steps).

    Invariants (audit 2026-09-02 red H1/H2, tested in tests.py): exactly one
    output row per career step -- rows with a NULL company key and companies
    missing from the table are emitted as unresolved, never dropped; ``l1`` is
    always a top-level code (the prior's L2/L3 codes are truncated); XOT rows
    carry no sector."""
    steps_path = Path(steps_path) if steps_path else STEPS_FILE
    company_path = Path(company_path) if company_path else COMPANY_OUT
    out_path = Path(out_path) if out_path else STEP_OUT
    if not company_path.exists():
        raise SystemExit("run build_company_table first (company_industry.parquet missing)")
    con = duckdb.connect()
    # Prior tables for the nonorg rows, mirroring occupation_prior (kept in sync
    # via the test suite), with the derived path columns computed in Python so
    # the SQL never has to truncate codes.
    from .occupation_prior import _MAJOR_TO_INDUSTRY, _SOC_OVERRIDE  # noqa: SLF001

    def _prior_rows(d: dict) -> str:
        vals = []
        for k, (code, conf) in d.items():
            l = [T.truncate(code, i) for i in (1, 2, 3, 4)]
            sector = T.sector_of(code)
            vals.append(
                f"('{k}', '{code}', {conf}, '{sector}', {T.level_of(code)}, "
                + ", ".join("NULL" if v is None else f"'{v}'" for v in l) + ")")
        return ", ".join(vals)

    cols = "(k, code, conf, sector, depth, l1, l2, l3, l4)"
    con.sql(f"CREATE TEMP TABLE major_prior AS SELECT * FROM (VALUES {_prior_rows(_MAJOR_TO_INDUSTRY)}) t{cols}")
    con.sql(f"CREATE TEMP TABLE soc_prior AS SELECT * FROM (VALUES {_prior_rows(_SOC_OVERRIDE)}) t{cols}")
    steps = f"read_parquet('{steps_path}')"
    con.sql(f"""
        COPY (
          WITH steps AS (
            SELECT linkedin_id, experience_idx, position_idx, source_table,
                   company_canonical_id AS key,
                   -- row-level occupation: the deterministic 6-digit code, else the
                   -- pooled (jury) major group (green I5 at row grain)
                   replace(occupation_code, 'soc:', '') AS occ6,
                   coalesce(substr(replace(occupation_code, 'soc:', ''), 1, 2),
                            occupation_major_pooled) AS occ_major
            FROM {steps}
          ),
          org AS (
            SELECT s.linkedin_id, s.experience_idx, s.position_idx, s.source_table, s.key,
                   coalesce(c.industry_code, 'XOT') AS industry_code,
                   coalesce(c.l1, 'XOT') AS l1, c.l2, c.l3, c.l4,
                   coalesce(c.depth, 1) AS depth,
                   coalesce(c.method, 'unresolved') AS method,
                   coalesce(c.confidence, 0.0) AS confidence,
                   CASE WHEN coalesce(c.industry_code, 'XOT') = 'XOT' THEN NULL ELSE c.sector END AS sector,
                   coalesce(c.needs_review, TRUE) AS needs_review
            FROM steps s LEFT JOIN read_parquet('{company_path}') c USING (key)
            WHERE s.key LIKE 'id:%' OR s.key LIKE 'raw:%'
          ),
          nonorg AS (
            SELECT s.linkedin_id, s.experience_idx, s.position_idx, s.source_table, s.key,
                   coalesce(o.code, m.code, 'XOT') AS industry_code,
                   coalesce(o.l1, m.l1, 'XOT') AS l1,
                   coalesce(o.l2, m.l2) AS l2, coalesce(o.l3, m.l3) AS l3, coalesce(o.l4, m.l4) AS l4,
                   coalesce(o.depth, m.depth, 1) AS depth,
                   CASE WHEN o.code IS NOT NULL OR m.code IS NOT NULL
                        THEN 'occupation_prior' ELSE 'unresolved' END AS method,
                   coalesce(o.conf, m.conf, 0.0) AS confidence,
                   coalesce(o.sector, m.sector) AS sector,
                   TRUE AS needs_review
            FROM steps s
            LEFT JOIN soc_prior  o ON o.k = s.occ6
            LEFT JOIN major_prior m ON m.k = s.occ_major
            WHERE s.key IS NULL OR (s.key NOT LIKE 'id:%' AND s.key NOT LIKE 'raw:%')
          )
          SELECT linkedin_id, experience_idx, position_idx, source_table, key,
                 industry_code, l1, l2, l3, l4, depth, method, confidence, sector, needs_review
          FROM org
          UNION ALL BY NAME
          SELECT linkedin_id, experience_idx, position_idx, source_table, key,
                 industry_code, l1, l2, l3, l4, depth, method, confidence, sector, needs_review
          FROM nonorg
        ) TO '{out_path}' (FORMAT parquet)
    """)
    n_in = con.sql(f"SELECT count(*) FROM {steps}").fetchone()[0]
    n, l1cov, dotted = con.sql(f"""
        SELECT count(*), round(100.0 * avg(CASE WHEN l1 <> 'XOT' THEN 1 ELSE 0 END), 2),
               sum(CASE WHEN l1 LIKE '%.%' THEN 1 ELSE 0 END)
        FROM read_parquet('{out_path}')
    """).fetchone()
    if n != n_in:
        raise AssertionError(f"propagation dropped rows: {n_in:,} steps in, {n:,} out")
    if dotted:
        raise AssertionError(f"{dotted:,} step rows carry a dotted l1")
    null_keys, nonorg_rows, missing = con.sql(f"""
        SELECT sum(CASE WHEN key IS NULL THEN 1 ELSE 0 END),
               sum(CASE WHEN key LIKE 'nonorg:%' THEN 1 ELSE 0 END),
               sum(CASE WHEN (key LIKE 'id:%' OR key LIKE 'raw:%') AND method = 'unresolved'
                         AND confidence = 0.0 AND key NOT IN (SELECT key FROM read_parquet('{company_path}'))
                        THEN 1 ELSE 0 END)
        FROM read_parquet('{out_path}')
    """).fetchone()
    return out_path, {
        "step_rows": n, "L1_coverage_pct": l1cov,
        "null_key_rows": int(null_keys or 0), "nonorg_rows": int(nonorg_rows or 0),
        "org_rows_missing_company": int(missing or 0),
    }


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
