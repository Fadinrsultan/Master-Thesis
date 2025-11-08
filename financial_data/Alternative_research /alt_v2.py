import requests
import json
import os
import time
from collections import defaultdict
from cosine_similarity_selection import choose_revenue_substitute

# ─────────────────── CONFIG ───────────────────
HEADERS = {"User-Agent": "FinancialDataCollector/1.0 (eng.sultan.fadi@gmail.com)"}
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
DATA_DIR = "financial_data_2"
os.makedirs(DATA_DIR, exist_ok=True)

TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "TSLA", "NVDA", "JPM", "V", "UNH",
    "HD", "PG", "MA", "DIS", "BAC",
    "ADBE", "INTC", "PFE", "KO", "CSCO",
]

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
    "AccountsReceivableNetCurrent",
    "FreeCashFlow",  # derived later
]

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
    return {d["ticker"].upper(): str(d["cik_str"]).zfill(10) for d in data.values()}

def fetch_concept(cik: str, tag: str, retries=3, pause=0.25):
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                units = r.json().get("units", {})
                # Keep both USD and USD/shares (EPS)
                return (units.get("USD", []) or []) + (units.get("USD/shares", []) or [])
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(pause * (attempt + 1))
                continue
            return []
        except requests.RequestException:
            time.sleep(pause * (attempt + 1))
    return []

def entries_since_2014(rows):
    for r in rows:
        fy = r.get("fy")
        if fy and str(fy).isdigit() and int(fy) >= 2014 and r.get("form") in ("10-K", "10-Q"):
            yield r

def pick_latest_by_period(rows):
    """Return dict {period_end: row} choosing the latest 'filed' per period."""
    best = {}
    for r in rows:
        end = r.get("end")
        filed = r.get("filed", "")
        if not end:
            continue
        if end not in best or filed > best[end].get("filed", ""):
            best[end] = r
    return best

# ───────────── MAIN PROCESS ─────────────
ticker2cik = load_cik_map()

for tkr in TICKERS:
    cik = ticker2cik.get(tkr)
    if not cik:
        print(f"CIK not found for {tkr}")
        continue

    print(f"\n▶ {tkr} (CIK {cik})")
    data = {"ticker": tkr, "cik": cik, "financials": {}}

    # Keep track of all periods we see from any metric/alt to build complete rows
    all_periods = set()

    # For each metric, keep alt maps so we can write per-period strings
    metric_alt_period_values = {}  # metric -> {alt_tag -> {period -> value}}

    # 1) Pull primary metrics and collect alternatives (but do NOT fill from alts)
    for metric in METRICS:
        if metric == "FreeCashFlow":
            continue  # derived later

        rows = fetch_concept(cik, metric)
        chosen = {}
        if rows:
            chosen = pick_latest_by_period(list(entries_since_2014(rows)))
            for period, r in chosen.items():
                all_periods.add(period)
                data["financials"].setdefault(period, {})[metric] = r["val"]

        # Prepare alt suggestions (values per period) for when primary is missing
        alt_maps = {}
        if not chosen:
            alt_tags = (choose_revenue_substitute(cik, metric, top_n=5) or [])[:5]
            for alt_tag in alt_tags:
                alt_rows = fetch_concept(cik, alt_tag)
                if not alt_rows:
                    time.sleep(0.05)
                    continue
                alt_chosen = pick_latest_by_period(list(entries_since_2014(alt_rows)))
                if alt_chosen:
                    # record which periods were observed overall
                    for p in alt_chosen.keys():
                        all_periods.add(p)
                    # save period -> value for this alternative
                    alt_maps[alt_tag] = {p: rr["val"] for p, rr in alt_chosen.items()}
                time.sleep(0.05)

        metric_alt_period_values[metric] = alt_maps

    # 2) Ensure every discovered period exists, then write "not available..." strings where needed
    for period in sorted(all_periods):
        row = data["financials"].setdefault(period, {})
        for metric in METRICS:
            if metric == "FreeCashFlow":
                continue
            if metric in row:
                continue  # already has a numeric value from primary tag

            # Build the exact string with alternatives (only those that have a value for this period)
            alt_maps = metric_alt_period_values.get(metric, {})
            pieces = []
            for alt_tag, per_map in alt_maps.items():
                if period in per_map:
                    pieces.append(f"{alt_tag}={per_map[period]}")
            if pieces:
                row[metric] = "not available from the company,but i can offer you the following: " + ", ".join(pieces)
            else:
                row[metric] = "not available from the company,but i can offer you the following"

    # 3) Derive Free Cash Flow per period; if not computable, write the same style string
    for period, vals in data["financials"].items():
        op = vals.get("NetCashProvidedByUsedInOperatingActivities")
        capex = vals.get("PaymentsToAcquirePropertyPlantAndEquipment")
        if isinstance(op, (int, float)) and isinstance(capex, (int, float)):
            capex_outflow = abs(capex)
            vals["FreeCashFlow"] = op - capex_outflow
        else:
            # Offer components if any are numeric
            pieces = []
            if isinstance(op, (int, float)):
                pieces.append(f"NetCashProvidedByUsedInOperatingActivities={op}")
            if isinstance(capex, (int, float)):
                pieces.append(f"PaymentsToAcquirePropertyPlantAndEquipment={capex}")
            suffix = (": " + ", ".join(pieces)) if pieces else ""
            vals["FreeCashFlow"] = "not available from the company,but i can offer you the following" + suffix

    # 4) Save JSON
    with open(os.path.join(DATA_DIR, f"{tkr}.json"), "w") as fp:
        json.dump(data, fp, indent=2)

print(f"\n✅ Completed. JSON files saved in ./{DATA_DIR}")
