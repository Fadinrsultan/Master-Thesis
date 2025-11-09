import os, json, time, requests
from typing import Dict, Any, List, Optional, Iterable
from collections import defaultdict
from cosine_similarity_selection import choose_revenue_substitute

# ───────────────── CONFIG ─────────────────
HEADERS = {"User-Agent": "FinancialDataCollector/1.0 (eng.sultan.fadi@gmail.com)"}
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
DATA_DIR = "financial_data_simple"
os.makedirs(DATA_DIR, exist_ok=True)

TICKERS = ["NVDA"]  # extend as you like

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

ALLOW_CARRY = True  # carry closest FY if needed

# ─────────────── helpers ───────────────
def load_cik_map(cache="company_tickers.json") -> Dict[str, str]:
    if not os.path.exists(cache):
        r = requests.get(SEC_TICKER_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        open(cache, "w").write(r.text)
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
                        rr = dict(row)
                        rr["uom"] = uom
                        out.append(rr)
                return out
            if r.status_code in (429,500,502,503,504):
                time.sleep(pause*(a+1))
                continue
            return []
        except requests.RequestException:
            time.sleep(pause*(a+1))
    return []

def entries_since_2014(rows: Iterable[Dict[str, Any]]):
    for r in rows:
        fy = r.get("fy")
        if fy and str(fy).isdigit() and int(fy) >= 2014 and r.get("form") in ("10-K","10-Q"):
            yield r

def unit_ok_for_metric(metric: str, uom: Optional[str]) -> bool:
    want = PREFERRED_UNITS.get(metric) or DEFAULT_UNIT
    return uom == want

def expected_period_type(metric: str) -> Optional[str]:
    return METRIC_PERIOD_TYPE.get(metric)

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

def latest_by_fy_for_form(rows: Iterable[Dict[str, Any]], form: str) -> Dict[int, Dict[str, Any]]:
    """Return {fy -> latest filed row} for the given form."""
    by = {}
    for r in rows:
        if r.get("form") != form:
            continue
        fy = r.get("fy")
        if not isinstance(fy, int):
            continue
        prev = by.get(fy)
        if (prev is None) or ((r.get("filed") or "") > (prev.get("filed") or "")):
            by[fy] = r
    return by

def to_fact(tag: str, r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tag": tag, "value": r.get("val"), "unit": r.get("uom"),
        "fy": r.get("fy"), "fp": r.get("fp"), "form": r.get("form"),
        "filed": r.get("filed"), "accn": r.get("accn"),
        "end": r.get("end"), "start": r.get("start")
    }

def nearest_fy_with(forms_map: Dict[str, Dict[int, Dict[str, Any]]], fy: int) -> Optional[int]:
    have = set(forms_map.get("10-K",{}).keys()) | set(forms_map.get("10-Q",{}).keys())
    if not have:
        return None
    return min(have, key=lambda y: (abs(y - fy), y != fy))

# ───────────── cache to avoid refetching ─────────────
_CONCEPT_CACHE: Dict[tuple, List[Dict[str, Any]]] = {}

def get_rows(cik: str, tag: str) -> List[Dict[str, Any]]:
    key = (cik, tag)
    if key not in _CONCEPT_CACHE:
        _CONCEPT_CACHE[key] = fetch_concept(cik, tag)
    return _CONCEPT_CACHE[key]

# ───────────── core logic per metric ─────────────
def get_metric_forms_per_fy(cik: str, metric: str) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """
    Returns:
      {
        "10-K": {fy: fact, ...},
        "10-Q": {fy: fact, ...}
      }
    Only uses choose_revenue_substitute IF primary metric returns no usable rows at all.
    """
    # 1) try primary
    rows = get_rows(cik, metric)
    rows = filter_rows_for_metric(metric, entries_since_2014(rows))
    k_map = latest_by_fy_for_form(rows, "10-K")
    q_map = latest_by_fy_for_form(rows, "10-Q")
    if k_map or q_map:
        return {
            "10-K": {fy: to_fact(metric, r) for fy, r in k_map.items()},
            "10-Q": {fy: to_fact(metric, r) for fy, r in q_map.items()},
        }

    # 2) primary missing → try ONE round of substitutes
    alt_tags = (choose_revenue_substitute(cik, metric, top_n=24) or [])
    for alt in alt_tags:
        if not alt or alt == metric:
            continue
        arows = get_rows(cik, alt)
        arows = filter_rows_for_metric(metric, entries_since_2014(arows))
        ak = latest_by_fy_for_form(arows, "10-K")
        aq = latest_by_fy_for_form(arows, "10-Q")
        if ak or aq:
            return {
                "10-K": {fy: to_fact(alt, r) for fy, r in ak.items()},
                "10-Q": {fy: to_fact(alt, r) for fy, r in aq.items()},
            }

    # 3) nothing found
    return {"10-K": {}, "10-Q": {}}

def pick_chosen(forms_map: Dict[str, Dict[int, Dict[str, Any]]], fy: int) -> Optional[Dict[str, Any]]:
    # prefer 10-K, else 10-Q (latest already picked)
    if fy in forms_map.get("10-K", {}):
        f = forms_map["10-K"][fy].copy()
        f["source"] = "primary_or_alt"
        return f
    if fy in forms_map.get("10-Q", {}):
        f = forms_map["10-Q"][fy].copy()
        f["source"] = "primary_or_alt"
        return f
    return None

# ───────────── main ─────────────
def main():
    ticker2cik = load_cik_map()
    for tkr in TICKERS:
        cik = ticker2cik.get(tkr.upper())
        if not cik:
            print(f"CIK not found for {tkr}")
            continue

        print(f"\n▶ {tkr} (CIK {cik})")
        data = {"ticker": tkr, "cik": cik, "financials_by_fy": {}}

        # collect per metric the maps of 10-K/10-Q
        per_metric_forms: Dict[str, Dict[str, Dict[int, Dict[str, Any]]]] = {}
        for metric in BASE_METRICS:
            per_metric_forms[metric] = get_metric_forms_per_fy(cik, metric)

        # full FY set
        all_fys = set()
        for metric in BASE_METRICS:
            km = per_metric_forms[metric]["10-K"].keys()
            qm = per_metric_forms[metric]["10-Q"].keys()
            all_fys.update(km)
            all_fys.update(qm)
        all_fys = sorted(all_fys)

        # build rows per FY
        for fy in all_fys:
            fy_row: Dict[str, Any] = {}
            for metric in BASE_METRICS:
                forms_map = per_metric_forms[metric]
                chosen = pick_chosen(forms_map, fy)

                # carry if needed
                if not chosen and ALLOW_CARRY:
                    near = nearest_fy_with(forms_map, fy)
                    if near is not None:
                        # use whichever form exists at near FY (prefer 10-K)
                        c2 = pick_chosen(forms_map, near)
                        if c2:
                            c2 = c2.copy()
                            c2["carry_from_fy"] = int(near)
                            chosen = c2

                # minimal duplication: store both forms under "forms", chosen is a pointer
                fy_row[metric] = {
                    "chosen": ({"tag": chosen["tag"], "form": chosen["form"], "fy": chosen["fy"],
                                "value": chosen["value"], "unit": chosen["unit"],
                                "source": chosen.get("source"), **({"carry_from_fy": chosen["carry_from_fy"]} if "carry_from_fy" in chosen else {})}
                               if chosen else None),
                    "forms": {
                        "10-K": (forms_map["10-K"].get(fy) or None),
                        "10-Q": (forms_map["10-Q"].get(fy) or None),
                    }
                }

            # derive FCF if possible
            ocf = (fy_row.get("NetCashProvidedByUsedInOperatingActivities") or {}).get("chosen")
            capex = (fy_row.get("PaymentsToAcquirePropertyPlantAndEquipment") or {}).get("chosen")
            derived = {"value": None, "unit": "USD", "formula": "OCF - abs(CapEx)", "source": "derived"}
            if ocf and isinstance(ocf.get("value"), (int, float)) and capex and isinstance(capex.get("value"), (int, float)):
                derived["value"] = ocf["value"] - abs(capex["value"])
            fy_row["FreeCashFlow"] = {"chosen": derived}

            data["financials_by_fy"][str(fy)] = fy_row

        out_path = os.path.join(DATA_DIR, f"{tkr}.json")
        with open(out_path, "w") as fp:
            json.dump(data, fp, indent=2)
        print(f"  ↳ saved: {out_path}")

    print("\n✅ Completed.")

if __name__ == "__main__":
    main()
