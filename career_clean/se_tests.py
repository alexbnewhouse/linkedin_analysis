"""Assertion tests for the three self-employment meaning-extraction recs.

Run with:

    uv run python -m career_clean.se_tests

Follows the repo's plain-assert convention (normalization_regression_checks.py),
no pytest dependency. Covers, red/green:

  Rec 1  se_qualifier      - qualifier-aware functional recovery for
                             owner/founder/consultant/freelance titles
  Rec 2  se_personal_brand - personal-brand company-name trade mining
  Rec 3  se_cluster        - the functional/industry cluster rollup that
                             composes SOC + Rec1 + Rec2 + an honest residue
"""

from __future__ import annotations

from . import occupation as O
from . import se_cluster as C
from . import se_description as D
from . import se_personal_brand as PB
from . import se_qualifier as Q


def eq(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def truthy(actual, label: str) -> None:
    if not actual:
        raise AssertionError(f"{label}: expected truthy, got {actual!r}")


def falsy(actual, label: str) -> None:
    if actual:
        raise AssertionError(f"{label}: expected falsy, got {actual!r}")


# --------------------------------------------------------------- Rec 3 base
def check_cluster_taxonomy() -> None:
    eq(C.major_group("15-1252"), "15", "major group of a SOC")
    eq(C.major_group("soc:15-1252"), "15", "major group tolerates soc: prefix")
    truthy(C.cluster_label("15"), "cluster 15 has a label")
    truthy(C.cluster_label("27"), "cluster 27 has a label")
    # keyword gazetteer scans tokens, returns (cluster, matched_keyword)
    eq(C.keyword_cluster("photography")[0], "27", "photography -> Arts/Design/Media")
    eq(C.keyword_cluster("construction")[0], "47", "construction -> Construction")
    eq(C.keyword_cluster("it")[0], "15", "IT -> Computer")
    eq(C.keyword_cluster("law office")[0], "23", "law -> Legal")
    eq(C.keyword_cluster("restaurant")[0], "35", "restaurant -> Food")
    eq(C.keyword_cluster("management")[0], "11", "management -> Management")
    falsy(C.keyword_cluster("widgets")[0], "unknown word -> no cluster")


# --------------------------------------------------------------- Rec 1
def check_qualifier_recovery() -> None:
    by_norm, by_tokens, _ = O.load_onet()

    def rec(title):
        return Q.recover_cluster(title, by_norm, by_tokens)

    # qualifier hits O*NET unambiguously after stripping the ownership shell
    cl, soc, _m, _c = rec("Restaurant Owner")
    eq(cl, "35", "Restaurant Owner -> Food cluster")
    # consultant + domain qualifier
    eq(rec("IT Consultant")[0], "15", "IT Consultant -> Computer cluster")
    eq(rec("Digital Marketing Consultant")[0], "13", "Marketing Consultant -> Business cluster")
    eq(rec("Human Resources Consultant")[0], "13", "HR Consultant -> Business cluster")
    # freelance + ambiguous-occupation noun still clusters (ambiguity-tolerant)
    eq(rec("Freelance Designer")[0], "27", "Freelance Designer -> Arts/Design cluster")
    cl, soc, _m, _c = rec("Freelance Graphic Designer")
    eq(cl, "27", "Freelance Graphic Designer -> Arts cluster")
    eq(soc, "27-1024", "Freelance Graphic Designer keeps its exact SOC")
    # owner + trade
    eq(rec("Photography Studio Owner")[0], "27", "Photography Studio Owner -> Arts")
    eq(rec("Construction Company Owner")[0], "47", "Construction Owner -> Construction")
    # generic-word qualifiers must not false-hit the O*NET military code (55)
    eq(rec("Management Consultant")[0], "11", "Management Consultant -> Management, not Military")
    # bare ownership/founder has no functional signal -> None (honest)
    falsy(rec("Owner")[0], "bare Owner -> no cluster")
    falsy(rec("Founder")[0], "bare Founder -> no cluster")
    falsy(rec("Founder & CEO")[0], "Founder & CEO -> no cluster")
    falsy(rec("Owner/Operator")[0], "Owner/Operator -> no cluster")
    # must not fire on a normal employee title (precision guard)
    falsy(rec("Software Engineer")[0], "plain title is not the rec1 population")


# --------------------------------------------------------------- Rec 2
def check_personal_brand() -> None:
    def pb(name):
        return PB.parse_brand(name)

    eq(pb("Smith Photography")[0], "27", "Smith Photography -> Arts cluster")
    eq(pb("Acme Construction LLC")[0], "47", "construction brand -> Construction")
    eq(pb("Jane Doe Law Office")[0], "23", "law office brand -> Legal")
    eq(pb("Johnson Plumbing & Heating")[0], "47", "plumbing brand -> Construction")
    eq(pb("Riverside Fitness")[0], "39", "fitness brand -> Personal Care")
    eq(pb("Bright Idea Marketing")[0], "13", "marketing brand -> Business")
    # a real employer with no trade keyword -> no proposal
    falsy(pb("Google")[0], "Google -> no brand trade")
    falsy(pb("Microsoft Corporation")[0], "Microsoft -> no brand trade")
    # confidence is propose-only (below the deterministic backbone)
    _cl, _trade, _m, conf = pb("Smith Photography")
    truthy(conf <= 0.7, "personal-brand proposals are low-confidence")


# --------------------------------------------------------------- Rec 3 rollup
def check_cluster_rollup() -> None:
    by_norm, by_tokens, _ = O.load_onet()

    def res(company, title, **kw):
        return C.resolve_functional_cluster(
            company=company, title=title, by_norm=by_norm, by_tokens=by_tokens, **kw
        )

    # 1. an existing exact SOC wins and rolls up to its major group
    cl, method, _c = res("Self-employed", "Freelance Writer", employment_type="self_employed")
    eq(cl, "27", "Freelance Writer rolls up to Arts via its SOC")
    truthy(method.startswith("soc"), f"writer via soc, got {method}")
    # 2. qualifier recovery (Rec1) supplies the cluster when SOC is blocked
    cl, method, _c = res("Self-employed", "IT Consultant", employment_type="self_employed")
    eq(cl, "15", "IT Consultant clusters via qualifier")
    eq(method, "qualifier", "IT Consultant via qualifier method")
    # 3. company-brand (Rec2) supplies the cluster for a bare owner title
    cl, method, _c = res("Smith Photography", "Owner", employment_type="business_owner")
    eq(cl, "27", "bare Owner of a photography brand clusters via company")
    eq(method, "company_brand", "photography owner via company_brand")
    # 2b. a bare ambiguous occupation noun (no shell marker) still clusters via
    # the gazetteer on the title -- the rollup is scoped to self-employment.
    cl, method, _c = res("Self-employed", "Artist", employment_type="self_employed")
    eq(cl, "27", "bare Artist self-employed clusters via title keyword")
    eq(method, "title_keyword", "artist via title_keyword")
    # but a bare generic status word stays unspecified
    cl, method, _c = res("Self-employed", "Consultant", employment_type="self_employed")
    eq(method, "unspecified", "bare Consultant has no industry keyword")
    # 3b. a REAL company (has a company_id) is not a personal brand: do not
    # keyword-guess its name (franchise/MLM employers like Anytime Fitness).
    cl, method, _c = res("Anytime Fitness", "Owner",
                         employment_type="business_owner", company_id="anytime-fitness")
    eq(cl, "business_owner_unspecified", "real-company owner is not brand-guessed")
    # 3c. Rec 4: description supplies the cluster when title+company are bare
    cl, method, _c = res("Self-employed", "Owner", employment_type="business_owner",
                         description="We provide residential plumbing and heating repair.")
    eq((cl, method), ("47", "description"), "bare owner clustered via description")
    # but a real signal (SOC/qualifier) still wins over the description
    cl, method, _c = res("Self-employed", "Freelance Writer", employment_type="self_employed",
                         description="I also do some plumbing on the side.")
    eq(method[:3], "soc", "SOC backbone beats the description")
    # 4. honest terminal residue when nothing carries a signal
    cl, method, _c = res("Self-employed", "Owner", employment_type="business_owner")
    eq(cl, "business_owner_unspecified", "bare owner, no brand -> unspecified")
    cl, method, _c = res("Self-employed", "Founder", employment_type="self_employed")
    eq(cl, "self_employed_unspecified", "bare founder self-employed -> unspecified")


# --------------------------------------------------------------- Rec 4 (desc)
def check_description() -> None:
    def inf(text):
        return D.infer_cluster(text)

    # lead-window strong keyword names the trade
    cl, method, conf, _ev = inf("We provide residential plumbing and heating repair.")
    eq((cl, method), ("47", "desc_lead"), "plumbing lead -> Construction")
    eq(inf("I run a small bakery making wedding cakes.")[0], "35", "bakery lead -> Food")
    eq(inf("Acquiring and growing home care and home health companies.")[0], "31",
       "home care lead -> Healthcare Support")
    # generic business/function words must NOT decide a cluster on their own
    falsy(inf("Manage daily operations, staffing, and financial budgeting.")[0],
          "weak business words alone -> no inference")
    falsy(inf("We build custom software. Our software team ships fast.")[0],
          "software alone is too generic to decide")
    # the "it" keyword (Information Technology) must NOT fire on the English
    # pronoun "it" in prose -- a description-specific tokenization hazard.
    falsy(inf("I help organizations build cultures where people take ownership of it.")[0],
          "pronoun 'it' must not trigger the IT cluster")
    falsy(inf("Build it from the ground up; I was hired as a sales rep.")[0],
          "'build it' must not trigger the IT cluster")
    # vote fallback: lead has no strong keyword, body has >=2 distinct strong ones
    cl, method, conf, _ev = inf(
        "Owner and operator since 2010. Photography and videography for weddings and events."
    )
    eq((cl, method), ("27", "desc_vote"), "photography+videography vote -> Arts")
    # confidence is propose-only / review-queue grade
    truthy(conf <= 0.55, "description inferences are low-confidence")
    # empty / missing
    falsy(inf("")[0], "empty description -> nothing")
    falsy(inf(None)[0], "None description -> nothing")


def main() -> None:
    check_cluster_taxonomy()
    check_qualifier_recovery()
    check_personal_brand()
    check_description()
    check_cluster_rollup()
    print("self-employment rec tests passed")


if __name__ == "__main__":
    main()
