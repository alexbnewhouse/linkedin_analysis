# Workflow ideas: what the subscriptions and the hardware could be doing

**Date:** 2026-09-02. **Context:** the employer/industry audit
(`docs/audits/2026-09-02-employer-industry-audit.md`) and the Phase 0 fixes that
landed the same day. This note is about the workbench, not the data: how the
Claude Code subscription, the Gemini Pro subscription, the Framework Desktop
(Strix Halo, 128 GB), and this box (RTX 5080, 24 threads) could each carry a
part of the work they are not carrying today. Measured facts are marked; the
rest are proposals, ordered inside each section by payoff per hour of setup.

Inventory on this machine today: `claude` 2.1.258 (Pro login, headless route
proven in `cleanlib/headless_claude.py`), `ollama`, `tailscale`, `gh`, `uv`,
`systemd-inhibit`. Not installed: `gemini` (Gemini CLI), `llama-server` on PATH
(it lives under `~/llm-serving`), any wake-on-LAN tool. The Framework has been
offline on every port since the evening of 2026-09-01.

---

## 1. The single biggest idea: a three-family jury

Every jury in this repo gates on agreement, and agreement only means something
when the jurors fail differently. Today every panel is either "two local Qwen
quantizations" or "Haiku plus Sonnet", which are siblings. The audit's CIP
tiebreak failed at 0.55 precisely because the disagreement band was
same-family noise. You now hold three independent model families at zero
marginal cost:

| Family | Route | Throughput on the subscription | Evidence stays on machine? |
|---|---|---|---|
| Anthropic | `claude -p` (headless, `--json-schema`) | measured 0.3 to 0.75 s/string at concurrency 4; Pro has 5-hour usage windows | no |
| Google | `gemini -p` (Gemini CLI, Google login; the AI Pro plan lifts the free 60 rpm / 1,000 rpd ceiling) | 25 items per call gives roughly 25k items/day on the free ceiling alone | no |
| Open weights | `industry/llm_pool.py` lanes: Qwen3-30B-A3B on the 5080 (measured about 200 tok/s aggregate), Qwen3.6-35B-A3B on the Framework (60 to 86 tok/s single stream, more batched) | about 2.3 items/s per lane measured in June | yes |

A unanimous L1 vote from Claude, Gemini and Qwen on a company with 1,960
characters of evidence is a different object from two Qwen quantizations
agreeing. Concretely:

- Add an `api="gemini"` host next to the planned `api="claude"` host in the pool
  (refactor plan E-3). Both are subprocess transports with a JSON schema; the
  `headless_claude.py` adapter is 88 lines and the Gemini one would be the same
  shape (`gemini -p --output-format json`).
- Re-run the industry head (ranks 1 to 30k, about 70% L1 coverage) as a
  three-family panel. Land unanimous L1 as `curated` with a `jury3_v1` method
  tag; send the majority band to review; abstain on three-way splits. The June
  agreement bands (unanimous 1.0 on n=24, majority 0.941 on n=34) were measured
  on a same-family panel and should be re-measured on this one using the
  residual gold.
- Reuse the same panel for the two open decisions that need a second blind
  annotator: the 100-company gate on the curated head, and the CIP gold v1
  double-label sheet (`gold_v1 sheet` / `gold_v1 agree` already compute Cohen's
  kappa; Gemini can be the second annotator this afternoon instead of waiting on
  a person).

Policy note: cloud jurors see company names, employee titles and up to three
self-written job descriptions. That is the same class of text this Claude Code
session reads every day. If the answer is still "local only" for production
votes, the three-family panel degrades to local-plus-one-cloud-for-gold, which
is what the June design did.

## 2. Gemini Pro specifically

- **Web-grounded curation.** Gemini CLI has Google Search grounding. For each
  of the top 3k unresolved company ids, ask for the company's primary industry
  with a source URL, constrained to the taxonomy enum. That is an evidence class
  the pipeline has never had: external ground truth instead of profile text.
  Land it as its own tier (`web_grounded_v1`) and let the three-family vote
  arbitrate when it disagrees with profile evidence (a staffing agency's
  profiles look like their clients; the web knows they are staffing).
