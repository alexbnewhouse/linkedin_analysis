"""Inject the map data and framework vocabulary into the demo template.

    uv run python -m archetype_methods.demo_build [out.html]
"""

from __future__ import annotations

import json
import sys

from . import common as C
from . import framework as F

DEMO = C.RESULTS / "demo"


def main(out: str | None = None):
    roles = json.loads((DEMO / "roles.json").read_text())
    slim = [{"title": r["title"], "n": r["n"], "x": r["x"], "y": r["y"], "a": r["a"], "b": r["b"]} for r in roles]
    fw = {a.key: {"orientation": a.orientation, "skills": list(a.skills), "pathways": list(a.pathways),
                  "titles": sorted({t for ts in a.pathways.values() for t in ts})} for a in F.ARCHETYPES}
    html = (C.HERE / "demo_template.html").read_text()
    html = html.replace("__ROLES__", json.dumps(slim, separators=(",", ":"))).replace(
        "__FRAMEWORK__", json.dumps(fw, separators=(",", ":")))
    dst = C.HERE / "figures" / "archetype-map.html" if out is None else __import__("pathlib").Path(out)
    dst.write_text(html)
    print("wrote", dst, len(html) // 1024, "KB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
