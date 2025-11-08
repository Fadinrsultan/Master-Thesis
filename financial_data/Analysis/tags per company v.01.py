"""
Script: gaap_yearly_tag_counts_last10.py

What it does
------------
1) Pull SEC XBRL "companyfacts" for each ticker.
2) For each fact in `facts["us-gaap"]`, determine the YEAR of that fact
   (prefer FY; else parse 'end' date).
3) For each YEAR in a rolling last-10-years window, count DISTINCT tags that
   have at least one fact in that year.
4) Print lines like: "apple 2015:400 tags 2016:401 tags ..."
5) Save:
   - tags/<TICKER>_yearly_tag_counts.csv  (columns: year, tag_count)
   - tags/yearly_tag_counts_long.csv      (ticker, year, tag_count)
   - tags/yearly_tag_counts_matrix.csv    (matrix: rows=ticker, cols=year)

Notes
-----
- Respect SEC fair-use: include a contact email in HEADERS and throttle requests.
- Years window is [CURRENT_YEAR - YEARS_BACK, CURRENT_YEAR - 1] inclusive.
"""

from __future__ import annotations

import datetime
import os
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

# --------------------------- configuration ---------------------------------
HEADERS: Dict[str, str] = {
    "User-Agent": "you@example.com"  # <-- put your email here (SEC fair-use)
}
TICKERS: List[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "JPM", "V", "UNH",
    "HD", "PG", "MA", "DIS", "BAC", "ADBE", "INTC", "PFE", "KO", "CSCO",
]
OUTDIR = "tags"
os.makedirs(OUTDIR, exist_ok=True)

YEARS_BACK = 10
CURRENT_YEAR = datetime.date.today().year
START_YEAR = CURRENT_YEAR - YEARS_BACK          # inclusive
END_YEAR = CURRENT_YEAR - 1                     # inclusive
YEAR_RANGE = list(range(START_YEAR, END_YEAR + 1))

# --------------------------- helpers ---------------------------------------
def _parse_end_date(end_str: str) -> Optional[datetime.date]:
    """Parse 'YYYY-MM-DD' to date; return None if invalid."""
    try:
        y, m, d = end_str.split("-")
        return datetime.date(int(y), int(m), int(d))
    except Exception:
        return None

def _fact_year(fact: dict) -> Optional[int]:
    """
    Extract the most reliable year for a fact:
    1) Use integer 'fy' if present.
    2) Else parse 'end' date to get calendar year.
    """
    fy = fact.get("fy")
    if isinstance(fy, int) and 1800 <= fy <= 3000:
        return fy
    end_str = fact.get("end")
    if end_str:
        dt = _parse_end_date(end_str)
        if dt:
            return dt.year
    return None

def yearly_distinct_gaap_tags(company_json: dict, years: List[int]) -> Dict[int, int]:
    """
    For each year in `years`, count distinct US-GAAP tags that have >=1 fact recorded in that year.
    Returns: {year: tag_count}
    """
    target_years = set(years)
    result: Dict[int, set] = {y: set() for y in years}

    gaap = company_json.get("facts", {}).get("us-gaap", {})
    for tag, tag_data in gaap.items():
        for unit, fact_list in tag_data.get("units", {}).items():
            for fact in fact_list:
                yr = _fact_year(fact)
                if yr in target_years:
                    result[yr].add(tag)

    return {y: len(result[y]) for y in years}

# ------------------- download ticker → CIK table ---------------------------
print("Downloading SEC ticker → CIK lookup table …")
lookup_resp = requests.get(
    "https://www.sec.gov/files/company_tickers.json",
    headers=HEADERS,
    timeout=30,
)
lookup_resp.raise_for_status()
ticker_table = lookup_resp.json()
cik_lookup: Dict[str, str] = {
    entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
    for entry in ticker_table.values()
}

# ------------------------------ main ---------------------------------------
all_rows_long = []   # for tidy long CSV (ticker, year, tag_count)
matrix_rows = []     # for matrix (one row per ticker)

for tkr in TICKERS:
    cik = cik_lookup.get(tkr)
    if not cik:
        print(f"[ERROR] No CIK for {tkr} – skipped")
        continue

    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    try:
        company_json = requests.get(url, headers=HEADERS, timeout=60).json()
    except Exception as exc:
        print(f"[ERROR] {tkr}: {exc} – skipped")
        continue

    yearly_counts = yearly_distinct_gaap_tags(company_json, YEAR_RANGE)

    # Save per-company CSV
    comp_df = (
        pd.DataFrame({"year": YEAR_RANGE, "tag_count": [yearly_counts.get(y, 0) for y in YEAR_RANGE]})
    )
    comp_csv = os.path.join(OUTDIR, f"{tkr}_yearly_tag_counts.csv")
    comp_df.to_csv(comp_csv, index=False)

    # Print in the requested style: "apple 2015:400 tags 2016:401 tags ..."
    human = tkr.lower()
    parts = [f"{y}:{yearly_counts.get(y,0)} tags" for y in YEAR_RANGE]
    print(f"{human} " + " ".join(parts))

    # Accumulate for combined outputs
    for y in YEAR_RANGE:
        all_rows_long.append({"ticker": tkr, "year": y, "tag_count": yearly_counts.get(y, 0)})

    matrix_row = {"ticker": tkr}
    matrix_row.update({y: yearly_counts.get(y, 0) for y in YEAR_RANGE})
    matrix_rows.append(matrix_row)

    time.sleep(0.4)  # SEC fair-use courtesy

# ------------------------ write combined CSVs ------------------------------
if all_rows_long:
    long_df = pd.DataFrame(all_rows_long).sort_values(["ticker", "year"])
    long_csv = os.path.join(OUTDIR, "yearly_tag_counts_long.csv")
    long_df.to_csv(long_csv, index=False)

    matrix_df = pd.DataFrame(matrix_rows).set_index("ticker").sort_index()
    matrix_csv = os.path.join(OUTDIR, "yearly_tag_counts_matrix.csv")
    matrix_df.to_csv(matrix_csv)

    print(f"\n✅ Saved per-company CSVs in {OUTDIR}/")
    print(f"✅ Tidy long table → {long_csv}")
    print(f"✅ Matrix table     → {matrix_csv}")
else:
    print("\n[INFO] No yearly tag data compiled. Check tickers/headers/network.\n")
