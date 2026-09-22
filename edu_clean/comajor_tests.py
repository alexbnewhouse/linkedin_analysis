"""Logic checks for the co-major splitter.

    uv run python -m edu_clean.comajor_tests
"""
from __future__ import annotations

import csv
from pathlib import Path

from edu_clean.comajors import (concentration, majors, marker_class, minor, primary_secondary,
                                split_field)

ROOT = Path(__file__).resolve().parent.parent


def check(name: str, cond: bool) -> None:
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def fams(s):
    return [c[:2] for c in majors(s)]


def main() -> None:
    s = split_field("History and Political Science")
    check("h&ps splits", s.status == "split")
    check("h&ps majors 54 + 45", fams(s) == ["54", "45"])
    check("h&ps plain class", s.marker_class == "plain")
    check("primary by pooled family (45 -> political science primary)",
          primary_secondary(s, "45")[0][:2] == "45" and primary_secondary(s, "45")[1][:2] == "54")
    check("primary by pooled family (54)", primary_secondary(s, "54")[0][:2] == "54")
    check("no_primary when pooled NULL", primary_secondary(s, None)[2] == "no_primary")
    check("conflict when pooled matches no component", primary_secondary(s, "30")[2] == "conflict")

    s = split_field("Biology, Chemistry Minor")
    check("bio/chem splits", s.status == "split" and fams(s) == ["26"])
    check("chem is the minor (40)", minor(s)[:2] == "40")
    check("bio/chem marker class", s.marker_class == "marker")
    s = split_field("English/Journalism")
    check("eng/journ", s.status == "split" and fams(s) == ["23", "09"])
    s = split_field("Double Major in History and French")
    check("double major", s.status == "split" and fams(s) == ["54", "16"])
    s = split_field("Business Administration, Concentration in Finance")
    check("concentration split", s.status == "split")
    check("concentration role", [c.role for c in s.components] == ["major", "concentration"])
    check("concentration kept within family", concentration(s)[:2] == "52")
    check("concentration is not a second major", len(majors(s)) == 1)
    s = split_field("Psychology (Minor in Sociology)")
    check("paren minor", s.status == "split" and minor(s)[:2] == "45")
    s = split_field("Economics, Business (minor)")
    check("trailing (minor) applies to preceding component",
          s.status == "split" and fams(s) == ["45"] and minor(s)[:2] == "52")
    s = split_field("Finance and Marketing")
    check("same-family co-majors collapse to one (unresolved)", s.status == "unresolved")

    for whole in ("Business Administration and Management, General", "English Language and Literature, General",
                  "Criminal Justice and Corrections", "Kinesiology and Exercise Science",
                  "Logistics, Materials, and Supply Chain Management", "History"):
        check(f"single: {whole}", split_field(whole).status == "single")
    check("deterministic method wins even when the lookup fails",
          split_field("Business and Economics", method="typo_to_cip").status == "single")
    check("typo method does not force single",
          split_field("History and Political Science", method="typo").status == "split")
    for prog in ("Computer Science and Engineering", "Computer Science & Engineering",
                 "Electrical Engineering and Computer Science", "Statistics and Data Science",
                 "Philosophy, Politics and Economics", "Criminology, Law & Society", "Radio/TV/Film"):
        check(f"compound single program: {prog}", split_field(prog).status == "single")
    s = split_field("Chemistry (Biochemistry)")
    check("bare parenthetical is a track, not a second major",
          s.status in ("split", "unresolved") and len(majors(s)) == 1 and concentration(s) is not None)
    s = split_field("Economics (Business) & Psychology")
    check("bare parenthetical does not displace the real second major", fams(s) == ["45", "42"])
    check("trailing ', Minor' on a CIP title stays single",
          split_field("Business Administration and Management, Minor").status == "single")
    s = split_field("Physics with Second Major in Mathematics")
    check("'with second major' consumed", s.status == "split" and fams(s) == ["40", "27"])
    s = split_field("Economics, Finance Concentration")
    check("trailing concentration demotes the preceding component", fams(s) == ["45"] and concentration(s)[:2] == "52")
    s = split_field("Electrical Engineering and Computer Science (EECS)")
    check("stoplisted head with a parenthetical stays single", s.status == "single")
    s = split_field("Computer Science and Engineering, Minor in Mathematics")
    check("stoplisted head keeps the minor", s.status == "split" and len(majors(s)) <= 1 and minor(s)[:2] == "27")
    check("criminology and criminal justice is one program", split_field("Criminology and Criminal Justice").status == "single")
    check("empty", split_field("").status == "empty" and split_field(None).status == "empty")
    check("unresolved junk", split_field("study of people and stuff").status in ("unresolved", "single"))
    check("marker_class", marker_class("Double Major in History and French") == "marker"
          and marker_class("History and Political Science") == "plain")

    # every CIP 2020 title is ONE field
    n = bad = 0
    with (ROOT / "reference" / "cip_codes.csv").open() as fh:
        reader = csv.DictReader(fh)
        title_col = next(k for k in reader.fieldnames if "title" in k.lower())
        for row in reader:
            title = row[title_col]
            n += 1
            if split_field(title).status == "split":
                bad += 1
                if bad <= 10:
                    print("   SPLIT CIP TITLE:", title)
    check(f"no CIP title splits ({n} titles, {bad} split)", bad == 0)
    print("comajor logic tests passed")


if __name__ == "__main__":
    main()
