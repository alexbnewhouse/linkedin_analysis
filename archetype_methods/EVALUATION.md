# Evaluation: protocol, results, and what they mean

Date: 2026-09-17. Tables are generated into `results/benchmark.md` by
`bench.py`; the numbers quoted here were copied from that file on the same day.

## 1. The gold set

**Sampling.** 400 roles from the universe (roles held by five or more
people), 100 from each person-support band: A (1,000 or more holders), B
(100 to 999), C (20 to 99), D (5 to 19). Seed 20260917. Band A is where the
population lives (the 829 roles in that band carry half of all person-role
holdings in the universe, as much as the other 109,000 roles together); band D
is where any method has to survive noise. Person-
weighted metrics weight each gold role by its holder count, so band A
dominates them and a single role ("Owner", 60,573 holders) is 13% of the
person weight on its own.

**Labels.** Each role received a primary archetype, an optional secondary
archetype when the role is genuinely hybrid, and a fit grade:

| fit | meaning | rule of thumb |
|---|---|---|
| strong | the framework has an obvious home for this work | a pathway lists this title or a near synonym |
| weak | placeable only by stretching an orientation statement | nurse aide as a helper, hydraulic engineer as a builder, HR director as a leader |
| none | outside all nine orientations | trades, production, transport, clinical practice, uniformed service, and placeholder titles (owner, founder, unemployed, intern, member) |

Labeling conventions that matter for reading the confusions:

- The archetype describes the work, not the industry, as the framework
  instructs. A functional manager belongs to the function: marketing manager
  to communicators, sales manager to connectors, accounting manager to
  stewards, IT director to builders. General management, project and program
  management, administration, and executives go to leaders.
- Sales representatives and account executives are connectors (the framework
  puts Sales there). Retail frontline work (sales associate, cashier) is
  helpers, weak, because the framework's nearest pathway is Hospitality and
  Guest Experience.
- Clinical licensed practice (physician, registered nurse, pharmacist,
  pharmacy technician, laboratory technician) is none. Aides and companions
  (home health aide, nanny, camp counselor) are helpers, weak.
- Real-estate agents and brokers are connectors, weak. Financial advisors and
  loan officers are stewards, weak, with connectors secondary.
- "Owner", "Founder", "Independent Contractor" and similar are none: the
  framework's work-context dimension holds founder and freelancer, and the
  title says nothing about the work. A method that labels "Owner" as leaders
  is scored wrong; that is deliberate.

**Who labeled.** One annotator (the assistant, from the title, raw title,
SOC code, industry, and self-employment share). There is no second human
annotator yet, so the label noise is unknown. The 27B zero-shot result (D3)
doubles as an agreement estimate: it disagreed with the annotator on 19% of
roles, concentrated in the weak-fit stratum, which is where the framework
itself is ambiguous.

Distribution of the gold, unweighted: leaders 66, none 61, connectors 47,
stewards 46, helpers 41, communicators 40, builders 39, researchers 37,
analysts 13, advocates 10. Person-weighted fit: strong 45%, weak 30%, none
25%.

## 2. Metrics

For methods that output labels (deductive, mixed, LLM):

| metric | definition |
|---|---|
| coverage | share of gold roles given a label other than abstain |
| strict | prediction equals the primary label (abstain counts as wrong; a correct "none" counts as right) |
| lenient | prediction equals primary or secondary |
| strict w | strict, person-weighted |
| assigned | strict among the roles the method did label (the precision side of abstention) |
| macro F1 | mean F1 over the ten labels (nine archetypes plus none) |
| by fit | strict within the strong, weak, and none strata |

For clusterings (inductive): adjusted mutual information with the gold
labels; recoverability, the accuracy of the majority cluster-to-archetype map
under five-fold cross-validation over gold roles (with the in-sample value in
parentheses, which is what a hand-mapped cluster set would score at best);
person-weighted SOC-major purity; the largest cluster's person share; the
effective number of clusters; and stability, the adjusted Rand index between
two random seeds.

For every full-universe labeled method: pairwise person-weighted Cohen's
kappa, and the person-weighted share of the universe each method sends to
each label.

## 3. Cost and throughput (measured on this hardware)

