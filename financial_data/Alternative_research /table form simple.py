import os, json, time, csv, requests
from typing import Dict, Any, Iterable, Optional
from datetime import datetime

# --------------- CONFIG ---------------
HEADERS = {"User-Agent": "FinancialDataCollector/1.0 (eng.sultan.fadi@gmail.com)"}
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
OUT_DIR = "financial_csv_10y"
os.makedirs(OUT_DIR, exist_ok=True)

# Edit tickers as you like
TICKERS = [
    "NVDA","MSFT","AAPL","AMZN","META","AVGO","GOOGL","GOOG","TSLA","NFLX",
    "PLTR","COST","ASML","CSCO","TMUS","AMD","AZN","LIN","APP","SHOP",
    "PEP","INTU","PDD","MU","QCOM","BKNG","TXN","LRCX","ISRG","ADBE",
    "AMGN","AMAT","ARM","GILD","PANW","INTC","KLAC","HON","CRWD","MELI",
    "ADI","ADP","CMCSA","DASH","CEG","CDNS","VRTX","MSTR","SBUX","SNPS",
    "ORLY","MDLZ","CTAS","ABNB","TRI","MAR","ADSK","PYPL","FTNT","MRVL",
    "REGN","MNST","WDAY","CSX","AXON","AEP","NXPI","FAST","ROP","IDXX",
    "PCAR","DDOG","WBD","ROST","PAYX","BKR","ZS","TTWO","TEAM","CPRT",
    "EXC","EA","XEL","CCEP","FANG","CSGP","KDP","CHTR","MCHP","GEHC",
    "VRSK","CTSH","KHC","ODFL","DXCM","TTD","CDW","BIIB","ON","LULU","GFS"
]

YEARS_BACK = 10           # last 10 fiscal years (inclusive)
SLEEP_BETWEEN_CALLS = 0.15

# 20 metrics; fetch only; if missing -> "null"
METRICS = [
    "Revenues","NetIncomeLoss","EarningsPerShareBasic","EarningsPerShareDiluted",
    "OperatingIncomeLoss","GrossProfit","ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense","Assets","Liabilities","StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue","NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment","LongTermDebt","ShortTermInvestments",
    "CostOfRevenue","OperatingExpenses","IncomeTaxExpenseBenefit","AccountsReceivableNetCurrent",
]

# Expected period type for each metric
METRIC_PERIOD_TYPE = {
    "Revenues":"duration","NetIncomeLoss":"duration","EarningsPerShareBasic":"duration",
    "EarningsPerShareDiluted":"duration","OperatingIncomeLoss":"duration","GrossProfit":"duration",
    "ResearchAndDevelopmentExpense":"duration","SellingGeneralAndAdministrativeExpense":"duration",
    "NetCashProvidedByUsedInOperatingActivities":"duration","PaymentsToAcquirePropertyPlantAndEquipment":"duration",
    "CostOfRevenue":"duration","OperatingExpenses":"duration","IncomeTaxExpenseBenefit":"duration",
    "Assets":"instant","Liabilities":"instant","StockholdersEquity":"instant",
    "CashAndCashEquivalentsAtCarryingValue":"instant","ShortTermInvestments":"instant",
    "AccountsReceivableNetCurrent":"instant","LongTermDebt":"instant",
}

# Unit preferences (EPS tags use USD/shares, others USD)
PREFERRED_UNITS = {
    "EarningsPerShareBasic": "USD/shares",
    "EarningsPerShareDiluted": "USD/shares",
}
DEFAULT_UNIT = "USD"

# --------------- HELPERS ---------------
def load_cik_map(cache="company_tickers.json") -> Dict[str, str]:
    if not os.path.exists(cache):
        r = requests.get(SEC_TICKER_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        open(cache, "w").write(r.text)
    data = json.load(open(cache))
    return {d["ticker"].upper(): str(d["cik_str"]).zfill(10) for d in data.values()}

def fetch_concept_rows(cik: str, tag: str) -> Iterable[Dict[str, Any]]:
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                js = r.json()
                for uom, rows in (js.get("units") or {}).items():
                    for row in rows or []:
                        rr = dict(row)
                        rr["uom"] = uom
                        yield rr
                return
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.25 * (attempt + 1))
                continue
            return
        except requests.RequestException:
            time.sleep(0.25 * (attempt + 1))