- **Sibling-id resolution.** The audit found 14,755 display names split across
  32,858 company ids (aon / aon-risk-services, 3m / 3m_2, netflix / netflixl).
  "Are these two LinkedIn slugs the same organization?" is a knowledge
  question, cheap for a grounded model and expensive for string matching.
  Output: an extension of `career_company_id_alias.parquet` (3 rows today).
- **Whole-band adjudication in one context.** Gemini's 1M-token window fits
  about 1,500 companies with full evidence per call. For the head, one call per
  1,500 with a tabular answer is faster than 1,500 calls, and the model sees
  siblings next to each other. Keep the append-only cache contract: each
  company's vote is still written keyed by its own evidence hash.
- **NotebookLM as the methods reviewer.** Load `docs/methods/`, `FOUNDATION.md`,
  the audit and the team reports; ask it for contradictions and stale numbers
  before the NHA report is drafted. It is a reading tool, so nothing leaves
  beyond the docs you upload.
- **Deep Research for the taxonomy gaps.** The audit's name-rule review found
  whole categories the 162-node taxonomy handles badly (staffing, government
  contractors, personal services, publishers). A Deep Research pass on "how do
  NAICS and LinkedIn's own industry list carve these" is a one-hour way to
  decide whether to add nodes before the head is curated at scale.

## 3. Claude Code subscription specifically

- **Scheduled routines (cloud cron).** A nightly routine that runs
  `make check-freshness`, `make test`, and re-scores the residual gold, and
  posts a three-line summary. The freshness check exists as of today
  (`scripts/check_freshness.py`); the routine is the part that makes someone
  read it. A weekly routine can re-run the red team's queries (section 5).
- **Headless jury with the pool scheduler.** `career_clean/headless_bench.py`
  drives `claude -p` with its own thread pool. Moving it behind `llm_pool` (E-3)
  gets retries, host mark-down and resumable JSONL for free, and lets a Pro
  usage window run out gracefully (the pool marks the host down and the local
  lanes keep going).
- **Hooks that guard the contracts.** A `PreToolUse` hook on `git commit` that
  runs `make test` and `make lint`; a `PostToolUse` hook that runs
  `check_freshness --quiet` after any `build_*` or `run_*` command and prints
  the stale table if it fails. The statusline already parses jury logs; the
  hooks close the loop on the build side.
- **Worktrees for the jury-core migration.** The refactor plan's E-7 migrates
  four drivers onto `cleanlib/jury` with per-axis parity checks. Each axis is
  independent and each has a golden-hash test (E-1), so four worktrees with four
  subagents is the right shape. Data lives outside git, so each worktree needs
  symlinks to `normalized/`, `parsed/`, and the module `cache/` and `results/`
  directories; a `scripts/link_data.sh` would make that one command.
- **Artifacts for the portal.** The share build is a single HTML file; the
  portal already has an artifact URL. Publishing the file as part of `make
  portal` (via a routine, since the shell cannot call the Artifact tool) keeps
  stakeholders on the current build instead of an emailed zip.
- **Remote Control from the phone** for long runs: start `make refresh` or a
  jury tranche from the terminal, check `.build_status` from anywhere, get a
  push when a stage fails.

## 4. The Framework Desktop

Nothing here works until the box is on, and the audit's Phase 3 local tranche
(ranks 30k to 180k, about 2 days for two jurors) depends on it.

- **Make the lanes survive reboots.** The llama-server watchdogs are setsid'd
  user processes; that is why every reboot silently kills the pool. Two
  `systemd --user` units (`llama-4b.service`, `llama-bulk.service`) with
  `Restart=always` and `loginctl enable-linger alex` fix it permanently.
  Keep the 6,144-token slot floor from the serving notes.
- **Stop it sleeping.** The evening-of-09-01 outage looks like suspend. Either
  mask sleep targets (`systemctl mask sleep.target suspend.target`) or wrap
  runs in `systemd-inhibit --what=sleep --who=jury`. The pool driver could do
  the latter itself on the Framework side.
