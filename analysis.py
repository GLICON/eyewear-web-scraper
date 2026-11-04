"""
analysis.py - turn the clean data into findings for Frame & Lens
================================================================
Reads data/clean_products.csv (made by clean.py) and:
  1. prints key findings in plain English
  2. saves 4 charts to the charts/ folder
  3. saves the findings to data/findings.txt

Run:  python analysis.py      (after clean.py)
"""

import os

import matplotlib
matplotlib.use("Agg")              # draw charts straight to files (no window needed)
import matplotlib.pyplot as plt
import pandas as pd

CLEAN_FILE = "data/clean_products.csv"
CHART_DIR = "charts"
FINDINGS_FILE = "data/findings.txt"

# One colour per retailer, used in every chart so they're easy to compare
COLORS = {"Glasses.com": "#1f6f8b", "FramesDirect.com": "#e07a3f"}
BAND_ORDER = ["Budget (<$100)", "Mid-range ($100-199)", "Premium ($200-349)", "Luxury ($350+)"]

df = pd.read_csv(CLEAN_FILE)
os.makedirs(CHART_DIR, exist_ok=True)
retailers = [r for r in COLORS if r in df["retailer"].unique()]

findings = []          # sentences collected here are printed and saved at the end


def save(fig, name):
    """Save a chart as a PNG image and close it."""
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, name), dpi=150)
    plt.close(fig)
    print(f"Saved chart: {CHART_DIR}/{name}")


# ---------------------------------------------------------------------------
# 1. Overview: how many frames, how many brands, what prices
# ---------------------------------------------------------------------------
findings.append(f"Frames collected: {len(df)} from {df['brand'].nunique()} brands.")
for r in retailers:
    sub = df[df["retailer"] == r]
    findings.append(
        f"{r}: {len(sub)} frames, {sub['brand'].nunique()} brands, prices ${sub['sale_price'].min():.0f}"
        f"-${sub['sale_price'].max():.0f} (median ${sub['sale_price'].median():.0f})."
    )

# ---------------------------------------------------------------------------
# Chart 1: price distribution per retailer (box plot)
# Shows the typical price (middle line) and the spread at each retailer.
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 4.5))
data = [df.loc[df["retailer"] == r, "sale_price"] for r in retailers]
# Horizontal box plot (the option's name changed in matplotlib 3.10, so support both)
horizontal = {"orientation": "horizontal"} if int(matplotlib.__version__.split(".")[1]) >= 10 \
    or int(matplotlib.__version__.split(".")[0]) > 3 else {"vert": False}
box = ax.boxplot(data, patch_artist=True, widths=0.5, **horizontal)
ax.set_yticks(range(1, len(retailers) + 1), retailers)
for patch, r in zip(box["boxes"], retailers):
    patch.set_facecolor(COLORS[r])
    patch.set_alpha(0.75)
ax.set_xlabel("Price paid (USD)")
ax.set_title("Frame prices by retailer")
ax.grid(axis="x", alpha=0.3)
save(fig, "1_price_by_retailer.png")

# ---------------------------------------------------------------------------
# Chart 2: frames per price band (grouped bars)
# Answers: how much choice does a patient have on each budget?
# ---------------------------------------------------------------------------
bands = (df.groupby(["price_band", "retailer"]).size()
           .unstack(fill_value=0)
           .reindex(BAND_ORDER, fill_value=0)[retailers])
ax = bands.plot(kind="bar", figsize=(8, 4.5), color=[COLORS[r] for r in retailers], rot=0)
ax.set_xlabel("")
ax.set_ylabel("Number of frames")
ax.set_title("Choice of frames for each budget")
ax.legend(title=None)
ax.grid(axis="y", alpha=0.3)
save(ax.get_figure(), "2_frames_per_price_band.png")

