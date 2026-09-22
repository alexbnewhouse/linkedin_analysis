"""Logic checks for coding/ (no data needed).

    uv run python -m coding.coding_tests
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from coding import common as C
from coding import export as E
from coding import ingest as I


def check(name: str, cond: bool) -> None:
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def main() -> None:
    a = {"1": {"label": "pass"}, "2": {"label": "pass"}, "3": {"label": "fail"}, "4": {"label": "unsure"}}
    p = C.precision(a)
    check("precision strict counts unsure against", abs(p["strict"] - 0.5) < 1e-9)
    check("precision lenient excludes unsure", abs(p["lenient"] - 2 / 3) < 1e-9)
    check("precision empty", C.precision({})["strict"] is None)
    b = {"1": {"label": "pass"}, "2": {"label": "fail"}, "3": {"label": "fail"}, "5": {"label": "pass"}}
    k = C.cohen_kappa(a, b)
    check("kappa on shared ids only", k["n"] == 3)
    check("kappa agreement 2/3", abs(k["agreement"] - 2 / 3) < 1e-9)
    check("kappa disagreement listed", k["disagreements"] == [{"id": "2", "a": "pass", "b": "fail"}])
    check("kappa perfect", C.cohen_kappa(a, a)["kappa"] == 1.0)
    check("kappa disjoint", C.cohen_kappa(a, {"9": {"label": "pass"}})["kappa"] is None)

    s = C.SAMPLES["imputed_bachelor"]
    xml = E.config_xml(s, "rubric text")
    for frag in ('<Choices name="label"', '<Choice value="pass"/>', 'value="$school_raw"',
                 '<TextArea name="note"'):
        check(f"config xml has {frag}", frag in xml)

    with tempfile.TemporaryDirectory() as td:
        exp = Path(td) / "export.json"
        exp.write_text(json.dumps([
            {"data": {"id": "x:000"}, "annotations": [{"result": [
                {"from_name": "label", "type": "choices", "value": {"choices": ["fail"]}},
                {"from_name": "note", "type": "textarea", "value": {"text": ["a minor"]}}]}]},
            {"data": {"id": "x:001"}, "annotations": [{"was_cancelled": True, "result": []}]},
            {"data": {"id": "x:002"}, "annotations": [{"result": [
                {"from_name": "label", "type": "choices", "value": {"choices": ["pass"]}}]}]},
        ]))
        got = I.parse_label_studio(exp)
        check("ingest keeps labeled, skips cancelled",
              got == [{"id": "x:000", "label": "fail", "note": "a minor"},
                      {"id": "x:002", "label": "pass", "note": ""}])
        csvp = Path(td) / "l.csv"
        csvp.write_text("id,label,note\nx:000,pass,\nx:001,unsure,hmm\n")
        check("ingest csv", I.parse_csv(csvp) == [{"id": "x:000", "label": "pass", "note": ""},
                                                   {"id": "x:001", "label": "unsure", "note": "hmm"}])
    print("coding tests passed")


if __name__ == "__main__":
    main()
