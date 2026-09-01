"""Build reference/bls_unemployment.parquet — US annual unemployment rate by year.

    uv run python reference/build_bls_unemployment.py

The entry-conditions ("scarring") instrument for cohort analysis
(COHORT_ANALYSIS_PLAN §2.2): the unemployment rate in a person's labor-market
entry year is an exogenous cohort characteristic. Values are the BLS civilian
unemployment rate, annual average (series LNS14000000 / LNU04000000), from
bls.gov/cps. Hardcoded (≈50 small public numbers) for reproducibility — no
fragile download. 2025 is a partial-year estimate; flag it if used.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

# BLS civilian unemployment rate, annual average (%), bls.gov/cps.
RATES = {
    1976: 7.7, 1977: 7.1, 1978: 6.1, 1979: 5.8, 1980: 7.1, 1981: 7.6, 1982: 9.7,
    1983: 9.6, 1984: 7.5, 1985: 7.2, 1986: 7.0, 1987: 6.2, 1988: 5.5, 1989: 5.3,
    1990: 5.6, 1991: 6.8, 1992: 7.5, 1993: 6.9, 1994: 6.1, 1995: 5.6, 1996: 5.4,
    1997: 4.9, 1998: 4.5, 1999: 4.2, 2000: 4.0, 2001: 4.7, 2002: 5.8, 2003: 6.0,
    2004: 5.5, 2005: 5.1, 2006: 4.6, 2007: 4.6, 2008: 5.8, 2009: 9.3, 2010: 9.6,
    2011: 8.9, 2012: 8.1, 2013: 7.4, 2014: 6.2, 2015: 5.3, 2016: 4.9, 2017: 4.4,
    2018: 3.9, 2019: 3.7, 2020: 8.1, 2021: 5.3, 2022: 3.6, 2023: 3.6, 2024: 4.0,
    2025: 4.2,  # partial-year estimate
}


def main() -> None:
    out = Path(__file__).resolve().parent / "bls_unemployment.parquet"
    years = sorted(RATES)
    table = pa.table({
        "year": years,
        "unemployment_rate": [RATES[y] for y in years],
        "is_estimate": [y == 2025 for y in years],
    })
    pq.write_table(table, out, compression="zstd")
    print(f"wrote {out}: {len(years)} years ({years[0]}-{years[-1]}), "
          f"mean {sum(RATES.values())/len(RATES):.1f}%")


if __name__ == "__main__":
    main()
