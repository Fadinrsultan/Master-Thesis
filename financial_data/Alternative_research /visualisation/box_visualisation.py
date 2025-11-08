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
    Path("//financial_data/Alternative_research /financial_data_2")
]
RECURSIVE      = False          # set True if JSONs in subfolders
EXPECTED_NCOS  = 101            # for sanity check only (not used in calc)
PLOT_KIND      = "box"          # "box" or "violin"
OUTPUT_HTML    = f"primary_share_by_year_{PLOT_KIND}.html"
TITLE          = "Primary Share by Year — Distribution Across Companies (FY only)"

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

def choose_fy_kind(payload):
    """
    Return ('primary'|'alternative', year) if FY is present; else None.
    Prefers primary; otherwise first FY alternative found.
    """
    if not isinstance(payload, dict):
        return None
    primary = payload.get("primary")
    alts    = payload.get("alternatives", [])
    if isinstance(primary, dict) and primary.get("fp") == "FY" and primary.get("fy") is not None:
        return "primary", int(primary["fy"])
    for a in alts:
        if isinstance(a, dict) and a.get("fp") == "FY" and a.get("fy") is not None:
            return "alternative", int(a["fy"])
    return None

# ============
# Aggregate: per (company, year) counts for primary/alt
# ============
files = find_json_files(DATA_DIRS, recursive=RECURSIVE)
if not files:
    raise SystemExit("[WARN] No JSON files found in the configured directories.")

# We'll produce a mapping: (ticker, year) -> dict(primary=count, alt=count)
per_cy_primary = defaultdict(int)
per_cy_alt     = defaultdict(int)

all_tickers = set()
all_years   = set()

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

    # De-duplicate once per (company, tag, year)
    seen_year_tag = set()

    for _period, metrics in financials.items():
        if not isinstance(metrics, dict):
            continue
        for tag, payload in metrics.items():
            res = choose_fy_kind(payload)
            if not res:
                continue
            kind, year = res
            key = (year, tag)
            if key in seen_year_tag:
                continue
            seen_year_tag.add(key)
            all_years.add(year)

            cy = (ticker, year)
            if kind == "primary":
                per_cy_primary[cy] += 1
            else:
                per_cy_alt[cy] += 1

# Sanity check on company count
n_companies_found = len(all_tickers)
if n_companies_found != EXPECTED_NCOS:
    print(f"[WARN] Companies found: {n_companies_found} (expected {EXPECTED_NCOS}).")

if not all_years:
    raise SystemExit("[INFO] No FY entries found across files.")

# ============
# Build dataframe: one row per (company, year)
# ============
rows = []
for (ticker, year) in set(list(per_cy_primary.keys()) + list(per_cy_alt.keys())):
    p = per_cy_primary.get((ticker, year), 0)
    a = per_cy_alt.get((ticker, year), 0)
    total = p + a
    p_share = np.nan if total == 0 else p / total
    rows.append({
        "ticker": ticker,
        "year": int(year),
        "primary_year": int(p),
        "alt_year": int(a),
        "total_year": int(total),
        "primary_share": p_share,
    })

if not rows:
    raise SystemExit("[INFO] No per-company/year records to plot.")

df = pd.DataFrame(rows)
# Optional: drop rows where total_year == 0 (shouldn't exist due to NaN guard)
df = df[df["total_year"] > 0].copy()

# Sort years for consistent x order
years_sorted = sorted(df["year"].unique())

# ============
# Plot: Box or Violin per Year
# ============
traces = []
for y in years_sorted:
    series = df.loc[df["year"] == y, "primary_share"]
    # skip empty years defensively
    if series.empty:
        continue
    name = str(y)
    if PLOT_KIND.lower() == "violin":
        traces.append(go.Violin(
            y=series,
            name=name,
            box_visible=True,
            meanline_visible=True,
            points="outliers",
            hovertemplate="Year=" + name + "<br>Primary share=%{y:.2f}<extra></extra>"
        ))
    else:
        # default: box
        traces.append(go.Box(
            y=series,
            name=name,
            boxmean=True,
            hovertemplate="Year=" + name + "<br>Primary share=%{y:.2f}<extra></extra>"
        ))

fig = go.Figure(data=traces)
fig.update_layout(
    title=TITLE,
    yaxis_title="Primary share (Primary / (Primary + Alternative))",
    xaxis_title="Fiscal Year",
    template="plotly_white",
    margin=dict(l=70, r=20, t=80, b=60),
    showlegend=False,
    yaxis=dict(range=[0, 1], tickformat=".0%"),  # keep 0..1; or remove range to auto
)

# Save
fig.write_html(OUTPUT_HTML, include_plotlyjs="cdn")
print(f"[OK] Wrote {OUTPUT_HTML}")
print(f"[INFO] Years: {len(years_sorted)}; Company-year rows: {len(df)}; Plot type: {PLOT_KIND}")
