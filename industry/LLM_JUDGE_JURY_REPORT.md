# LLM-as-judge / LLM-as-jury: best practices and their applicability to the industry classifier

> **Research report, 2026-06-09.** Deep-dive on the LLM-as-judge / LLM-as-jury
> literature, distilled into best practices, then mapped onto the 4-level industry
> classification task as built in `industry/` (see `README.md`, `INDUSTRY_PLAN.md`).
> Scope: *should* and *how* we borrow from this literature; what transfers, what
> doesn't, and a concrete proposed design. Sources are listed at the end.
>
> **Status — implemented (2026-06-09).** The recommendations below are built:
> reason-before-verdict output schema (`taxonomy.output_json_schema`), the
> hierarchical-consensus jury (`jury.py`), the diverse Claude-tier panel +
> triaged firing (`llm.propose_panel`, `fire_llm` modes `tail`/`jury`/`calibrate`),
> agreement-based propose-only merge into `llm_*` columns (`build_industry`), the
> rebuilt calibration harness + residual gold set (`run_industry.llm_calibration`,
> `gold_residual.py`), the labeling-worksheet sampler (`fire_llm sample-gold`), and
> idiot-proof onboarding (`doctor.py`, `SETUP.md`), and an **entirely-local jury
> backend** (`local_llm.py`, Gemma/Phi/Llama via Ollama — no key, no PII egress).
> The §6 table notes what shipped per item. Not built (documented as future): the
> human inter-annotator labeling for the full AltTest (the harness + seed gold are
> ready for it) and reference-guided few-shot retrieval.

---

## 0. TL;DR

The LLM-as-judge literature is about **evaluating generated text** (scoring or
ranking model outputs); our task is **classification** (assign one of 162 taxonomy
codes to a company). They are different, and roughly half the famous "judge biases"
(position, verbosity) are artifacts of *pairwise comparison* and **do not apply** to
single-label classification. But the *disciplines* that make a judge trustworthy —
reasoning-before-verdict, rubric decomposition, reference grounding, principled
abstention, calibration against a human gold set, and above all **panels (juries)
with disagreement-as-signal** — transfer cleanly and are directly useful to us.

Five findings, in priority order:

1. **The single highest-leverage idea is a *hierarchical jury*.** A panel of diverse
   models, aggregated by **walking the taxonomy top-down and stopping at the deepest
   level a majority of jurors agree on**, is a near-perfect fit for our depth-truncated,
   partial-assignment design (§3.8). Juror *agreement sets the depth*; juror
   *disagreement routes to the review queue*. This is a generalization of what
   `classify.py` already does with M1/M3/M5 — the LLM(s) just become additional jurors.
2. **Our self-reported confidence is miscalibrated and should not gate anything.**
   The 5,000 cached Haiku proposals are **95.9% "high"** (4,797/189/14). A judge that
   says "high" almost always carries no information. The literature is unambiguous that
   *verbalized* confidence is poorly calibrated; **agreement-based** confidence
   (jury vote spread, or self-consistency across samples) is the fix.
3. **We have never measured LLM accuracy on the population it actually labels.** The
   gold set (30 companies) is dominated by the curated head the deterministic stack
   already nails; the 5,000 tail proposals are **unvalidated against any gold**. The
   *Alternative Annotator Test* gives us the bar: the LLM must agree with humans at
   least as well as humans agree with each other, on the *residual*.
4. **Our output schema is backwards.** `output_json_schema()` requires
   `["code", "confidence", "rationale"]` — the verdict is emitted *first* and the
   rationale is a post-hoc justification. G-Eval shows reasoning-*before*-verdict
   materially improves judgments. Flip the field order.
5. **Don't jury the whole 2.99M companies.** Industry-from-name is easy and the
   deterministic backbone already covers it at P≈1.0. A jury earns its 3–5× cost
   only on the **hard residual** (no-token brand names, conglomerates,
   staffing-vs-client, gov-vs-contractor). Use a single cheap juror for the bulk and
   **escalate to a jury only on triggers** (low agreement, disagreement with the
   deterministic prior, or high row-frequency head companies).

