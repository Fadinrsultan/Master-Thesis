import os, json, time, csv, requests
from typing import Dict, Any, Iterable, Optional, Tuple
from datetime import datetime

from cosine_similarity_selection import choose_revenue_substitute  # your function

# --------------- CONFIG ---------------
HEADERS = {"User-Agent": "FinancialDataCollector/1.0 (eng.sultan.fadi@gmail.com)"}
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
OUT_DIR = "financial_csv_final_y"
os.makedirs(OUT_DIR, exist_ok=True)

#TICKERS = ["NVDA"]
TICKERS = [ "NVDA","MSFT","AAPL","AMZN","META","AVGO","GOOGL","GOOG","TSLA","NFLX", "PLTR","COST","ASML","CSCO","TMUS","AMD","AZN","LIN","APP","SHOP", "PEP","INTU","PDD","MU","QCOM","BKNG","TXN","LRCX","ISRG","ADBE", "AMGN","AMAT","ARM","GILD","PANW","INTC","KLAC","HON","CRWD","MELI", "ADI","ADP","CMCSA","DASH","CEG","CDNS","VRTX","MSTR","SBUX","SNPS", "ORLY","MDLZ","CTAS","ABNB","TRI","MAR","ADSK","PYPL","FTNT","MRVL", "REGN","MNST","WDAY","CSX","AXON","AEP","NXPI","FAST","ROP","IDXX", "PCAR","DDOG","WBD","ROST","PAYX","BKR","ZS","TTWO","TEAM","CPRT", "EXC","EA","XEL","CCEP","FANG","CSGP","KDP","CHTR","MCHP","GEHC", "VRSK","CTSH","KHC","ODFL","DXCM","TTD","CDW","BIIB","ON","LULU","GFS" ]

YEARS_BACK = 10
SLEEP_BETWEEN_CALLS = 0.15

METRICS = [
    "Revenues","NetIncomeLoss","EarningsPerShareBasic","EarningsPerShareDiluted",
    "OperatingIncomeLoss","GrossProfit","ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense","Assets","Liabilities","StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue","NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment","LongTermDebt","ShortTermInvestments",
    "CostOfRevenue","OperatingExpenses","IncomeTaxExpenseBenefit","AccountsReceivableNetCurrent",
]

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

PREFERRED_UNITS = {
    "EarningsPerShareBasic": "USD/shares",
    "EarningsPerShareDiluted": "USD/shares",
}
DEFAULT_UNIT = "USD"

