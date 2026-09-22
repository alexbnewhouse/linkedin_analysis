"""Export a blind sample as a Label Studio project: tasks JSON + labeling config XML.

    uv run python -m coding.export imputed_bachelor        # -> coding/label_studio/imputed_bachelor.{tasks.json,config.xml}
    uv run python -m coding.export --all

Then in Label Studio (see coding/README.md): create a project, paste the config XML into
Labeling Interface > Code, import the tasks JSON, code, export JSON, and run
`coding.ingest` on the export.
"""
from __future__ import annotations

import json
import sys
from xml.sax.saxutils import escape

from coding import common as C


def config_xml(sample: C.Sample, rubric: str) -> str:
    fields = "\n".join(
        f'    <Header value="{escape(f)}" size="6"/>\n    <Text name="{escape(f)}" value="${escape(f)}"/>'
        for f in sample.fields)
    choices = "\n".join(f'      <Choice value="{escape(lbl)}"/>' for lbl in sample.labels)
    return f"""<View>
  <Header value="{escape(sample.question)}"/>
  <Text name="rubric" value="$rubric"/>
  <View style="display: grid; grid-template-columns: 1fr; gap: 4px; padding: 8px; background: #f7f7f7; border-radius: 6px">
{fields}
  </View>
  <Choices name="label" toName="rubric" choice="single" required="true" showInline="true">
{choices}
  </Choices>
  <TextArea name="note" toName="rubric" placeholder="why (optional)" maxSubmissions="1" rows="2"/>
</View>
"""


def export(name: str) -> tuple[str, str]:
    sample = C.SAMPLES[name]
    header, rows = C.read_sample(sample)
    rubric = header.get("rubric", "")
    tasks = []
    for r in rows:
        data = {"id": r["id"], "rubric": rubric}
        for f in sample.fields:
            v = r.get(f)
            data[f] = "" if v is None else (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v))
        tasks.append({"data": data})
    C.LS_DIR.mkdir(parents=True, exist_ok=True)
    tpath = C.LS_DIR / f"{name}.tasks.json"
    cpath = C.LS_DIR / f"{name}.config.xml"
    tpath.write_text(json.dumps(tasks, indent=1, ensure_ascii=False) + "\n")
    cpath.write_text(config_xml(sample, rubric))
    return str(tpath.relative_to(C.ROOT)), str(cpath.relative_to(C.ROOT))


def main() -> None:
    names = list(C.SAMPLES) if "--all" in sys.argv else sys.argv[1:]
    for n in names:
        if not C.SAMPLES[n].path.exists():
            print(f"{n}: sample not drawn yet ({C.SAMPLES[n].path.relative_to(C.ROOT)})")
            continue
        t, c = export(n)
        print(f"{n}: wrote {t} and {c}")


if __name__ == "__main__":
    main()
