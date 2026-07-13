"""Build the shareable Humanities Workforce portal page.

    python -m portal.run_share_build

Injects portal/results/portal_data.json verbatim into portal/share_template.html
(at the __PORTAL_DATA_JSON__ token) and writes the self-contained page + zip to
share/. The template carries only layout and editorial copy; every number the
page displays comes from the injected JSON, so the page can never drift from
the pipeline output — regenerate it after any portal.run_portal_data run.
"""

from __future__ import annotations

import json
import zipfile

from portal import common as C

TEMPLATE = C.ROOT / "portal" / "share_template.html"
OUT_HTML = C.ROOT / "share" / "Humanities-Workforce-portal.html"
OUT_ZIP = C.ROOT / "share" / "Humanities-Workforce-portal.zip"
TOKEN = "__PORTAL_DATA_JSON__"


def build() -> None:
    data = C.DATA_OUT.read_text().strip()
    json.loads(data)  # refuse to inject anything that isn't valid JSON
    html = TEMPLATE.read_text()
    n = html.count(TOKEN)
    if n != 1:
        raise SystemExit(f"expected exactly one {TOKEN} token in template, found {n}")
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html.replace(TOKEN, data))
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(OUT_HTML, OUT_HTML.name)
    print(f"wrote {OUT_HTML} ({OUT_HTML.stat().st_size:,} bytes) and {OUT_ZIP.name}")


if __name__ == "__main__":
    build()