---

## 1. The two paradigms, and what they are actually for

**LLM-as-judge.** One LLM scores or ranks the output of another, as a scalable proxy
for human evaluation. Two sub-modes: *pairwise* (which of A/B is better) and
*pointwise / single-grading* (score this one output on a rubric). Our classifier is
the pointwise analog — "grade" a company into a taxonomy node — so **pointwise
best practices are the ones that transfer**, and the pairwise-only biases largely
don't.

**LLM-as-jury (PoLL).** Replace one big judge with a *panel of several smaller,
diverse models* and aggregate their votes. Verga et al. ("Replacing Judges with
Juries", Cohere, 2024) showed a panel of **Command R + Claude Haiku + GPT-3.5**:

- **agrees with humans better than a single GPT-4 judge** — Cohen's κ on KILT QA:
  Natural Questions **0.763 vs 0.627**, TriviaQA **0.906 vs 0.841**, HotpotQA
  **0.867 vs 0.830**; Chatbot-Arena rank correlation Pearson **0.917 vs 0.817**;
- costs **7–8× less** than GPT-4 Turbo;
- shows **less intra-model bias** because the panel spans *disjoint model families*
  (a single GPT-4 judge over-ranks GPT-4 outputs — self-preference);
- aggregation: **max/majority voting** for discrete correct/incorrect, **mean
  pooling** for a 1–5 scale.

The jury's core value for us is not the averaging — it's that **inter-juror
(dis)agreement is a free, externally-grounded, calibratable uncertainty signal**,
which is exactly what our review-queue ratchet needs and exactly what a single
model's self-reported confidence fails to provide.

---

## 2. Best practices distilled (with what transfers to classification)

| # | Best practice (judge/jury literature) | Transfers to our 162-class task? |
|---|---|---|
| **B1** | **Reason before you verdict** (G-Eval CoT-style; lifts human-correlation ρ 0.51→0.66 on summarization). | **Yes, directly.** Emit `rationale` *before* `code`. We currently do the opposite. |
| **B2** | **Decompose the rubric** — score explicit dimensions, separate correctness from style. | **Partial.** Our "what does the org *do*" rubric is good; could add explicit sub-questions for the known-hard cases (staffing vs client, gov vs contractor, holding co.). |
| **B3** | **Reference-guided grading** — give the judge a gold/reference to anchor against. | **Yes.** Feed the curated answer for *similar* companies (retrieval/few-shot) or the NAICS crosswalk as an anchor for the residual. |
| **B4** | **Allow abstention** — a judge that can say "can't tell" is more precise. | **Yes, and we have it** (`XOT`/`XDV`). Underused as an *external* signal — jury disagreement should *force* abstention, not just model self-doubt. |
| **B5** | **Calibrate against a human gold set** (30–50+ labeled items), tune until aligned, recalibrate for drift. | **Yes — and this is our biggest gap.** Gold must cover the *residual* the LLM labels, not the easy head. |
| **B6** | **Verbalized confidence is unreliable**; prefer consistency-based or token-probability signals. | **Yes.** Replace/augment self-reported high/med/low with **agreement-based** confidence. |
| **B7** | **Self-inconsistency is real** ("Rating Roulette") — the same judge re-rates differently across runs. | **Yes.** Sampling the same model N× and measuring agreement is a cheap single-vendor "jury." |
| **B8** | **Jury > single judge**: diverse panel, vote-aggregate; disagreement = signal; cheaper. | **Yes — the centerpiece.** See §4. |
| **B9** | **Statistically justify replacement** (Alternative Annotator Test): LLM must match inter-human agreement before it substitutes for a human. | **Yes.** The acceptance bar for ever auto-applying a proposal (open decision §7.10). |
| — | **Position bias** (favoring A vs B by slot). | **N/A** — no pairwise comparison. |
| — | **Verbosity bias** (longer = higher score). | **N/A** for the verdict, but watch it in *rationale*-graded review. |
| — | **Self-preference / intra-model bias** (a model favors its own outputs). | **Relevant if** we ever use one Claude model to *judge* another Claude model's proposals, or use the proposer model in its own calibration. Mitigate with cross-family jurors. |
| — | **Prevalence / label bias** (over-predicting salient or prompt-early classes). | **Relevant.** With 162 codes listed in a fixed order, the model can drift toward salient/early labels. Worth measuring per-class precision, not just overall. |

---

## 3. Where `industry/` stands today (honest audit)

What the as-built system already does **well**, judged against the literature:

- **Propose-only, never autonomous** (§3.9). The LLM never overwrites a deterministic
  answer; proposals are review-queue candidates. This is the single most important
  guardrail and we have it.
- **Enum-constrained structured output** to the frozen taxonomy — the model *cannot*
  emit an off-taxonomy code (`output_json_schema()` / `all_codes()`). Eliminates a
  whole class of judge failure (free-text label drift).
- **Frozen, content-hashed cache** (`llm_proposals.jsonl`, keyed on
  evidence+model+prompt+schema) → reproducibility, the thing LLMs usually break.
- **Model split** (Haiku tail / Opus head) and **Batch API + system-prompt caching**
  of the taxonomy catalog — cost-disciplined, in the spirit of PoLL's "smaller models
  for the bulk."
- **A depth-truncating fusion engine** (`classify.py` §3.8) that already arbitrates
  multiple methods and emits a partial path — *this is a jury aggregator in
  embryo*; the LLM layer just isn't a juror in it yet.
- **A calibration harness exists** (`run_industry.llm_calibration`) mapping
  confidence band → observed precision.

What's **missing or wrong**, against the literature:

1. **Reasoning-after-verdict.** `output_json_schema()` requires
   `["code", "confidence", "rationale"]`; the code token is generated before any
   reasoning. **(B1 violated.)**
2. **Miscalibrated, trusted-by-default confidence.** 95.9% of cached proposals are
   "high"; nothing downstream should gate on a near-constant signal. **(B6.)**
3. **Single juror.** Every one of the 5,000 proposals is a single Haiku call. No
   panel, no self-consistency, no cross-family check, so no disagreement signal and
   no intra-model-bias mitigation. **(B7, B8.)**
4. **Unvalidated on its real population + a dead calibration path.** The gold set is
   30 companies dominated by the curated head; the tail proposals are checked against
   *nothing*. Worse, `llm_calibration` builds items with **Opus** keys and **empty
   titles/descriptions**, while the committed cache is **Haiku** proposals built from
   **full evidence** — different cache keys, so the two never intersect and
   calibration currently returns nothing. **(B5, B9.)**
5. **No abstention-by-disagreement.** `XOT` fires only on the model's *own* judgment
   of thin signal; there is no *external* trigger (e.g. jurors split) forcing
   abstention. **(B4.)**

---

## 4. The proposed design: a *hierarchical jury* wired into the existing fusion

This is the recommendation. It synthesizes PoLL aggregation (B8) with our
depth-truncated partial-assignment schema (§3.8), and it changes very little of the
architecture — the LLM(s) become jurors in the engine `classify.py` already is.

### 4.1 Hierarchical consensus = depth selection

Each juror emits a full path `p_k` (e.g. `FIN.BNK.COM.RET`), possibly at different
depths. Aggregate by walking **L1 → L4**:

```
consensus(paths, jurors=K, tau=majority):
  accepted = ""               # the agreed prefix
  for level in 1..4:
    votes = Counter(truncate(p, level) for p in paths if compatible(p, accepted))
    label, n = votes.most_common(1)
    if n / K >= tau and parent_of(label) == accepted:
        accepted = label      # enough jurors agree at this depth -> descend
    else:
        break                 # jurors diverge here -> stop, emit the shallower path
  return accepted or "XOT", support_fraction_per_level
```

Why this is the right fit:

- **Agreement sets the depth.** Jurors that all say "Finance/Banking" but split on
  L3/L4 yield `FIN.BNK` — a *correct shallow* answer, never a *guessed deep* one.
  This is precisely the precision/recall-by-depth trade the plan wants, now driven by
  evidence instead of a single model's nerve.
- **The support fraction per level is a real, calibratable confidence** (B6) — "3/3
  at L1, 2/3 at L2, 1/3 at L3" — far better than "high."
- **Total disagreement (no L1 majority) → `XOT` + review** — principled,
  externally-grounded abstention (B4), feeding the existing ratchet.
- **The deterministic methods can be jurors too**, with veto/high weight: M1 curated
  (P≈1.0) as a juror that, when present, the others can only *corroborate* (raising
  confidence) or *contradict* (raising a review flag) — which is what `_from_spine`
  already does. The jury is a clean generalization of the current arbitration.

### 4.2 Who sits on the jury (given our PII/governance constraint)

The PoLL result wants *disjoint model families*, but `INDUSTRY_PLAN §7.9` flags that
the data is scraped profile text (PII), so shipping it to OpenAI/Cohere has ToS
implications. Two compliant ways to get most of the diversity benefit:

- **Intra-vendor jury / self-consistency (recommended default).** Sample across the
  Claude tiers — Haiku + Sonnet + Opus, or the *same* Haiku at temperature N× — and
  aggregate with §4.1. This captures within-model and cross-tier disagreement (B7)
  and keeps all data with one vendor. It is the cheapest way to kill the "95.9% high"
  problem: replace the verbalized band with the *agreement* band.
- **One local open-weight juror** (e.g. a small local model) added to the panel for
  genuine cross-family diversity with **no PII leaving the environment** — addresses
  the governance decision and the intra-model-bias point (B8) at once.
  **Built (`local_llm.py`):** in fact the panel can be made *entirely* local — a
  diverse on-device jury of **Gemma 3 12B + Phi-4 14B + Llama 3.1 8B** via Ollama
  (three disjoint families), enum-constrained to the taxonomy, writing the same
  frozen cache so local and cloud jurors mix freely. Validated end-to-end: on the
  gold set the local trio correctly calls Stripe *fintech*, the case the cloud
  Haiku run got wrong. The trade-off is throughput — it is serial on one GPU, so
  it is the privacy-preserving / zero-marginal-cost path, fired with `--limit`
  pilots, while the cloud Batch API remains the way to fan out over millions.

A true external-API multi-vendor jury is *not* recommended here purely on the PII
ground, even though it is the textbook PoLL configuration.

### 4.3 Triage — jury only where it pays

Industry-from-name is easy; the deterministic backbone already puts 42% of rows on
an L1 at P≈1.0, and a single Haiku call nails most self-describing names. Reserve the
jury (the 3–5× cost) for where it earns out:

- **Escalate to the full jury when** any of: (a) the cheap single juror returns
  shallow/low agreement, (b) the juror's L1 **disagrees with the deterministic prior**
  (M5 occupation prior, or a name-rule partial), or (c) the company is **high
  row-frequency** (head), where an error propagates to many career steps.
- **Single cheap juror** for the long low-frequency tail.
- **Never call the LLM at all** where M1/M3 already resolve at high precision — the
  current `_residual()` filter in `fire_llm.py` already enforces this; keep it.

This mirrors PoLL's economics: many cheap evaluations, escalation only on genuine
ambiguity.

---

## 5. Calibration & validation — the prerequisite before any auto-accept

Open decision §7.10 asks whether high-confidence proposals ever auto-apply. The
literature gives a concrete bar; here is the procedure to earn it:

1. **Build a residual gold set (the missing asset).** 150–300 hand-labeled companies
   **sampled from the LLM's actual target population** — the no-token brands,
   conglomerates, staffing agencies, holding companies, multilingual names — *not* the
   curated head. Stratify by L1 and by row-frequency band. This is the analog of the
   "30–50 human-labeled examples" calibration set (B5), sized up for a 162-class space.
2. **Fix the calibration harness.** Make `llm_calibration` key on the *same* model and
   the *same* evidence the cache was built from, so it actually intersects
   `llm_proposals.jsonl`. Then it can report **observed precision per
   agreement/confidence band**, per level.
3. **Apply the Alternative Annotator Test (B9).** Have ≥2 humans label a slice; compute
   inter-human agreement (Cohen's κ / Krippendorff's α over the *truncated-to-L1/L2*
   labels, since deep leaves are genuinely ambiguous even for humans). The LLM (or
   jury) may substitute for a human reviewer **only on the level where it agrees with
   humans at least as well as humans agree with each other** — almost certainly L1/L2,
   not L4.
4. **Auto-accept policy that falls out of this.** e.g. *"auto-apply a proposal at
   level L iff jury support ≥ τ_L **and** measured precision in that band ≥ the
   inter-human-agreement floor at L; otherwise → review queue."* Likely: L1/L2 may
   auto-apply at high agreement; L3/L4 always stay propose-only. This keeps the
   precision-first contract while letting the ratchet turn faster.

---

## 6. Concrete, prioritized changes

| Priority | Change | Shipped | Why (best practice) |
|---|---|---|---|
| **P0** | Flip `output_json_schema()` field order to `rationale` → `code` → `confidence` (reason before verdict). | ✅ `taxonomy.py`; `PROMPT_VERSION` bumped to 3 (busts the answer-first cache). | B1; free accuracy on the hard residual. |
| **P0** | Stop gating on verbalized `confidence`; treat the 95.9%-"high" field as advisory only. | ✅ jury **agreement** is the gating signal; `llm_confidence` is carried as advisory only. | B6. |
| **P1** | Build the **residual gold set** and **fix `llm_calibration`** to intersect the cache. | ✅ `gold_residual.py` (61 items keyed to real cache entries, incl. 2 planted misses); calibration reads the cache directly and joins by key — works offline. | B5, B9; the 5,000 proposals were unvalidated. |
| **P1** | Add a **panel** + the **hierarchical-consensus aggregator** (§4.1); emit agreement-per-level as confidence; route disagreement to `XOT`/review. | ✅ `jury.py` (`consensus`/`aggregate`), `llm.propose_panel`; degrades gracefully to a single juror. | B7, B8, B4. |
| **P2** | Make the LLM a **juror** corroborating the deterministic answer (M1 veto), generalizing the fusion. | ✅ merged in `build_industry` as a propose-only `llm_*` candidate + `llm_agrees_det`; never overwrites the deterministic spine. | B8; unifies the architecture. |
| **P2** | Add a **local open-weight juror** for cross-family diversity with no PII egress. | ✅ `local_llm.py` — an **entirely on-device** panel (Gemma/Phi/Llama via Ollama), enum-constrained, cache-compatible, coexists/mixes with the cloud jurors. `fire_llm … --backend local`. | B8 + governance. |
| **P2** | **Triage/escalation** (§4.3): single juror for the tail, full jury on the head. | ✅ `fire_llm` modes: `tail` (single Haiku) vs `jury` (full panel on the top-N head). | PoLL economics. |
| **P3** | Add **sub-questions** for the named hard cases, and **prevalence** reporting to catch label bias. | ✅ disambiguation rules in `_SYSTEM`; predicted-L1 prevalence in calibration. | B2, prevalence bias. |
| **P3** | Reference-guided few-shot anchored on the curated/NAICS labels. | ◻︎ not built — the catalog already carries NAICS hints; retrieval-of-similar-companies is the documented next step. | B3. |

---

## 7. What *not* to do

- **Don't run a jury over all 2.99M companies.** It's the easy bulk; a single cheap
  juror plus the deterministic backbone is right. Jury is for the ambiguous residual
  and the costly head only.
- **Don't trust "high."** A near-constant self-reported band cannot gate auto-accept;
  only an agreement-based, gold-validated band can.
- **Don't let the LLM (or jury) overwrite a deterministic answer.** M1/M3 precision-1.0
  stays the spine; the jury corroborates or flags, never replaces. (Already true —
  keep it.)
- **Don't ship scraped PII to a multi-vendor external panel** just to satisfy the
  textbook PoLL recipe; get diversity from cross-tier Claude + one local model.
- **Don't use the proposer model as its own judge** in any future eval loop
  (self-preference / intra-model bias) — keep proposer and evaluator in different
  families.

---

## 8. Bottom line on applicability

The judge/jury literature is *evaluation* literature, and a chunk of its most-cited
content (pairwise position/verbosity bias, win-rate calibration) is **not** about our
problem. But its deeper lessons are exactly on point for a hierarchical classifier
that already believes in partial assignment, precision-first arbitration, and a
human-gated review ratchet:

- **The jury, aggregated hierarchically, is the natural next evolution of our fusion
  engine** — it turns "how deep dare I label?" from a single model's nerve into a
  measurable consensus, and turns disagreement into the review-queue signal we already
  consume.
- **Agreement replaces self-reported confidence** as the thing we calibrate and gate on.
- **A residual gold set + the Alternative Annotator Test** is the missing measurement
  that would let any of this *ever* auto-apply without betraying the precision-first
  contract.

Everything above is additive to the as-built design and consistent with
`INDUSTRY_PLAN §3.8–3.9`; none of it requires abandoning the deterministic backbone,
which remains the reproducible spine and the fallback.

---

## Sources

- Verga et al., **"Replacing Judges with Juries: Evaluating LLM Generations with a
  Panel of Diverse Models"** (PoLL), Cohere, 2024 — <https://arxiv.org/abs/2404.18796>
- Liu et al., **"G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment"**,
  EMNLP 2023 (chain-of-thought-before-score) — via
  <https://arxiv.org/pdf/2408.09235> (reference-guided verdict) and
  <https://www.evidentlyai.com/llm-guide/llm-as-a-judge>
- **"The Alternative Annotator Test for LLM-as-a-Judge: How to Statistically Justify
  Replacing Human Annotators with LLMs"**, 2025 — <https://arxiv.org/pdf/2501.10970>
- **"Rating Roulette: Self-Inconsistency in LLM-as-a-Judge Frameworks"**, 2025 —
  <https://arxiv.org/pdf/2510.27106>
- Evidently AI, **"LLM-as-a-judge: a complete guide"** and **"Is this email okay? We
  asked a jury of LLM judges"** — <https://www.evidentlyai.com/llm-guide/llm-as-a-judge>,
  <https://www.evidentlyai.com/blog/llm-judges-jury>
- Comet, **"LLM Juries for Evaluation"** — <https://www.comet.com/site/blog/llm-juries-for-evaluation/>
- Deepchecks, **"What Is LLM-as-a-Judge Calibration? Power & Limits"** —
  <https://deepchecks.com/llm-judge-calibration-automated-issues/>
- Sebastian Sigl, **"The 5 Biases That Can Silently Kill Your LLM Evaluations"** —
  <https://www.sebastiansigl.com/blog/llm-judge-biases-and-how-to-fix-them/>
- On verbalized-confidence miscalibration: **"Direct Confidence Alignment"** —
  <https://arxiv.org/html/2512.11998v1>; Lin et al., "Teaching Models to Express Their
  Uncertainty in Words."
