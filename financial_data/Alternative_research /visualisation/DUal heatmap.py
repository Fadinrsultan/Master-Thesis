# pip install plotly pandas

import json
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============
# Config
# ============
DATA_DIRS = [
    Path("//financial_data/Alternative_research /financial_data_2")
]
EXPECTED_NCOS = 101            # denominator for % coverage (per your spec)
RECURSIVE     = False          # set True if JSONs in subfolders
TOP_N_TAGS    = 50             # None to include all tags (can be tall)
OUTPUT_HTML   = "heatmap_primary_vs_alternative_share.html"
TITLE         = "Primary vs Alternative Share — % of Companies (out of 101) by Tag × Year (FY)"

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

def years_from_pairs(dct):
    """Extract a set of years from dict keyed by (tag, year)."""
    return {year for (_tag, year) in dct.keys()}

# ============
# Aggregate
# ============
files = find_json_files(DATA_DIRS, recursive=RECURSIVE)
if not files:
    raise SystemExit("[WARN] No JSON files found in the configured directories.")

all_tickers = set()
# sets of companies per (tag, year)
primary_sets     = defaultdict(set)   # (tag, year) -> set(ticker)
alternative_sets = defaultdict(set)   # (tag, year) -> set(ticker)

# also track overall tag popularity to pick top-N tags
tag_popularity = Counter()

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

            if kind == "primary":
                primary_sets[(tag, year)].add(ticker)
            else:
                alternative_sets[(tag, year)].add(ticker)

            tag_popularity[tag] += 1  # for top-N filtering

n_companies_found = len(all_tickers)
if n_companies_found != EXPECTED_NCOS:
    print(f"[WARN] Companies found: {n_companies_found} (expected {EXPECTED_NCOS}). "
          f"Percentages still use 101 as denominator per your spec.")

# ===== FIXED: build 'all_years' correctly using set union =====
all_years = sorted(years_from_pairs(primary_sets) | years_from_pairs(alternative_sets))
if not all_years:
    raise SystemExit("[INFO] No FY entries found across files.")

# Tag selection (top-N tags by overall popularity to keep the figure readable)
if TOP_N_TAGS is not None:
    chosen_tags = [t for t, _ in tag_popularity.most_common(TOP_N_TAGS)]
else:
    chosen_tags = sorted(tag_popularity.keys())

if not chosen_tags:
    raise SystemExit("[INFO] No tags found to plot.")

# Build matrices (rows=tags, cols=years)
years_idx = {y: i for i, y in enumerate(all_years)}
tags_idx  = {t: i for i, t in enumerate(chosen_tags)}

P = np.zeros((len(chosen_tags), len(all_years)), dtype=float)  # primary %
A = np.zeros((len(chosen_tags), len(all_years)), dtype=float)  # alternative %

for (tag, year), comps in primary_sets.items():
    if tag in tags_idx and year in years_idx:
        P[tags_idx[tag], years_idx[year]] = 100.0 * len(comps) / float(EXPECTED_NCOS)

for (tag, year), comps in alternative_sets.items():
    if tag in tags_idx and year in years_idx:
        A[tags_idx[tag], years_idx[year]] = 100.0 * len(comps) / float(EXPECTED_NCOS)

# Order tags (rows) by total coverage (primary+alternative) descending
totals = (P + A).sum(axis=1)
order = np.argsort(-totals)
P = P[order, :]
A = A[order, :]
ordered_tags = [chosen_tags[i] for i in order]

# ============
# Plotly Dual Heatmaps
# ============
fig = make_subplots(
    rows=1, cols=2,
    specs=[[{"type": "heatmap"}, {"type": "heatmap"}]],
    shared_yaxes=True,
    horizontal_spacing=0.08,
    subplot_titles=("Primary share (% of 101)", "Alternative share (% of 101)")
)

# use the same color scale/range for easy comparison
coloraxis_common = dict(colorscale="Viridis", cmin=0, cmax=100,
                        colorbar=dict(title="% Companies", ticksuffix="%"))

fig.add_trace(
    go.Heatmap(
        z=P,
        x=[str(y) for y in all_years],
        y=ordered_tags,
        coloraxis="coloraxis",
        hovertemplate="Tag=%{y}<br>Year=%{x}<br>Primary=%{z:.1f}%<extra></extra>",
    ),
    row=1, col=1
)

fig.add_trace(
    go.Heatmap(
        z=A,
        x=[str(y) for y in all_years],
        y=ordered_tags,
        coloraxis="coloraxis",
        hovertemplate="Tag=%{y}<br>Year=%{x}<br>Alternative=%{z:.1f}%<extra></extra>",
    ),
    row=1, col=2
)

fig.update_layout(
    title=TITLE,
    coloraxis=coloraxis_common,   # shared scale 0–100%
    xaxis=dict(title="Fiscal Year"),
    xaxis2=dict(title="Fiscal Year"),
    yaxis=dict(title="Tag"),
    template="plotly_white",
    margin=dict(l=90, r=40, t=90, b=60),
    width=1200,
    height=max(550, 24 * len(ordered_tags))
)

# Save interactive HTML
fig.write_html(OUTPUT_HTML, include_plotlyjs="cdn")
print(f"[OK] Wrote {OUTPUT_HTML}")
print(f"[INFO] Heatmap size: {len(ordered_tags)} tags × {len(all_years)} years (two panels)")
