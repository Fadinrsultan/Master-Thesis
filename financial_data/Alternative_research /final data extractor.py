import requests, json, os, time
from collections import defaultdict
from typing import Dict, List, Any, Iterable, Optional
from cosine_similarity_selection import choose_revenue_substitute

# ─────────────────── CONFIG ───────────────────
HEADERS = {"User-Agent": "FinancialDataCollector/1.0 (eng.sultan.fadi@gmail.com)"}
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
DATA_DIR = "financial_data_2"
os.makedirs(DATA_DIR, exist_ok=True)

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

# 19 base metrics; FCF is derived → total 20
METRICS = [
    "Revenues","NetIncomeLoss","EarningsPerShareBasic","EarningsPerShareDiluted",
    "OperatingIncomeLoss","GrossProfit","ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense","Assets","Liabilities","StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue","NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment","LongTermDebt","ShortTermInvestments",
    "CostOfRevenue","OperatingExpenses","IncomeTaxExpenseBenefit","AccountsReceivableNetCurrent",
    "FreeCashFlow"
]
BASE_METRICS = [m for m in METRICS if m != "FreeCashFlow"]

PREFERRED_UNITS = {
    "EarningsPerShareBasic": "USD/shares",
    "EarningsPerShareDiluted": "USD/shares",
}
DEFAULT_UNIT = "USD"

# period-type expectations (duration vs instant)
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

# if True, fill missing FY with nearest other FY that has a valid fact (adds carry_from_fy flag)
ALLOW_CARRY = True

