import requests, pandas as pd

# --- SEC API call -----------------------------------------------------------
CIK = "0000320193"                                       # Apple Inc.
URL = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"
HEADERS = {"User-Agent": "you@example.com"}              # <-- required by SEC
data = requests.get(URL, headers=HEADERS, timeout=60).json()

# --- collect every distinct US-GAAP tag Apple has used ----------------------
tags = sorted(data["facts"]["us-gaap"].keys())
df = pd.DataFrame({"us-gaap tag": tags})

# --- save and preview -------------------------------------------------------
csv_path = "../apple_gaap_tags.csv"
df.to_csv(csv_path, index=False)
print(f"✅  {len(df):,} unique tags written to {csv_path}")
df.head(25)                                              # show a sample
