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
TITLE         = "All Companies — Primary vs Alternative Tag Coverage (Aggregated Over All Years)"
OUTPUT_HTML   = "tag_coverage_by_company_all_years.html"
RECURSIVE     = False
EXPECTED_NCOS = 101     # you said there should be 101 companies
COL_WIDTHS    = [0.78, 0.22]
HSPACE        = 0.03

# Sort options: 'total' or 'ticker'
SORT_BY       = "total"
ASCENDING     = False

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

def aggregate_counts_one_company(financials):
    """
    Return total primary/alternative counts across ALL years for a single company.
    Deduplicate by (year, metric) exactly once per company.
    """
    primary_count_by_year = defaultdict(int)
    alt_count_by_year     = defaultdict(int)
    seen_year_metric = set()

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

            if used == "primary":
                primary_count_by_year[year] += 1
            else:
                alt_count_by_year[year] += 1

    total_primary = sum(primary_count_by_year.values())
    total_alt     = sum(alt_count_by_year.values())
    return total_primary, total_alt

def combine_all(files):
    rows = []
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

        primary_total, alt_total = aggregate_counts_one_company(fin)
        # if a company has zero counts overall, we still include it (but you can skip if desired)
        ticker = infer_ticker(data, p)
        rows.append({"ticker": ticker, "primary": primary_total, "alternative": alt_total})

    if not rows:
        return pd.DataFrame(columns=["ticker", "primary", "alternative", "total", "ratio_ap"])

    df = pd.DataFrame(rows)
    df["total"] = df["primary"] + df["alternative"]

    def ap_ratio_row(row):
        p, a = row["primary"], row["alternative"]
        if p == 0:
            return None if a == 0 else float("inf")
        return a / p

    df["ratio_ap"] = df.apply(ap_ratio_row, axis=1)

    # sort
    if SORT_BY == "ticker":
        df = df.sort_values("ticker", ascending=True)
    else:
        df = df.sort_values("total", ascending=ASCENDING)

    return df.reset_index(drop=True)

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
    # Overall totals for donut
    total_primary = int(df["primary"].sum())
    total_alt     = int(df["alternative"].sum())
    ap_overall = None if (total_primary == 0 and total_alt == 0) else (float("inf") if total_primary == 0 else total_alt / total_primary)

    # Dynamic width so 101 companies don’t squash labels
    base_width = 1000
    per_company = 25   # pixels per company
    fig_width = max(base_width, per_company * max(1, len(df)))

    fig = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "xy"}, {"type": "domain"}]],
        column_widths=COL_WIDTHS,
        horizontal_spacing=HSPACE,
        subplot_titles=[None, "Overall (All Companies, All Years)"]
    )

    # Bars: two bars per company
    x_vals = df["ticker"]
    custom_ap = [fmt_ratio(r) for r in df["ratio_ap"]]

    fig.add_trace(
        go.Bar(
            name="Primary",
            x=x_vals, y=df["primary"],
            hovertemplate="Company=%{x}<br>Primary=%{y}<br>Total=%{customdata[0]}<br>A/P=%{customdata[1]}<extra></extra>",
            customdata=list(zip(df["total"], custom_ap)),
            # No text labels to avoid clutter for 101 companies
            cliponaxis=False
        ),
        row=1, col=1
    )

    fig.add_trace(
        go.Bar(
            name="Alternative",
            x=x_vals, y=df["alternative"],
            hovertemplate="Company=%{x}<br>Alternative=%{y}<br>Total=%{customdata[0]}<br>A/P=%{customdata[1]}<extra></extra>",
            customdata=list(zip(df["total"], custom_ap)),
            cliponaxis=False
        ),
        row=1, col=1
    )

    # Donut
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

    # Center A/P annotation using the pie's domain
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
        xaxis_title="Company",
        yaxis_title="# of tags (all years)",
        xaxis=dict(tickangle=60, automargin=True),
        legend_title_text="Tag Source",
        legend=dict(orientation="h", x=0.0, y=0.99),
        margin=dict(l=50, r=40, t=110, b=80),
        template="plotly_white",
        width=fig_width
    )

    fig.update_yaxes(automargin=True, row=1, col=1)
    return fig

# --------------------------------
# Main
# --------------------------------
if __name__ == "__main__":
    files = find_json_files(DATA_DIRS, recursive=RECURSIVE)
    if not files:
        print("[WARN] No JSON files found in the configured directories.")
    else:
        print(f"[INFO] Found {len(files)} JSON files — aggregating per company over all years…")
        df_companies = combine_all(files)

        # Basic sanity check for company count
        n_companies = df_companies["ticker"].nunique()
        if n_companies != EXPECTED_NCOS:
            print(f"[WARN] Companies found: {n_companies} (expected {EXPECTED_NCOS})")

        if df_companies.empty:
            print("[INFO] No FY entries found across files.")
        else:
            fig = build_figure(df_companies)
            fig.write_html(OUTPUT_HTML, include_plotlyjs="cdn")
            print(f"[OK] Wrote {OUTPUT_HTML}")
            # fig.show()  # optional