biggest_band = bands.sum(axis=1).idxmax()
budget_share = bands.loc["Budget (<$100)"].sum() / len(df) * 100
findings.append(f"Most frames fall in the {biggest_band} band; {budget_share:.0f}% cost under $100.")

# ---------------------------------------------------------------------------
# Chart 3: top 10 brands (stacked horizontal bars)
# ---------------------------------------------------------------------------
top = df["brand"].value_counts().head(10).index
brands = (df[df["brand"].isin(top)].groupby(["brand", "retailer"]).size()
            .unstack(fill_value=0).reindex(columns=retailers, fill_value=0))
brands = brands.loc[brands.sum(axis=1).sort_values().index]   # biggest at the top
ax = brands.plot(kind="barh", stacked=True, figsize=(8, 5), color=[COLORS[r] for r in retailers])
ax.set_xlabel("Number of frames")
ax.set_ylabel("")
ax.set_title("Top 10 brands")
ax.legend(title=None)
ax.grid(axis="x", alpha=0.3)
save(ax.get_figure(), "3_top_brands.png")

both = set(df.loc[df["retailer"] == "Glasses.com", "brand"]) & set(df.loc[df["retailer"] == "FramesDirect.com", "brand"])
findings.append(f"Top brand: {df['brand'].value_counts().index[0]}. "
                f"{len(both)} brands are sold by both retailers.")

# ---------------------------------------------------------------------------
# Chart 4: discounts (share of frames on sale, and average discount)
# ---------------------------------------------------------------------------
sale = df.groupby("retailer").agg(on_sale_pct=("on_sale", "mean"),
                                  avg_discount=("discount_pct", lambda s: s[s > 0].mean())).reindex(retailers)
sale["on_sale_pct"] *= 100
fig, axes = plt.subplots(1, 2, figsize=(9, 4))
for ax, col, title in [(axes[0], "on_sale_pct", "Frames on sale (%)"),
                       (axes[1], "avg_discount", "Average discount when on sale (%)")]:
    bars = ax.bar(sale.index, sale[col].fillna(0), color=[COLORS[r] for r in retailers])
    ax.bar_label(bars, fmt="%.0f%%")
    ax.set_title(title)
    ax.set_ylim(0, 110)            # room above the bars for the % labels
    ax.grid(axis="y", alpha=0.3)
save(fig, "4_discounts.png")

for r, row in sale.iterrows():
    findings.append(f"{r}: {row['on_sale_pct']:.0f}% of frames on sale, "
                    f"average discount {0 if pd.isna(row['avg_discount']) else row['avg_discount']:.0f}%.")

# ---------------------------------------------------------------------------
# Extra findings useful for patients
# ---------------------------------------------------------------------------
if "includes_lenses" in df:
    lenses = df[df["includes_lenses"] == True]  # noqa: E712 (column holds True/False)
    if len(lenses):
        findings.append(f"{len(lenses)} Glasses.com frames include lenses in the price "
                        f"(median ${lenses['sale_price'].median():.0f}).")

shapes = df.loc[df["frame_shape"] != "Not listed", "frame_shape"].value_counts()
if len(shapes):
    findings.append("Most common frame shapes (FramesDirect): "
                    + ", ".join(f"{s} ({n})" for s, n in shapes.head(3).items()) + ".")

cheapest = df.nsmallest(5, "sale_price")[["retailer", "product_name", "sale_price"]]
findings.append("Five lowest-priced frames: " + "; ".join(
    f"{r.product_name} ${r.sale_price:.2f} ({r.retailer})" for r in cheapest.itertuples()) + ".")

# ---------------------------------------------------------------------------
# Print and save the findings
# ---------------------------------------------------------------------------
print("\nKEY FINDINGS")
for line in findings:
    print(" - " + line)
with open(FINDINGS_FILE, "w", encoding="utf-8") as f:
    f.write("KEY FINDINGS\n" + "\n".join(" - " + line for line in findings) + "\n")
print(f"\nSaved findings to {FINDINGS_FILE}")
