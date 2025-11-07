import os, json, time, requests
from collections import defaultdict

# ─── CONFIG ────────────────────────────────────────────────────────────────
HEADERS = {"User-Agent": "eng.sultan.fadi@gmail.com"}      # SEC requirement
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
DATA_DIR = "../gaap_tags/tree_financial_data"
os.makedirs(DATA_DIR, exist_ok=True)

TICKERS = ["AAPL"]

# ─── RELATIONSHIP DICTS ────────────────────────────────────────────────────
revenues_info = {
    "self": "Revenues",
    "brother": [],
    "children": [
        "DirectFinancingLeaseRevenue", "DirectFinancingLeaseVariableLeaseIncome",
        "DirectFinancingLeaseInterestIncome", "SalesTypeLeaseRevenue",
        "SalesTypeLeaseVariableLeaseIncome", "SalesTypeLeaseInterestIncome",
        "OperatingLeaseLeaseIncome", "SubleaseIncome",
        "SaleOfTrustAssetsToPayExpenses", "InsuranceCommissionsAndFees",
        "ContractuallySpecifiedServicingFeeLateFeeAndAncillaryFeeEarnedInExchangeForServicingFinancialAsset",
        "InsuranceAgencyManagementFee",
        "GainLossOnDispositionOfAssetsForFinancialServiceOperations",
        "PremiumsEarnedNet", "InvestmentIncomeNet",
        "RealizedInvestmentGainsLosses",
        "RevenuesExcludingInterestAndDividends",
        "OtherOperatingIncome", "FeeIncome", "OtherIncome"
    ],
    "father": "GrossProfit",
    "grandfather": "OperatingIncomeLoss",
    "2nd_grandfather": "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"
}
net_income_loss_info = {
    "self": "NetIncomeLoss",
    "brother": ["EarningsPerShareBasic", "EarningsPerShareDiluted"],
    "children": [],
    "father": "StatementLineItems",
    "grandfather": "StatementIncomeIncludingGrossMargin",
    "2nd_grandfather": None
}
METRIC_STRUCT = {
    "Revenue_info": revenues_info,
    "NetIncomeLoss_info": net_income_loss_info
}

# ─── HELPERS ───────────────────────────────────────────────────────────────
def load_cik_mapping(cache="company_tickers.json"):
    if not os.path.exists(cache):
        txt = requests.get(SEC_TICKER_URL, headers=HEADERS, timeout=30).text
        with open(cache, "w") as f: f.write(txt)
    with open(cache) as f:
        data = json.load(f)
    return {d["ticker"].upper(): str(d["cik_str"]).zfill(10) for d in data.values()}

def fetch_metric(cik: str, tag: str):
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200: return []
    try:
        units = r.json()["units"]
    except (ValueError, KeyError):
        return []
    vals = []
    for v in units.values(): vals.extend(v)
    return vals

def recent(rows):
    for r in rows:
        if r.get("form") in ("10-K", "10-Q") and (fy := r.get("fy")) and int(fy) >= 2014:
            yield r

# ─── MAIN ──────────────────────────────────────────────────────────────────
ticker_to_cik = load_cik_mapping()
missing = defaultdict(list)

for ticker in TICKERS:
    cik = ticker_to_cik[ticker]
    print(f"\n▶ {ticker}  CIK {cik}")
    periods = defaultdict(dict)        # {end_date: {metric_block: {tag: val}}}

    for block_name, rel in METRIC_STRUCT.items():
        tag_set = {rel["self"], *rel["children"], *rel["brother"]}
        for anc in ("father", "grandfather", "2nd_grandfather"):
            if rel.get(anc): tag_set.add(rel[anc])

        found = False
        for tag in tag_set:
            rows = fetch_metric(cik, tag)
            time.sleep(0.25)
            if not rows: continue
            found = True
            for row in recent(rows):
                end = row["end"]
                periods[end].setdefault(block_name, {})[tag] = row["val"]

        if not found:
            missing[ticker].append(block_name)

        # ensure tag placeholder in every collected period
        for p in periods.values():
            p.setdefault(block_name, {})
            for tag in tag_set:
                p[block_name].setdefault(tag, "not available")

    # save
    out = {"ticker": ticker, "cik": cik, "financials": dict(periods)}
    path = os.path.join(DATA_DIR, f"{ticker}.json")
    with open(path, "w") as f: json.dump(out, f, indent=2)
    print(f"  ↳ saved {path}")

print("\n====== Missing root blocks ======")
for t in TICKERS:
    print(f"{t}: {', '.join(missing[t]) if missing[t] else 'none'}")

print("\n✅ Done — metrics grouped under 'Revenue_info' and 'NetIncomeLoss_info'.")
