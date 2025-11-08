
import requests
import pandas as pd
import os
import time
from typing import Dict

# --------------------------- config ----------------------------------------
HEADERS: Dict[str, str] = {"User-Agent": "you@example.com"}  # <-- put your email / firm here
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "TSLA", "NVDA", "JPM", "V", "UNH",
    "HD", "PG", "MA", "DIS", "BAC",
    "ADBE", "INTC", "PFE", "KO", "CSCO",
]
OUTDIR = "tags"  # save all CSV files here
os.makedirs(OUTDIR, exist_ok=True)

# ------------------- download ticker → CIK table ---------------------------
print("Downloading SEC ticker → CIK lookup table …")
ticker_table = requests.get(
    "https://www.sec.gov/files/company_tickers.json",
    headers=HEADERS,
    timeout=30,
).json()

# build {ticker: CIK} dict
cik_lookup = {
    entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
    for entry in ticker_table.values()
}

# --------------------- loop through tickers -------------------------------
for tkr in TICKERS:
    cik = cik_lookup.get(tkr)
    if not cik:
        print(f"[ERROR] No CIK for {tkr} – skipped")
        continue

    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    try:
        data = requests.get(url, headers=HEADERS, timeout=60).json()
    except Exception as exc:
        print(f"[ERROR] {tkr}: {exc} – skipped")
        continue

    # collect every distinct US‑GAAP tag
    try:
        tags = sorted(data["facts"]["us-gaap"].keys())
    except KeyError:
        print(f"[WARN] {tkr}: no us‑gaap facts found – skipped")
        continue

    # write CSV
    df = pd.DataFrame({"us-gaap tag": tags})
    csv_path = f"{OUTDIR}/{tkr}_gaap_tags.csv"
    df.to_csv(csv_path, index=False)
    print(f"{tkr}: {len(tags):4d} tags → {csv_path}")

    time.sleep(0.4)  # be polite to the SEC’s servers

print("✅  All tickers processed.")
