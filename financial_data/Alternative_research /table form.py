import os, time, json, requests
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from cosine_similarity_selection import choose_revenue_substitute  # will be called ONLY on-demand

# ───────────────────── CONFIG ─────────────────────
HEADERS = {"User-Agent": "FinancialDataCollector/1.0 (eng.sultan.fadi@gmail.com)"}
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
OUT_CSV = "edgar_metrics.csv"

# keep small while testing
TICKERS = ["NVDA"]
METRICS = [
    "Revenues","NetIncomeLoss","EarningsPerShareBasic","EarningsPerShareDiluted",
    "OperatingIncomeLoss","GrossProfit","ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense","Assets","Liabilities","StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue","NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment","LongTermDebt","ShortTermInvestments",
    "CostOfRevenue","OperatingExpenses","IncomeTaxExpenseBenefit","AccountsReceivableNetCurrent",
]

# preferred units / period-types
PREFERRED_UNITS = {
    "EarningsPerShareBasic": "USD/shares",
    "EarningsPerShareDiluted": "USD/shares",
}
DEFAULT_UNIT = "USD"
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

# ───────────────────── HELPERS ─────────────────────
def load_cik_map(cache="company_tickers.json") -> Dict[str, str]:
    if not os.path.exists(cache):
        r = requests.get(SEC_TICKER_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        open(cache, "w").write(r.text)
    data = json.load(open(cache))
    return {d["ticker"].upper(): str(d["cik_str"]).zfill(10) for d in data.values()}

def fetch_concept_rows(cik: str, tag: str, retries=3, pause=0.25) -> List[Dict[str, Any]]:
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    for a in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                js = r.json()
                out=[]
                for uom, rows in (js.get("units") or {}).items():
                    for row in rows or []:
                        row2 = dict(row); row2["uom"]=uom
                        out.append(row2)
                return out
            if r.status_code in (429,500,502,503,504):
                time.sleep(pause*(a+1)); continue
            return []
        except requests.RequestException:
            time.sleep(pause*(a+1))
    return []

def unit_ok(metric: str, uom: Optional[str]) -> bool:
    want = PREFERRED_UNITS.get(metric) or DEFAULT_UNIT
    return uom == want

def period_type(metric: str) -> Optional[str]:
    return METRIC_PERIOD_TYPE.get(metric)

def valid_since_2014(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out=[]
    for r in rows:
        fy = r.get("fy")
        if fy and str(fy).isdigit() and int(fy) >= 2014 and r.get("form") in ("10-K","10-Q"):
            out.append(r)
    return out

def filter_metric_rows(metric: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pt_expected = period_type(metric)
    out=[]
    for r in rows:
        pt = "duration" if r.get("start") else "instant"
        if pt_expected and pt != pt_expected:
            continue
        if not unit_ok(metric, r.get("uom")):
            continue
        out.append(r)
    return out

def pick_latest_filed_per_fy_form(rows: List[Dict[str, Any]]) -> Dict[Tuple[int, str], Dict[str, Any]]:
    """
    Keep the latest-filed row for each (FY, FORM). FORM ∈ {"10-K","10-Q"}.
    """
    best: Dict[Tuple[int,str], Dict[str,Any]] = {}
    for r in rows:
        fy = r.get("fy")
        form = r.get("form")
        if not isinstance(fy, int) or form not in ("10-K","10-Q"):
            continue
        key = (fy, form)
        prev = best.get(key)
        if prev is None or (r.get("filed") or "") > (prev.get("filed") or ""):
            best[key] = r
    return best

def to_fact(tag: str, r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tag": tag,
        "value": r.get("val"),
        "unit": r.get("uom"),
        "fy": r.get("fy"),
        "fp": r.get("fp"),
        "form": r.get("form"),
        "filed": r.get("filed"),
        "accn": r.get("accn"),
        "start": r.get("start"),
        "end": r.get("end"),
    }

# ───────────────────── CORE LOGIC ─────────────────────
def get_primary_best(cik: str, metric: str) -> Dict[Tuple[int,str], Dict[str,Any]]:
    rows = fetch_concept_rows(cik, metric)
    rows = valid_since_2014(rows)
    rows = filter_metric_rows(metric, rows)
    return {k: to_fact(metric, v) for k, v in pick_latest_filed_per_fy_form(rows).items()}

def get_first_available_alternative(
    cik: str,
    metric: str,
    missing_keys: List[Tuple[int,str]],
    substitute_cache: Dict[Tuple[str,str], List[str]],
) -> Dict[Tuple[int,str], Dict[str,Any]]:
    """
    Call choose_revenue_substitute ONLY IF we actually have missing (FY,FORM) pairs.
    Returns a dict of filled facts for those keys where an alternative produced a non-null value.
    """
    filled: Dict[Tuple[int,str], Dict[str,Any]] = {}
    if not missing_keys:
        return filled

    cache_key = (cik, metric)
    if cache_key not in substitute_cache:
        # ← THIS is where we call it — only now, because primary was missing
        alts = choose_revenue_substitute(cik, metric, top_n=24) or []
        # store once per (CIK, metric)
        substitute_cache[cache_key] = [a for a in alts if a and a != metric]
    alt_tags = substitute_cache.get(cache_key, [])

    if not alt_tags:
        return filled

    # Try alternatives in order; accept first non-null for each missing (fy, form)
    # We fetch each alt tag once, then reuse rows for all (fy, form)
    alt_rows_by_tag: Dict[str, Dict[Tuple[int,str], Dict[str,Any]]] = {}
    for alt_tag in alt_tags:
        rows = fetch_concept_rows(cik, alt_tag)
        if not rows:
            continue
        rows = valid_since_2014(rows)
        rows = filter_metric_rows(metric, rows)  # enforce original metric's unit + period-type
        best = {k: to_fact(alt_tag, v) for k, v in pick_latest_filed_per_fy_form(rows).items()}
        alt_rows_by_tag[alt_tag] = best
        time.sleep(0.03)

    for key in missing_keys:
        fy, form = key
        chosen = None
        for alt_tag in alt_tags:
            fact = alt_rows_by_tag.get(alt_tag, {}).get(key)
            if fact is not None and fact.get("value") is not None:
                chosen = dict(fact)  # copy
                chosen["source"] = "alternative"
                break
        if chosen:
            filled[key] = chosen
    return filled

def collect_to_csv(tickers: List[str], metrics: List[str], out_csv: str):
    ticker2cik = load_cik_map()
    rows_out = []
    substitute_cache: Dict[Tuple[str,str], List[str]] = {}  # (cik, metric) -> [alt tags]

    for tkr in tickers:
        cik = ticker2cik.get(tkr.upper())
        if not cik:
            print(f"CIK not found for {tkr}")
            continue

        for metric in metrics:
            # 1) Primary facts (latest per FY+FORM)
            prim = get_primary_best(cik, metric)

            # Determine which (FY,FORM) slots exist across data for this metric
            # We use the union of keys we see in primary; but also allow alternatives
            # to introduce new FYs — so build the universe by peeking at primary; then
            # we’ll fill only where primary is missing/None.
            # First, list of candidate keys is just what primary already has:
            keys = set(prim.keys())

            # Identify missing or null primary values
            missing_keys = [k for k in keys if (k not in prim) or (prim.get(k, {}).get("value") is None)]

            # If we have NO primary at all for this metric, we still need some FY/FORM keys to try.
            # In that case, try to discover keys from the first alternative tag after we call the chooser.
            if not keys:
                # call chooser once – only because everything is missing
                alt_filled_probe = get_first_available_alternative(cik, metric, [(9999,"10-K")], substitute_cache)  # dummy key to force cache fill
                # Now that cache is filled, probe actual alt tags to collect keys universe
                keys = set()
                for alt_tag in substitute_cache.get((cik, metric), []):
                    rows = fetch_concept_rows(cik, alt_tag)
                    rows = valid_since_2014(rows)
                    rows = filter_metric_rows(metric, rows)
                    best = pick_latest_filed_per_fy_form(rows)
                    keys.update(best.keys())
                    time.sleep(0.03)
                missing_keys = list(keys)  # all are missing

            # 2) Fill missing ONLY IF needed (this is the only place we ever call the chooser)
            alt = get_first_available_alternative(cik, metric, missing_keys, substitute_cache)

            # 3) Emit rows for both 10-K and 10-Q (whatever exists among keys)
            for (fy, form) in sorted(keys):
                fact = prim.get((fy, form))
                source = "primary"
                tag_used = metric
                if fact is None or fact.get("value") is None:
                    fact = alt.get((fy, form))
                    source = (fact or {}).get("source") or "missing"
                    tag_used = (fact or {}).get("tag") or metric

                rows_out.append({
                    "ticker": tkr,
                    "cik": cik,
                    "fy": fy,
                    "form": form,                 # "10-K" or "10-Q"
                    "metric": metric,             # requested metric
                    "tag_used": tag_used,         # actual tag used (metric or alternative)
                    "value": (fact or {}).get("value"),
                    "unit": (fact or {}).get("unit"),
                    "filed": (fact or {}).get("filed"),
                    "fp": (fact or {}).get("fp"),
                    "start": (fact or {}).get("start"),
                    "end": (fact or {}).get("end"),
                    "source": source,             # "primary" / "alternative" / "missing"
                })
            time.sleep(0.05)

    # 4) Save CSV (tidy table)
    df = pd.DataFrame(rows_out).sort_values(["ticker","fy","form","metric"])
    df.to_csv(out_csv, index=False)
    print(f"✓ Saved {out_csv} with {len(df):,} rows")

if __name__ == "__main__":
    collect_to_csv(TICKERS, METRICS, OUT_CSV)

