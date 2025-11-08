import requests
import json
import os
import time
from collections import defaultdict

# ─── CONFIG ───────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": "eng.sultan.fadi@gmail.com"  # REQUIRED by SEC
}
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
DATA_DIR = ""
os.makedirs(DATA_DIR, exist_ok=True)

TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "TSLA", "NVDA", "JPM", "V", "UNH",
    "HD", "PG", "MA", "DIS", "BAC",
    "ADBE", "INTC", "PFE", "KO", "CSCO"
]

METRIC_ALIASES = {
"Revenues": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
        "TotalRevenuesAndOtherIncome",
        "RegulatedAndUnregulatedOperatingRevenue",
    ],
    "NetIncomeLoss": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "NetIncomeLossAttributableToParent",
    ],
    "EarningsPerShareBasic": [
        "EarningsPerShareBasic",
        "EarningsPerShareBasic",
        "EarningsPerShareBasicAndDiluted",
        "EarningsPerShareBasicRestated",
        "EarningsPerShareBasicAndDilutedBeforeExtraordinaryItems",
    ],
    "EarningsPerShareDiluted": [
        "EarningsPerShareDiluted",
        "EarningsPerShareDilutedRestated",
    ],
    "OperatingIncomeLoss": [
        "OperatingIncomeLoss",
        "IncomeLossFromOperations",
        "OperatingIncome",
        "OperatingIncomeLossOfReportableSegments",
    ],
    "GrossProfit": [
        "GrossProfit",
        "GrossIncome",
    ],
    "ResearchAndDevelopmentExpense": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessResearchAndDevelopment",
    ],
    "SellingGeneralAndAdministrativeExpense": [
        "SellingGeneralAndAdministrativeExpense",
        "SellingGeneralAndAdministrativeExpenses",
        "SGAndAExpense",
        "SellingAndMarketingExpense",
    ],
    "Assets": [
        "Assets",
        "TotalAssets",
    ],
    "Liabilities": [
        "Liabilities",
        "TotalLiabilities",
        "LiabilitiesAndStockholdersEquity",
        "LiabilitiesCurrent",
        "LiabilitiesNoncurrent"
    ],
    "StockholdersEquity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "PartnersCapital",
    ],
    "CashAndCashEquivalentsAtCarryingValue": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashCashEquivalentsAndShortTermInvestments",
    ],
    "NetCashProvidedByUsedInOperatingActivities": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "NetCashProvidedByUsedInOperatingActivitiesExcludingDiscontinuedOperations",
    ],
    "PaymentsToAcquirePropertyPlantAndEquipment": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "CapitalExpenditures",
        "PaymentsForPropertyPlantAndEquipment",
        "AdditionsToPropertyPlantAndEquipment",
    ],
    "LongTermDebt": [
        "LongTermDebt",
        "LongTermDebtCurrentAndNoncurrent",
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
    ],
    "ShortTermInvestments": [
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesCurrent",
    ],
    "CostOfRevenue": [
        "CostOfRevenue",
        "CostOfSales",
        "CostOfGoodsSold",
        "CostOfGoodsAndServicesSold",
    ],
    "OperatingExpenses": [
        "OperatingExpenses",
        "TotalOperatingExpenses",
        "OperatingExpense",
    ],
    "IncomeTaxExpenseBenefit": [
        "IncomeTaxExpenseBenefit",
        "IncomeTaxExpenseContinuingOperations",
        "ProvisionForIncomeTaxes",
        "IncomeTaxExpenseBenefitContinuingOperations",
    ],
    "AccountsReceivableNetCurrent": [
        "AccountsReceivableNetCurrent",
        "AccountsReceivableTradeNetCurrent",
    ],
    "FreeCashFlow": []  # derived manually
}

# ─── HELPERS ───────────────────────────────────────────────────────────────

def load_cik_mapping(path: str = "company_tickers.json") -> dict:
    """Load or download ticker→CIK mapping."""
    if not os.path.exists(path):
        print("Downloading company_tickers.json …")
        resp = requests.get(SEC_TICKER_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        with open(path, "w") as fp:
            fp.write(resp.text)
    with open(path, "r") as fp:
        data = json.load(fp)
    return {d["ticker"].upper(): str(d["cik_str"]).zfill(10) for d in data.values()}


def fetch_metric(cik: str, tag: str):
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        return []
    try:
        data = r.json().get("units", {})
        all_values = []
        for unit in data.values():
            all_values.extend(unit)
        return all_values
        #return r.json()["units"]["USD"]
    except KeyError:
        return []


def recent_entries(entries):
    for e in entries:
        fy = e.get("fy")
        if fy and int(fy) >= 2014 and e.get("form") in ("10-K", "10-Q"):
            yield e

# ─── MAIN ──────────────────────────────────────────────────────────────────

ticker_to_cik = load_cik_mapping()
missing_summary = defaultdict(list)

for ticker in TICKERS:
    cik = ticker_to_cik.get(ticker)
    if not cik:
        print(f"CIK not found for {ticker}")
        continue

    print(f"\n▶ Processing {ticker} (CIK {cik}) …")
    financials = {}

    for main, aliases in METRIC_ALIASES.items():
        tag_found = False
        for alias in aliases:
            data = fetch_metric(cik, alias)
            if data:
                tag_found = True
                for entry in recent_entries(data):
                    period = entry["end"]
                    financials.setdefault(period, {})[main] = entry["val"]
                break
            time.sleep(0.25)
        if not tag_found and main != "FreeCashFlow":
            missing_summary[ticker].append(main)

    # derive FreeCashFlow if possible
    for period, vals in financials.items():
        op = vals.get("NetCashProvidedByUsedInOperatingActivities")
        capex = vals.get("PaymentsToAcquirePropertyPlantAndEquipment")
        if op is not None and capex is not None:
            vals["FreeCashFlow"] = op - capex
        else:
            # If derivation not possible, mark as missing
            missing_summary[ticker].append("FreeCashFlow")

    # save JSON
    with open(os.path.join(DATA_DIR, f"{ticker}.json"), "w") as fp:
        json.dump({"ticker": ticker, "cik": cik, "financials": financials}, fp, indent=2)

# ─── REPORT MISSING TAGS ───────────────────────────────────────────────────
print("\n====== Missing Tags Report ======")
for ticker in TICKERS:
    missed = missing_summary.get(ticker, [])
    if missed:
        print(f"{ticker}: {', '.join(sorted(set(missed)))}")
    else:
        print(f"{ticker}: All metrics found")

print("\n✅ All companies processed with missing-tag summary above.")
