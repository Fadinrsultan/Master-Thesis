# pip install plotly pandas

import json
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --------------------------------
# Config
# --------------------------------
DATA_DIRS = [
    Path("//financial_data/Alternative_research /financial_data_2")
]
EXPECTED_NCOS = 101
TOP_N_TAGS    = 20
RECURSIVE     = False

TITLE_3D  = "Top 20 Tags — # of Companies by Year (Primary vs Alternative)"
TITLE_PIE = "Overall (All Companies, All Years)"

# --------------------------------
# Helpers
# --------------------------------
def find_json_files(dirs, recursive=False):
    files = []
    for d in dirs:
        if not d.exists():
            print(f"[WARN] Directory not found: {d}")
            continue
        files.extend(sorted((d.rglob("*.json") if recursive else d.glob("*.json"))))
    return [p for p in files if p.is_file()]

def infer_ticker(json_obj, path: Path):
    t = None
    if isinstance(json_obj, dict):
        t = json_obj.get("ticker") or json_obj.get("symbol") or json_obj.get("companyTicker")
    return (t or path.stem).upper()

def choose_entry(payload):
    """Return ('primary'|'alternative', year, metric) if FY is present; else None."""
    if not isinstance(payload, dict):
        return None
    primary = payload.get("primary")
    alts    = payload.get("alternatives", [])
    if isinstance(primary, dict) and primary.get("fp") == "FY" and primary.get("fy") is not None:
        return "primary", int(primary["fy"])
    alt = next((a for a in alts if isinstance(a, dict) and a.get("fp") == "FY" and a.get("fy") is not None), None)
    if alt:
        return "alternative", int(alt["fy"])
    return None

# --------------------------------
# Parse & aggregate
# --------------------------------
files = find_json_files(DATA_DIRS, recursive=RECURSIVE)
if not files:
    raise SystemExit("[WARN] No JSON files found in the configured directories.")

company_ids = set()
# counts per (year, tag) -> #companies for primary/alternative
primary_counts = defaultdict(set)     # (year, tag) -> set of company ids
alternative_counts = defaultdict(set) # (year, tag) -> set of company ids
# for selecting top tags
tag_total_counter = Counter()         # tag -> total occurrences (primary+alt across years & companies)

for p in files:
    try:
        with p.open("r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ERROR] {p}: {e}")
        continue

    ticker = infer_ticker(data, p)
    company_ids.add(ticker)

    fin = data.get("financials")
    if not isinstance(fin, dict):
        print(f"[WARN] Missing/invalid 'financials' in {p}")
        continue

    # Deduplicate per (year, metric) per company
    seen_year_metric = set()

    for period, metrics in fin.items():
        if not isinstance(metrics, dict):
            continue
        for metric, payload in metrics.items():
            chosen = choose_entry(payload)
            if not chosen:
                continue
            used, year = chosen
            key = (year, metric)
            if key in seen_year_metric:
                continue
            seen_year_metric.add(key)

            # record counts per (year, tag)
            if used == "primary":
                primary_counts[(year, metric)].add(ticker)
            else:
                alternative_counts[(year, metric)].add(ticker)

            # for top-20 selection
            tag_total_counter[metric] += 1

# sanity on company count
n_companies = len(company_ids)
if n_companies != EXPECTED_NCOS:
    print(f"[WARN] Companies found: {n_companies} (expected {EXPECTED_NCOS})")

# years present
years = sorted(set(y for (y, _t) in (set(primary_counts.keys()) | set(alternative_counts.keys()))))
if not years:
    raise SystemExit("[INFO] No FY entries found across files.")

# pick top N tags
top_tags = [t for t, _ in tag_total_counter.most_common(TOP_N_TAGS)]
if not top_tags:
    raise SystemExit("[INFO] No tags found to plot.")

# Build Z matrices:
# axes: x = tag index (0..TOP_N_TAGS-1), y = year index (0..len(years)-1)
tag_to_idx = {t: i for i, t in enumerate(top_tags)}
year_to_idx = {y: i for i, y in enumerate(years)}

