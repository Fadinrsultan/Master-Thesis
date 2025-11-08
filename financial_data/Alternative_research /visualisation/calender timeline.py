# pip install plotly pandas

import json
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# ============
# Config
# ============
DATA_DIRS = [
    Path("//financial_data/Alternative_research /financial_data_2"),

]
RECURSIVE        = False         # set True if JSONs are in subfolders
EXPECTED_NCOS    = 101           # sanity check (not used in calc unless PERCENT=True)
OUTPUT_HTML      = "yearly_coverage_count.html"
TITLE            = "Yearly Coverage — # Companies with ≥1 FY Tag"
PERCENT          = False         # if True, plot % of 101 instead of raw count

# ============
# Helpers
# ============
def find_json_files(dirs, recursive=False):
    files = []
    for d in dirs:
        if not d.exists():
            print(f"[WARN] Directory not found: {d}")
            continue
        files.extend(sorted((d.rglob("*.json") if recursive else d.glob("*.json"))))
    return [p for p in files if p.is_file()]

def infer_ticker(json_obj, path: Path):
    if isinstance(json_obj, dict):
        t = json_obj.get("ticker") or json_obj.get("symbol") or json_obj.get("companyTicker")
        if t:
            return str(t).upper()
    return path.stem.upper()

def choose_fy_year(payload):
    """
    Return the FY year if present (prefers primary, else first FY alternative), else None.
    """
    if not isinstance(payload, dict):
        return None
    primary = payload.get("primary")
    alts    = payload.get("alternatives", [])
    if isinstance(primary, dict) and primary.get("fp") == "FY" and primary.get("fy") is not None:
        return int(primary["fy"])
    for a in alts:
        if isinstance(a, dict) and a.get("fp") == "FY" and a.get("fy") is not None:
            return int(a["fy"])
    return None

# ============
# Aggregate: for each year, the set of companies with ≥1 FY tag
# ============
files = find_json_files(DATA_DIRS, recursive=RECURSIVE)
if not files:
    raise SystemExit("[WARN] No JSON files found in the configured directories.")

year_to_companies = defaultdict(set)  # year -> set(ticker)
all_tickers = set()

for p in files:
    try:
        with p.open("r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ERROR] {p}: {e}")
        continue

    ticker = infer_ticker(data, p)
    all_tickers.add(ticker)

    financials = data.get("financials")
    if not isinstance(financials, dict):
        print(f"[WARN] Missing/invalid 'financials' in {p}")
        continue

    # For each company, ensure we don't overcount tags within the same year:
    seen_year = set()

    for _period, metrics in financials.items():
        if not isinstance(metrics, dict):
            continue
        for _tag, payload in metrics.items():
            year = choose_fy_year(payload)
            if year is None:
                continue
            if year in seen_year:
                continue
            seen_year.add(year)
            year_to_companies[year].add(ticker)

n_companies_found = len(all_tickers)
if n_companies_found != EXPECTED_NCOS:
    print(f"[WARN] Companies found: {n_companies_found} (expected {EXPECTED_NCOS}).")

if not year_to_companies:
    raise SystemExit("[INFO] No FY entries found across files.")

# ============
# Build series and plot
# ============
years_sorted = sorted(year_to_companies.keys())
counts = [len(year_to_companies[y]) for y in years_sorted]

if PERCENT:
    y_values = [100.0 * c / float(EXPECTED_NCOS) for c in counts]
    y_title = "% of companies (out of 101)"
else:
    y_values = counts
    y_title = "# of companies"

fig = go.Figure(
    data=go.Scatter(
        x=years_sorted,
        y=y_values,
        mode="lines+markers",
        hovertemplate=("Year=%{x}<br>" + ("Coverage=%{y:.1f}%<extra></extra>" if PERCENT
                                          else "Coverage=%{y:d}<extra></extra>"))
    )
)

fig.update_layout(
    title=TITLE,
    xaxis_title="Fiscal Year",
    yaxis_title=y_title,
    template="plotly_white",
    margin=dict(l=70, r=20, t=80, b=60),
)

# Save interactive HTML
fig.write_html(OUTPUT_HTML, include_plotlyjs="cdn")
print(f"[OK] Wrote {OUTPUT_HTML}")
print(f"[INFO] Years plotted: {len(years_sorted)}; First–Last: {years_sorted[0]}–{years_sorted[-1]}")
