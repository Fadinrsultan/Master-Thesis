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
    Path("//financial_data/Alternative_research /financial_data_2")]
TITLE_ALL    = "All Companies — Primary vs Alternative Tag Coverage (Aggregated Over All Years)"
OUTPUT_ALL   = "tag_coverage_by_company_all_years.html"
OUTPUT_YR_FP = "tag_coverage_by_company_{year}.html"

RECURSIVE     = False
# Expectation: set to 100 for companies or ~101 for tickers (due to dual-class)
EXPECTED_N    = 101

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

def aggregate_counts_one_company_per_year(financials):
    """
    Return per-year primary/alternative counts for a single company as:
    {year: (primary_total, alternative_total)}
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

    out = {}
    for y in set(list(primary_count_by_year.keys()) + list(alt_count_by_year.keys())):
        out[y] = (primary_count_by_year[y], alt_count_by_year[y])
    return out

def combine_all(files):
    rows = []
    for p in files:
        try:
            with p.open("r") as f:
                data = json.load(f)
        except Exception as e:
            print(f("[ERROR] {p}: {e}"))
            continue

        fin = data.get("financials")
        if not isinstance(fin, dict):
            print(f"[WARN] Missing/invalid 'financials' in {p}")
            continue

        primary_total, alt_total = aggregate_counts_one_company(fin)
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

    if SORT_BY == "ticker":
        df = df.sort_values("ticker", ascending=True)
    else:
        df = df.sort_values("total", ascending=ASCENDING)

    return df.reset_index(drop=True)

def combine_by_year(files):
    """
    Return a dict: year -> DataFrame[ticker, primary, alternative, total, ratio_ap]
    """
    per_year_acc = defaultdict(list)

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

        per_year = aggregate_counts_one_company_per_year(fin)
        ticker = infer_ticker(data, p)

        for year, (prim, alt) in per_year.items():
            per_year_acc[year].append({"ticker": ticker, "primary": prim, "alternative": alt})

    out = {}
    for year, rows in per_year_acc.items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["total"] = df["primary"] + df["alternative"]

        def ap_ratio_row(row):
            p, a = row["primary"], row["alternative"]
            if p == 0:
                return None if a == 0 else float("inf")
            return a / p

        df["ratio_ap"] = df.apply(ap_ratio_row, axis=1)

        if SORT_BY == "ticker":
            df = df.sort_values("ticker", ascending=True)
        else:
            df = df.sort_values("total", ascending=ASCENDING)

        out[year] = df.reset_index(drop=True)

    return out

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

def build_figure(df, title):
    # Overall totals for donut
    total_primary = int(df["primary"].sum())
    total_alt     = int(df["alternative"].sum())
    ap_overall = None if (total_primary == 0 and total_alt == 0) else (float("inf") if total_primary == 0 else total_alt / total_primary)

    # Dynamic width so many companies don’t squash labels
    base_width = 1000
    per_company = 25
    fig_width = max(base_width, per_company * max(1, len(df)))

    fig = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "xy"}, {"type": "domain"}]],
        column_widths=COL_WIDTHS,
        horizontal_spacing=HSPACE,
        subplot_titles=[None, "Overall (This Selection)"]
    )

    x_vals = df["ticker"]
    custom_ap = [fmt_ratio(r) for r in df["ratio_ap"]]

    fig.add_trace(
        go.Bar(
            name="Primary",
            x=x_vals, y=df["primary"],
            hovertemplate="Company=%{x}<br>Primary=%{y}<br>Total=%{customdata[0]}<br>A/P=%{customdata[1]}<extra></extra>",
            customdata=list(zip(df["total"], custom_ap)),
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

    # Center annotation (pie domain coordinates)
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
        title=title,
        barmode="group",
        xaxis_title="Company",
        yaxis_title="# of tags (FY metrics only)",
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
        # All-years (original)
        df_all = combine_all(files)
        n_entities = df_all["ticker"].nunique()
        if n_entities != EXPECTED_N:
            print(f"[WARN] Unique tickers/companies found: {n_entities} (expected ~{EXPECTED_N})")

        if df_all.empty:
            print("[INFO] No FY entries found across files (all-years).")
        else:
            fig_all = build_figure(df_all, TITLE_ALL)
            fig_all.write_html(OUTPUT_ALL, include_plotlyjs="cdn")
            print(f"[OK] Wrote {OUTPUT_ALL}")

        # Per-year outputs
        print("[INFO] Building per-year charts…")
        year_to_df = combine_by_year(files)
        if not year_to_df:
            print("[INFO] No per-year FY entries found.")
        else:
            for year in sorted(year_to_df.keys()):
                df_y = year_to_df[year]
                if df_y.empty:
                    continue
                title = f"All Companies — Primary vs Alternative Tag Coverage (FY {year})"
                outfp = OUTPUT_YR_FP.format(year=year)
                fig_y = build_figure(df_y, title)
                fig_y.write_html(outfp, include_plotlyjs="cdn")
                print(f"[OK] Wrote {outfp}")