- **Wake it from here.** Wake-on-LAN over the LAN (or a Tailscale exit on the
  same subnet) makes "turn it on later" a `make wake-framework` target. Needs
  the MAC address and WoL enabled in firmware once.
- **Embeddings as a service.** The 128 GB box can hold a bge-large embedding
  server permanently. Two consumers exist already (`edu_clean/knn_tail.py`, the
  dead career embedding prefilter), and the sibling-id problem is a third: an
  ANN index over 3.4M company strings with evidence text finds "MetLife" next to
  "MetLife Investment Management" in milliseconds.
- **The overnight worker pattern.** A single long-lived process on the
  Framework that drains a queue of fire lists (JSONL in, votes JSONL out,
  resumable) is a better fit than SSH-launched runs that die with the session.
  `industry/run_tail.sh` is most of it; the queue is a directory.

## 5. This box (RTX 5080, 24 threads, 2.0M-profile parquet)

- **Red team as code.** Every finding in the red report came from a query
  that can be pinned. `industry/audit_checks.py` under `make test-data`: no
  dotted `l1`; inherited-id rows below a ceiling; every top-40 name-rule hit
  from the audit still resolves to the fixed L1; XOT rows carry no sector;
  `step_industry` row count equals `career_steps`; jury mapping unique on
  `role_canonical`. Several of these landed today as unit tests; the data-level
  versions are the regression guard for the next rebuild.
- **The 30B MoE lane is idle capacity.** The Q3 Qwen3-30B-A3B on the 5080 does
  about 200 tok/s aggregate and sits unused between jury runs. It is enough to
  run the industry tail (ranks 30k to 180k) alone in about 45 hours, without the
  Framework. Start it tonight with the resumable driver and let the Framework
  join when it is back.
- **Description mining, bounded.** The green report's E8 (what the work
  involves, from 5.5M free-text descriptions) is only feasible on-machine and
  only worth it for a bounded population. The windowed portal cohort's year-10
  steps are about 22k persons; a first pass on those alone is a few hours on
  the local lane and answers whether the signal is there.
- **DuckDB is the right substrate for the freq-1 tail.** Before firing any
  juror on the 1.4M singleton companies, a pure-SQL pass (has description, has
  title, name length, name has an industry token after the rule cleanup) can
  drop the half with no usable evidence at zero cost. The vocab already carries
  everything needed.

## 6. Process ideas that need no new tooling

- **A decision log.** Six decisions in the audit are the owner's to make (cloud
  juror on company evidence, curated-head provenance, canonical cohort, sector
  as a product requirement, refresh cadence, the `SNAPSHOT_YEAR` rename). A
  `docs/decisions/` folder with one dated file each, written when decided, is
  how the next agent avoids re-asking.
- **Every landing ends with `make refresh` and `make check-freshness`.** The
  audit's staleness table existed because nothing required it. The refresh
  driver now ends with the freshness check and fails if anything is stale.
- **Gold before jury, always.** The residual industry gold has 61 companies;
  `fire_llm sample-gold` writes a worksheet. A 200-company gold labeled blind by
  two families (Claude, Gemini) with disagreements resolved by hand is a
  morning's work and turns every later agreement band into a measured number.

## 7. What to do first

1. Install Gemini CLI, log in, and run the 100-company blind second pass on the
   curated head. The sample is already cut: feed
   `industry/results/head_gate_blind.jsonl` (evidence, no codes) to Gemini
   with the taxonomy catalog, write its `code` per `n` to
   `industry/results/head_gate_review.jsonl`, and run
   `uv run python -m industry.head_gate industry/results/head_gate_review.jsonl`.
   Cost: an hour. Payoff: the provenance gate the audit asked for,
   cross-family, with the disagreements listed for retraction.
2. Land the `claude` and `gemini` hosts in the pool (E-2, E-3) and the
   `fire_llm --backend` adapter (E-4). Then calibrate the three-family panel on
   the residual gold before firing anything at scale.
3. When the Framework is back: systemd units, suspend inhibit, and the overnight
   worker. Then the 30k to 180k tranche.
4. Nightly routine: freshness, tests, gold re-score, summary.
