import requests
import json
import os
import time

# Configure your user agent as required by the SEC
HEADERS = {
    "User-Agent": "eng.sultan.fadi@gmail.com"  #
}

# Top 20 US tickers (modify as needed)
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "TSLA", "NVDA", "JPM", "V", "UNH",
    "HD", "PG", "MA", "DIS", "BAC",
    "ADBE", "INTC", "PFE", "KO", "CSCO"
]

# Top 20 financial metrics (XBRL tags from SEC)
METRICS = [
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
    "AccountsReceivableNetCurrent"
]


# Output directory
os.makedirs("financial_data", exist_ok=True)

# Get CIK for a given ticker from SEC
def get_cik(ticker):
    url = "https://www.sec.gov/files/company_tickers.json"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    companies = r.json()
    for company in companies.values():
        if company["ticker"].upper() == ticker.upper():
            return str(company["cik_str"]).zfill(10)
    return None

# Fetch metric data for a given CIK and tag
def fetch_metric_data(cik, tag):
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        return []
    try:
        return r.json()["units"]["USD"]
    except KeyError:
        return []

def filter_last_10_years(data):
    filtered = []
    for entry in data:
        fy = entry.get("fy")
        if fy is not None and entry.get("form") in ["10-Q", "10-K"]:
            try:
                if int(fy) >= 2014:
                    filtered.append({
                        "fiscal_year": fy,
                        "period": entry.get("end"),
                        "value": entry.get("val"),
                        "form": entry.get("form")
                    })
            except ValueError:
                continue  # skip if fy is not convertible to int
    return filtered


# Process one company
def process_company(ticker):
    cik = get_cik(ticker)
    if not cik:
        print(f"CIK not found for {ticker}")
        return

    print(f"Processing {ticker} (CIK: {cik})")
    company_data = {
        "ticker": ticker,
        "cik": cik,
        "financials": {}
    }

    for tag in METRICS:
        data = fetch_metric_data(cik, tag)
        filtered = filter_last_10_years(data)
        for item in filtered:
            key = item["period"]
            if key not in company_data["financials"]:
                company_data["financials"][key] = {}
            company_data["financials"][key][tag] = item["value"]
        time.sleep(0.5)  # To respect SEC API rate limits

    # Save to JSON
    with open(f"financial_data/{ticker}.json", "w") as f:
        json.dump(company_data, f, indent=2)

# Run the full process
for ticker in TICKERS:
    try:
        process_company(ticker)
    except Exception as e:
        print(f"Error processing {ticker}: {e}")
        continue

print("✅ Data collection complete.")
