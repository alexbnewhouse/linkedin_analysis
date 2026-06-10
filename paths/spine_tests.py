"""Regression tests for the spine SQL (run: `uv run python -m paths.spine_tests`).

Plain-assert style, mirroring `career_clean/se_tests.py`. Builds a tiny synthetic
`career_steps` table, runs the three real SQL stages from `build_spine`, and
asserts on the resulting rows. Each case pins a decision that is easy to break
silently — especially the order-sensitive `kind` ladder and the red-team fixes
(H1 gap boundary, H3 empty-string seniority, M1 future-start, M2 kind order).
"""

from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq

import duckdb

from paths import common as C
from paths.build_spine import STEPS_SQL, CONCURRENCY_SQL, TRANSITIONS_SQL, _ranks_values

_COLS = [
    "linkedin_id", "source_table", "experience_idx", "position_idx",
    "company_canonical_id", "company_id_canonical", "company_raw",
    "employment_type", "title_raw", "role_canonical", "seniority_level",
    "seniority_rank_token", "occupation_code", "location", "start_date", "end_date",
]


def _step(lid, ec_id, emp, sen, start, end, role="r", occ=None, cid=None):
    """One synthetic step. ec_id is company_canonical_id; cid the bare slug."""
    return {
        "linkedin_id": lid, "source_table": "experience", "experience_idx": 0,
        "position_idx": None, "company_canonical_id": ec_id,
        "company_id_canonical": cid, "company_raw": ec_id, "employment_type": emp,
        "title_raw": role, "role_canonical": role, "seniority_level": sen,
        "seniority_rank_token": sen, "occupation_code": occ, "location": None,
        "start_date": start, "end_date": end,
    }


# id:acme/id:beta = real employers; nonorg:* = placeholders (self-emp / terminal)
ROWS = [
    # P1 same-employer seniority increase, seamless handoff -> promotion/up, no gap
    _step("p1", "id:acme", "employee", "associate", "Jan 2018", "Dec 2018", cid="acme"),
    _step("p1", "id:acme", "employee", "senior",    "Jan 2019", "Dec 2019", cid="acme"),
    # P2 employee -> self_employed -> into_self_employment
    _step("p2", "id:acme", "employee",      "", "Jan 2018", "Dec 2018", cid="acme"),
    _step("p2", "nonorg:self_employed", "self_employed", "", "Jan 2019", "Dec 2019"),
    # P3 self_employed -> retired: exit must win over out_of_self_employment (M2)
    _step("p3", "nonorg:self_employed", "self_employed", "", "Jan 2018", "Dec 2018"),
    _step("p3", "nonorg:retired", "retired", "", "Jan 2019", "Dec 2019"),
    # P4 same-employer senior -> unmarked: direction unknown, kind lateral (H3)
    _step("p4", "id:beta", "employee", "senior", "Jan 2018", "Dec 2018", cid="beta"),
    _step("p4", "id:beta", "employee", "",       "Jan 2019", "Dec 2019", cid="beta"),
    # P5 real 2-month gap (Feb+Mar empty); first role is a single month (L1)
    _step("p5", "id:c", "employee", "", "Jan 2018", "Jan 2018", cid="c"),
    _step("p5", "id:d", "employee", "", "Apr 2018", "Dec 2018", cid="d"),
    # P6 long role fully contains a shorter concurrent one -> shorter is secondary
    _step("p6", "id:e", "employee", "", "Jan 2018", "Dec 2020", cid="e"),
    _step("p6", "id:f", "employee", "", "Jan 2019", "Jun 2019", cid="f"),
]


def _run(con, tmp):
    steps_in, steps_out, trans_out = f"{tmp}/in.parquet", f"{tmp}/steps.parquet", f"{tmp}/tr.parquet"
    pq.write_table(pa.Table.from_pylist(ROWS, schema=pa.schema(
        [(c, pa.string() if c not in ("experience_idx", "position_idx")
          else pa.int64()) for c in _COLS])), steps_in)
    # empty revealed-seniority table (bootstrap path: scores come only from the
    # lexical layer here, so the kind/seniority assertions stay deterministic)
    con.sql("CREATE TEMP TABLE sen_scores(role_canonical VARCHAR, "
            "revealed_pct DOUBLE, revealed_confidence DOUBLE, "
            "revealed_z DOUBLE, support DOUBLE)")
    con.sql("CREATE TEMP TABLE soc_status(soc_code VARCHAR, job_zone INT, "
            "svp_low DOUBLE, svp_high DOUBLE, job_zone_norm DOUBLE)")
    con.sql(STEPS_SQL.format(steps_in=steps_in, steps_out=steps_out, ranks=_ranks_values()))
    con.sql(f"CREATE TEMP TABLE concurrency AS {CONCURRENCY_SQL.format(steps_out=steps_out)}")
    con.sql(TRANSITIONS_SQL.format(steps_out=steps_out, trans_out=trans_out))
    return steps_out, trans_out


def main() -> None:
    import tempfile
    con = duckdb.connect()
    with tempfile.TemporaryDirectory() as tmp:
        steps_out, trans_out = _run(con, tmp)
        edges = {r[0]: r for r in con.sql(f"""
            SELECT linkedin_id, kind, seniority_direction, gap_months, has_gap,
                   overlap_months, has_overlap
            FROM read_parquet('{trans_out}')""").fetchall()}
        steps = {(r[0], r[1]): r for r in con.sql(f"""
            SELECT linkedin_id, start_date_raw, tenure_months, seniority_ordinal
            FROM read_parquet('{steps_out}')""").fetchall()}
        dominated = {r[0] for r in con.sql(f"""
            SELECT s.linkedin_id FROM read_parquet('{steps_out}') s
            JOIN concurrency c USING (row_id) WHERE c.dominated""").fetchall()}

    def check(name, cond):
        assert cond, f"FAIL: {name}"
        print(f"  ok: {name}")

    check("P1 same-employer seniority up = promotion", edges["p1"][1] == "promotion")
    check("P1 promotion direction = up", edges["p1"][2] == "up")
    check("P1 seamless Dec->Jan handoff is NOT a gap (H1)",
          edges["p1"][3] == 0 and edges["p1"][4] is False)
    check("P2 employee->self_employed = into_self_employment", edges["p2"][1] == "into_self_employment")
    check("P3 self_employed->retired = exit, not out_of_self_employment (M2)", edges["p3"][1] == "exit")
    check("P4 unmarked seniority side = unknown direction (H3)", edges["p4"][2] == "unknown")
    check("P4 same-employer unknown direction = lateral (H3)", edges["p4"][1] == "lateral")
    check("P5 two empty months = gap_months 2, has_gap (H1)",
          edges["p5"][3] == 2 and edges["p5"][4] is True)
    check("P5 single-month role tenure = 1, not 0 (L1)", steps[("p5", "Jan 2018")][2] == 1)
    check("P6 contained shorter role flagged concurrent-secondary", "p6" in dominated)
    check("P6 single primary step => no edge emitted", "p6" not in edges)
    check("unmarked '' seniority -> NULL ordinal (H3)", steps[("p2", "Jan 2018")][3] is None)
    print("\nAll spine regression checks passed.")


if __name__ == "__main__":
    main()