def period_type_for_row(r: Dict[str, Any]) -> str:
    return "duration" if r.get("start") else "instant"

def unit_ok(metric: str, uom: Optional[str]) -> bool:
    want = PREFERRED_UNITS.get(metric) or DEFAULT_UNIT
    return uom == want

def wanted_form(r: Dict[str, Any]) -> bool:
    return r.get("form") in ("10-K", "10-Q")

def filter_metric_rows(metric: str, rows: Iterable[Dict[str, Any]], start_fy: int) -> Iterable[Dict[str, Any]]:
    expected = METRIC_PERIOD_TYPE.get(metric)
    for r in rows:
        fy = r.get("fy")
        if not wanted_form(r):
            continue
        if not isinstance(fy, int) or fy < start_fy:
            continue
        if expected and period_type_for_row(r) != expected:
            continue
        if not unit_ok(metric, r.get("uom")):
            continue
        yield r

def sec_row_common_fields(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "fy": r.get("fy"),
        "fp": r.get("fp"),
        "form": r.get("form"),
        "filed": r.get("filed"),
        "end": r.get("end"),
        "start": r.get("start"),
        "accn": r.get("accn"),
    }

# --------------- MAIN ---------------
def main():
    ticker2cik = load_cik_map()
    current_year = datetime.utcnow().year
    start_fy = current_year - YEARS_BACK + 1  # ex: for 10y in 2025 => 2016..2025

    # We'll collect ALL filings from ALL tickers into one list, then write ONE csv
    all_rows = []

    for tkr in TICKERS:
        cik = ticker2cik.get(tkr.upper())
        if not cik:
            print(f"CIK not found for {tkr}")
            continue

        # Build per-filing row dicts for this ticker
        # filing_rows[accn] = {common fields..., metrics...}
        filing_rows: Dict[str, Dict[str, Any]] = {}

        for metric in METRICS:
            rows = list(filter_metric_rows(metric, fetch_concept_rows(cik, metric), start_fy))

            # Keep latest 'filed' value per filing accession
            by_accn: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                accn = r.get("accn")
                if not accn:
                    continue
                prev = by_accn.get(accn)
                if (prev is None) or ((r.get("filed") or "") > (prev.get("filed") or "")):
                    by_accn[accn] = r

            # Merge into filing_rows
            for accn, r in by_accn.items():
                row = filing_rows.setdefault(accn, {})
                if "accn" not in row:
                    row.update(sec_row_common_fields(r))
                    row["ticker"] = tkr
                    row["cik"] = cik
                val = r.get("val")
                row[metric] = val if isinstance(val, (int, float)) else ("null" if val is None else val)

            time.sleep(SLEEP_BETWEEN_CALLS)

        # Ensure each filing row has all metrics; fill missing with literal 'null'
        for accn, row in filing_rows.items():
            for m in METRICS:
                if m not in row:
                    row[m] = "null"
            all_rows.append(row)

        print(f"{tkr}: collected {len(filing_rows)} filings")

    # Sort ALL rows (all tickers) nicely
    all_rows.sort(key=lambda x: (x.get("ticker",""), x.get("fy") or 0, x.get("fp") or "", x.get("filed") or "", x.get("form") or ""))

    out_path = os.path.join(OUT_DIR, "all_tickers_facts_10y.csv")
    fieldnames = ["ticker","cik","fy","fp","form","filed","end","start","accn"] + METRICS

    with open(out_path, "w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=fieldnames)
        w.writeheader()
        for r in all_rows:
            w.writerow({k: r.get(k, "null") for k in fieldnames})

    print(f"Saved ONE CSV: {out_path}  ({len(all_rows)} filings total)")

if __name__ == "__main__":
    main()