# ──────────────── HELPERS ────────────────
def load_cik_map(cache="company_tickers.json"):
    if not os.path.exists(cache):
        r = requests.get(SEC_TICKER_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        open(cache,"w").write(r.text)
    data = json.load(open(cache))
    return {d["ticker"].upper(): str(d["cik_str"]).zfill(10) for d in data.values()}

def fetch_concept(cik: str, tag: str, retries=3, pause=0.25) -> List[Dict[str, Any]]:
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

def entries_since_2014(rows: Iterable[Dict[str, Any]]):
    for r in rows:
        fy = r.get("fy")
        if fy and str(fy).isdigit() and int(fy) >= 2014 and r.get("form") in ("10-K","10-Q"):
            yield r

def sec_row_to_fact(tag: str, r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tag": tag, "value": r.get("val"), "unit": r.get("uom"),
        "fy": r.get("fy"), "fp": r.get("fp"), "form": r.get("form"),
        "filed": r.get("filed"), "accn": r.get("accn"),
        "end": r.get("end"), "start": r.get("start")
    }

def expected_period_type(metric: str) -> Optional[str]:
    return METRIC_PERIOD_TYPE.get(metric)

def unit_ok_for_metric(metric: str, uom: Optional[str]) -> bool:
    want = PREFERRED_UNITS.get(metric) or DEFAULT_UNIT
    return uom == want

def filter_rows_for_metric(metric: str, rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    et = expected_period_type(metric)
    out=[]
    for r in rows:
        pt = "duration" if r.get("start") else "instant"
        if et and pt != et:
            continue
        if not unit_ok_for_metric(metric, r.get("uom")):
            continue
        out.append(r)
    return out

def choose_latest_filed_per_fy(rows: Iterable[Dict[str, Any]], metric: str) -> Dict[int, Dict[str, Any]]:
    """
    From SEC rows (already filtered by period-type/unit), pick best per FY:
    prefer 10-K, else latest filed (10-Q) within FY.
    Returns {fy -> row}
    """
    by_fy: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        fy = r.get("fy")
        if not isinstance(fy, int):
            continue
        prev = by_fy.get(fy)
        if prev is None:
            by_fy[fy] = r; continue
        # prefer 10-K over 10-Q
        if (r.get("form")=="10-K") and (prev.get("form")!="10-K"):
            by_fy[fy]=r; continue
        # else newer filing date
        if (r.get("filed") or "") > (prev.get("filed") or ""):
            by_fy[fy]=r
    return by_fy

def frequency_from_form(form: Optional[str]) -> Optional[str]:
    if form == "10-K": return "annual"
    if form == "10-Q": return "quarterly"
    return None

def pick_best_alternative_for_fy(alts_fy_map: Dict[int, List[Dict[str, Any]]], fy: int, metric: str) -> Optional[Dict[str, Any]]:
    cand = alts_fy_map.get(fy, [])
    if not cand:
        return None
    # prefer latest filed among already-filtered, unit-matching alts
    cand = sorted(cand, key=lambda a: a.get("filed") or "")
    return cand[-1] if cand else None

def nearest_fy_with_fact(fy: int, fy_to_fact: Dict[int, Dict[str, Any]]) -> Optional[int]:
    if not fy_to_fact: return None
    pool = sorted(fy_to_fact.keys())
    # find closest FY by absolute distance
    best = None; bestdist = 10**9
    for k in pool:
        if k == fy: continue
        d = abs(k - fy)
        if d < bestdist:
            bestdist = d; best = k
    return best

# ───────────── MAIN ─────────────
ticker2cik = load_cik_map()

for tkr in TICKERS:
    cik = ticker2cik.get(tkr)
    if not cik:
        print(f"CIK not found for {tkr}"); continue

    print(f"\n▶ {tkr} (CIK {cik})")
    data = {"ticker": tkr, "cik": cik, "financials_by_fy": {}}

    # Collect facts by FY
    primary_by_metric_fy: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(dict)
    alt_by_metric_fylist: Dict[str, Dict[int, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))

    # 1) Primary + alternatives (cosine) for ALL metrics
    for metric in BASE_METRICS:
        # primary
        rows = fetch_concept(cik, metric)
        rows = list(entries_since_2014(rows))
        rows = filter_rows_for_metric(metric, rows)
        best_per_fy = choose_latest_filed_per_fy(rows, metric)
        for fy, r in best_per_fy.items():
            primary_by_metric_fy[metric][fy] = sec_row_to_fact(metric, r)

        # alternatives (cosine only)
        alt_tags = (choose_revenue_substitute(cik, metric, top_n=24) or [])[:24]
        for alt_tag in alt_tags:
            if not alt_tag or alt_tag == metric:
                continue
            alt_rows = fetch_concept(cik, alt_tag)
            if not alt_rows:
                time.sleep(0.03); continue
            alt_rows = list(entries_since_2014(alt_rows))
            alt_rows = filter_rows_for_metric(metric, alt_rows)  # enforce period-type + unit
            if not alt_rows:
                time.sleep(0.03); continue
            alt_best_fy = choose_latest_filed_per_fy(alt_rows, metric)
            for fy, rr in alt_best_fy.items():
                alt_by_metric_fylist[metric][fy].append(sec_row_to_fact(alt_tag, rr))
            time.sleep(0.03)

    # 2) Build FY rows — one chosen per metric; guarantee coverage (with optional carry)
    all_fys = set()
    for m in BASE_METRICS:
        all_fys.update(primary_by_metric_fy[m].keys())
        all_fys.update(alt_by_metric_fylist[m].keys())
    all_fys = sorted(all_fys)

    for fy in all_fys:
        row = data["financials_by_fy"].setdefault(str(fy), {})  # JSON keys as strings
        freq = None
        for metric in BASE_METRICS:
            primary = primary_by_metric_fy[metric].get(fy)
            best_alt = pick_best_alternative_for_fy(alt_by_metric_fylist[metric], fy, metric)

            chosen = None
            source = None
            if primary:
                chosen = primary; source = "primary"
            elif best_alt:
                chosen = best_alt; source = "alternative"
            elif ALLOW_CARRY:
                # carry from nearest FY that has either primary or alt
                available = {}
                if primary_by_metric_fy[metric]:
                    available.update(primary_by_metric_fy[metric])
                if alt_by_metric_fylist[metric]:
                    for k, lst in alt_by_metric_fylist[metric].items():
                        if lst:
                            # pick last as it is latest filed among stored alts for that FY
                            available.setdefault(k, lst[-1])
                k = nearest_fy_with_fact(fy, available)
                if k is not None:
                    chosen = available[k].copy()
                    chosen["carry_from_fy"] = int(k)
                    source = "carried"

            row[metric] = {
                "chosen": ({"source": source, **chosen} if chosen else None),
                "primary": primary if primary else None,
                "alternatives": alt_by_metric_fylist[metric].get(fy, [])
            }

            # set frequency (prefer 10-K)
            if freq is None and row[metric]["chosen"]:
                freq = frequency_from_form(row[metric]["chosen"].get("form"))
        if freq:
            row.setdefault("_meta", {})["frequency"] = freq

    # 3) Derive FCF from CHOSEN values
    for fy, vals in data["financials_by_fy"].items():
        ocf = (vals.get("NetCashProvidedByUsedInOperatingActivities") or {}).get("chosen")
        capex = (vals.get("PaymentsToAcquirePropertyPlantAndEquipment") or {}).get("chosen")
        derived = {"value": None, "unit":"USD", "formula":"FreeCashFlow = OCF - abs(CapEx)", "derived_from": [], "source":"derived"}
        if ocf:   derived["derived_from"].append({"metric":"NetCashProvidedByUsedInOperatingActivities", **ocf})
        if capex: derived["derived_from"].append({"metric":"PaymentsToAcquirePropertyPlantAndEquipment", **capex})
        if ocf and isinstance(ocf.get("value"), (int,float)) and capex and isinstance(capex.get("value"), (int,float)):
            derived["value"] = ocf["value"] - abs(capex["value"])
        vals["FreeCashFlow"] = {"chosen": derived}

        # assert 20 tags
        base_count = sum(1 for m in BASE_METRICS if (vals.get(m) or {}).get("chosen"))
        if base_count + 1 != 20:
            missing = [m for m in BASE_METRICS if not (vals.get(m) or {}).get("chosen")]
            print(f"  [WARN] {tkr} FY {fy}: {base_count+1} tags of 20. Missing: {missing}")

    # 4) Save
    out_path = os.path.join(DATA_DIR, f"{tkr}.json")
    with open(out_path,"w") as fp:
        json.dump(data, fp, indent=2)
    print(f"  ↳ saved: {out_path}")

print(f"\n✅ Completed. JSON files (by FY) saved in ./{DATA_DIR}")
