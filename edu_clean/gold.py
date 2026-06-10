"""Hand-labeled gold pairs for the same-vs-distinct benchmark.

Every pair is (value_a, value_b, should_merge). Pairs are drawn from values
actually observed during exploration; the runner validates that both endpoints
exist in the vocabulary and drops (with a warning) any that do not, so the
benchmark stays honest.

The pairs are chosen to stress the hard boundary: lexically-similar values that
are nonetheless DISTINCT (subfields/combinations/adjacent degrees) versus
genuinely-same values that differ by case, punctuation, '&'/and, CIP synonym
form, abbreviation, or spelling typo.
"""

# ------------------------------------------------------------------ FIELD
FIELD_PAIRS = [
    # --- same: case ---
    ("PSYCHOLOGY", "Psychology", True),
    ("EDUCATION", "Education", True),
    ("Mechanical Engineering", "mechanical engineering", True),
    ("Mechanical Engineering", "Mechanical engineering", True),
    # --- same: & vs and ---
    ("Computer Science & Engineering", "Computer Science and Engineering", True),
    ("Accounting & Finance", "Accounting and Finance", True),
    # --- same: CIP "General" suffix is filler ---
    ("Finance, General", "Finance", True),
    ("Biology, General", "Biology", True),
    ("Communication, General", "Communications", True),
    (
        "Business Administration and Management, General",
        "Business Administration and Management",
        True,
    ),
    # --- same: CIP synonym forms / case of family names ---
    (
        "English Language and Literature, General",
        "English Language and Literature/Letters",
        True,
    ),
    (
        "English Language and Literature/Letters",
        "ENGLISH LANGUAGE AND LITERATURE/LETTERS",
        True,
    ),
    ("Biology/Biological Sciences, General", "Biology, General", True),
    # --- distinct: subfield/specialization ---
    ("Psychology", "Clinical Psychology", False),
    ("Psychology", "Counseling Psychology", False),
    ("Psychology", "Industrial and Organizational Psychology", False),
    ("English", "English Literature", False),
    ("Mechanical Engineering", "Mechanical Engineering Technology", False),
    # --- distinct: combination vs single ---
    ("Computer Science", "Computer Science and Engineering", False),
    ("Computer Science", "Mathematics and Computer Science", False),
    ("Computer Science", "Electrical Engineering and Computer Science", False),
    ("Accounting", "Accounting and Finance", False),
    ("Accounting", "Accounting and Business/Management", False),
    # --- distinct: sibling fields ---
    ("Mechanical Engineering", "Electrical Engineering", False),
    ("Mechanical Engineering", "Civil Engineering", False),
    ("Finance", "Economics", False),
    ("Finance", "Accounting", False),
    ("Biology", "Chemistry", False),
    ("Marketing", "Business Administration", False),
    ("Political Science", "Sociology", False),
    # ====================================================================
    # 2026-06 expansion (audit Finding 7): pairs drawn from the newly mapped
    # strata — 2-digit CIP family titles, the CIP-2020 30.70/30.71 series,
    # and the expanded curated alias list.
    # --- same: verbatim CIP family titles (case variants) ---
    (
        "BUSINESS, MANAGEMENT, MARKETING, AND RELATED SUPPORT SERVICES",
        "Business, Management, Marketing, and Related Support Services",
        True,
    ),
    (
        "COMPUTER AND INFORMATION SCIENCES AND SUPPORT SERVICES",
        "Computer and Information Sciences and Support Services",
        True,
    ),
    (
        "HIGH SCHOOL/SECONDARY DIPLOMAS AND CERTIFICATES",
        "High School/Secondary Diplomas and Certificates",
        True,
    ),
    (
        "COMMUNICATION, JOURNALISM, AND RELATED PROGRAMS",
        "Communication, Journalism, and Related Programs",
        True,
    ),
    # --- same: bare label joins its family / group via alias ---
    ("BUSINESS, MANAGEMENT, MARKETING, AND RELATED SUPPORT SERVICES", "Business", True),
    ("English", "English Language and Literature, General", True),
    ("Geology", "Geology/Earth Science, General", True),
    ("Math", "Mathematics", True),
    # --- distinct: family vs more specific group/program ---
    ("BUSINESS, MANAGEMENT, MARKETING, AND RELATED SUPPORT SERVICES", "Business Administration", False),
    ("COMPUTER AND INFORMATION SCIENCES AND SUPPORT SERVICES", "Computer Science", False),
    ("Business", "Business Administration", False),
    ("Business", "Management", False),
    # --- same: CIP-2020 30.70/30.71 + alias variants ---
    ("Cybersecurity", "Cyber Security", True),
    ("Theatre", "Theater", True),
    ("Theatre/Theater", "Theatre", True),
    ("Theatre", "Theatre Arts", True),
    ("Kinesiology", "Exercise Science", True),
    ("Sports Management", "Sport Management", True),
    ("Healthcare Administration", "Health Care Administration", True),
    ("Healthcare Management", "Healthcare Administration", True),
    ("Accountancy", "Accounting", True),
    ("Paralegal", "Paralegal Studies", True),
    ("Government", "Political Science", True),
    ("MIS", "Management Information Systems", True),
    ("IT", "Information Technology", True),
    ("Educational Leadership", "Education Administration", True),
    ("Mass Communication", "Media Studies", True),
    ("Speech Communication", "Speech Communications", True),
    ("Strategic Communication", "Strategic Communications", True),
    ("Electronics Engineering Technology", "Electrical Engineering Technology", True),
    ("Biomedical Engineering", "Bioengineering", True),
    ("Fine Arts", "Fine Art", True),
    ("Health Science", "Health Sciences", True),
    # --- distinct: the hard boundary around the new strata ---
    ("Data Science", "Data Analytics", False),
    ("Data Science", "Business Analytics", False),
    ("Business Analytics", "Data Analytics", False),
    ("Cybersecurity", "Computer Science", False),
    ("Software Engineering", "Computer Science", False),
    ("Theatre", "Musical Theatre", False),
    ("Geology", "Geography", False),
    ("Kinesiology", "Physical Therapy", False),
    ("Government", "Public Administration", False),
    ("Special Education", "Elementary Education", False),
    ("Zoology", "Biology", False),
    ("Humanities", "Liberal Arts", False),
    ("Healthcare Administration", "Public Health", False),
    ("Spanish", "French", False),
    ("IT", "Information Systems", False),  # "Information Systems" stays raw on purpose
    ("High School", "GED", False),
]

