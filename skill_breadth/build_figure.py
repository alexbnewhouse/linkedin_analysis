"""Task 4: build the breadth figure page from results/breadth.json.

Writes skill_breadth/figure/index.html: a self-contained fragment (no doctype,
html, head or body tags, because the claude.ai Artifact host wraps it) with the
data inlined, a two-panel ranked dot plot drawn as SVG by a little vanilla JS,
and a table twin of every plotted value.

Run: python -m skill_breadth.build_figure
"""
from __future__ import annotations

import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results" / "breadth.json"
MANIFEST = HERE / "results" / "_cohort_manifest.json"
OUT = HERE / "figure" / "index.html"

SOURCE_LINE = (
    "Source: LinkedIn profile sample (snapshot 2026-02-19; experience through "
    "Oct 2025); O*NET 29.3."
)

# Series role per group: "accent" = the humanities pair, "base" = STEM and
# finance, "ref" = the comparison fields drawn in muted ink.
ROLE = {
    "humanities": "accent",
    "humanistic_social_sciences": "accent",
    "stem": "base",
    "finance": "base",
    "nursing": "ref",
    "accounting": "ref",
}


def pct(x: float) -> str:
    return f"{round(100 * x)}"


def build_rows(d: dict) -> list[dict]:
    meta = d["meta"]
    labels = meta["group_labels"]
    vendi = d["vendi"]
    spread = d["within_person_spread"]
    desc_len = d["median_description_length_chars"]

    def row(g: str, section: str) -> dict:
        v = vendi[g]
        s5 = spread[g]["5+"]
        return {
            "key": g,
            "label": labels[g],
            "section": section,
            "role": ROLE[g],
            "n": v["n_people_available"],
            "text": [v["text"]["median"], v["text"]["lo"], v["text"]["hi"]],
            "skills": [
                v["onet_skills"]["median"],
                v["onet_skills"]["lo"],
                v["onet_skills"]["hi"],
            ],
            "spread5": s5["median_spread"],
            "spread5_n": s5["n_people"],
            "desc_len": desc_len[g],
        }

    by_text = lambda gs: sorted(gs, key=lambda g: -vendi[g]["text"]["median"])
    head = [row(g, "head") for g in by_text(meta["headline_groups"])]
    ref = [row(g, "ref") for g in by_text(meta["sanity_groups"]) if g in vendi]
    return head + ref


def caption_text(d: dict) -> str:
    meta = d["meta"]
    man = json.loads(MANIFEST.read_text())
    dl = d["median_description_length_chars"]
    rho = d["spearman_rank_agreement"]["rho"]
    soc = d["soc_source_share"]
    nearest = [soc[g]["nearest"] for g in soc]
    n_groups = len(d["spearman_rank_agreement"]["groups_order"])
    words = {6: "six", 5: "five", 4: "four"}.get(n_groups, str(n_groups))
    return " ".join(
        [
            "The sample is drawn from a 2.0-million-profile LinkedIn snapshot of "
            "the US workforce: people who finished a bachelor's degree between "
            f"{man['cohort_year_min']} and {man['cohort_year_max']}, and the jobs "
            "they started in their graduation year or the "
            f"{man['role_window_years']} years after, counting only jobs with a "
            f"description of at least {man['min_description_len']} characters.",
            f"Each estimate draws {meta['n_people']} graduates per field with one "
            f"job each, and the draw is repeated {meta['n_boot']} times. Dots mark "
            "the middle value; lines span the middle 95 percent of draws.",
            "The right panel repeats the count using the O*NET skill ratings of "
            "each job's occupation instead of the description text.",
            "Humanities follows the NHA definition, except that general studies "
            "and liberal arts majors are left out because they also match other "
            "groups.",
            "Humanities graduates write shorter job descriptions than STEM "
            f"graduates (a median of {dl['humanities']:.0f} characters against "
            f"{dl['stem']:.0f}), so wordier write-ups do not explain the gap.",
            f"The two measures rank all {words} fields in the same order "
            f"(Spearman rho = {rho:.2f}).",
            "Most O*NET occupation codes were matched automatically from job "
            f"titles and descriptions ({pct(min(nearest))} to {pct(max(nearest))} "
            "percent of jobs, depending on the field); the rest came from "
            "occupation codes already in the data.",
        ]
    )


def fmt1(x: float) -> str:
    return f"{x:.1f}"


