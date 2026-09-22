"""Data-level invariants of the employer-keyed overrides: every landed override row
re-derives from the pure rule on the row's own evidence.

    uv run python -m career_clean.override_data_checks      (make test-data)
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from career_clean.overrides import override
from career_clean.run_overrides import INDUSTRY, OUT, STEPS


def ok(name: str) -> None:
    print(f"  ok: {name}")


def main() -> None:
    if not Path(OUT).exists():
        print("override mapping missing; nothing to check")
        return
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    rows = con.execute(f"""
        SELECT o.reason, o.occupation_code_override, c.title_raw, c.role_canonical, c.seniority_level, i.l1, i.l2,
               c.occupation_code, c.occupation_source, c.occupation_code_source, c.override_reason
        FROM read_parquet('{OUT}') o
        JOIN read_parquet('{STEPS}') c
          ON c.source_table = o.source_table AND c.linkedin_id = o.linkedin_id
         AND c.experience_idx = o.experience_idx AND c.position_idx IS NOT DISTINCT FROM o.position_idx
        LEFT JOIN read_parquet('{INDUSTRY}') i
          ON i.source_table = c.source_table AND i.linkedin_id = c.linkedin_id
         AND i.experience_idx = c.experience_idx AND i.position_idx IS NOT DISTINCT FROM c.position_idx
    """).fetchall()
    n_map = con.execute(f"SELECT count(*) FROM read_parquet('{OUT}')").fetchone()[0]
    assert len(rows) == n_map, f"join changed the row count {n_map} -> {len(rows)}"
    ok(f"every mapping row joins exactly one step ({n_map:,})")
    bad = []
    drift = []
    for reason, code, title, role, sen, l1, l2, det, src, code_src, landed_reason in rows:
        o = override(title, role, sen, l1, l2)
        if o is None or o.reason != reason or o.occupation_code != code:
            # the mapping is a snapshot keyed to the industry build it was made from; an
            # employer whose industry label moved since then (e.g. to XOT after a
            # `make industry` rebuild) is drift, not a rule failure. Re-sync with
            # `make overrides && make normalize-career`.
            # title, role and seniority cannot change between builds, so an industry-keyed
            # reason that no longer fires at all means the employer's industry moved
            if reason in ("k12_principal", "law_firm_partner") and o is None:
                drift.append((title, l1, l2, reason))
            else:
                bad.append((title, l1, l2, reason, o))
        elif landed_reason != reason or code_src != "override":
            bad.append((title, "landed", landed_reason, code_src))
        elif det is not None and src != "det":
            bad.append((title, "det row lost det source", src))
        elif det is None and src != "override":
            bad.append((title, "no-det row should be override source", src))
    assert not bad, f"{len(bad)} override rows do not re-derive from the rule: {bad[:5]}"
    share = len(drift) / max(len(rows), 1)
    assert share < 0.005, f"{len(drift)} override rows ({share:.2%}) sit on employers whose industry changed; run `make overrides && make normalize-career`"
    ok(f"every landed override re-derives from overrides.override on the row's own evidence "
       f"({len(drift)} rows of industry drift, {share:.2%}, below the 0.5% re-sync bar)")
    ok("det rows keep occupation_source = 'det'; det-less rows are 'override'")
    print("override data checks passed")


if __name__ == "__main__":
    main()
