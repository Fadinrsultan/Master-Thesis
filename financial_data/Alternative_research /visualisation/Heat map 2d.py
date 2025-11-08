# pip install plotly pandas

import json
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# ============
# Config
# ============
DATA_DIRS = [
    Path("//financial_data/Alternative_research /financial_data_2")
]
EXPECTED_NCOS = 101           # denominator for % coverage (as requested)
RECURSIVE     = False         # set True if JSONs in subfolders
TOP_N_TAGS    = 50            # None to include all tags (can be very tall)
OUTPUT_HTML   = "heatmap_tag_year_coverage.html"
TITLE         = "Coverage: % of Companies (out of 101) Reporting Tag × Year (FY; Primary or Alternative)"

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

def choose_fy(payload):
    """
    Return (year) if the entry has FY (primary preferred, else first FY alternative), else None.
    We only need the year to credit coverage for this (company, tag, year).
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
# Aggregate
# ============
files = find_json_files(DATA_DIRS, recursive=RECURSIVE)
if not files:
    raise SystemExit("[WARN] No JSON files found in the configured directories.")

pair_to_companies = defaultdict(set)  # (tag, year) -> set of tickers having FY for that tag
all_tickers = set()
all_tags_counter = Counter()

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

    # De-duplicate per (year, tag) for this company
    seen_year_tag = set()

    for _period, metrics in financials.items():
        if not isinstance(metrics, dict):
            continue
        for tag, payload in metrics.items():
            year = choose_fy(payload)
            if year is None:
                continue
            key = (year, tag)
            if key in seen_year_tag:
                continue
            seen_year_tag.add(key)
            pair_to_companies[(tag, year)].add(ticker)
            all_tags_counter[tag] += 1

n_companies_found = len(all_tickers)
if n_companies_found != EXPECTED_NCOS:
    print(f"[WARN] Companies found: {n_companies_found} (expected {EXPECTED_NCOS}). "
          f"Percentages still use 101 as denominator per your spec.")

# Build dataframe with counts per (tag, year)
records = []
years = sorted({y for (_tag, y) in { (t, y) for (t, y) in pair_to_companies.keys() }})
for (tag, year), comps in pair_to_companies.items():
    records.append({
        "tag": tag,
        "year": int(year),
        "companies_with_tag": len(comps),
        "pct": 100.0 * len(comps) / float(EXPECTED_NCOS)  # denominator fixed at 101
    })

if not records:
    raise SystemExit("[INFO] No FY entries found across files.")

df_cells = pd.DataFrame.from_records(records)

# Keep top-N tags by overall company count (sum across years) to keep the heatmap readable
if TOP_N_TAGS is not None:
    top_tags = (df_cells.groupby("tag")["companies_with_tag"]
                .sum()
                .sort_values(ascending=False)
                .head(TOP_N_TAGS)
                .index.tolist())
    df_cells = df_cells[df_cells["tag"].isin(top_tags)]

# Pivot to Tag × Year matrix (values = % companies)
pivot_pct = (df_cells
             .pivot(index="tag", columns="year", values="pct")
             .fillna(0.0))

# Sort tags by total coverage (descending) for nicer ordering
tag_order = (df_cells.groupby("tag")["companies_with_tag"]
             .sum()
             .sort_values(ascending=False)
             .index.tolist())
pivot_pct = pivot_pct.loc[tag_order]

# ============
# Plotly Heatmap
# ============
fig = go.Figure(
    data=go.Heatmap(
        z=pivot_pct.values,
        x=pivot_pct.columns.astype(str).tolist(),  # years as strings for nice ticks
        y=pivot_pct.index.tolist(),
        coloraxis="coloraxis",
        hovertemplate="Tag=%{y}<br>Year=%{x}<br>% Companies=%{z:.1f}%<extra></extra>",
    )
)

fig.update_layout(
    title=TITLE,
    coloraxis=dict(
        colorscale="Viridis",
        colorbar=dict(
            title="% Companies",
            ticksuffix="%",
        )
    ),
    xaxis=dict(title="Fiscal Year", tickmode="array", tickvals=[str(c) for c in pivot_pct.columns.tolist()]),
    yaxis=dict(title="Tag"),
    template="plotly_white",
    margin=dict(l=80, r=20, t=80, b=60),
    width=1100,
    height=max(500, 24 * len(pivot_pct.index))  # dynamic height so labels remain readable
)

# Save interactive HTML
fig.write_html(OUTPUT_HTML, include_plotlyjs="cdn")
print(f"[OK] Wrote {OUTPUT_HTML}")
print(f"[INFO] Heatmap shape: {pivot_pct.shape[0]} tags × {pivot_pct.shape[1]} years")
