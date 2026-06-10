"""Pre-flight doctor for the industry layer -- run this FIRST.

    uv run python -m industry.doctor

Checks every prerequisite for the deterministic backbone AND the LLM-as-jury layer,
then prints the exact next command for your situation. It is read-only and safe:
it never calls the API, never mutates the cache, and never needs a key. Each line
is [ OK ] / [WARN] / [FAIL] with a one-line fix, followed by a tailored NEXT STEPS.

The whole point: a new user (or you, six months from now) can run one command and
know exactly what to do next -- no spelunking through five modules.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent

_ok = "\033[32m OK \033[0m"
_warn = "\033[33mWARN\033[0m"
_fail = "\033[31mFAIL\033[0m"


def _line(status: str, label: str, detail: str = "") -> None:
    print(f"  [{status}] {label}" + (f" -- {detail}" if detail else ""))


def main() -> None:
    print("=" * 68)
    print("industry/ doctor -- prerequisites for the classifier + LLM jury")
    print("=" * 68)

    steps: list[str] = []

    # 1. taxonomy + deterministic stack import and validate ---------------------
    print("\ncore (deterministic backbone -- needs no data, no key):")
    try:
        from . import taxonomy as T
        from . import classify, jury  # noqa: F401
        summary = T.validate()
        _line(_ok, "taxonomy + classifier import & validate",
              f"{summary['n_nodes']} nodes, schema reason-first="
              f"{T.output_json_schema()['required'][0] == 'rationale'}")
    except Exception as e:  # pragma: no cover - defensive
        _line(_fail, "core import failed", repr(e))
        print("\nfix the import error above before continuing.")
        return

    # 2. anthropic SDK (only needed to FIRE the jury; build/eval don't need it) --
    print("\nLLM jury layer:")
    has_sdk = importlib.util.find_spec("anthropic") is not None
    _line(_ok if has_sdk else _warn, "anthropic SDK",
          "installed" if has_sdk else "missing -> `uv sync --group llm` (only needed to FIRE)")
    if not has_sdk:
        steps.append("uv sync --group llm        # install the anthropic SDK (to fire jurors)")

    # 3. credentials (only needed to FIRE) --------------------------------------
    from . import llm
    has_cred = llm._has_credentials()  # noqa: SLF001
    _line(_ok if has_cred else _warn, "Anthropic credential",
          "found" if has_cred else "none -> `ant auth login` or export ANTHROPIC_API_KEY (only to FIRE)")
    if not has_cred:
        steps.append('ant auth login             # or: export ANTHROPIC_API_KEY=...   (to fire jurors)')

    # 3b. fully-local backend (Ollama host pool) -- no key, no PII egress --------
    from . import local_llm, llm_pool
    pool = llm_pool.HostPool()
    if pool.hosts:
        for h in pool.hosts:
            _line(_ok, f"Ollama host '{h.name}'",
                  f"{h.base_url}  x{h.parallel} parallel, {len(h.models)} models pulled")
        want = dict.fromkeys(
            local_llm._model_name(m)  # noqa: SLF001
            for m in (*local_llm.LOCAL_JURY, local_llm.LOCAL_BULK, local_llm.LOCAL_HEAD))
        for bare in want:
            on = [h.name for h in pool.serves(bare)]
            _line(_ok if on else _warn, f"  model {bare}",
                  f"on {on}" if on else "not pulled on any live host")
            if not on:
                steps.append(f"ollama pull {bare}        # on the host that should serve it")
    else:
        _line(_warn, "Ollama host pool",
              "no host reachable -> `ollama serve` locally, or bring up the framework "
              "(see SETUP.md for the tailnet bind)")

    # 4. frozen proposal cache --------------------------------------------------
    cache = llm.load_cache()
    if cache:
        models = sorted({p.model for p in cache.values()})
        is_panel = len(models) >= 2
        _line(_ok if is_panel else _warn, "frozen proposal cache",
              f"{len(cache):,} proposals from {models}"
              + ("" if is_panel else "  (single juror -> fire `jury`/`calibrate` for a real panel)"))
        if not is_panel:
            steps.append("uv run python -m industry.fire_llm calibrate --execute   # add Sonnet+Opus jurors on the gold set")
    else:
        _line(_warn, "frozen proposal cache", "empty -> the pipeline runs deterministic-only until you fire")

    # 5. production data + vocab cache (needed to BUILD / fire on real companies)-
    print("\nproduction data (needed to build the company table / fire on real companies):")
    data = ROOT / "normalized" / "career_steps.parquet"
    _line(_ok if data.exists() else _warn, "normalized/career_steps.parquet",
          "present" if data.exists() else "missing -> run the upstream normalize step")
    vocab = HERE / "cache" / "company_vocab.parquet"
    if vocab.exists():
        _line(_ok, "company_vocab.parquet (cache)", "present")
    elif data.exists():
        _line(_warn, "company_vocab.parquet (cache)", "will be built on first run (~1-2 min)")
    else:
        _line(_warn, "company_vocab.parquet (cache)", "needs career_steps.parquet first")

    # 6. results present? -------------------------------------------------------
    evalf = HERE / "results" / "industry_eval.json"
    if evalf.exists():
        with evalf.open() as fh:
            ev = json.load(fh)
        g = ev.get("gold_companies", {}).get("per_level", {})
        if g:
            _line(_ok, "last gold eval", "  ".join(f"{k} P={v['precision']}" for k, v in g.items()))

    # ---- tailored next steps (what to do RIGHT NOW given your state) ----------
    print("\n" + "=" * 68)
    print("NEXT STEPS (tailored to your current state)")
    print("=" * 68)
    print("  always available (no data, no key):")
    print("    uv run python -m industry.tests           # deterministic tests")
    print("    uv run python -m industry.run_industry    # gold eval + offline calibration")
    if steps:
        print("\n  to enable / improve the LLM jury, in order:")
        for s in steps:
            print(f"    {s}")
    if data.exists():
        print("\n  build the production company table (deterministic backbone):")
        print("    uv run python -m industry.build_industry --propagate")
        print("\n  preview a jury firing (safe, no API call, shows cost):")
        print("    uv run python -m industry.fire_llm jury --limit 2000")

    # ---- full pipeline (the whole thing, in order, cold start) ----------------
    _full_run()
    print("\n  full guide: industry/SETUP.md")


def _full_run() -> None:
    """Print the complete end-to-end pipeline, in order, with prerequisites."""
    print("\n" + "=" * 68)
    print("FULL RUN (end to end, in order)")
    print("=" * 68)
    print("""  # 1. Orient + sanity-check -- no key, no data, always safe
  uv run python -m industry.doctor
  uv run python -m industry.tests
  uv run python -m industry.run_industry        # gold P/R + offline calibration
  uv run python -m industry.taxonomy build      # (only if you edited taxonomy.py)

  # 2. Build the deterministic backbone -- needs normalized/career_steps.parquet
  uv run python -m industry.build_industry --propagate   # company + step tables

  # 3. Enable the LLM jury -- only needed to FIRE (build/eval never need a key)
  uv sync --group llm                           # install the anthropic SDK
  ant auth login                                # or: export ANTHROPIC_API_KEY=...

  # 4. Fire the jury (Batch API; each mode previews cost first, --execute fires).
  #    Order: calibrate (cheap, validates the panel) -> head jury -> bulk tail.
  uv run python -m industry.fire_llm calibrate --execute          # panel on the gold set
  uv run python -m industry.fire_llm jury --limit 20000 --execute # full panel, residual head
  uv run python -m industry.fire_llm tail --execute               # single cheap juror, the rest

  # 5. Re-merge the frozen jury cache + re-read calibration
  uv run python -m industry.build_industry --propagate            # merges llm_* candidates
  uv run python -m industry.run_industry --full                   # calibration + prod coverage

  # Extend the calibration gold set (no API): label the worksheet, paste into
  # industry/gold_residual.py, then re-run step 4's `calibrate`.
  uv run python -m industry.fire_llm sample-gold --limit 150""")
    print("\n  --- FULLY LOCAL variant (Ollama host pool; no key, no PII egress, free) ---")
    print("""  # the pool uses every reachable Ollama daemon: this machine + the framework
  # (tailnet). Placement is automatic: a juror runs where its model is pulled.
  uv run python -m industry.fire_llm calibrate --backend local --execute
  uv run python -m industry.fire_llm jury --backend local --limit 2000 --execute
  uv run python -m industry.fire_llm tail --backend local --execute
  uv run python -m industry.build_industry --propagate   # merges local jurors too
  uv run python -m industry.run_industry                 # calibration picks them up""")


if __name__ == "__main__":
    main()
