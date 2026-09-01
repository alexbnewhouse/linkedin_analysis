"""Integrity + sanity checks for the Pathways portal pipeline.

    uv run python -m portal.portal_tests

Plain-assert style (cf. cohorts/cohort_tests.py, paths/spine_tests.py). Builds
the shared substrate in-memory and validates: join-key integrity (no fan-out on
linkedin_id), window discipline (no partially-observed person in a windowed
stat), suppression (an injected tiny cell is suppressed), nested-tier
consistency (L1 subset of L2 subset of L3), and RR sanity (baseline RR == 1.0).
"""

from __future__ import annotations


import duckdb

from portal import analyses, build, common as C, pillars


def main() -> None:
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={C.DEFAULT_THREADS}")
    build.load_or_build_substrate(con)   # default membership + panel (cached)
    analyses.register_occ_nodes(con)

    def check(name, cond):
        assert cond, f"FAIL: {name}"
        print(f"  ok: {name}")

    # --- 1. join-key integrity: membership is unique per (group, person) -----
    dup = con.execute(
        "SELECT count(*) - count(DISTINCT (group_key, linkedin_id)) FROM membership"
    ).fetchone()[0]
    check("membership: one row per (group_key, linkedin_id) [no fan-out]", dup == 0)

    # panel is unique per (person, calendar_year) -> joining membership to panel
    # cannot fan out a person within a group beyond one row per year.
    pdup = con.execute(
        "SELECT count(*) - count(DISTINCT (linkedin_id, cal_year)) FROM panel"
    ).fetchone()[0]
    check("panel: one primary row per (person, calendar_year)", pdup == 0)

    # --- 2. window discipline -----------------------------------------------
    fan = analyses.destination_fan(con)  # materializes fan_endpoint (y10 window)
    cut10 = C.SNAPSHOT_YEAR - C.FAN_YEAR
    leak = con.execute(
        f"SELECT count(*) FROM fan_endpoint fe JOIN membership m "
        f"USING (group_key, linkedin_id) WHERE m.anchor > {cut10}").fetchone()[0]
    check("window: no fan-endpoint person with anchor > snapshot-10", leak == 0)

    # every curve horizon confines its cohort to anchor <= snapshot - y
    cv = analyses.curve(con)
    win_ok = True
    for y in C.CURVE_YEARS:
        cut = C.SNAPSHOT_YEAR - y
        n = con.execute(
            f"SELECT count(*) FROM membership m JOIN panel p "
            f"ON p.linkedin_id = m.linkedin_id AND p.cal_year = m.anchor + {y} "
            f"WHERE m.anchor > {cut} AND p.seniority_score IS NOT NULL"
        ).fetchone()[0]
        win_ok = win_ok and (n == 0)
    check("window: no partially-observed person in any curve horizon", win_ok)

    # curve n per point is the count of observed persons; a windowed y10 person
    # is fully observed for all y <= 10, so n at y0 >= n at y10 within a group.
    eng = cv["english"]
    check("window: curve n non-increasing across long horizons (english)",
          eng["n"][eng["years"].index(0)] >= eng["n"][eng["years"].index(20)])

    # --- 3. suppression: an injected tiny cell must be suppressed ------------
    # inject a synthetic 3-person group and assert its fan cells never surface.
    con.execute("""
      INSERT INTO membership (group_key, linkedin_id, anchor, anchor_method)
      SELECT '_tiny' AS group_key, linkedin_id, 2000 AS anchor, 'A1' AS anchor_method
      FROM (SELECT DISTINCT linkedin_id FROM membership LIMIT 3)
    """)
    tiny_fan = analyses.destination_fan(con)
    tiny_cells = tiny_fan.get("_tiny", {}).get("fan", [])
    check(f"suppression: 3-person group emits no fan cell (all < MIN_SUPPORT="
          f"{C.MIN_SUPPORT})",
          all(c["n"] >= C.MIN_SUPPORT for c in tiny_cells) and len(tiny_cells) == 0)
    con.execute("DELETE FROM membership WHERE group_key = '_tiny'")

    # every emitted fan/sector/curve cell in the real output clears MIN_SUPPORT
    fan = analyses.destination_fan(con)
    sec = analyses.sectors(con)
    emitted_ok = all(
        c["n"] >= C.MIN_SUPPORT
        for g in C.MAJORS for c in fan[g]["fan"] + sec[g]["sectors"])
    check("suppression: no emitted fan/sector cell below MIN_SUPPORT", emitted_ok)

    # --- 4. nested-tier consistency L1 subset L2 subset L3 -------------------
    b = build.boundary_counts(con)
    check("tiers: records L1 <= L2 <= L3",
          b["l1"]["records"] <= b["l2"]["records"] <= b["l3"]["records"])
    check("tiers: persons L1 <= L2 <= L3",
          b["l1"]["persons"] <= b["l2"]["persons"] <= b["l3"]["persons"])
    # explicit subset: every L1 person is an L2 person is an L3 person
    edu = f"read_parquet('{C.q(C.EDUCATION)}')"
    subset = con.execute(f"""
      SELECT
        (SELECT count(*) FROM (SELECT DISTINCT linkedin_id FROM {edu} WHERE nha_level = 1) a
         WHERE a.linkedin_id NOT IN (SELECT DISTINCT linkedin_id FROM {edu} WHERE nha_level IN (1,2))),
        (SELECT count(*) FROM (SELECT DISTINCT linkedin_id FROM {edu} WHERE nha_level IN (1,2)) a
         WHERE a.linkedin_id NOT IN (SELECT DISTINCT linkedin_id FROM {edu} WHERE nha_level IN (1,2,3)))
    """).fetchone()
    check("tiers: L1 persons subset of L2 subset of L3", subset[0] == 0 and subset[1] == 0)

    # --- 5. RR sanity: baseline fan RR is identically 1.0 -------------------
    base_rr = [c["rr"] for c in fan[C.BASELINE_KEY]["fan"]]
    check("RR: baseline fan RR == 1.0 for every cell",
          all(abs(r - 1.0) < 1e-9 for r in base_rr))

    # --- 6. pillar parity: baseline pillars sit at ~50 (self-percentile) ----
    pil = pillars.compute(con)
    base_pil = pil[C.BASELINE_KEY]
    check("pillars: baseline near parity (45-55) by construction",
          all(v is None or 44 <= v <= 56 for v in base_pil.values()))

    # --- 7. Anchor tiers (COVERAGE_PLAN.md Plan 2) ---------------------------
    # (a) anchor table has no person-level fan-out, for every tier combo.
    for tiers in (("A1",), ("A1", "A2"), ("A1", "A2", "A3")):
        build.build_membership(con, tiers=tiers)
        dup = con.execute(
            "SELECT count(*) - count(DISTINCT (group_key, linkedin_id)) FROM membership"
        ).fetchone()[0]
        check(f"anchors {tiers}: membership has no person-level fan-out", dup == 0)

    # (b) A1-only anchors are byte-identical to the pre-Plan-2 rule (the
    # original inline min(end_year) SQL that used to live in build_membership).
    # Pinned to det-only CIP inputs: the old rule reads the raw education
    # parquet, so with CIP_SOURCES pooling (field_cip_jury, 2026-07-09) the
    # default membership legitimately admits jury-coded fields and diverges.
    build.build_membership(con, tiers=("A1",), cip_sources=("deterministic",))
    edu = f"read_parquet('{C.q(C.EDUCATION)}')"
    old_rule_ok = True
    for key, (_name, fams, _tier) in C.MAJORS.items():
        pred = C.major_cip_predicate(fams, "e")
        old = con.execute(f"""
          SELECT e.linkedin_id, min(e.end_year) AS anchor
          FROM {edu} e
          WHERE e.degree_level = {C.BACHELOR_LEVEL} AND {pred}
            AND e.end_year BETWEEN {C.MIN_ANCHOR_YEAR} AND {C.SNAPSHOT_YEAR}
            AND NOT coalesce(e.in_progress, FALSE)
          GROUP BY e.linkedin_id
        """).fetchall()
        new = con.execute(
            f"SELECT linkedin_id, anchor FROM membership WHERE group_key = '{key}'"
        ).fetchall()
        old_rule_ok = old_rule_ok and (sorted(old) == sorted(new))
    check("anchors: A1-only membership byte-identical to the pre-Plan-2 rule", old_rule_ok)

    # (c) excluding a tier shrinks cohorts monotonically: A1 <= A1+A2 <= A1+A2+A3.
    sizes = []
    for tiers in (("A1",), ("A1", "A2"), ("A1", "A2", "A3")):
        build.build_membership(con, tiers=tiers)
        n = con.execute(
            "SELECT count(*) FROM membership WHERE group_key = 'english'").fetchone()[0]
        sizes.append(n)
    check("anchors: cohort size non-decreasing as tiers are added (A1 <= A1+A2 <= A1+A2+A3)",
          sizes[0] <= sizes[1] <= sizes[2])

    # anchor_method_mix sums to 1.0 and only cites methods in the active ANCHOR_TIERS.
    build.build_membership(con)  # restore the default (ANCHOR_TIERS) membership
    funnel = build.group_funnel(con)
    mix_ok = all(
        abs(sum(f["anchor_method_mix"].values()) - 1.0) < 1e-6
        and set(f["anchor_method_mix"]) <= set(C.ANCHOR_TIERS)
        for f in funnel.values())
    check("anchor_method_mix sums to 1.0 and only cites tiers in ANCHOR_TIERS", mix_ok)

    # --- SOC source pooling (career_clean LLM jury) ---------------------------
    # These checks build the POOLED panel EXPLICITLY (not the SOC_SOURCES
    # default, which may be held at deterministic-only by the bias-check
    # policy) -- the 2026-07-08 review found the original version compared
    # det-only to det-only, which was vacuous.
    jury_available = C.ROLE_SOC_JURY.exists()
    build.build_panel(con, soc_sources=("deterministic", "llm_jury"))

    # (a) pooled panel is still unique per (person, year) -- the jury join
    # must not fan out (guarded at read time in build_panel; verified here).
    pdup2 = con.execute(
        "SELECT count(*) - count(DISTINCT (linkedin_id, cal_year)) FROM panel"
    ).fetchone()[0]
    check("soc pooling: POOLED panel keeps one row per (person, year)", pdup2 == 0)

    # (b) the deterministic backbone always wins: no det-coded panel row may
    # carry a jury source, and det rows' soc_major must match their own code.
    bad = con.execute(f"""
      SELECT count(*) FROM panel
      WHERE occupation_code IS NOT NULL
        AND (soc_source != 'det'
             OR soc_major IS DISTINCT FROM {C.soc_major_case('occupation_code')})
    """).fetchone()[0]
    check("soc pooling: deterministic rows keep their own major + 'det' source", bad == 0)

    # (c) soc_major and soc_source are null together (consistency).
    bad = con.execute(
        "SELECT count(*) FROM panel "
        "WHERE (soc_major IS NULL) != (soc_source IS NULL)").fetchone()[0]
    check("soc pooling: soc_major and soc_source null together", bad == 0)

    if jury_available:
        jury_rows = con.execute(
            "SELECT count(*) FROM panel WHERE soc_source = 'jury'").fetchone()[0]
        check("soc pooling: pooled panel actually contains jury rows "
              f"({jury_rows:,})", jury_rows > 0)

    # (d) det-only panel: excluding the jury never CHANGES a det label, only
    # removes jury ones -- and the pipeline runs without the jury source.
    con.execute("CREATE OR REPLACE TEMP TABLE panel_pooled AS SELECT * FROM panel")
    build.build_panel(con, soc_sources=("deterministic",))
    bad = con.execute("""
      SELECT count(*) FROM panel d JOIN panel_pooled p
        ON d.linkedin_id = p.linkedin_id AND d.cal_year = p.cal_year
      WHERE (d.soc_major IS NOT NULL AND d.soc_major IS DISTINCT FROM p.soc_major)
         OR (p.soc_source = 'det' AND d.soc_major IS NULL)
    """).fetchone()[0]
    check("soc pooling: det-only run is a strict subset (jury only fills NULLs)", bad == 0)
    jury_only = con.execute(
        "SELECT count(*) FROM panel WHERE soc_source = 'jury'").fetchone()[0]
    check("soc pooling: det-only panel carries zero jury rows", jury_only == 0)
    build.build_panel(con)  # restore default

    # (d) pathway mining at soc grain: every emitted route clears the support
    # bar, stages collapse duplicates, and grain is declared.
    fan2 = analyses.destination_fan(con)
    top5 = {g: [c["group"] for c in fan2[g]["fan"][:5]] for g in C.MAJORS}
    from portal import pathways
    soc_paths = pathways.mine_soc(con, top5)
    ok_paths = True
    for g, res in soc_paths.items():
        ok_paths = ok_paths and res["paths_grain"] == "soc_major_pooled"
        for p in res["paths"]:
            ok_paths = ok_paths and p["n_persons"] >= C.PATH_MIN_PERSONS
            stages = [s["group"] for s in p["stages"]]
            ok_paths = ok_paths and all(a != b for a, b in zip(stages, stages[1:]))
            ok_paths = ok_paths and (C.PATH_MIN_STAGES <= len(stages) <= C.PATH_MAX_STAGES)
    check("paths(soc): support >= bar, no consecutive-duplicate stages, grain declared",
          ok_paths)

    # --- CIP source pooling (edu_clean LLM jury) ------------------------------
    # (a) regression: on the committed parquet the cip2-based baseline
    # predicate is EXACTLY the historical cip_code-based rule -- the
    # equivalence _edu_table and build_membership rely on.
    mismatch = con.execute(f"""
      SELECT count(*) FROM read_parquet('{C.q(C.EDUCATION)}')
      WHERE degree_level = {C.BACHELOR_LEVEL}
        AND ((cip_code IS NOT NULL) != (cip2 IS NOT NULL))
    """).fetchone()[0]
    check("cip pooling: cip2 predicate == historical cip_code predicate "
          "(0 mismatched rows)", mismatch == 0)
    build.build_membership(con, cip_sources=("deterministic",))
    det_membership = sorted(con.execute(
        "SELECT group_key, linkedin_id, anchor, anchor_method FROM membership").fetchall())

    # (b) pooled membership is a superset per group; a det-admitted person's
    # anchor may move when the jury codes an additional qualifying bachelor's
    # row for the same person: EARLIER within the same tier (min(end_year)
    # picks the newly-visible earlier degree), or in either direction when
    # the method upgrades A2 -> A1 (a real end_year outranks an inference by
    # tier precedence). Measured 2026-07-11: 651/259,780 persons = 0.25%
    # moved (640 earlier same-tier, 11 A2->A1). Never later without a tier
    # upgrade; total movement bounded at 1% so a jury regression can't
    # silently re-anchor a material share of a cohort.
    if C.FIELD_CIP_JURY.exists():
        build.build_membership(con, cip_sources=("deterministic", "llm_jury"))
        pooled_membership = {(g, lid): (a, m) for g, lid, a, m in con.execute(
            "SELECT group_key, linkedin_id, anchor, anchor_method FROM membership").fetchall()}
        superset_ok, anchor_ok = True, True
        n_moved = 0
        for g, lid, a, m in det_membership:
            if (g, lid) not in pooled_membership:
                superset_ok = False
                break
            pa, pm = pooled_membership[(g, lid)]
            if pa != a:
                n_moved += 1
                if pa > a and (m, pm) != ("A2", "A1"):
                    anchor_ok = False
                    break
        check("cip pooling: pooled membership is a superset of det-only", superset_ok)
        check("cip pooling: anchors never move later without an A2->A1 upgrade; "
              f"total moves < 1% (moved={n_moved})",
              anchor_ok and n_moved < 0.01 * len(det_membership))
        funnel2 = build.group_funnel(con, cip_sources=("deterministic", "llm_jury"))
        mix_ok = all(
            abs(sum(f["cip_source_mix"].values()) - 1.0) < 1e-6
            and set(f["cip_source_mix"]) <= {"det", "jury"}
            for f in funnel2.values())
        check("cip pooling: cip_source_mix sums to 1.0 with only det/jury", mix_ok)
    else:
        print("  -- skipped: cip pooled checks (field_cip_jury.parquet not built yet)")
    build.build_membership(con)  # restore default membership

    # --- launchboard -----------------------------------------------------------
    build.build_panel(con)
    from portal import launchboard
    lb = launchboard.compute(con)
    lb_ok = True
    for g, d in lb.items():
        for h, blk in [("y1", d["first_destinations"])] + list(d["outlook"].items()):
            for cell in blk["fan"]:
                lb_ok = lb_ok and cell["n"] >= C.MIN_SUPPORT
            shares = sum(c["share"] for c in blk["fan"]) + (blk["unclassified_share"] or 0)
            # up to 24 cells rounded to 4dp can legitimately sum a hair over 1
            lb_ok = lb_ok and shares <= 1.0 + 2e-3
        for cls, s in d["stability"].items():
            for k, v in s.items():
                if k.startswith("n_"):
                    lb_ok = lb_ok and v >= C.MIN_SUPPORT
    check("launchboard: fan cells clear MIN_SUPPORT, shares bounded, "
          "stability cells suppressed below bar", lb_ok)
    # window discipline: y5 outcome cohort only contains anchors <= snapshot-5
    leak = con.execute(f"""
      SELECT count(*) FROM lb_moves WHERE anchor > {C.SNAPSHOT_YEAR - 5}
    """).fetchone()[0]
    check("launchboard: mover cohort respects the year-5 window", leak == 0)
    # mover classes partition each group's cohort
    part = con.execute("""
      SELECT count(*) FROM lb_moves
      WHERE moves IS NULL OR moves < 0""").fetchone()[0]
    check("launchboard: mover classes partition the cohort (no null/negative counts)",
          part == 0)

    # graduate-school step: headline cells clear MIN_SUPPORT; professional facet
    # clears its (lower, badged) bar with Medicine allowed down to its floor;
    # distinct-person accounting means no bucket exceeds the "any-grad" count.
    gt_ok = True
    for g in C.MAJORS:
        gt = lb[g].get("grad_track")
        if not gt or not gt.get("any"):
            continue
        gt_ok = gt_ok and gt["any"]["n"] >= C.MIN_SUPPORT
        for lv in gt["by_level"]:
            gt_ok = gt_ok and lv["n"] >= C.MIN_SUPPORT and lv["n"] <= gt["any"]["n"]
        for t in gt["by_type"]:
            floor = launchboard.GRAD_MEDICINE_FLOOR if t["type"].startswith("Medicine") \
                else C.DETAIL_MIN_SUPPORT
            gt_ok = gt_ok and t["n"] >= floor and t["n"] <= gt["any"]["n"]
            gt_ok = gt_ok and t["below_bar"] == (t["n"] < C.MIN_SUPPORT)
    check("launchboard: grad-track headline clears MIN_SUPPORT, facet clears its "
          "bar, no bucket exceeds any-grad count", gt_ok)

    # snapshot fan drill-down (y1 first destinations + y3/y5 outlook): the same
    # coverage identities as the y10 fan detail, on each horizon's own endpoint
    sd_ok, sd_cells, sd_named = True, 0, 0
    for g in C.MAJORS:
        snap_fans = ([lb[g]["first_destinations"]]
                     + [lb[g]["outlook"][k] for k in sorted(lb[g]["outlook"])])
        for blk in snap_fans:
            for cell in blk["fan"]:
                d = cell.get("detail")
                if d is None:
                    continue
                sd_cells += 1
                sd_ok = sd_ok and (d["detail_coded"] + d["no_detail_n"]
                                   == d["group_total"] == cell["n"])
                sd_ok = sd_ok and (d["roles_shown_n"] + d["other_coded_n"]
                                   == d["detail_coded"])
                sd_ok = sd_ok and all(
                    r["n"] >= C.DETAIL_MIN_SUPPORT for r in d["roles"])
                sd_ok = sd_ok and d["roles_shown_n"] == sum(r["n"] for r in d["roles"])
                sd_named += len(d["roles"])
    check("launchboard: snapshot fan detail identities hold on y1/y3/y5 "
          f"(cells with detail={sd_cells}, named roles={sd_named})",
          sd_ok and sd_cells > 0)

    # --- employer field ---------------------------------------------------------
    ef = analyses.employer_field(con)
    ef_ok = True
    for g, d in ef.items():
        if d is None:
            continue
        ef_ok = ef_ok and sum(b["employers"] for b in d["size_buckets"]) == d["n_employers"]
        ef_ok = ef_ok and all(c["n"] >= C.MIN_SUPPORT for c in d["labeled"])
        singles = next(b["employers"] for b in d["size_buckets"] if b["size_min"] == 1 and b["size_max"] == 1)
        ef_ok = ef_ok and abs(singles / d["n_employers"] - d["singleton_employer_share"]) < 1e-3
        ef_ok = ef_ok and 0 <= d["top10_share_of_cohort"] <= 1
    check("employer field: buckets partition employers, names only at "
          "n >= MIN_SUPPORT, shares consistent", ef_ok)

    # --- within-group occupation drill-down ------------------------------------
    fan3 = analyses.destination_fan(con)          # refresh fan_endpoint
    detail = analyses.destination_fan_detail(con)
    dd_ok, dd_named = True, 0
    for g in C.MAJORS:
        cells = {c["group"]: c for c in fan3[g]["fan"]}
        for soc, d in detail[g].items():
            # coverage identities: coded + jury-only = total; named + tail = coded
            dd_ok = dd_ok and d["detail_coded"] + d["no_detail_n"] == d["group_total"]
            dd_ok = dd_ok and d["roles_shown_n"] + d["other_coded_n"] == d["detail_coded"]
            # named roles clear the drill-down bar (coded-subset composition;
            # coincides with the headline bar since the 2026-07-13 loosening
            # -- see DETAIL_MIN_SUPPORT)
            dd_ok = dd_ok and all(r["n"] >= C.DETAIL_MIN_SUPPORT for r in d["roles"])
            dd_ok = dd_ok and d["roles_shown_n"] == sum(r["n"] for r in d["roles"])
            # the composition never claims more people than the cell holds
            dd_ok = dd_ok and d["detail_coded"] <= d["group_total"]
            # a drilled cell's total matches the fan cell it opens
            if soc in cells:
                dd_ok = dd_ok and d["group_total"] == cells[soc]["n"]
            dd_named += len(d["roles"])
    check("fan detail: coverage identities hold, named roles clear "
          "DETAIL_MIN_SUPPORT, group_total matches fan cell "
          f"(named roles surfaced={dd_named})", dd_ok)

    # --- diversity block ---------------------------------------------------------
    div = analyses.diversity(con, fan3)   # fan_endpoint fresh from fan3
    groups_classified = {g: int(n) for g, n in con.execute("""
      SELECT group_key, count(DISTINCT soc_major) FROM fan_endpoint
      WHERE soc_major IS NOT NULL GROUP BY 1""").fetchall()}
    div_ok = True
    for g in list(C.MAJORS) + [C.BASELINE_KEY]:
        d = div[g]
        gc = groups_classified.get(g, 0)
        # inverse Simpson is bounded by the number of classified categories
        div_ok = div_ok and (d["effective_destinations"] is None
                             or 1.0 <= d["effective_destinations"] <= gc + 1e-9)
        div_ok = div_ok and d["groups_reached"] == len(fan3[g]["fan"]) <= d["groups_of"]
        cells = fan3[g]["fan"]
        div_ok = div_ok and d["top_bucket_share"] == (cells[0]["share"] if cells else None)
        div_ok = div_ok and (d["top3_classified_share"] is None
                             or 0.0 <= d["top3_classified_share"] <= 1.0)
        div_ok = div_ok and d["classified_n"] <= fan3[g]["denom"]
    check("diversity: effective_destinations <= classified groups, "
          "groups_reached == published fan, top_bucket == fan[0].share, "
          "baseline present", div_ok and set(div) == set(list(C.MAJORS) + [C.BASELINE_KEY]))

    # --- choices ------------------------------------------------------------------
    from portal import choices
    ch = choices.compute(con)
    cut10 = C.SNAPSHOT_YEAR - C.FAN_YEAR

    # (a) window discipline + spine integrity: the choices cohort is exactly
    # the windowed membership; flag join produced one row per (group, person).
    leak = con.execute(
        f"SELECT count(*) FROM ch_cohort WHERE anchor > {cut10}").fetchone()[0]
    rows, dedup, cohort = con.execute("""
      SELECT (SELECT count(*) FROM ch_flags),
             (SELECT count(DISTINCT (group_key, linkedin_id)) FROM ch_flags),
             (SELECT count(*) FROM ch_cohort)""").fetchone()
    check("choices: windowed cohort respects the y10 window; flag join has no "
          "fan-out and partitions the cohort",
          leak == 0 and rows == dedup == cohort)
    pool_dup = con.execute(
        "SELECT count(*) - count(DISTINCT linkedin_id) FROM ch_pool_flags"
    ).fetchone()[0]
    se_dup = con.execute(
        "SELECT count(*) - count(DISTINCT linkedin_id) FROM ch_first_se"
    ).fetchone()[0]
    check("choices: pooled flags and first-SE-step are one row per person",
          pool_dup == 0 and se_dup == 0)

    # (b) participation shares in [0, 1]; grad split partitions the cohort
    def _shares_ok(block):
        ok = True
        for key in ("double_major", "grad_school", "internship", "military",
                    "service_year", "self_employment"):
            b = block.get(key)
            if b is None:
                continue
            s = b.get("participation_share", b.get("ever_share"))
            ok = ok and (s is None or 0.0 <= s <= 1.0)
        return ok

    part_ok, grad_ok = True, True
    for g, block in ch["per_group"].items():
        part_ok = part_ok and _shares_ok(block)
        gs = block["grad_school"]
        grad_ok = grad_ok and gs["n_grad"] + gs["n_nograd"] == block["cohort"]
    part_ok = part_ok and 0.0 <= ch["pooled"]["double_major"]["participation_share"] <= 1.0
    part_ok = part_ok and 0.0 <= ch["pooled"]["service_year"]["participation_share"] <= 1.0
    part_ok = part_ok and 0.0 <= ch["pooled"]["self_employment"]["ever_share"] <= 1.0
    check("choices: participation shares in [0,1] everywhere (incl. pooled)", part_ok)
    check("choices: grad/no-grad split partitions each windowed cohort", grad_ok)

    # (c) suppression: every named cell in ANY choices fan/list clears
    # MIN_SUPPORT; fans are null (never a thinner list) when nothing clears
    def _fan_ok(fan):
        if fan is None:
            return True
        return len(fan) > 0 and all(c["n"] >= C.MIN_SUPPORT for c in fan)

    sup_ok = True
    for g, block in ch["per_group"].items():
        for key in ("double_major", "internship", "military"):
            sup_ok = sup_ok and _fan_ok(block[key].get("fan"))
        sup_ok = sup_ok and _fan_ok(block["grad_school"].get("fan_grad"))
        sup_ok = sup_ok and _fan_ok(block["grad_school"].get("fan_nograd"))
        sv = block["service_year"]
        sup_ok = sup_ok and (sv is None or sv["n_windowed"] >= C.MIN_SUPPORT)
    pl = ch["pooled"]
    sup_ok = sup_ok and _fan_ok(pl["double_major"]["fan"])
    sup_ok = sup_ok and _fan_ok(pl["service_year"]["fan"])
    sup_ok = sup_ok and all(p["n"] >= C.MIN_SUPPORT for p in pl["service_year"]["programs"])
    sup_ok = sup_ok and all(p["n"] >= C.MIN_SUPPORT for p in pl["double_major"]["top_partners"])
    sup_ok = sup_ok and all(t["n"] >= C.MIN_SUPPORT for t in pl["self_employment"]["top_groups"])
    check("choices: every named cell (fans, programs, partners, SE groups) "
          "clears MIN_SUPPORT; unsupported fans ship null", sup_ok)

    # (d) baseline gets participation stats only -- no destination fans
    base_block = ch["per_group"][C.BASELINE_KEY]
    base_ok = ("fan" not in base_block["double_major"]
               and "fan_grad" not in base_block["grad_school"]
               and "fan" not in base_block["internship"]
               and "fan" not in base_block["military"])
    check("choices: baseline block is participation-only (no fans)", base_ok)

    con.close()
    print("\nAll portal tests passed.")


if __name__ == "__main__":
    main()
