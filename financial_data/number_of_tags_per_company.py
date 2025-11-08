"""
Script: gaap_metric_presence.py
Description:
  1. Fetch every US‑GAAP tag each of 20 large‑cap U.S. companies has ever filed (SEC “companyfacts” API).
  2. Save one CSV per company containing the tag list (in the `tags/` directory).
  3. Build a presence‑matrix for 20 key financial metrics (METRICS list below) indicating whether each company has ever reported that tag.  The matrix is written to `tags/metric_presence.csv` for easy inspection.
"""

from __future__ import annotations
import requests
import pandas as pd
import os
import time
from typing import Dict, List

# --------------------------- configuration ---------------------------------
HEADERS: Dict[str, str] = {"User-Agent": "you@example.com"}  # <-- required
TICKERS: List[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "TSLA", "NVDA", "JPM", "V", "UNH",
    "HD", "PG", "MA", "DIS", "BAC",
    "ADBE", "INTC", "PFE", "KO", "CSCO",
]
OUTDIR = "tags"          # all CSV outputs land here
os.makedirs(OUTDIR, exist_ok=True)

# ---------------------------------------------------------------------------
METRICS: List[str] = [
    "Revenues",
    "NetIncomeLoss",
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
    "OperatingIncomeLoss",
    "GrossProfit",
    "ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue",
    "NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "LongTermDebt",
    "ShortTermInvestments",
    "CostOfRevenue",
    "OperatingExpenses",
    "IncomeTaxExpenseBenefit",
    "AccountsReceivableNetCurrent",
]

# ------------------- download ticker → CIK table ---------------------------
print("Downloading SEC ticker → CIK lookup table …")
lookup_resp = requests.get(
    "https://www.sec.gov/files/company_tickers.json", headers=HEADERS, timeout=30
)
lookup_resp.raise_for_status()
ticker_table = lookup_resp.json()

cik_lookup: Dict[str, str] = {
    entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
    for entry in ticker_table.values()
}

# ---------------------------------------------------------------------------
metric_presence_records = []  # collect rows for the summary matrix

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

    # full US‑GAAP tag set this company has used
    try:
        gaap_tags = set(company_json["facts"]["us-gaap"].keys())
    except KeyError:
        print(f"[WARN] {tkr}: no us-gaap facts found – skipped")
        continue

    # Write company tag list CSV
    tag_df = pd.DataFrame({"us-gaap tag": sorted(gaap_tags)})
    tag_csv = f"{OUTDIR}/{tkr}_gaap_tags.csv"
    tag_df.to_csv(tag_csv, index=False)
    print(f"{tkr}: {len(tag_df):4d} tags → {tag_csv}")

    # Build record for metric presence
    presence_row = {"ticker": tkr}
    presence_row.update({m: (m in gaap_tags) for m in METRICS})
    metric_presence_records.append(presence_row)

    time.sleep(0.4)  # respect SEC’s fair-use guidance

# ---------------------------------------------------------------------------
# Assemble and save metric‑presence matrix
presence_df = (
    pd.DataFrame(metric_presence_records)
    .set_index("ticker")
    .sort_index()
)
presence_csv = f"{OUTDIR}/metric_presence.csv"
presence_df.to_csv(presence_csv)
print(f"\n✅  Metric‑presence matrix written to {presence_csv}")

# Optional: show a preview
print("\nPreview (True = tag present):\n")
print(presence_df)
