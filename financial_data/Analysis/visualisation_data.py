"""
Visualization for yearly GAAP tag counts (last 10 years)
Reads CSVs produced by gaap_yearly_tag_counts_last10.py
Generates 2 static (matplotlib) and 2 interactive (plotly) plots.
"""

import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns  # optional, just for prettier static plots
import plotly.express as px

OUTDIR = "tags"
LONG_CSV = os.path.join(OUTDIR, "yearly_tag_counts_long.csv")
MATRIX_CSV = os.path.join(OUTDIR, "yearly_tag_counts_matrix.csv")

# -------------------------------------------------------------------------
# Load data
long_df = pd.read_csv(LONG_CSV)     # ticker, year, tag_count
matrix_df = pd.read_csv(MATRIX_CSV) # ticker, 2015, 2016, ...

# ----------------------------- STATIC -----------------------------------
# 1. Static line chart (matplotlib)
plt.figure(figsize=(12, 6))
sns.lineplot(data=long_df, x="year", y="tag_count", hue="ticker", marker="o")
plt.title("Yearly distinct GAAP tags per company (last 10 years)")
plt.ylabel("Distinct tags")
plt.xlabel("Year")
plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
plt.tight_layout()
plt.savefig(os.path.join(OUTDIR, "static_linechart.png"))
plt.show()

# 2. Static boxplot by year
plt.figure(figsize=(10, 6))
sns.boxplot(data=long_df, x="year", y="tag_count")
sns.stripplot(data=long_df, x="year", y="tag_count", color="black", size=2, alpha=0.5)
plt.title("Distribution of GAAP tag counts across companies, by year")
plt.ylabel("Distinct tags")
plt.xlabel("Year")
plt.tight_layout()
plt.savefig(os.path.join(OUTDIR, "static_boxplot.png"))
plt.show()

# ---------------------------- DYNAMIC -----------------------------------
# 3. Interactive line chart
fig1 = px.line(
    long_df,
    x="year",
    y="tag_count",
    color="ticker",
    markers=True,
    title="Interactive yearly GAAP tags per company",
)
fig1.write_html(os.path.join(OUTDIR, "interactive_linechart.html"))
fig1.show()

# 4. Animated bar chart (per-year)
fig2 = px.bar(
    long_df,
    x="ticker",
    y="tag_count",
    color="ticker",
    animation_frame="year",
    title="Animated GAAP tag counts per company (yearly)",
)
fig2.update_layout(xaxis={'categoryorder': 'total descending'})
fig2.write_html(os.path.join(OUTDIR, "animated_barchart.html"))
fig2.show()
# 5. Horizontal bar race (all companies, per year)
fig5 = px.bar(
    long_df,
    x="tag_count",
    y="ticker",
    orientation="h",
    color="ticker",
    animation_frame="year",
    animation_group="ticker",
    title="Bar Race: Distinct GAAP tag counts per company by year",
    text="tag_count",
)
fig5.update_traces(textposition="outside")
fig5.update_layout(
    xaxis_title="Distinct GAAP tags",
    yaxis_title="",
    xaxis={'rangemode': 'tozero'},
    showlegend=False
)
fig5.write_html(os.path.join(OUTDIR, "animated_bar_race_all_companies.html"))
fig5.show()
# 6. Animated rank “bump” chart
rank_df = (
    long_df
    .assign(rank=long_df.groupby("year")["tag_count"].rank(method="dense", ascending=False))
    .sort_values(["ticker", "year"])
)

# Scatter points per frame + static connecting lines for context
fig6 = px.scatter(
    rank_df,
    x="year",
    y="rank",
    color="ticker",
    animation_frame="year",
    animation_group="ticker",
    hover_data=["tag_count"],
    title="Animated Rank Bump: Company rank by yearly GAAP tag count (1 = highest)",
)

# Add static lines so trajectories are visible while animating
static_lines = px.line(
    rank_df,
    x="year",
    y="rank",
    color="ticker",
).data
for tr in static_lines:
    fig6.add_trace(tr)

fig6.update_yaxes(autorange="reversed", title="Rank (1 = highest)")
fig6.update_xaxes(title="Year")
fig6.write_html(os.path.join(OUTDIR, "animated_rank_bump.html"))
fig6.show()
# 7. Animated distribution (violin) across companies by year
fig7 = px.violin(
    long_df,
    y="tag_count",
    x=long_df["year"].astype(str),  # just for a consistent axis label
    color=long_df["year"].astype(str),
    animation_frame="year",
    box=True,
    points="all",
    title="Animated Distribution: GAAP tag counts across companies by year",
)
fig7.update_layout(
    xaxis_title="Year",
    yaxis_title="Distinct GAAP tags",
    showlegend=False
)
fig7.write_html(os.path.join(OUTDIR, "animated_violin_distribution.html"))
fig7.show()
