import requests

# SEC wants a descriptive User-Agent with email
HEADERS = {
    "User-Agent": "SimpleRevenueFetcher/1.0 (your_email@example.com)"
}

# CIK for NVIDIA (NVDA) as 10-digit string
NVDA_CIK = "0001045810"

def get_latest_nvda_revenue():
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{NVDA_CIK}/us-gaap/Revenues.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()

    # Collect only USD rows
    usd_rows = []
    for uom, rows in (data.get("units") or {}).items():
        if uom != "USD":
            continue
        usd_rows.extend(rows or [])

    # Filter to 10-K, full-year (FY) rows
    filtered = [
        row for row in usd_rows
        if row.get("form") == "10-K" and row.get("fp") == "FY"
    ]

    if not filtered:
        print("No 10-K FY revenue rows found for NVDA.")
        return

    # Take the most recently filed one
    latest = max(filtered, key=lambda r: r.get("filed", ""))

    fy    = latest.get("fy")
    end   = latest.get("end")
    filed = latest.get("filed")
    val   = latest.get("val")   # this is straight from SEC, no modification
    accn  = latest.get("accn")

    print(f"NVIDIA revenue (us-gaap:Revenues)")
    print(f"  Fiscal year:      {fy}")
    print(f"  Period end date:  {end}")
    print(f"  Filed date:       {filed}")
    print(f"  Accession:        {accn}")
    print(f"  Revenue (USD):    {val}")


if __name__ == "__main__":
    get_latest_nvda_revenue()
