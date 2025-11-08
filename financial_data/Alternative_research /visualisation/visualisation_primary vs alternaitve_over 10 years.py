# pip install plotly pandas

import json
from pathlib import Path
from collections import defaultdict
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --------------------------------
# Config (two default data dirs)
# --------------------------------
DATA_DIRS = [
    Path("//financial_data/Alternative_research /financial_data_2")
]
TITLE       = "All Companies — Tag Coverage by Fiscal Year — Primary vs Alternative"
OUTPUT_HTML = "tag_coverage_all_companies.html"
RECURSIVE   = False
COL_WIDTHS  = [0.78, 0.22]
HSPACE      = 0.03

def find_json_files(dirs, recursive=False):
    files = []
    for d in dirs:
        if not d.exists():
            print(f"[WARN] Directory not found: {d}")
            continue
        files.extend(sorted((d.rglob("*.json") if recursive else d.glob("*.json"))))
    return [p for p in files if p.is_file()]

def aggregate_counts_for_one(financials):
    """Return per-file counts by year (primary/alt) and set of years covered."""
    primary_count = defaultdict(int)
    alt_count     = defaultdict(int)
    seen_year_metric = set()
    years_covered = set()

    for period, metrics in (financials or {}).items():
        if not isinstance(metrics, dict):
            continue
        for metric, payload in metrics.items():
            if not isinstance(payload, dict):
                continue
            primary = payload.get("primary")
            alts    = payload.get("alternatives", [])

            chosen = None
            used = None
            if isinstance(primary, dict) and primary.get("fp") == "FY" and primary.get("fy") is not None:
                chosen = primary
                used = "primary"
            else:
                alt = next((a for a in alts if isinstance(a, dict) and a.get("fp") == "FY" and a.get("fy") is not None), None)
                if alt:
                    chosen = alt
                    used = "alternative"

            if not chosen:
                continue

            try:
                year = int(chosen["fy"])
            except Exception:
                continue

            key = (year, metric)
            if key in seen_year_metric:
                continue
            seen_year_metric.add(key)
            years_covered.add(year)

            if used == "primary":
                primary_count[year] += 1
            else:
                alt_count[year] += 1

    return primary_count, alt_count, years_covered

def combine_all(files):
    """Aggregate across all companies into a single df + helper stats."""
    total_primary = defaultdict(int)
    total_alt     = defaultdict(int)
    companies_per_year = defaultdict(int)  # how many companies contributed for each year

    for p in files:
        try:
            with p.open("r") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[ERROR] {p}: {e}")
            continue

        fin = data.get("financials")
        if not isinstance(fin, dict):
            print(f"[WARN] Missing/invalid 'financials' in {p}")
            continue

        pc, ac, years_covered = aggregate_counts_for_one(fin)

        # sum counts
        for y, v in pc.items():
            total_primary[y] += v
        for y, v in ac.items():
            total_alt[y] += v

        # increment company coverage per year
        for y in years_covered:
            companies_per_year[y] += 1

    years = sorted(set(total_primary.keys()) | set(total_alt.keys()))
    df = pd.DataFrame({
        "year": years,
        "primary": [total_primary.get(y, 0) for y in years],
        "alternative": [total_alt.get(y, 0) for y in years],
        "companies": [companies_per_year.get(y, 0) for y in years],
    })
    df["total"] = df["primary"] + df["alternative"]

    def ap_ratio_row(row):
        p, a = row["primary"], row["alternative"]
        if p == 0:
            return None if a == 0 else float("inf")
        return a / p

    df["ratio_ap"] = df.apply(ap_ratio_row, axis=1)
    return df

def fmt_ratio(r):
    if r is None:
        return "A/P = 0.00"
    if r == float("inf"):
        return "A/P = ∞"
    return f"A/P = {r:.2f}"

def fmt_ap_overall(r):
    if r is None:
        return "A/P\n0.00"
    if r == float("inf"):
        return "A/P\n∞"
    return f"A/P\n{r:.2f}"

def build_figure(df):
    labels_for_bars = [fmt_ratio(r) for r in df["ratio_ap"]]

    total_primary = int(df["primary"].sum())
    total_alt     = int(df["alternative"].sum())
    ap_overall = None if (total_primary == 0 and total_alt == 0) else (float("inf") if total_primary == 0 else total_alt / total_primary)

    fig = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "xy"}, {"type": "domain"}]],
        column_widths=COL_WIDTHS,
        horizontal_spacing=HSPACE,
        subplot_titles=[None, "Overall (All Companies, All Years)"]
    )

    # Bars (grouped): primary + alternative
    fig.add_trace(
        go.Bar(
            name="Primary",
            x=df["year"], y=df["primary"],
            text=labels_for_bars, textposition="outside",
            hovertemplate="Year=%{x}<br>Primary=%{y}<br>Total=%{customdata[0]}<br>Companies=%{customdata[1]}<br>A/P=%{customdata[2]}<extra></extra>",
            customdata=list(zip(df["total"], df["companies"], [fmt_ratio(r) for r in df["ratio_ap"]])),
            cliponaxis=False
        ),
        row=1, col=1
    )
    fig.add_trace(
        go.Bar(
            name="Alternative",
            x=df["year"], y=df["alternative"],
            text=labels_for_bars, textposition="outside",
            hovertemplate="Year=%{x}<br>Alternative=%{y}<br>Total=%{customdata[0]}<br>Companies=%{customdata[1]}<br>A/P=%{customdata[2]}<extra></extra>",
            customdata=list(zip(df["total"], df["companies"], [fmt_ratio(r) for r in df["ratio_ap"]])),
            cliponaxis=False
        ),
        row=1, col=1
    )

    # Donut (overall)
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

    # Center A/P annotation using pie's domain
    pie = fig.data[-1]
    try:
        xc = (pie.domain.x[0] + pie.domain.x[1]) / 2
        yc = (pie.domain.y[0] + pie.domain.y[1]) / 2
    except Exception:
        x0 = COL_WIDTHS[0] + HSPACE
        xc = x0 + COL_WIDTHS[1] / 2.0
        yc = 0.5

    fig.add_annotation(
        x=xc, y=yc, xref="paper", yref="paper",
        text=fmt_ap_overall(ap_overall).replace("\n", "<br>"),
        showarrow=False, font=dict(size=13)
    )

    fig.update_layout(
        title=TITLE,
        barmode="group",
        xaxis_title="Fiscal Year",
        yaxis_title="# of tags (sum across companies)",
        xaxis=dict(dtick=1),
        legend_title_text="Tag Source",
        legend=dict(orientation="h", x=0.0, y=0.99),
        margin=dict(l=50, r=40, t=110, b=50),
        template="plotly_white",
    )

    fig.update_yaxes(automargin=True, row=1, col=1)
    return fig

if __name__ == "__main__":
    files = find_json_files(DATA_DIRS, recursive=RECURSIVE)
    if not files:
        print("[WARN] No JSON files found in the configured directories.")
    else:
        print(f"[INFO] Found {len(files)} JSON files — aggregating…")
        df_all = combine_all(files)
        if df_all.empty:
            print("[INFO] No FY entries found across files.")
        else:
            fig = build_figure(df_all)
            fig.write_html(OUTPUT_HTML, include_plotlyjs="cdn")
            print(f"[OK] Wrote {OUTPUT_HTML}")
            # fig.show()  # uncomment if you want the live window
