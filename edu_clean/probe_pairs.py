"""Categorized string-pair probe for comparing encoders.

Unlike the gold mapping pairs (which must be real vocab rows), these are free
string pairs used only to measure pairwise cosine, so we can construct a
balanced set across the phenomena that matter:

  same_case   - identical meaning, only case/whitespace differs        (MERGE)
  same_punct  - '&' vs 'and', punctuation                              (MERGE)
  same_typo   - spelling error / transposition                        (MERGE)
  same_sem    - synonym / abbreviation / plural / paraphrase           (MERGE)
  diff_sib    - sibling fields, clearly distinct                       (KEEP)
  diff_sub    - a field vs one of its subfields                        (KEEP)
  diff_combo  - a field vs a combined/joint program                    (KEEP)

The decisive question for encoders: can they score `same_sem` ABOVE
`diff_sib/sub/combo`? Typos we already concede to the lexical layer.
"""

PROBE = {
    "same_case": [
        ("Psychology", "PSYCHOLOGY"),
        ("Computer Science", "computer science"),
        ("Mechanical Engineering", "mechanical engineering"),
        ("Education", "EDUCATION"),
        ("Marketing", "marketing"),
        ("Civil Engineering", "CIVIL ENGINEERING"),
    ],
    "same_punct": [
        ("Computer Science & Engineering", "Computer Science and Engineering"),
        ("Accounting & Finance", "Accounting and Finance"),
        ("Arts & Sciences", "Arts and Sciences"),
        ("Science, Technology & Society", "Science Technology and Society"),
    ],
    "same_typo": [
        ("english", "engilsh"),
        ("accounting", "acounting"),
        ("psychology", "psycology"),
        ("mechanical engineering", "mechancial enginering"),
        ("mathematics", "mathmatics"),
        ("finance", "finanace"),
        ("marketing", "markteing"),
        ("biology", "bioligy"),
        ("economics", "ecnomics"),
        ("nursing", "nrusing"),
        ("chemistry", "chemstry"),
        ("sociology", "socilogy"),
    ],
    "same_sem": [
        ("Communications", "Communication"),
        ("Mathematics", "Maths"),
        ("Computer Science", "Computing"),
        ("Political Science", "Politics"),
        ("Economics", "Econ"),
        ("Psychology", "Psych"),
        ("Information Technology", "IT"),
        ("Registered Nursing", "Nursing"),
        ("Business Administration", "Business Management"),
        ("Mechanical Engineering", "Mechanical Eng"),
        ("Accounting", "Accountancy"),
        ("Statistics", "Stats"),
        ("Electrical Engineering", "Electrical & Electronics Engineering"),
        ("Graphic Design", "Graphic Arts"),
        ("Law", "Juris Doctor"),
    ],
    "diff_sib": [
        ("Biology", "Chemistry"),
        ("Finance", "Economics"),
        ("Marketing", "Finance"),
        ("Sociology", "Psychology"),
        ("Physics", "Chemistry"),
        ("Mechanical Engineering", "Electrical Engineering"),
        ("Mechanical Engineering", "Civil Engineering"),
        ("History", "Geography"),
        ("Accounting", "Marketing"),
        ("Political Science", "Sociology"),
        ("Nursing", "Pharmacy"),
        ("Mathematics", "Statistics"),
    ],
    "diff_sub": [
        ("Psychology", "Clinical Psychology"),
        ("Psychology", "Counseling Psychology"),
        ("Biology", "Marine Biology"),
        ("Engineering", "Mechanical Engineering"),
        ("History", "Art History"),
        ("Education", "Special Education"),
        ("Mechanical Engineering", "Mechanical Engineering Technology"),
        ("Nursing", "Pediatric Nursing"),
    ],
    "diff_combo": [
        ("Computer Science", "Computer Science and Engineering"),
        ("Accounting", "Accounting and Finance"),
        ("Mathematics", "Mathematics and Computer Science"),
        ("Computer Science", "Electrical Engineering and Computer Science"),
        ("Biology", "Biology and Chemistry"),
        ("Finance", "Accounting and Finance"),
    ],
}

MERGE_CATS = {"same_case", "same_punct", "same_typo", "same_sem"}
KEEP_CATS = {"diff_sib", "diff_sub", "diff_combo"}
