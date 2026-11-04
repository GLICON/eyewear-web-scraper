"""
clean.py - clean, standardise and store the scraped eyewear data
=================================================================
Reads data/raw_products.csv (made by scraper.py) and:
  1. tidies text and converts prices to numbers
  2. standardises brand names and gender across the two retailers
  3. adds useful columns: discount, on_sale, price_band
  4. runs quality checks and removes bad rows and duplicates
  5. saves data/clean_products.csv and a SQLite database data/eyewear.db

Run:  python clean.py      (after scraper.py)
"""

import sqlite3        # built into Python: a database stored in a single file

import pandas as pd   # tables ("DataFrames") for cleaning and analysis

# File locations
RAW_FILE = "data/raw_products.csv"       # input: made by scraper.py
CLEAN_FILE = "data/clean_products.csv"   # output: cleaned table
DB_FILE = "data/eyewear.db"              # output: database

# Load the raw data into a table. product_id is read as text so long
# barcodes like 0888392593948 keep their leading zeros.
df = pd.read_csv(RAW_FILE, dtype={"product_id": str})
print(f"Raw rows: {len(df)}")

# ---------------------------------------------------------------------------
# 1. Tidy text and numbers
# ---------------------------------------------------------------------------
# Remove spaces at the start/end and collapse double spaces, e.g. " Ray-Ban  " -> "Ray-Ban"
text_columns = ["brand", "model", "color_name", "frame_shape", "frame_material", "gender"]
for col in text_columns:
    df[col] = df[col].astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    df[col] = df[col].replace("", pd.NA)   # an empty cell means "no value"

# Make sure prices are numbers. Anything that isn't a number becomes empty (NaN)
# instead of crashing the script.
df["list_price"] = pd.to_numeric(df["list_price"], errors="coerce")
df["sale_price"] = pd.to_numeric(df["sale_price"], errors="coerce")

# A product that isn't discounted may show only one price.
# In that case the original price and the sale price are the same.
df["list_price"] = df["list_price"].fillna(df["sale_price"])
df["sale_price"] = df["sale_price"].fillna(df["list_price"])

# ---------------------------------------------------------------------------
# 2. Standardise values so both retailers use the same wording
# ---------------------------------------------------------------------------
# The same brand can be spelled differently on each site:
#   FramesDirect: "RALPH by Ralph Lauren"   Glasses.com: "Ralph by Ralph Lauren"
# Group brands by their lower-case version, then use the most common spelling
# in each group for every row in that group.
brand_key = df["brand"].str.lower()
most_common_spelling = df.groupby(brand_key)["brand"].agg(lambda s: s.mode()[0])
df["brand"] = brand_key.map(most_common_spelling)

# FramesDirect shortens "Polo Ralph Lauren" to "Polo"
df["brand"] = df["brand"].replace({"Polo": "Polo Ralph Lauren"})

# Consistent capitals: "rectangular" -> "Rectangular"
df["frame_shape"] = df["frame_shape"].str.title()
df["frame_material"] = df["frame_material"].str.title()

# One readable name per frame, e.g. "Ray-Ban RB7075"
df["product_name"] = df["brand"] + " " + df["model"]


# FramesDirect lists gender as e.g. "Men,Unisex,Women".
# Turn that into one simple value.
def simplify_gender(value):
    if pd.isna(value):                     # no gender given (all Glasses.com rows)
        return pd.NA
    if "Unisex" in value or ("Men" in value and "Women" in value):
        return "Unisex"
    return value                           # "Men", "Women" or "Kids" stay as they are


df["gender"] = df["gender"].apply(simplify_gender)

# ---------------------------------------------------------------------------
# 3. New columns that help compare frames
# ---------------------------------------------------------------------------
# Discount as a percentage of the original price, e.g. 154 -> 77 = 50.0
df["discount_pct"] = ((df["list_price"] - df["sale_price"]) / df["list_price"] * 100).round(1)

# Money saved, e.g. 154 - 77 = 77.00
df["discount_amount"] = (df["list_price"] - df["sale_price"]).round(2)

# True if the frame is currently discounted
df["on_sale"] = df["discount_pct"] > 0

# Put each frame in a budget group (helps match frames to a patient's budget)
df["price_band"] = pd.cut(
    df["sale_price"],
    bins=[0, 100, 200, 350, float("inf")],
    labels=["Budget (<$100)", "Mid-range ($100-199)", "Premium ($200-349)", "Luxury ($350+)"],
    right=False,   # e.g. exactly $100 counts as Mid-range, not Budget
)

# ---------------------------------------------------------------------------
# 4. Quality checks
# ---------------------------------------------------------------------------
# A row is only useful if it has these values
required = ["product_id", "brand", "model", "sale_price", "product_url"]
missing = df[required].isna().any(axis=1)                       # True where any of them is empty

# A price of $0 or above $5,000 for glasses is almost certainly a scraping error
bad_price = (df["sale_price"] <= 0) | (df["sale_price"] > 5000)

print(f"Removed {int((missing | bad_price).sum())} rows with missing or impossible values")
df = df[~(missing | bad_price)]                                 # ~ means "not": keep the good rows

# The same product should appear only once per retailer
before = len(df)
df = df.drop_duplicates(subset=["retailer", "product_id"])
print(f"Removed {before - len(df)} duplicate rows")

# ---------------------------------------------------------------------------
# 5. Save the results
# ---------------------------------------------------------------------------
# Choose the column order for the final table
columns = ["retailer", "product_id", "brand", "model", "product_name", "list_price",
           "sale_price", "discount_amount", "discount_pct", "on_sale", "price_band",
           "colors_available", "color_name", "frame_shape", "frame_material", "gender",
           "includes_lenses", "product_url", "image_url", "page", "scraped_at"]
df = df[columns].sort_values(["retailer", "brand", "sale_price"]).reset_index(drop=True)

# Glasses.com doesn't show colour name, shape, material or gender on its listing
# pages. Write "Not listed" instead of leaving the cell blank, so anyone reading
# the spreadsheet knows the value is missing at the source, not lost by the scraper.
for col in ["color_name", "frame_shape", "frame_material", "gender"]:
    df[col] = df[col].fillna("Not listed")

# CSV file: opens in Excel
df.to_csv(CLEAN_FILE, index=False)

# SQLite database: a table called "products" that can be searched with SQL, e.g.
#   SELECT brand, model, sale_price FROM products WHERE sale_price < 150;
# if_exists="replace" overwrites the table with the latest run.
with sqlite3.connect(DB_FILE) as con:
    df.astype({"price_band": "string"}).to_sql("products", con, if_exists="replace", index=False)

# Print a short summary so you can check the result straight away
print(f"Clean rows: {len(df)}  ->  {CLEAN_FILE} and {DB_FILE}\n")
print("Products and average price by retailer:")
print(df.groupby("retailer")["sale_price"].agg(["count", "mean", "min", "max"]).round(2))
print("\nTop 5 brands:")
print(df["brand"].value_counts().head(5))