# --------------- HELPERS ---------------
def load_cik_map(cache: str = "company_tickers.json") -> Dict[str, str]:
    if not os.path.exists(cache):
        r = requests.get(SEC_TICKER_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        with open(cache, "w") as f:
            f.write(r.text)
    with open(cache, "r") as f:
        data = json.load(f)
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

def filter_metric_rows(metric: str,
                       rows: Iterable[Dict[str, Any]],
                       start_fy: int) -> Iterable[Dict[str, Any]]:
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

def _normalize_alt_tag(raw_alt: Any) -> Optional[str]:
    """
    Ensure we end up with a string tag name, even if choose_revenue_substitute
    returns ('SalesRevenueNet', 0.98) or ['SalesRevenueNet', 0.98].
    """
    alt = raw_alt
    if isinstance(alt, (list, tuple)) and alt:
        alt = alt[0]
    if not isinstance(alt, str):
        return None
    return alt

def substitute_missing_value(metric: str, row: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    """
    For a missing primary metric, use choose_revenue_substitute to pick an
    alternative us-gaap tag and fetch a numeric value for this CIK/filing
    (or at least for the same FY). Always return the tag name as source.
    """
    cik = row.get("cik")
    accn = row.get("accn")
    fy = row.get("fy")
    fp = row.get("fp")

    if not cik:
        return None, None

    # --- Call choose_revenue_substitute robustly ---
    raw_alt = None
    try:
        raw_alt = choose_revenue_substitute(row, metric)
    except TypeError:
        try:
            raw_alt = choose_revenue_substitute(metric, row)
        except TypeError:
            try:
                raw_alt = choose_revenue_substitute(metric)
            except TypeError:
                raw_alt = None

    alt_tag = _normalize_alt_tag(raw_alt)
    if not alt_tag:
        return None, None

    alt_rows = list(fetch_concept_rows(cik, alt_tag))
    if not alt_rows:
        return None, alt_tag

    expected = METRIC_PERIOD_TYPE.get(metric)

    # Helper to select numeric val if passes a filter
    def first_match(filter_fn):
        for r in alt_rows:
            if not wanted_form(r):
                continue
            if not filter_fn(r):
                continue
            v = r.get("val")
            if isinstance(v, (int, float)):
                return v
        return None

    # 1) same accn, strict period + unit
    def f1(r):
        if accn and r.get("accn") != accn:
            return False
        if expected and period_type_for_row(r) != expected:
            return False
        if not unit_ok(metric, r.get("uom")):
            return False
        return True

    val = first_match(f1)

    # 2) same fy/fp, unit ok
    if val is None and fy is not None:
        def f2(r):
            if r.get("fy") != fy:
                return False
            if fp and r.get("fp") != fp:
                return False
            if not unit_ok(metric, r.get("uom")):
                return False
            return True
        val = first_match(f2)

    # 3) same fy, any unit
    if val is None and fy is not None:
        def f3(r):
            return r.get("fy") == fy
        val = first_match(f3)

    # 4) any numeric value as last resort
    if val is None:
        def f4(r):  # always True
            return True
        val = first_match(f4)

    return val, alt_tag  # val may still be None, but tag is known

# --------------- MAIN ---------------
def main():
    ticker2cik = load_cik_map()
    current_year = datetime.utcnow().year
    start_fy = current_year - YEARS_BACK + 1

    all_rows = []

    for tkr in TICKERS:
        cik = ticker2cik.get(tkr.upper())
        if not cik:
            print(f"CIK not found for {tkr}")
            continue

        filing_rows: Dict[str, Dict[str, Any]] = {}

        for metric in METRICS:
            rows = list(filter_metric_rows(metric, fetch_concept_rows(cik, metric), start_fy))

            # Keep latest 'filed' per accn
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
                v = r.get("val")
                # keep numeric; everything else -> None (missing)
                row[metric] = v if isinstance(v, (int, float)) else None

            time.sleep(SLEEP_BETWEEN_CALLS)

        # Fill missing metrics using alternative tags
        for accn, row in filing_rows.items():
            for m in METRICS:
                val = row.get(m, None)

                if val is None:
                    sub_val, sub_source = substitute_missing_value(m, row)

                    # If we could get a numeric substitute, use it
                    if sub_val is not None:
                        row[m] = sub_val

                    # Source: alternative tag if we have one, otherwise "missing"
                    row[m + "_source"] = sub_source or "missing"
                else:
                    # Value came from primary SEC tag
                    row[m + "_source"] = "sec"

            all_rows.append(row)

        print(f"{tkr}: collected {len(filing_rows)} filings")

    # Sort rows
    all_rows.sort(
        key=lambda x: (
            x.get("ticker", ""),
            x.get("fy") or 0,
            x.get("fp") or "",
            x.get("filed") or "",
            x.get("form") or "",
        )
    )

    # Fieldnames
    fieldnames = ["ticker","cik","fy","fp","form","filed","end","start","accn"]
    for m in METRICS:
        fieldnames.append(m)
        fieldnames.append(m + "_source")

    out_path = os.path.join(OUT_DIR, "all_tickers_facts_10y.csv")

    def safe(v: Any) -> Any:
        # Never write literal "null" – empty string for missing
        return "" if v is None else v

    with open(out_path, "w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=fieldnames)
        w.writeheader()
        for r in all_rows:
            w.writerow({k: safe(r.get(k)) for k in fieldnames})

    print(f"Saved ONE CSV: {out_path}  ({len(all_rows)} filings total)")

if __name__ == "__main__":
    main()