# ------------------------------------------------------------------ DEGREE
DEGREE_PAIRS = [
    # --- same: punctuation / abbreviation style of the SAME degree type ---
    ("Bachelor of Science - BS", "Bachelor of Science (BS)", True),
    ("Bachelor of Science - BS", "Bachelor of Science (B.S.)", True),
    ("Bachelor of Science - BS", "Bachelor of Science", True),
    ("Bachelor of Science - BS", "BS", True),
    ("Bachelor of Science - BS", "B.S.", True),
    ("Bachelor of Arts - BA", "Bachelor of Arts (BA)", True),
    ("Bachelor of Arts - BA", "Bachelor of Arts (B.A.)", True),
    ("Bachelor of Arts - BA", "BA", True),
    ("Bachelor of Arts - BA", "B.A.", True),
    (
        "Master of Business Administration - MBA",
        "Master of Business Administration (MBA)",
        True,
    ),
    (
        "Master of Business Administration - MBA",
        "Master of Business Administration (M.B.A.)",
        True,
    ),
    ("Master of Business Administration - MBA", "MBA", True),
    ("Master of Science - MS", "Master of Science (MS)", True),
    ("Master of Science - MS", "MS", True),
    # --- same: generic level spelling variants (incl. curly apostrophe) ---
    ("Bachelor's degree", "Bachelor's Degree", True),
    ("Bachelor's degree", "Bachelor\u2019s Degree", True),
    ("Bachelor's degree", "Bachelors", True),
    ("Master's degree", "Master\u2019s Degree", True),
    ("Master's degree", "Masters", True),
    ("Associate's degree", "Associate's Degree", True),
    # --- distinct: different degree TYPE (same level) ---
    ("Bachelor of Science - BS", "Bachelor of Arts - BA", False),
    ("Bachelor of Arts - BA", "Bachelor of Fine Arts - BFA", False),
    ("Master of Science - MS", "Master of Arts - MA", False),
    ("Master of Business Administration - MBA", "Master of Science - MS", False),
    # --- distinct: different LEVEL ---
    ("Bachelor's degree", "Master's degree", False),
    ("Associate's degree", "Bachelor's degree", False),
    ("Master's degree", "Doctor of Philosophy - PhD", False),
    ("High School Diploma", "Bachelor's degree", False),
    ("Certificate", "Bachelor's degree", False),
    ("Bachelor of Science - BS", "Master of Science - MS", False),
    # ====================================================================
    # 2026-06 expansion (audit Finding 7): taxonomy-tail categories and the
    # degree->field cross-pass strata.
    # --- same: case + subject-carrying variants of the same category ---
    ("Undergraduate", "undergraduate", True),
    ("Minor", "Minor in Psychology", True),
    ("Bachelor of Science in Computer Science", "Bachelor of Science - BS", True),
    # --- distinct: tail level words are different categories ---
    ("Undergraduate", "Graduate", False),
    ("Postgraduate Degree", "Graduate", False),
    ("Graduate", "Master's degree", False),
    ("Undergraduate", "Bachelor's degree", False),
    ("Minor", "Bachelor's degree", False),
    ("Study Abroad", "Bachelor's degree", False),
    ("Postgraduate Degree", "Postgraduate Diploma", False),
    # --- distinct: a swapped field-in-degree cell is not a real degree ---
    ("Computer Science", "Bachelor of Science - BS", False),
    ("Business Administration and Management, General", "MBA", False),
    ("Bachelor of Science in Computer Science", "Bachelor of Arts in English", False),
]

# ------------------------------------------------------------------ INSTITUTION
INSTITUTION_PAIRS = [
    # --- same: case / punctuation ---
    ("University of Phoenix", "University Of Phoenix", True),
    # --- same: spelling typo ---
    ("University of Phoenix", "University of Pheonix", True),
    # --- same: campus variant of one institution ---
    ("University of Phoenix", "University of Phoenix-Southern California Campus", True),
    ("University of Phoenix", "University of Phoenix-Colorado Campus", True),
    # --- distinct: different universities (lexically share tokens) ---
    ("University of Washington", "University of Michigan", False),
    ("University of Michigan", "University of Maryland", False),
    ("University of Florida", "University of Houston", False),
    ("New York University", "University of Phoenix", False),
    ("Boston University", "Boston College", False),
    ("Indiana University", "University of Indianapolis", False),
    ("Pennsylvania State University", "Pennsylvania College of Technology", False),
    ("Arizona State University", "University of Arizona", False),
]

PAIRS = {
    "field": FIELD_PAIRS,
    "degree": DEGREE_PAIRS,
    "title": INSTITUTION_PAIRS,
}
