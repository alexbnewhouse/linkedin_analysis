# IPEDS institution reference + LinkedIn crosswalk

Attaches institution metadata (control, Carnegie classification, level, region,
metro) to graduates, so downstream analyses can moderate humanities career
outcomes by **institution type** — a first-order axis that was entirely absent.

## Source
- `HD2023.csv` — IPEDS **Institutional Characteristics / Directory**, 2023 (HD2023),
  6,163 US Title-IV institutions. NCES, **US Gov public domain**.
  Re-fetch: `https://nces.ed.gov/ipeds/datacenter/data/HD2023.zip` (unzip → HD2023.csv).

## Build
`uv run python -m reference.build_ipeds_crosswalk --execute` produces:
- `normalized/mappings/school_ipeds.parquet` — `school_slug → unitid` + `match_method`
  (`exact` | `core` | `curated_flagship`) + `match_confidence`. One row per slug.
- `reference/institution_meta.parquet` — one row per `unitid`: `instnm`, `control` +
  `control_label`, `iclevel` + `iclevel_label`, `carnegie_c21basic` + `carnegie_label`,
  `state`, `region` (OBEREG), `cbsa_metro`, `city`.
- `reference/ipeds/_crosswalk_manifest.json` — coverage + method mix + a top-40 sample.

Tests: `uv run python -m reference.ipeds_tests`.

## Method (precision-first)
Match each slug's modal `school_raw` name (normalized: lowercased, `&`→and,
separators→space, stop-words dropped) to IPEDS `INSTNM`/`IALIAS`:
1. **exact** — normalized name == a *unique* IPEDS name.
2. **core** — normalized name == a *unique* IPEDS "core" (INSTNM minus the campus
   suffix after `-`/` at `), requiring ≥3 tokens (short cores like "university east"
   collide across schools — e.g. *University of the East* vs *University of East-West
   Medicine* — and are rejected).
3. **curated_flagship** — a small hand-verified map (`CURATED_FLAGSHIP`) resolving
   high-volume bare names that are multi-campus by rule (University of Washington →
   Seattle, Michigan → Ann Arbor, Maryland → College Park, …).
Everything else stays UNMATCHED. IPEDS is US Title-IV only vs ~40k LinkedIn slugs
(many foreign / sub-Title-IV / high schools), so a low *slug* match rate is expected.

## Coverage & precision (HD2023 build)
- **Slug coverage:** 3,733 / 39,634 slugs (9.4%).
- **Person-weighted coverage:** ~68% of all graduates; **~71% of L1-humanities persons.**
- **Precision:** gold-inspected (top-40 by volume + all 37 core + a mid-frequency
  exact sample) — no residual errors after the ≥3-token core guard; well above the
  0.95 precision bar. Method mix: exact 3,687 / core 37 / curated 9.

## Code → label decodes (documented in `build_ipeds_crosswalk.py`)
- `CONTROL`: 1 public, 2 private-nonprofit, 3 private-for-profit.
- `ICLEVEL`: 1 = 4yr+, 2 = 2yr, 3 = <2yr.
- `C21BASIC` (Carnegie 2021 Basic): bucketed — 15 R1, 16 R2, 17 doctoral/professional,
  18–20 master's, 21 bacc arts&sciences (liberal arts), 22–23 other bacc, special-focus
  and associate's families labelled; raw code passed through for finer analysis.

## Limitations
- Metadata is 2023-vintage; a graduate's institution attributes are treated as
  time-invariant (fine for control/type; Carnegie class can shift over decades).
- Only the modal `school_raw` per slug is matched; rare within-slug name variants
  are not separately resolved.
- No selectivity/admissions join yet (would need IPEDS `ADM2023`) — a follow-up.