def table_html(rows: list[dict]) -> str:
    out = []
    for i, r in enumerate(rows):
        cls = []
        if r["section"] == "ref" and (i == 0 or rows[i - 1]["section"] != "ref"):
            cls.append("first-ref")
        if r["section"] == "ref":
            cls.append("ref")
        t, s = r["text"], r["skills"]
        out.append(
            f'<tr class="{" ".join(cls)}">'
            f'<th scope="row">{html.escape(r["label"])}</th>'
            f'<td>{r["n"]:,}</td>'
            f"<td>{fmt1(t[0])}</td>"
            f'<td class="rng">{fmt1(t[1])}–{fmt1(t[2])}</td>'
            f"<td>{fmt1(s[0])}</td>"
            f'<td class="rng">{fmt1(s[1])}–{fmt1(s[2])}</td>'
            f'<td>{r["spread5"]:.2f} <span class="sub">({r["spread5_n"]:,})</span></td>'
            f'<td>{r["desc_len"]:,.0f}</td>'
            "</tr>"
        )
    return "\n".join(out)


TEMPLATE = r"""<title>Breadth of Work by Major</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=Public+Sans:wght@400;500;600&display=swap">
<style>
:root{
  color-scheme: light;
  --paper:#ffffff; --ink:#1c1c1c; --ink2:#4a4a46; --muted:#73736d;
  --rule:#dedcd6; --rule2:#c4c2bb; --line:#3a6fb0; --focus:#1d4f8a;
  --tip-bg:#ffffff; --tip-shadow:rgba(0,0,0,.10);
  --serif:Newsreader,Georgia,"Times New Roman",serif;
  --sans:"Public Sans","Helvetica Neue",Arial,sans-serif;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --paper:#161615; --ink:#ebeae4; --ink2:#c3c2bb; --muted:#8e8d86;
    --rule:#2f2f2c; --rule2:#484743; --line:#5b8dc9; --focus:#8fb8e6;
    --tip-bg:#1e1e1c; --tip-shadow:rgba(0,0,0,.4);
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --paper:#161615; --ink:#ebeae4; --ink2:#c3c2bb; --muted:#8e8d86;
  --rule:#2f2f2c; --rule2:#484743; --line:#5b8dc9; --focus:#8fb8e6;
  --tip-bg:#1e1e1c; --tip-shadow:rgba(0,0,0,.4);
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--paper)}
body{color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.55;-webkit-font-smoothing:antialiased;overflow-x:hidden}
em,i,cite,var,address{font-style:normal}
.page{max-width:1040px;margin:0 auto;padding:36px 16px 56px}
h1{font-family:var(--serif);font-weight:500;font-size:40px;line-height:1.1;margin:0 0 12px;letter-spacing:-.01em;text-wrap:balance;max-width:18em}
.lede{font-size:17px;color:var(--ink2);margin:0 0 28px;max-width:38em}
h2{font-family:var(--serif);font-weight:600;font-size:21px;line-height:1.25;margin:0 0 8px}
.howto{border-top:1px solid var(--rule);padding-top:18px;margin:0 0 28px}
.howto p{margin:0;max-width:40em;color:var(--ink)}
figure{margin:0 0 40px;padding:0}
.fig-head{display:grid;grid-template-columns:48px minmax(0,1fr);gap:8px;align-items:baseline;margin-bottom:18px;border-top:1px solid var(--rule);padding-top:18px}
.fig-n{font-size:13px;color:var(--muted);font-weight:500}
.fig-title{font-family:var(--serif);font-weight:600;font-size:24px;line-height:1.2;margin:0;text-wrap:balance}
.fig-dek{margin:4px 0 0;font-size:15.5px;color:var(--ink2)}
.panels{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:24px 44px}
.panel h3{font-family:var(--sans);font-weight:600;font-size:15px;margin:0 0 2px;color:var(--ink)}
.panel .axis-note{font-size:13px;color:var(--muted);margin:0 0 6px}
.panel svg{display:block;width:100%;overflow:visible}
svg text{font-family:var(--sans)}
.grid{stroke:var(--rule);stroke-width:1}
.sep{stroke:var(--rule2);stroke-width:1}
.tick{font-size:11.5px;fill:var(--muted);font-variant-numeric:tabular-nums}
.axt{font-size:12px;fill:var(--muted)}
.rl{font-size:13.5px;fill:var(--ink)}
.rl.ref{fill:var(--muted)}
.rl.head{font-weight:500}
.sec{font-size:12px;fill:var(--muted)}
.val{font-size:12.5px;fill:var(--ink2);font-variant-numeric:tabular-nums;paint-order:stroke;stroke:var(--paper);stroke-width:3px;stroke-linejoin:round}
.whisk{stroke-width:1.5;stroke-linecap:round}
.dot{stroke:var(--paper);stroke-width:2}
.accent .whisk{stroke:var(--line)} .accent .dot{fill:var(--line)}
.base .whisk{stroke:var(--ink2)} .base .dot{fill:var(--ink2)}
.ref .whisk{stroke:var(--muted)} .ref .dot{fill:var(--muted)}
.hit{fill:transparent;cursor:default}
.mark:focus{outline:none}
.mark:focus .ring,.mark:hover .ring{stroke:var(--focus);stroke-width:1.5;fill:none}
.ring{stroke:none;fill:none}
.key{display:flex;flex-wrap:wrap;gap:4px 20px;font-size:13px;color:var(--ink2);margin:0 0 14px;padding:0;list-style:none}
.key li{display:flex;align-items:center;gap:7px}
.key svg{flex:none}
figcaption{margin-top:18px;padding-top:10px;border-top:1px solid var(--rule);font-size:13px;color:var(--muted);line-height:1.55}
figcaption p{margin:0 0 6px;max-width:62em}
figcaption p:last-child{margin:0}
.tip{position:fixed;z-index:10;pointer-events:none;background:var(--tip-bg);color:var(--ink);border:1px solid var(--rule2);border-radius:3px;padding:8px 10px;font-size:13px;line-height:1.45;box-shadow:0 4px 14px var(--tip-shadow);max-width:260px;opacity:0;transition:opacity .08s}
.tip.on{opacity:1}
.tip b{font-weight:600;display:block;margin-bottom:2px}
.tip .k{color:var(--muted)}
.tip span{font-variant-numeric:tabular-nums}
.tbl-sec{border-top:1px solid var(--rule);padding-top:18px}
.tbl-head{display:grid;grid-template-columns:48px minmax(0,1fr);gap:8px;align-items:baseline;margin-bottom:12px}
.tbl-head h2{font-size:19px;margin:0}
.tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:640px}
th,td{padding:7px 10px;border-bottom:1px solid var(--rule);vertical-align:bottom}
thead th{font-weight:500;color:var(--muted);font-size:12.5px;line-height:1.3;text-align:right;border-bottom:1px solid var(--rule2)}
thead th:first-child{text-align:left;padding-left:0}
tbody th{text-align:left;font-weight:500;padding-left:0;white-space:nowrap}
td{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.rng{color:var(--ink2);padding-left:2px}
td .sub{color:var(--muted);font-size:12px}
tr.ref th,tr.ref td{color:var(--muted)}
tr.first-ref th,tr.first-ref td{border-top:1px solid var(--rule2)}
thead tr.grp th{border-bottom:none;padding-bottom:0}
.scroll-cue{display:none;font-size:13px;color:var(--muted);margin:0 0 6px}
.tbl-note{font-size:13px;color:var(--muted);margin:10px 0 0;max-width:62em}
@media (max-width:720px){
  h1{font-size:30px}
  .panels{grid-template-columns:minmax(0,1fr);gap:28px}
  .fig-head,.tbl-head{grid-template-columns:minmax(0,1fr);gap:2px}
  .fig-title{font-size:21px}
  .scroll-cue{display:block}
  .page{padding-top:24px}
}
</style>

<main class="page">
  <h1>Humanities graduates go on to a broad range of work</h1>
  <p class="lede">A comparison of how many distinct kinds of jobs graduates of four fields hold in their first ten years after a bachelor's degree, with nursing and accounting for comparison.</p>

  <section class="howto" aria-labelledby="howto-h">
    <h2 id="howto-h">How to read this</h2>
    <p>__HOWTO__</p>
  </section>

  <figure aria-labelledby="fig1-title">
    <div class="fig-head">
      <span class="fig-n">Fig. 1</span>
      <div>
        <p class="fig-title" id="fig1-title">__FIGTITLE__</p>
        <p class="fig-dek">__FIGDEK__</p>
      </div>
    </div>
    <ul class="key" aria-label="Key">
      <li><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="var(--line)"/></svg>Humanities fields</li>
      <li><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="var(--ink2)"/></svg>STEM and finance</li>
      <li><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="var(--muted)"/></svg>Included for comparison</li>
      <li><svg width="30" height="14" aria-hidden="true"><line x1="2" y1="7" x2="28" y2="7" stroke="var(--ink2)" stroke-width="1.5" stroke-linecap="round"/></svg>Range across resamples</li>
    </ul>
    <div class="panels">
      <div class="panel">
        <h3>Job descriptions</h3>
        <p class="axis-note">Effective number of distinct jobs</p>
        <svg id="p-text" role="group" aria-label="Job descriptions: effective number of distinct jobs by field"></svg>
      </div>
      <div class="panel">
        <h3>O*NET skill profiles</h3>
        <p class="axis-note">Effective number of distinct skill profiles</p>
        <svg id="p-skills" role="group" aria-label="O*NET skill profiles: effective number of distinct skill profiles by field"></svg>
      </div>
    </div>
    <figcaption>
      <p>Note: __CAPTION__</p>
      <p>__SOURCE__</p>
    </figcaption>
  </figure>

  <section class="tbl-sec" aria-labelledby="t1-h">
    <div class="tbl-head">
      <span class="fig-n">Table 1</span>
      <h2 id="t1-h">The numbers behind the figure</h2>
    </div>
    <p class="scroll-cue">Scroll sideways for more columns.</p>
    <div class="tbl-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Field</th>
            <th scope="col">People in sample pool</th>
            <th scope="col" colspan="2">Job-description breadth<br>and range</th>
            <th scope="col" colspan="2">Skill-profile breadth<br>and range</th>
            <th scope="col">Within-person spread, 5+ jobs (people)</th>
            <th scope="col">Median description length (characters)</th>
          </tr>
        </thead>
        <tbody>
__TBODY__
        </tbody>
      </table>
    </div>
    <p class="tbl-note">Breadth values are the middle of __NBOOT__ draws of __NPEOPLE__ graduates; the range spans the middle 95 percent of draws. Within-person spread is the average difference between the descriptions of one person's own jobs, from 0 for identical descriptions upward, for people with five or more described jobs. Nursing and Accounting are included for comparison.</p>
  </section>
</main>
<div class="tip" id="tip" role="tooltip" aria-hidden="true"></div>

<script>
const DATA = __DATA__;
(function(){
  const NS = "http://www.w3.org/2000/svg";
  const tip = document.getElementById("tip");
  const f1 = x => x.toFixed(1);
  const fint = n => n.toLocaleString("en-US");
  const PANELS = [
    {id:"p-text", key:"text", max:30, ticks:[0,10,20,30], unit:"distinct jobs"},
    {id:"p-skills", key:"skills", max:10, ticks:[0,2,4,6,8,10], unit:"distinct skill profiles"}
  ];
  function el(tag, attrs, parent, text){
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  function showTip(r, p, target){
    const v = r[p.key];
    tip.innerHTML = "<b></b><div><span class='k'>Middle value: </span><span></span></div>"
      + "<div><span class='k'>Range: </span><span></span></div>"
      + "<div><span class='k'>People in sample pool: </span><span></span></div>";
    tip.querySelector("b").textContent = r.label;
    const s = tip.querySelectorAll("div > span:not(.k)");
    s[0].textContent = f1(v[0]) + " " + p.unit;
    s[1].textContent = f1(v[1]) + " to " + f1(v[2]);
    s[2].textContent = fint(r.n);
    tip.classList.add("on");
    const b = target.getBoundingClientRect(), t = tip.getBoundingClientRect();
    let x = b.left + b.width/2 - t.width/2, y = b.top - t.height - 8;
    if (y < 8) y = b.bottom + 8;
    x = Math.max(8, Math.min(x, window.innerWidth - t.width - 8));
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  function hideTip(){ tip.classList.remove("on"); }

  function draw(p){
    const svg = document.getElementById(p.id);
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const W = svg.clientWidth || svg.parentNode.clientWidth;
    const narrow = W < 440;
    const labelW = narrow ? 0 : 178;
    const padR = 40;                      // room for the value label past the whisker
    const x0 = labelW + 4, x1 = W - padR;
    const X = v => x0 + (v / p.max) * (x1 - x0);
    const rowH = narrow ? 46 : 32, secH = narrow ? 30 : 34, top = 6;
    // Row positions: headline rows, then a separator block, then reference rows.
    let y = top, ys = [], sepY = null;
    DATA.rows.forEach((r, i) => {
      if (r.section === "ref" && DATA.rows[i-1].section !== "ref"){ sepY = y; y += secH; }
      ys.push(y + (narrow ? 32 : rowH/2)); y += rowH;
    });
    const plotBottom = y + 2, H = plotBottom + 40;
    svg.setAttribute("height", H);
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    const g0 = el("g", {"aria-hidden":"true"}, svg);
    p.ticks.forEach(t => {
      el("line", {class:"grid", x1:X(t), x2:X(t), y1:top, y2:plotBottom}, g0);
      el("text", {class:"tick", x:X(t), y:plotBottom + 16, "text-anchor":"middle"}, g0, t);
    });
    el("text", {class:"axt", x:x0, y:plotBottom + 34}, g0,
       p.key === "text" ? "Effective number of distinct jobs" : "Effective number of distinct skill profiles");
    if (sepY != null){
      el("line", {class:"sep", x1:0, x2:W, y1:sepY + 6, y2:sepY + 6}, g0);
      el("text", {class:"sec", x:0, y:sepY + 24}, g0, "Fields included for comparison");
    }
    DATA.rows.forEach((r, i) => {
      const cy = ys[i], v = r[p.key];
      const lab = el("text", {class:"rl " + r.section, x:0, y: narrow ? cy - 11 : cy + 4.5, "aria-hidden":"true"}, g0, r.label);
      const g = el("g", {class:"mark " + r.role, tabindex:"0", role:"img",
        "aria-label": r.label + ": " + f1(v[0]) + " " + p.unit + ", range " + f1(v[1]) + " to " + f1(v[2])
          + ", " + fint(r.n) + " people in sample pool"}, svg);
      el("line", {class:"whisk", x1:X(v[1]), x2:X(v[2]), y1:cy, y2:cy}, g);
      el("circle", {class:"ring", cx:X(v[0]), cy:cy, r:9}, g);
      el("circle", {class:"dot", cx:X(v[0]), cy:cy, r:5}, g);
      el("rect", {class:"hit", x:X(v[1]) - 8, y:cy - 12, width:Math.max(24, X(v[2]) - X(v[1]) + 16), height:24}, g);
      if (r.section === "head")
        el("text", {class:"val", x:X(v[2]) + 8, y:cy + 4.5, "aria-hidden":"true"}, g0, f1(v[0]));
      g.addEventListener("pointerenter", () => showTip(r, p, g.querySelector(".dot")));
      g.addEventListener("pointerleave", hideTip);
      g.addEventListener("focus", () => showTip(r, p, g.querySelector(".dot")));
      g.addEventListener("blur", hideTip);
    });
  }
  let raf = 0, lastW = 0;
  function drawAll(){
    const w = document.documentElement.clientWidth;
    if (w === lastW) return; lastW = w;
    PANELS.forEach(draw);
  }
  drawAll();
  window.addEventListener("resize", () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(drawAll); });
  window.addEventListener("scroll", hideTip, {passive:true});
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { lastW = 0; drawAll(); });
})();
</script>
"""

