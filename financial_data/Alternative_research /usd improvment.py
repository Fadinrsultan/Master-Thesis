import requests
import json
import os
import time
from collections import defaultdict

# ─────────────────── CONFIG ───────────────────
HEADERS = {"User-Agent": "eng.sultan.fadi@gmail.com"}
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
DATA_DIR = "financial_data_2"
os.makedirs(DATA_DIR, exist_ok=True)

TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "TSLA", "NVDA", "JPM", "V", "UNH",
    "HD", "PG", "MA", "DIS", "BAC",
    "ADBE", "INTC", "PFE", "KO", "CSCO",
]

# Main metric → list of acceptable XBRL tags
METRIC_ALIASES = {
    "Revenues": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ],
    "NetIncomeLoss": ["NetIncomeLoss", "ProfitLoss"],
    "EarningsPerShareBasic": [
        "EarningsPerShareBasic",
        "EarningsPerShareBasicAndDiluted",
    ],
    "EarningsPerShareDiluted": ["EarningsPerShareDiluted"],
    "OperatingIncomeLoss": [
        "OperatingIncomeLoss",
        "IncomeLossFromOperations",
        "OperatingProfit",
    ],
    "GrossProfit": ["GrossProfit"],
    "ResearchAndDevelopmentExpense": ["ResearchAndDevelopmentExpense"],
    "SellingGeneralAndAdministrativeExpense": [
        "SellingGeneralAndAdministrativeExpense",
        "SGAndAExpense",
    ],
    "Assets": ["Assets"],
    "Liabilities": ["Liabilities"],
    "StockholdersEquity": ["StockholdersEquity"],
    "CashAndCashEquivalentsAtCarryingValue": [
        "CashAndCashEquivalentsAtCarryingValue"
    ],
    "NetCashProvidedByUsedInOperatingActivities": [
        "NetCashProvidedByUsedInOperatingActivities",
    ],
    "PaymentsToAcquirePropertyPlantAndEquipment": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "CapitalExpenditures",
        # Apple sometimes uses this investing‑cash‑flow tag
        "InvestingCashFlowPaymentsForPropertyPlantAndEquipment",
    ],
    "LongTermDebt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "ShortTermInvestments": [
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        # Apple groups cash & marketable securities in recent filings
        "CashCashEquivalentsAndMarketableSecurities",
    ],
    "CostOfRevenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfSales",
    ],
    "OperatingExpenses": ["OperatingExpenses"],
    "IncomeTaxExpenseBenefit": [
        "IncomeTaxExpenseBenefit",
        "ProvisionForIncomeTaxes",
    ],
    "AccountsReceivableNetCurrent": ["AccountsReceivableNetCurrent"],
    "FreeCashFlow": [],  # derived later
}

# ──────────────── HELPERS ────────────────

def load_cik_map(cache="company_tickers.json"):
    if not os.path.exists(cache):
        print("Downloading ticker→CIK map …")
        res = requests.get(SEC_TICKER_URL, headers=HEADERS, timeout=30)
        res.raise_for_status()
        with open(cache, "w") as fp:
            fp.write(res.text)
    with open(cache, "r") as fp:
        data = json.load(fp)
    return {
        d["ticker"].upper(): str(d["cik_str"]).zfill(10) for d in data.values()
    }


def fetch_concept(cik: str, tag: str):
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        return []
    units = r.json().get("units", {})
    # Combine USD *and* USD/shares so metrics are not lost
    return units.get("USD", []) + units.get("USD/shares", [])


def entries_since_2014(entries):
    for e in entries:
        fy = e.get("fy")
        if fy and int(fy) >= 2014 and e.get("form") in ("10-K", "10-Q"):
            yield e

# ───────────── MAIN PROCESS ─────────────

ticker2cik = load_cik_map()
missing = defaultdict(list)

for tkr in TICKERS:
    cik = ticker2cik.get(tkr)
    if not cik:
        print(f"CIK not found for {tkr}")
        continue

    print(f"\n▶ {tkr} (CIK {cik})")
    data = {"ticker": tkr, "cik": cik, "financials": {}}

    for main, alts in METRIC_ALIASES.items():
        found = False
        for alt in alts:
            rows = fetch_concept(cik, alt)
            if rows:
                found = True
                for r in entries_since_2014(rows):
                    period = r["end"]
                    data["financials"].setdefault(period, {})[main] = r["val"]
                break
            time.sleep(0.25)
        if not found and main != "FreeCashFlow":
            missing[tkr].append(main)

    # derive FreeCashFlow
    for p, vals in data["financials"].items():
        op = vals.get("NetCashProvidedByUsedInOperatingActivities")
        capex = vals.get("PaymentsToAcquirePropertyPlantAndEquipment")
        if op is not None and capex is not None:
            vals["FreeCashFlow"] = op - capex
        else:
            missing[tkr].append("FreeCashFlow")

    with open(os.path.join(DATA_DIR, f"{tkr}.json"), "w") as fp:
        json.dump(data, fp, indent=2)

# ───────────── REPORT ─────────────
print("\n===== Missing‑Tag Report =====")
for tkr in TICKERS:
    miss = sorted(set(missing.get(tkr, [])))
    if miss:
        print(f"{tkr}: {', '.join(miss)}")
    else:
        print(f"{tkr}: All metrics present")

print("\n✅ Completed. JSON files saved in ./financial_data")
