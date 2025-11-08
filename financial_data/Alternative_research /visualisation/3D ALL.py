# pip install plotly pandas

import json
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# =========================
# Config
# =========================
DATA_DIRS = [
    Path("//financial_data/Alternative_research /financial_data_2"),

]
EXPECTED_NCOS = 101        # for %/sanity only; not strictly needed here
RECURSIVE     = False      # set True if JSONs are in subfolders
TOP_N_TAGS    = 20         # limit tags for 3D surfaces/bars (readability/performance)
OUTPUT_HTML   = "all_3d_overview.html"

TITLE_SURF    = "3D Surfaces — #Companies by Tag × Year (Primary vs Alternative)"
TITLE_BARS    = "3D Bars — #Companies by Tag × Year (Primary vs Alternative)"
TITLE_SCATTER = "3D Scatter — Company × Year × Primary Share (color = total tags)"

# =========================
# Helpers
# =========================
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
    Prefers primary; else first FY alternative.
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

def build_cuboid(xc, yc, z, dx=0.38, dy=0.38):
    """
    Build vertices & i,j,k faces for a cuboid bar centered at (xc,yc), height=z (from 0..z).
    dx,dy are half-widths along x,y. Returns dict for Mesh3d.
    Vertex order: bottom 0..3, top 4..7.
    """
    x0, x1 = xc - dx, xc + dx
    y0, y1 = yc - dy, yc + dy
    z0, z1 = 0.0, float(z)

    # 8 vertices
    xs = [x0, x1, x1, x0, x0, x1, x1, x0]
    ys = [y0, y0, y1, y1, y0, y0, y1, y1]
    zs = [z0, z0, z0, z0, z1, z1, z1, z1]

    # 12 triangular faces (2 per face × 6 faces)
    faces = [
        (0,1,2), (0,2,3),   # bottom
        (4,5,6), (4,6,7),   # top
        (0,1,5), (0,5,4),   # side x+
        (1,2,6), (1,6,5),   # side y+
        (2,3,7), (2,7,6),   # side x-
        (3,0,4), (3,4,7),   # side y-
    ]
    i, j, k = zip(*faces)
    return dict(x=xs, y=ys, z=zs, i=i, j=j, k=k)

# =========================
# Aggregate
# =========================
files = find_json_files(DATA_DIRS, recursive=RECURSIVE)
if not files:
    raise SystemExit("[WARN] No JSON files found in the configured directories.")

# sets of companies per (tag, year)
primary_sets     = defaultdict(set)  # (tag, year) -> set(ticker)
alternative_sets = defaultdict(set)  # (tag, year) -> set(ticker)

# per (company, year) counts (for primary share scatter)
per_cy_primary = defaultdict(int)
per_cy_alt     = defaultdict(int)

all_tickers = set()
tag_popularity = Counter()
all_years = set()

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

    # Deduplicate once per (company, tag, year)
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

            # sets for surfaces/bars
            if kind == "primary":
                primary_sets[(tag, year)].add(ticker)
                per_cy_primary[(ticker, year)] += 1
            else:
                alternative_sets[(tag, year)].add(ticker)
                per_cy_alt[(ticker, year)] += 1

            tag_popularity[tag] += 1

n_companies_found = len(all_tickers)
if n_companies_found != EXPECTED_NCOS:
    print(f"[WARN] Companies found: {n_companies_found} (expected {EXPECTED_NCOS}).")

if not all_years:
    raise SystemExit("[INFO] No FY entries found across files.")

years = sorted(all_years)

# Choose top-N tags for surfaces/bars to keep it readable
if TOP_N_TAGS is not None:
    tags = [t for t, _ in tag_popularity.most_common(TOP_N_TAGS)]
else:
    tags = sorted(tag_popularity.keys())

if not tags:
    raise SystemExit("[INFO] No tags found to plot.")

tag_to_idx = {t: i for i, t in enumerate(tags)}
year_to_idx = {y: i for i, y in enumerate(years)}

# Build Z matrices (years × tags) for surfaces
Zp = np.zeros((len(years), len(tags)), dtype=int)
Za = np.zeros((len(years), len(tags)), dtype=int)

for (tag, year), comps in primary_sets.items():
    if tag in tag_to_idx and year in year_to_idx:
        Zp[year_to_idx[year], tag_to_idx[tag]] = len(comps)

for (tag, year), comps in alternative_sets.items():
    if tag in tag_to_idx and year in year_to_idx:
        Za[year_to_idx[year], tag_to_idx[tag]] = len(comps)

# Build company-year table for scatter
rows = []
for (ticker, year) in set(list(per_cy_primary.keys()) + list(per_cy_alt.keys())):
    p = per_cy_primary.get((ticker, year), 0)
    a = per_cy_alt.get((ticker, year), 0)
    total = p + a
    if total == 0:
        continue
    p_share = p / total
    rows.append({"ticker": ticker, "year": year, "primary": p, "alt": a, "total": total, "p_share": p_share})

df_cy = pd.DataFrame(rows)
if df_cy.empty:
    raise SystemExit("[INFO] No per-company/year records to plot for scatter.")

# Map companies to indices for X in scatter
tickers_sorted = sorted(df_cy["ticker"].unique())
ticker_to_idx = {t: i for i, t in enumerate(tickers_sorted)}
df_cy["company_idx"] = df_cy["ticker"].map(ticker_to_idx)