| step | scale | time |
|---|---|---|
| bge-base embeddings, role titles | 110,344 roles | 40 s on the 5080 |
| bge-base embeddings, step descriptions | 171,907 descriptions | 4.5 min on the 5080 |
| k-means, k = 80, 110k by 768 | one run | about 2 min on 24 threads |
| kNN graph, k = 15 | 110k | 3 s on the 5080 |
| mobility SVD, 64 dims | 1.75M edges | 22 s |
| logistic regression on 23.6k weak labels | 110k by 808 | 42 s |
| 27B zero-shot, 50 titles per call | 400 roles | 8 calls, 45 s each, run in parallel |
| 8B zero-shot, 50 titles per call | 400 roles | 8 calls, 75 to 115 s each, run in parallel on a busy GPU |

Scaling the 27B zero-shot to the whole universe: 110k roles at 50 per call is
2,200 calls at 45 s, about 28 hours serial on the Strix Halo, or about a day
at the concurrency measured here. The 829 band-A roles that carry most of the
population take 17 calls. A head-first run (band A and B, 8,164 roles, about
two hours) followed by M3 for the tail is the practical shape.

## 4. Results

Full tables: `results/benchmark.md`. The headline table, strict accuracy on
the 400 gold roles (abstentions count as wrong, a correct "none" counts as
right):

| method | family | cov | strict | strict w | macro F1 | strong / weak / none |
|---|---|---|---|---|---|---|
| D3 LLM zero-shot, 27B | deductive | 1.00 | 0.81 | 0.92 | 0.81 | 0.93 / 0.67 / 0.75 |
| M3 bootstrapped classifier | mixed | 1.00 | 0.69 | 0.82 | 0.66 | 0.81 / 0.47 / 0.82 |
| M5 vote (D1, D2, M1b, M3) | mixed | 0.89 | 0.67 | 0.81 | 0.69 | 0.79 / 0.45 / 0.75 |
| D2 seed nearest-neighbor | deductive | 1.00 | 0.64 | 0.74 | 0.61 | 0.80 / 0.40 / 0.62 |
| M2x geometry times mobility | mixed | 1.00 | 0.62 | 0.72 | 0.59 | 0.71 / 0.40 / 0.79 |
| M1b embedding label spread | mixed | 1.00 | 0.60 | 0.73 | 0.58 | 0.69 / 0.38 / 0.82 |
| D1 lexicon and SOC crosswalk | deductive | 0.90 | 0.57 | 0.76 | 0.58 | 0.64 / 0.48 / 0.57 |
| D3 LLM zero-shot, 8B | deductive | 0.99 | 0.56 | 0.67 | 0.53 | 0.63 / 0.47 / 0.51 |
| M2 mobility label spread | mixed | 1.00 | 0.55 | 0.63 | 0.51 | 0.65 / 0.32 / 0.74 |
| D2p prototype cosine | deductive | 1.00 | 0.51 | 0.65 | 0.51 | 0.70 / 0.34 / 0.30 |
| D4 O*NET bridge | deductive | 0.85 | 0.49 | 0.65 | 0.50 | 0.55 / 0.40 / 0.51 |
| M4 cluster then map (I1, k = 80) | mixed | 0.82 | 0.43 | 0.63 | 0.44 | 0.45 / 0.28 / 0.72 |
| M1 seeded k-means | mixed | 1.00 | 0.32 | 0.32 | 0.34 | 0.34 / 0.24 / 0.44 |

Clusterings, scored on how much framework structure they already contain:

| clustering | k | AMI | recoverability, cross-validated (in-sample) | SOC purity | stability |
|---|---|---|---|---|---|
| I2 descriptions | 20 | 0.32 | 0.54 (0.55) | 0.48 | 0.63 |
| I2 descriptions | 80 | 0.29 | 0.55 (0.70) | 0.62 | 0.58 |
| I1 titles | 20 | 0.20 | 0.39 (0.45) | 0.52 | 0.63 |
| I1 titles | 80 | 0.21 | 0.45 (0.61) | 0.63 | 0.62 |
| I3 mobility | 20 | 0.19 | 0.40 (0.44) | 0.47 | 0.51 |
| I3 mobility | 80 | 0.16 | 0.32 (0.53) | 0.52 | 0.76 |

## 5. What the results say

**The framework covers about three quarters of the head, and only half of it
comfortably.** Person-weighted, 45% of gold roles fit an archetype strongly,
30% weakly, 25% not at all. The 25% is not exotic: it is "Owner" and
"Founder" (titles that name a work context, not work), clinical practice,
trades, production, transport, uniformed service, and retail frontline
titles. Every method's accuracy splits the same way: high on strong-fit
roles, mediocre on weak-fit, and the "none" class is where the methods
differ most. Any production assignment needs an explicit residual, and the
share of people in it is a finding to publish, not a defect to hide.