HOWTO = (
    "Each dot counts how many different kinds of work a field's graduates hold. "
    "We call this the effective number of distinct jobs: if the jobs of 500 "
    "randomly drawn graduates were sorted into groups of truly different work, "
    "this is roughly how many groups you would get. A higher number means the "
    "field's graduates spread across a wider range of work. The thin line around "
    "each dot shows how much the number moves when the draw of 500 is repeated."
)


def main() -> None:
    d = json.loads(RESULTS.read_text())
    rows = build_rows(d)
    by = {r["key"]: r for r in rows}
    hum, stem = by["humanities"], by["stem"]
    assert hum["text"][1] > stem["text"][2], "title claim no longer holds (text)"
    assert hum["skills"][1] > stem["skills"][2], "title claim no longer holds (skills)"
    fin = by["finance"]
    assert hum["text"][1] > fin["text"][2], "title claim no longer holds (finance, text)"
    assert hum["skills"][1] > fin["skills"][2], "title claim no longer holds (finance, skills)"
    fig_title = (
        "Humanities graduates hold a wider range of jobs than STEM or finance "
        "graduates"
    )
    fig_dek = (
        "Humanistic social sciences follow close behind. Both measures put the "
        "fields in the same order."
    )
    payload = {"rows": rows}
    page = (
        TEMPLATE.replace("__HOWTO__", html.escape(HOWTO))
        .replace("__FIGTITLE__", html.escape(fig_title))
        .replace("__FIGDEK__", html.escape(fig_dek))
        .replace("__CAPTION__", html.escape(caption_text(d)))
        .replace("__SOURCE__", html.escape(SOURCE_LINE))
        .replace("__TBODY__", table_html(rows))
        .replace("__NBOOT__", str(d["meta"]["n_boot"]))
        .replace("__NPEOPLE__", str(d["meta"]["n_people"]))
        .replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page)
    print(f"wrote {OUT} ({len(page):,} bytes)")


if __name__ == "__main__":
    main()
