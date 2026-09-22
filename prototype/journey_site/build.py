"""Build prototype/journey-site.html from template.html and journey_data.json.

Usage:
  .venv/bin/python prototype/journey_site/extract.py   # needs duckdb; rebuilds journey_data.json
  python3 prototype/journey_site/build.py              # injects it into the template

Published artifact (update in place):
https://claude.ai/code/artifact/4d61ae32-0cfc-4b24-95d2-d8b159f54b0e
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "journey-site.html"


def main():
    data = (HERE / "journey_data.json").read_text().replace("</", "<\\/")
    html = (HERE / "template.html").read_text()
    assert "__DATA__" in html
    OUT.write_text(html.replace("__DATA__", data))
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
