# Candidate methods for career work archetypes

Date: 2026-09-17. Status: a fresh survey, written and benchmarked without
reference to the shipped `archetypes/` module or its 2026-08-05 proposals.

The question every method answers: given a career step (a job title, held by
some person, at some employer, with a SOC code and often a free-text
description), what kind of work is it? An archetype is a class of work, not of
industry and not of seniority. The colleague's framework (nine archetypes,
75 pathways, 390 representative titles; transcribed in `framework.py`) is the
deductive prior throughout. It says explicitly that sector and work context are
separate dimensions, and the methods below keep them separate.

The unit of classification is the normalized title string (`role_canonical`),
which is what every other layer of the repo keys on. The universe for the
benchmark is the head of that vocabulary: the 110,344 roles held by five or
more people, which carry 72% of all career steps. Person-weighted numbers
weight each role by the number of distinct people who held it.

## What the data offers

| Signal | Coverage of steps | Used by |
|---|---|---|
| Title text (display + modal raw title) | 100% | D1, D2, I1, M1, M1b, M3 |
| SOC code, 6-digit, jury or deterministic | 21% detail, 61% major | D1, D4, M3 |
| Employer industry (L1) | 47% not "other" | M3 |
| Free-text description, more than 80 chars | 48% | I2 |
| Role-to-role transitions (who moves where) | 1.75M edges inside the universe | I3, M2 |
| Self-employment share, seniority | 100% | D1, M3 |

There is no skills field in the corpus. Skills are inferred, never observed.

## Inductive methods: let the archetypes emerge

The framework is not consulted. The output is a clustering, and the question
for the benchmark is how much of the framework's structure the data already
contains, and what structure it contains that the framework does not.

**I1. Title-embedding clusters.** Embed each role's title text with a
sentence encoder (bge-base), k-means at k = 9, 20, 40, 80, roles weighted by
the square root of their person count. The cheapest possible inductive method.
It answers: if you let titles alone group themselves, do the groups look like
archetypes? The cluster cards in `results/inductive.json` list each cluster's
most common titles.

**I2. Description-document clusters.** For every role with 20 or more
holders, pull up to six step descriptions written by different people, embed
each, average them into one vector per role, and cluster as in I1. This is the
only method that reads what people say they did rather than what they were
called. It answers: does the description evidence draw different boundaries
from the title evidence, and are they closer to "kind of work"?

**I3. Mobility blocks.** Build the role-to-role transition matrix inside the
universe, row-normalize both the out-profile and the in-profile, concatenate,
reduce with a truncated SVD to 64 dimensions, and cluster. Two roles land
together when people move between the same places. It answers: does the labor
market itself sort roles into archetypes, independent of language? This is
the one inductive signal that a title-based framework cannot see at all.

Not run, but on the list: an LLM-only bottom-up taxonomy (ask a model to name
the clusters of I1 or I2 and then merge them), and a topic model over
descriptions. Both are variations on I1/I2 with a language model doing the
naming; M4 below covers the naming step.

## Deductive methods: start from the framework

The framework text is the only supervision. No labeled data from the corpus
is used to fit anything.

**D1. Lexicon and SOC crosswalk.** Five explainable layers, most specific
first: a self-employment placeholder rule (owner, founder with a 90%+
self-employment share becomes "none"); exact match against the framework's
390 titles plus a short enumerated list of what the framework says it is not
for (trades, clinical practice, uniformed service, placeholder titles); the
longest multiword framework title contained in the role; a head-noun lexicon
derived from the framework's own titles (a role ending in "writer" is a
communicator, provided at least 80% of framework titles ending in "writer"
agree and the noun is not a generic like manager or analyst); then a
hand-written SOC crosswalk (six-digit overrides, two-digit defaults), applied
only when the SOC code has at least three supporting steps. Anything left
abstains. Every assignment carries the name of the layer that made it.

**D2. Seed nearest-neighbor.** Embed the 390 framework titles (plus the
"none" list). A role takes the cosine-weighted vote of its five nearest seeds.
The top cosine is the confidence, and a floor turns low-confidence votes into
abstentions. The floor sweep is reported; there is no tuning on the gold.

**D2p. Prototype cosine.** One paragraph per archetype (orientation, signature
skills, representative roles) plus one "outside the framework" paragraph.
Each role goes to the nearest paragraph. This is the method that uses the
framework's orientation statements and skills lists, which D1 and D2 ignore.

**D3. LLM zero-shot.** The framework as a prompt (keys, orientations, roles,
and the director's classification guidance in three sentences), a local model
as the classifier, one title per line with SOC hints. Run on the 400 gold
roles with the 27B model on the Strix Halo and the 8B on the 5080. Cost and
throughput are in EVALUATION.md; a full-head run is a scale-up, not a new
method.

**D4. O*NET bridge.** Classify the 1,016 O*NET occupations by their official
descriptions (prototype cosine averaged with the seed vote), which yields an
O*NET-SOC to archetype map with no reference to the corpus. Roles inherit the
label of their SOC code when the code has three or more supporting steps; roles
with only a major group take the majority label of that group's mapped
occupations. This is deduction through the occupational literature rather than
through the title, and it inherits every SOC coding error.

## Mixed and semi-supervised methods

The framework supplies seeds; the corpus supplies the geometry.

**M1. Seeded k-means.** k-means over the title embeddings initialized at the
ten prototype paragraphs, so every cluster starts with a name and the data
moves its boundary.

**M1b. Embedding label spreading.** D1's confident labels (exact and
multiword seed matches, placeholders, and roles whose supported SOC major is a
trades, production, transport, clinical, or uniformed group) are diffused over
the 15-nearest-neighbor cosine graph of the title embeddings (label spreading,
alpha 0.9, 30 iterations). Seeds keep their label; every other role takes the
label with the most diffused mass.

**M2. Mobility label spreading.** The same seeds, diffused over the symmetrized
transition graph (log-weighted edges). A role with no framework match takes the
archetype of the roles its holders came from and went to.

**M2x. Geometry times mobility.** The elementwise product of the normalized
M1b and M2 score vectors: a label must be supported by both the title space
and the labor market.

**M3. Bootstrapped classifier.** Multinomial logistic regression on the title
embedding, one-hot SOC major, one-hot industry, self-employment share, and mean
seniority, trained on the ~30k confident seeds, class-balanced, predicting the
whole universe with an optional probability floor. The natural next step, not
run, is an active-learning loop: label the roles it is least sure of, retrain.

**M4. Cluster then map.** Take I1 at k = 80, show a language model each
cluster's most common titles, and ask for one archetype per cluster, "none",
or "mixed". Roles inherit their cluster's label. The count of "mixed" and
"none" clusters measures how badly the data-native structure fits the
framework.

**M5. Vote.** Majority of D1, D2, M1b, and M3, abstaining on ties. A cheap
ensemble baseline.

## What each family is for

Inductive methods cannot produce the nine archetypes; they produce the shape
of the data, which is the only way to find out what the framework is missing
(frontline retail service, clinical work, trades, and founder placeholders,
which together are a quarter of the head). Deductive methods produce the nine
archetypes and nothing else; their ceiling is the framework's coverage. Mixed
methods are the production path: seeds from the framework, boundaries from the
data, and an explicit residual for the work the framework does not name.