**A 27B local model reading the framework is the ceiling, at 81% strict and
93% on strong-fit roles.** Its errors are the framework's ambiguities:
"Owner"-type placeholders it calls leaders, helper roles it calls none or
leaders, functional managers it calls leaders. The 8B model is 26 points
worse and cannot be used for this; it labels teachers as helpers. Cost puts
the 27B out of reach for the whole vocabulary (about a day of Strix Halo time
for the 110k head) but well within reach for the population-bearing bands A
and B (about two hours).

**The best non-LLM method is the bootstrapped classifier at 69%,** trained on
23.6k weak labels that come entirely from the framework's titles, a short
"none" list, and SOC majors that are outside the framework. It beats every
pure deductive method because it can use SOC, industry, and self-employment
alongside the title, and it is the only cheap method that handles "none" and
strong-fit roles equally well (82% and 81%). Its weak spot is the weak-fit
stratum (47%), which is the framework's weak spot too. With a 0.5 probability
floor it abstains on 23% of roles and is right 76% of the time on the rest.

**Pure deduction tops out in the low 60s.** Seed nearest-neighbor (64%) beats
the explainable lexicon (57%), the prototype paragraphs (51%), and the O*NET
bridge (49%). The orientation statements and skills lists, which are the
framework's intellectual content, are its least useful part for
classification: a role is closer to "I bring people, processes, and
resources together" than to any other paragraph far too often. The O*NET
bridge inherits the corpus's SOC coding, which sends "Owner" to a physician
code and "Operations" to a protective-service code. Abstention floors on the
embedding methods trade coverage for precision at a poor rate: at 70%
coverage the seed method is 70% right on what it labels.

**Label spreading works once the seed classes are balanced, and mobility adds
information the title does not have.** Spreading seeds over the title-embedding
graph gives 60%; over the transition graph 55%; requiring both to agree gives
62%, and the mobility signal's best per-label scores are on analysts and
builders, where titles are noisiest. Seeded k-means (32%) fails: ten centroids
cannot hold a space that the inductive runs say wants sixty or more.

**Inductively, the data does not want nine archetypes, and descriptions are
a better lens than titles.** At every k the description clusters (I2) contain
more of the framework's structure than the title clusters (I1) or the
mobility blocks (I3): AMI 0.32 against 0.20 and 0.19, and a cluster-to-
archetype map that reaches 54% cross-validated against 39% and 40%. The
description clusters at k = 20 are readable as archetypes with the framework's
gaps drawn in: a teaching cluster (17 of 20 gold votes are researchers), a
production cluster (12 of 12 communicators), a marketing and design cluster
(13 of 15 communicators), a software and product cluster, a finance and
administration cluster, a clinical cluster, a protective-service cluster, a
food-and-hospitality cluster, and an owner-and-president cluster. What the
descriptions refuse to separate is what the framework separates by fiat:
sales, general management, and operations sit in one cluster (the largest,
11% of people), and administration sits with accounting.

**Cluster-then-map is the wrong direction for this framework.** Asked to name
80 title clusters, the 27B model called 12 mixed and 18 none; those thirty
clusters hold 40% of people. The mixed ones are the generic-noun clusters
(managers, representatives, specialists, coordinators, analysts,
administrators) that titles form and archetypes cut across. Mapping clusters
to archetypes scores 43%.

**Methods agree with each other less than they agree with the gold.**
Person-weighted kappa between the full-universe methods runs 0.4 to 0.7; the
vote agrees with its members at 0.75 to 0.90. The population shares differ
accordingly: leaders is 10% of people under mobility spreading and 29% under
the lexicon, because the lexicon's SOC layer sends every management code to
leaders while the transition graph puts functional managers with their
function. The share of the population in each archetype is therefore a
method-dependent number until a method is chosen and its bias measured.

## 6. Caveats

- One annotator, no adjudication. Weak-fit labels are the annotator's
  reading of the orientation statements and should be checked by the
  framework's author before any number is published.
- The gold is stratified by support, not by archetype, so advocates (10) and
  analysts (13) are thin; their per-label F1 has wide error.
- "Owner" alone is 13% of person weight in the gold. The person-weighted
  columns say more about that one role than about the method.
- The universe excludes roles with fewer than five holders (28% of steps).
  Nothing here says how any method behaves on the long tail.
- Descriptions cover 48% of steps and are written by the people who chose
  the titles; I2 is not an independent check on the title, only a richer
  reading of it.
- The SOC codes and industry labels come from the repo's own juries and carry
  their errors into D1, D4, and M3.
- D3 and M4 used the same 27B model, so M4's "mixed" verdicts are not
  independent of D3's labels.