Z_primary = np.zeros((len(years), len(top_tags)), dtype=int)
Z_alt     = np.zeros((len(years), len(top_tags)), dtype=int)

for (y, tag), comps in primary_counts.items():
    if tag in tag_to_idx and y in year_to_idx:
        Z_primary[year_to_idx[y], tag_to_idx[tag]] = len(comps)
for (y, tag), comps in alternative_counts.items():
    if tag in tag_to_idx and y in year_to_idx:
        Z_alt[year_to_idx[y], tag_to_idx[tag]] = len(comps)

# Overall totals for donut
total_primary = int(Z_primary.sum())
total_alt     = int(Z_alt.sum())

def fmt_ap_overall(tp, ta):
    if tp == 0 and ta == 0:
        return "A/P\n0.00"
    if tp == 0:
        return "A/P\n∞"
    return f"A/P\n{ta/tp:.2f}"

# --------------------------------
# Figure: 3D surfaces + donut
# --------------------------------
fig = make_subplots(
    rows=1, cols=2,
    specs=[[{"type": "scene"}, {"type": "domain"}]],
    column_widths=[0.78, 0.22],
    horizontal_spacing=0.03,
    subplot_titles=[None, TITLE_PIE]
)

# surface coordinates
X = np.arange(len(top_tags))          # numeric indices for tags
Y = np.array(years)                   # years on Y axis (as numeric)

# We need grid shapes: use np.meshgrid
XX, YY = np.meshgrid(X, Y)            # shape: (len(years), len(tags))

# Primary surface
fig.add_trace(
    go.Surface(
        x=XX, y=YY, z=Z_primary,
        name="Primary",
        showscale=True,
        colorbar=dict(title="# Companies", x=0.45),
        hovertemplate="Tag=%{customdata[0]}<br>Year=%{y}<br>Primary Companies=%{z}<extra></extra>",
        customdata=np.dstack([[top_tags[i] for i in X] for _ in Y])
    ),
    row=1, col=1
)

# Alternative surface (slightly more transparent to compare)
fig.add_trace(
    go.Surface(
        x=XX, y=YY, z=Z_alt,
        name="Alternative",
        opacity=0.8,
        showscale=False,
        hovertemplate="Tag=%{customdata[0]}<br>Year=%{y}<br>Alternative Companies=%{z}<extra></extra>",
        customdata=np.dstack([[top_tags[i] for i in X] for _ in Y])
    ),
    row=1, col=1
)

# Axis labels and tag tick text
fig.update_scenes(
    dict(
        xaxis=dict(
            title="Tag",
            tickmode="array",
            tickvals=list(range(len(top_tags))),
            ticktext=top_tags
        ),
        yaxis=dict(title="Year"),
        zaxis=dict(title="# of companies (out of {})".format(EXPECTED_NCOS)),
        camera=dict(eye=dict(x=4, y=1.7, z=0.9))
    ),
    row=1, col=1
)

# Donut on the right
fig.add_trace(
    go.Pie(
        labels=["Primary", "Alternative"],
        values=[total_primary, total_alt],
        hole=0.55, sort=False, direction="clockwise",
        textinfo="label+percent",
        hovertemplate="%{label}<br>Count=%{value}<br>Share=%{percent}<extra>Overall</extra>",
        showlegend=False
    ),
    row=1, col=2
)

# Center A/P in donut using annotation anchored to paper coords
pie_trace = fig.data[-1]
fig.add_annotation(
    x=0.89, y=0.5, xref="paper", yref="paper",
    text=fmt_ap_overall(total_primary, total_alt).replace("\n", "<br>"),
    showarrow=False, font=dict(size=13)
)

fig.update_layout(
    title=TITLE_3D,
    margin=dict(l=40, r=40, t=80, b=40),
    template="plotly_white",
)

# Save
out_html = "tag_companies_by_year_3d_with_donut.html"
fig.write_html(out_html, include_plotlyjs="cdn")
print(f"[OK] Wrote {out_html}")
