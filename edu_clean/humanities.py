"""NHA (National Humanities Alliance) hierarchical Field-of-Study Classification.

A deterministic, CIP-2020-grounded classifier that labels a degree program with
three *nested* boolean flags and a short field group, given its NCES CIP code
(the same `cip_code` produced by the `edu_clean` field-resolution pipeline, e.g.
`final_hybrid.py`).

The three levels, strictest -> loosest, are NESTED (L1 implies L2 implies L3):

  L1  is_humanities                      -- the humanities, narrowly defined
  L2  is_humanistic_social_science_incl  -- L1 + humanistic/interpretive social sciences
  L3  is_liberal_arts                    -- L2 + math & natural sciences (a College of
                                            Arts & Sciences); excludes professional/
                                            vocational/applied programs

The schema is grounded in three published definitions; each entry below cites the
source (HIP / ACLS / PBK) that justifies it:

  HIP  - Humanities Indicators Project, American Academy of Arts & Sciences:
         "The Definition of the 'Humanities' for Purposes of the Humanities
         Indicators" (https://www.amacad.org/humanities-indicators/scope-of-humanities).
         Core humanities = history; languages & linguistics (incl. classical
         studies); philosophy; English & literature; area/ethnic/cultural/gender
         studies; (secular) religious studies; the academic study of the arts.
         Per the project owner's methodology we ADD theology/seminary and ADD all
         (not just academic) fine & performing arts to this core for L1.

  ACLS - American Council of Learned Societies, member societies
         (https://www.acls.org/acls-member-societies/): the "humanities and
         interpretive social sciences." Member societies confirm sociology
         (ASA), anthropology (AAA), archaeology (AIA), political science (APSA),
         geography (AAG), communication (NCA), and cinema/media studies (SCMS).
         These define the L2 humanistic social sciences. Per the methodology we
         also add named interpretive branches of otherwise-quantitative fields:
         international affairs/peace studies, historical demography/population
         studies, environmental psychology, library & information science, and
         museum studies.

  PBK  - Phi Beta Kappa membership stipulations
         (https://www.pbk.org/membership/membership-stipulations): "the liberal
         arts and sciences ... the traditional disciplines of the natural
         sciences, mathematics, social sciences, and humanities," and applied/
         pre-professional/vocational coursework is excluded. This defines L3:
         L2 + mathematics + natural (biological & physical) sciences, minus
         professional/vocational/applied programs (business, nursing,
         engineering, education-as-pedagogy, etc.).

Design: a 2-digit-series base map plus explicit 4-/6-digit overrides. The CIP is
hierarchical (2-digit family -> 4-digit -> 6-digit); we classify at the family
level and override the handful of sub-codes whose humanistic-ness diverges from
their family (e.g. within 45 Social Sciences, 45.06 Economics is more
quantitative; within 30 Multi/Interdisciplinary, 30.22 Classical Studies is L1
while 30.08 Math & Computer Science is L3-only).

CIP groupings verified against `reference/cip_codes.csv` (CIP 2020, 2,319 rows).

Usage:

    from edu_clean.humanities import classify, classify_cip
    res = classify("cip:54.0101")   # accepts 'cip:' prefix or bare code
    res.is_humanities, res.field_group  # -> (True, "History")

    # or build the crosswalk parquet for joining onto education.parquet:
    #   uv run python -m edu_clean.humanities build
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIP_CSV = ROOT / "reference" / "cip_codes.csv"
OUT_PARQUET = ROOT / "reference" / "cip_humanities.parquet"

# --------------------------------------------------------------------------
# Levels as ordinals so nesting can be enforced as a single invariant.
# A program is assigned the *innermost* level it qualifies for; the booleans
# are then derived (level <= L1 => is_humanities, etc.). 0 = none of the three.
# --------------------------------------------------------------------------
L_NONE = 0
L1 = 1  # humanities
L2 = 2  # humanistic social science (and L1)
L3 = 3  # liberal arts (and L1, L2)


@dataclass(frozen=True)
class Classification:
    cip_code: str
    level: int  # 0=none, 1=humanities, 2=hum. social sci, 3=liberal arts
    field_group: str

    @property
    def is_humanities(self) -> bool:  # L1
        return self.level == L1

    @property
    def is_humanistic_social_science_incl(self) -> bool:  # L2 (nested: includes L1)
        return self.level in (L1, L2)

    @property
    def is_liberal_arts(self) -> bool:  # L3 (nested: includes L1, L2)
        return self.level in (L1, L2, L3)


# --------------------------------------------------------------------------
# Base map: 2-digit CIP family -> (innermost level, field group).
# Every family present in CIP 2020 is listed (default L_NONE = professional/
# vocational/applied, i.e. not a liberal art). Comments tie each to a source.
# --------------------------------------------------------------------------
FAMILY_MAP: dict[str, tuple[int, str]] = {
    # ---- L1 humanities (HIP core + methodology additions) ----
    "54": (L1, "History"),                       # HIP: History
    "23": (L1, "English & Literature"),          # HIP: English language & literature
    "16": (L1, "Languages & Linguistics"),       # HIP: languages & linguistics
    "38": (L1, "Philosophy & Religion"),         # HIP: philosophy + (secular) religious studies
    "39": (L1, "Theology"),                      # methodology add: theology/seminary
    "05": (L1, "Area & Cultural Studies"),       # HIP: area/ethnic/cultural/gender/group studies
    "50": (L1, "Fine & Performing Arts"),        # methodology add: ALL fine & performing arts
    "24": (L1, "Liberal Arts & Humanities"),     # HIP: general humanities / liberal arts studies
    # ---- L2 humanistic social sciences (ACLS) ----
    "45": (L2, "Humanistic Social Science"),     # ACLS: sociology, anthropology, archaeology,
                                                 #   political science, geography (+ economics
                                                 #   override below)
    "09": (L2, "Communication & Media"),         # ACLS: communication (NCA), cinema/media (SCMS)
    # ---- L3 liberal arts: math & natural sciences (PBK) ----
    "27": (L3, "Math & Statistics"),             # PBK: mathematics
    "26": (L3, "Biological Sciences"),           # PBK: natural sciences
    "40": (L3, "Physical Sciences"),             # PBK: natural sciences
    "03": (L3, "Natural Sciences"),              # PBK: natural resources/environmental science
    # ---- families needing overrides; family default set conservatively ----
    "42": (L3, "Psychology"),                    # PBK: psychology is a liberal-art social science;
                                                 #   only the named interpretive branch (42.21
                                                 #   Environmental Psych) is lifted to L2 below
    "30": (L3, "Interdisciplinary Studies"),     # Multi/interdisciplinary: family default L3,
                                                 #   many sub-codes overridden up/down below
    "25": (L2, "Library & Information Science"),  # methodology add (ACLS-adjacent): LIS -> L2
    # ---- L_NONE: professional / vocational / applied (PBK excludes) ----
    "01": (L_NONE, "Other"),  # Agriculture (applied)
    "04": (L_NONE, "Other"),  # Architecture (professional)
    "10": (L_NONE, "Other"),  # Communications technologies (vocational)
    "11": (L_NONE, "Other"),  # Computer & information sciences (applied/professional)
    "12": (L_NONE, "Other"),  # Personal & culinary services
    "13": (L_NONE, "Other"),  # Education (pedagogy) -- PBK excludes education-as-pedagogy
    "14": (L_NONE, "Other"),  # Engineering
    "15": (L_NONE, "Other"),  # Engineering technologies
    "19": (L_NONE, "Other"),  # Family & consumer sciences
    "21": (L_NONE, "Other"),  # Technology education / industrial arts
    "22": (L_NONE, "Other"),  # Legal professions (professional)
    "28": (L_NONE, "Other"),  # Military science
    "29": (L_NONE, "Other"),  # Military technologies
    "31": (L_NONE, "Other"),  # Parks, recreation, fitness
    "32": (L_NONE, "Other"),  # Basic skills / remedial
    "33": (L_NONE, "Other"),  # Citizenship activities
    "34": (L_NONE, "Other"),  # Health-related knowledge/skills
    "35": (L_NONE, "Other"),  # Interpersonal & social skills
    "36": (L_NONE, "Other"),  # Leisure & recreational activities
    "37": (L_NONE, "Other"),  # Personal awareness / self-improvement
    "41": (L_NONE, "Other"),  # Science technologies/technicians (vocational)
    "43": (L_NONE, "Other"),  # Homeland security, law enforcement
    "44": (L_NONE, "Other"),  # Public administration & social services (professional)
    "46": (L_NONE, "Other"),  # Construction trades
    "47": (L_NONE, "Other"),  # Mechanic & repair technologies
    "48": (L_NONE, "Other"),  # Precision production
    "49": (L_NONE, "Other"),  # Transportation
    "51": (L_NONE, "Other"),  # Health professions
    "52": (L_NONE, "Other"),  # Business / management / marketing
    "53": (L_NONE, "Other"),  # High school diplomas/certificates
    "60": (L_NONE, "Other"),  # Residency programs
}

# --------------------------------------------------------------------------
# Overrides keyed by 4-digit (e.g. "45.06") or 6-digit (e.g. "30.2202") CIP.
# The longest matching prefix wins, so a 6-digit override beats a 4-digit one
# which beats the 2-digit family. Each cites the schema that justifies it.
# --------------------------------------------------------------------------
OVERRIDES: dict[str, tuple[int, str]] = {
    # ---- within 45 Social Sciences: split humanistic vs quantitative/applied ----
    "45.02": (L2, "Humanistic Social Science"),  # ACLS: Anthropology
    "45.03": (L2, "Humanistic Social Science"),  # ACLS: Archeology
    "45.05": (L2, "Humanistic Social Science"),  # methodology: historical demography & population
    "45.06": (L3, "Economics"),                  # economics is quantitative; not an ACLS humanistic
                                                 #   field -> liberal art (L3) but not L2
    "45.07": (L2, "Humanistic Social Science"),  # ACLS: Geography (AAG)
    "45.09": (L2, "Humanistic Social Science"),  # methodology: international relations/affairs
    "45.10": (L2, "Humanistic Social Science"),  # ACLS: Political Science (APSA)
    "45.11": (L2, "Humanistic Social Science"),  # ACLS: Sociology (ASA)
    "45.04": (L3, "Social Science"),             # Criminology: applied/quantitative -> L3 only
    "45.12": (L3, "Social Science"),             # Urban Studies/Affairs: applied -> L3 only
    # ---- within 42 Psychology: only the named interpretive branch is L2 ----
    "42.21": (L2, "Humanistic Social Science"),  # methodology: Environmental Psychology
    # ---- within 30 Multi/Interdisciplinary: per-subcode placement ----
    # L1 humanities sub-codes (HIP "Selected Interdisciplinary Studies"):
    "30.12": (L1, "History"),                    # HIP: Historic Preservation & Conservation
    "30.13": (L1, "Area & Cultural Studies"),    # HIP: Medieval & Renaissance Studies
    "30.21": (L1, "Area & Cultural Studies"),    # HIP: Holocaust & Related Studies
    "30.22": (L1, "Languages & Linguistics"),    # HIP: Classical & Ancient Studies
    "30.23": (L1, "Area & Cultural Studies"),    # HIP: Intercultural/Multicultural/Diversity
    "30.26": (L1, "Area & Cultural Studies"),    # HIP: Cultural Studies/Critical Theory
    # L2 humanistic social science / methodology adds:
    "30.05": (L2, "Humanistic Social Science"),  # methodology: Peace Studies & Conflict Resolution
    "30.14": (L2, "Museum Studies"),             # methodology: Museology/Museum Studies
    "30.15": (L2, "Science, Technology & Society"),  # ACLS-adjacent / methodology: STS
    "30.20": (L2, "Humanistic Social Science"),  # methodology: International/Global Studies
    "30.28": (L2, "Humanistic Social Science"),  # Dispute Resolution (peace-studies adjacent)
    "30.17": (L3, "Social Science"),             # Behavioral Sciences: L3 social science
    # L3 math/natural-science interdisciplinary (PBK), default already L3 but labeled:
    "30.01": (L3, "Natural Sciences"),           # Biological & Physical Sciences
    "30.06": (L3, "Math & Statistics"),          # Systems Science & Theory
    "30.08": (L3, "Math & Statistics"),          # Mathematics & Computer Science
    "30.10": (L3, "Natural Sciences"),           # Biopsychology
    "30.18": (L3, "Natural Sciences"),           # Natural Sciences
    "30.19": (L3, "Natural Sciences"),           # Nutrition Sciences
    "30.24": (L3, "Natural Sciences"),           # Neuroscience
    "30.25": (L3, "Social Science"),             # Cognitive Science (interdisciplinary)
    "30.27": (L3, "Natural Sciences"),           # Human Biology
    "30.30": (L3, "Math & Statistics"),          # Computational Science
    "30.32": (L3, "Natural Sciences"),           # Marine Sciences
    # L_NONE applied/professional interdisciplinary:
    "30.16": (L_NONE, "Other"),                  # Accounting & Computer Science (applied)
    "30.31": (L_NONE, "Other"),                  # Human Computer Interaction (applied)
    "30.70": (L_NONE, "Other"),                  # Data Science (CIP 2020; applied/professional)
    "30.71": (L_NONE, "Other"),                  # Data Analytics (CIP 2020; applied/professional)
    # ---- within 50 Visual & Performing Arts: arts management is professional ----
    "50.10": (L_NONE, "Other"),                  # Arts, Entertainment & Media Management (business)
    # ---- within 27 Math: keep all L3 (no override needed) ----
    # ---- within 24: liberal arts general (already L1) ----
}


def _bare_cip(cip_code: str) -> str:
    """Strip an optional 'cip:' prefix and surrounding whitespace."""
    if cip_code is None:
        return ""
    s = cip_code.strip()
    if s.lower().startswith("cip:"):
        s = s[4:]
    return s.strip()


def classify_cip(cip_code: str) -> Classification:
    """Classify a bare or 'cip:'-prefixed CIP code into the NHA hierarchy.

    Resolution order (most specific wins): 6-digit override -> 4-digit override
    -> 2-digit family base map. Unknown / empty codes return level 0.
    """
    bare = _bare_cip(cip_code)
    if not bare:
        return Classification(bare, L_NONE, "Other")

    # Try 6-digit then 4-digit overrides (longest prefix wins).
    # 6-digit form like "30.2202" -> 4-digit prefix "30.22".
    if "." in bare:
        whole, _, frac = bare.partition(".")
        # 6-digit override (whole.frac[:4]) e.g. "30.2202"
        if len(frac) >= 4:
            six = f"{whole}.{frac[:4]}"
            if six in OVERRIDES:
                lvl, grp = OVERRIDES[six]
                return Classification(bare, lvl, grp)
        # 4-digit override e.g. "45.06"
        four = f"{whole}.{frac[:2]}"
        if four in OVERRIDES:
            lvl, grp = OVERRIDES[four]
            return Classification(bare, lvl, grp)
        family = whole[:2]
    else:
        family = bare[:2]

    lvl, grp = FAMILY_MAP.get(family, (L_NONE, "Other"))
    return Classification(bare, lvl, grp)


def classify(cip_code: str) -> Classification:
    """Alias for classify_cip (accepts 'cip:' prefixed codes)."""
    return classify_cip(cip_code)


# --------------------------------------------------------------------------
# Builder / exporter: emit reference/cip_humanities.parquet keyed by cip_code
# for every valid CIP 2020 code, so education.parquet can be labeled by join.
# --------------------------------------------------------------------------
def build_crosswalk() -> Path:
    """Write reference/cip_humanities.parquet: one row per CIP 2020 code with
    the three nested flags + field group. Joinable onto education.parquet on
    cip_code."""
    import duckdb

    con = duckdb.connect()
    rows = con.sql(
        f"SELECT DISTINCT CIPCode FROM read_csv('{CIP_CSV}') WHERE CIPCode IS NOT NULL"
    ).fetchall()

    records = []
    for (code,) in rows:
        c = classify_cip(code)
        records.append(
            (
                code,
                c.level,
                c.is_humanities,
                c.is_humanistic_social_science_incl,
                c.is_liberal_arts,
                c.field_group,
            )
        )

    con.execute(
        """CREATE TABLE cw (
            cip_code VARCHAR,
            nha_level INTEGER,
            is_humanities BOOLEAN,
            is_humanistic_social_science_incl BOOLEAN,
            is_liberal_arts BOOLEAN,
            humanities_field_group VARCHAR
        )"""
    )
    con.executemany("INSERT INTO cw VALUES (?, ?, ?, ?, ?, ?)", records)
    if OUT_PARQUET.exists():
        OUT_PARQUET.unlink()
    con.execute(f"COPY cw TO '{OUT_PARQUET}' (FORMAT parquet)")
    return OUT_PARQUET


def coverage_stats() -> dict:
    """Compute % of resolved education rows in each NHA level + group breakdown,
    against normalized/education.parquet (joined on cip_code)."""
    import duckdb

    if not OUT_PARQUET.exists():
        build_crosswalk()
    con = duckdb.connect()
    edu = ROOT / "normalized" / "education.parquet"
    con.execute(
        f"""CREATE VIEW j AS
            SELECT e.cip_code, c.nha_level, c.is_humanities,
                   c.is_humanistic_social_science_incl, c.is_liberal_arts,
                   c.humanities_field_group
            FROM read_parquet('{edu}') e
            JOIN read_parquet('{OUT_PARQUET}') c ON e.cip_code = c.cip_code"""
    )
    total_all = con.sql(f"SELECT count(*) FROM read_parquet('{edu}')").fetchone()[0]
    coded = con.sql("SELECT count(*) FROM j").fetchone()[0]
    l1 = con.sql("SELECT count(*) FROM j WHERE is_humanities").fetchone()[0]
    l2 = con.sql(
        "SELECT count(*) FROM j WHERE is_humanistic_social_science_incl"
    ).fetchone()[0]
    l3 = con.sql("SELECT count(*) FROM j WHERE is_liberal_arts").fetchone()[0]
    groups = con.sql(
        "SELECT humanities_field_group, count(*) n FROM j GROUP BY 1 ORDER BY n DESC"
    ).fetchall()
    return {
        "total_rows": total_all,
        "coded_rows": coded,
        "pct_coded": round(100 * coded / total_all, 1),
        "L1_humanities": l1,
        "L2_hum_social_sci": l2,
        "L3_liberal_arts": l3,
        "pct_L1_of_coded": round(100 * l1 / coded, 1),
        "pct_L2_of_coded": round(100 * l2 / coded, 1),
        "pct_L3_of_coded": round(100 * l3 / coded, 1),
        "pct_L1_of_all": round(100 * l1 / total_all, 1),
        "pct_L2_of_all": round(100 * l2 / total_all, 1),
        "pct_L3_of_all": round(100 * l3 / total_all, 1),
        "groups": groups,
    }


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        p = build_crosswalk()
        print(f"wrote {p}")
    elif cmd == "coverage":
        import json

        print(json.dumps(coverage_stats(), indent=2, default=str))
    else:
        print(__doc__)
