"""Hand-labeled gold pairs for the career same-vs-distinct benchmark.

Every pair is ``(value_a, value_b, should_merge)``. All endpoints were confirmed
to exist in the data during exploration (see exploration/career_explore.py); the
runner drops, with a warning, any pair whose endpoints are missing from the
loaded vocab so the benchmark stays honest.

Pairs stress the hard boundary:

  company: same employer across spelling / case / '&'-and / abbreviation /
           acquired-brand, AND placeholder values that mean the same non-job
           status -- versus distinct organizations that merely share tokens.
  title:   same role across case / punctuation / '&'-and / abbreviation /
           seniority-word style -- versus distinct roles or distinct seniority
           LEVELS of the same role (the central tension, mirroring degree level).
"""

# ------------------------------------------------------------------ COMPANY
COMPANY_PAIRS = [
    # --- same: case / punctuation ---
    ("Bank of America", "bank of america", True),
    ("Wells Fargo", "wells fargo", True),
    # --- same: '&' vs 'and' / legal suffix ---
    ("Ernst & Young", "Ernst and Young", True),
    ("PricewaterhouseCoopers", "PricewaterhouseCoopers LLP", True),
    # --- same: abbreviation / sub-brand under one LinkedIn company id ---
    ("EY", "Ernst & Young", True),               # id: ernstandyoung
    ("PwC", "PricewaterhouseCoopers", True),      # id: pwc
    ("Citi", "Citigroup", True),                  # id: citi
    ("AT&T", "AT&T Mobility", True),              # id: att
    ("US Army", "United States Army", True),      # id: us-army
    ("US Army", "U.S. Army", True),               # id: us-army
    # --- same: rebrand / parent reorganization (curated cross-id alias) ---
    ("Facebook", "Meta", True),                   # facebook -> meta
    ("Google", "Alphabet Inc.", True),            # alphabet-inc -> google
    # --- same: placeholder values meaning the same non-job status ---
    ("Self-employed", "Self Employed", True),     # NON_ORG: self_employed
    ("Self-employed", "Self-Employed", True),
    ("Freelance", "Freelancer", True),            # NON_ORG: self_employed
    # --- distinct: different organizations that share tokens ---
    ("Citizens Bank", "First Citizens Bank", False),
    ("Citi", "Citizens Bank", False),
    ("Bank of America", "Wells Fargo", False),
    ("US Army", "US Navy", False),
    ("Deloitte", "PwC", False),
    ("Google", "Meta", False),
    # --- distinct: a real employer vs a placeholder ---
    ("Deloitte", "Self-employed", False),
    ("Google", "Freelance", False),
]

# ------------------------------------------------------------------ TITLE
TITLE_PAIRS = [
    # --- same: case ---
    ("Software Engineer", "software engineer", True),
    # --- same: abbreviation of the seniority word ---
    ("Sr. Software Engineer", "Senior Software Engineer", True),
    ("Sr Software Engineer", "Senior Software Engineer", True),
    # --- same: role abbreviation / acronym ---
    ("VP", "Vice President", True),
    ("CEO", "Chief Executive Officer", True),
    ("RN", "Registered Nurse", True),
    # --- same: punctuation / '&' vs 'and' ---
    ("Co-Founder", "Co-founder", True),
    ("Co-Founder", "Cofounder", True),
    ("Sales & Marketing Manager", "Sales and Marketing Manager", True),
    # --- distinct: same role, different seniority LEVEL (the key tension) ---
    ("Software Engineer", "Senior Software Engineer", False),
    ("Software Engineer", "Software Engineer II", False),
    ("Vice President", "VP of Sales", False),
    ("Founder", "Co-Founder", False),
    # --- distinct: different roles (some lexically close) ---
    ("Project Manager", "Product Manager", False),
    ("Account Manager", "Account Executive", False),
    ("Owner", "Founder", False),
    ("Software Engineer", "Sales Engineer", False),
    ("Registered Nurse", "Nurse Practitioner", False),
]

# --------------------------------------------------------------- OCCUPATION
# Same-vs-distinct on the O*NET-SOC occupation axis (semantic job family),
# orthogonal to the literal title and to seniority. All endpoints resolve to a
# SOC code via the lexicon (verified), so the pairs actually exercise grouping.
OCCUPATION_PAIRS = [
    # --- same SOC: synonymous roles the literal parser can't merge ---
    ("Software Engineer", "Software Developer", True),       # 15-1252
    ("Senior Software Engineer", "Software Developer", True),  # de-leveled -> 15-1252
    ("Sr. Software Engineer", "Software Engineer", True),     # 15-1252
    ("Staff Accountant", "Accountant", True),                # 13-2011
    # --- distinct SOC: lexically close but different occupations ---
    ("Software Engineer", "Computer Programmer", False),     # 15-1252 vs 15-1251
    ("Software Developer", "Accountant", False),             # 15-1252 vs 13-2011
    ("Data Scientist", "Graphic Designer", False),           # 15-2051 vs 27-1024
    ("Accountant", "High School Teacher", False),            # 13-2011 vs 25-2031
]

# ---------------------------------------------------------- EMPLOYMENT TYPE
# Row-level same-vs-distinct on the employment-status axis. Endpoints are
# ``(company, title)`` keys because this axis is resolved from both fields.
EMPLOYMENT_TYPE_PAIRS = [
    (("Self-employed", "Graphic Designer"), ("Freelance", "Graphic Designer"), True),
    (("Self-employed", "Retired"), ("Deloitte", "Retired"), True),
    (("Deloitte", "Consultant"), ("Deloitte", "Freelance Consultant"), False),
    (("Deloitte", "Consultant"), ("Deloitte", "Independent Consultant"), False),
    (("Example LLC", "Founder"), ("Deloitte", "Consultant"), False),
    (("Example LLC", "Founder"), ("Example LLC", "Product Owner"), False),
]

PAIRS = {
    "company": COMPANY_PAIRS,
    "title": TITLE_PAIRS,
    "occupation": OCCUPATION_PAIRS,
    "employment_type": EMPLOYMENT_TYPE_PAIRS,
}