# =========================
# Figure with 3 scenes (1 row × 3 cols)
# =========================
fig = make_subplots(
    rows=1, cols=3,
    specs=[[{"type": "scene"}, {"type": "scene"}, {"type": "scene"}]],
    column_widths=[0.38, 0.32, 0.30],
    horizontal_spacing=0.03,
    subplot_titles=[TITLE_SURF, TITLE_BARS, TITLE_SCATTER],
)

# ---------- (1) Surfaces ----------
# x: tag index, y: years (numeric), z: #companies
X = np.arange(len(tags))
Y = np.array(years)
XX, YY = np.meshgrid(X, Y)

fig.add_trace(
    go.Surface(
        x=XX, y=YY, z=Zp,
        name="Primary Surface",
        showscale=True,
        colorbar=dict(title="# Companies", x=0.31),
        hovertemplate="Tag=%{customdata[0]}<br>Year=%{y}<br>Primary=%{z}<extra></extra>",
        customdata=np.dstack([[tags[i] for i in X] for _ in Y])
    ),
    row=1, col=1
)

fig.add_trace(
    go.Surface(
        x=XX, y=YY, z=Za,
        name="Alternative Surface",
        opacity=0.8,
        showscale=False,
        hovertemplate="Tag=%{customdata[0]}<br>Year=%{y}<br>Alternative=%{z}<extra></extra>",
        customdata=np.dstack([[tags[i] for i in X] for _ in Y])
    ),
    row=1, col=1
)

fig.update_scenes(dict(
    xaxis=dict(title="Tag", tickmode="array", tickvals=list(range(len(tags))), ticktext=tags),
    yaxis=dict(title="Year"),
    zaxis=dict(title="# Companies"),
    camera=dict(eye=dict(x=1.8, y=1.8, z=1.0))
), row=1, col=1)

# ---------- (2) 3D Bars with Mesh3d ----------
# side-by-side bars at each (tag, year): primary (left), alternative (right)
bar_traces = []
dx = 0.18  # half-width along x for each bar
dy = 0.40  # half-width along y (year axis)
offset = 0.22  # shift between primary and alternative along x

# We'll build two Mesh3d traces (one for primary, one for alternative)
def build_mesh_for_grid(Z, label, x_shift):
    xs_all, ys_all, zs_all, i_all, j_all, k_all = [], [], [], [], [], []
    vert_offset = 0
    for yi, year in enumerate(years):
        for xi, tag in enumerate(tags):
            h = int(Z[yi, xi])
            if h <= 0:
                continue
            cub = build_cuboid(xc=xi + x_shift, yc=year, z=h, dx=dx, dy=dy)
            # append, shifting face indices
            xs_all += cub["x"]; ys_all += cub["y"]; zs_all += cub["z"]
            i_all += [v + vert_offset for v in cub["i"]]
            j_all += [v + vert_offset for v in cub["j"]]
            k_all += [v + vert_offset for v in cub["k"]]
            vert_offset += 8  # 8 vertices per cuboid
    return go.Mesh3d(
        x=xs_all, y=ys_all, z=zs_all,
        i=i_all, j=j_all, k=k_all,
        name=label,
        opacity=0.95,
        flatshading=True,
        hoverinfo="skip"  # bars are dense; rely on surfaces for precise values
    )

bars_primary = build_mesh_for_grid(Zp, "Primary Bars", x_shift=-offset)
bars_alt     = build_mesh_for_grid(Za, "Alternative Bars", x_shift=+offset)
fig.add_trace(bars_primary, row=1, col=2)
fig.add_trace(bars_alt,     row=1, col=2)

fig.update_scenes(dict(
    xaxis=dict(title="Tag", tickmode="array", tickvals=list(range(len(tags))), ticktext=tags),
    yaxis=dict(title="Year"),
    zaxis=dict(title="# Companies"),
    camera=dict(eye=dict(x=1.8, y=1.8, z=1.1))
), row=1, col=2)

# ---------- (3) 3D Scatter: Company × Year × Primary Share ----------
# Color by total tags that year; size by total (capped)
size = np.clip(4 + 1.0 * df_cy["total"], 4, 18)
fig.add_trace(
    go.Scatter3d(
        x=df_cy["company_idx"],
        y=df_cy["year"],
        z=df_cy["p_share"],
        mode="markers",
        marker=dict(
            size=size,
            color=df_cy["total"],  # color scale by total tags
            colorbar=dict(title="Total Tags", x=0.98),
            colorscale="Viridis",
            opacity=0.85
        ),
        text=df_cy["ticker"],
        hovertemplate=(
            "Company=%{text}<br>"
            "Index=%{x}<br>"
            "Year=%{y}<br>"
            "Primary share=%{z:.2f}<br>"
            "Total=%{marker.color:.0f}<extra></extra>"
        ),
        name="Company-Year"
    ),
    row=1, col=3
)

fig.update_scenes(dict(
    xaxis=dict(title="Company Index", tickmode="auto"),
    yaxis=dict(title="Year"),
    zaxis=dict(title="Primary Share (0–1)", range=[0, 1]),
    camera=dict(eye=dict(x=1.6, y=1.6, z=0.9))
), row=1, col=3)

# ---------- Layout ----------
fig.update_layout(
    title="3D Overview — Surfaces, Bars, and Company-Year Scatter",
    template="plotly_white",
    margin=dict(l=20, r=20, t=70, b=20),
    width=1800,
    height=720
)

# Save one HTML with all three 3D panels
fig.write_html(OUTPUT_HTML, include_plotlyjs="cdn")
print(f"[OK] Wrote {OUTPUT_HTML}")
print(f"[INFO] Surfaces: {len(tags)} tags × {len(years)} years; Scatter points: {len(df_cy)} company-years")
