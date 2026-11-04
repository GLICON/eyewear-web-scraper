"""
scraper.py - Frame & Lens eyewear scraper
=========================================
Collects prescription eyeglasses from Glasses.com and FramesDirect.com.

How it works
  1. Selenium opens each listing page in Chrome. Both sites build their
     product grid with JavaScript, so a plain HTTP request would miss it.
  2. BeautifulSoup reads the finished HTML and pulls out each product.
  3. Everything is saved to data/raw_products.csv for clean.py to tidy up.

Run:  python scraper.py
"""

# ---------------------------------------------------------------------------
# Imports: the libraries this script uses
# ---------------------------------------------------------------------------
import os                          # to create the "data" folder
import random                      # to pick a random pause between pages
import re                          # "regular expressions": find patterns in text, e.g. a price
import time                        # to pause and to record when we scraped
from urllib.parse import urljoin   # to turn a link like "/oakley-airdrop" into a full web address

import pandas as pd                # to put the products in a table and save it as CSV
from bs4 import BeautifulSoup      # to read (parse) the HTML of a page
from selenium import webdriver     # to control the Chrome browser
from selenium.common.exceptions import TimeoutException          # error raised when waiting takes too long
from selenium.webdriver.common.by import By                      # tells Selenium how to find elements (here: by CSS selector)
from selenium.webdriver.support import expected_conditions as EC  # conditions to wait for, e.g. "element is present"
from selenium.webdriver.support.ui import WebDriverWait          # waits until a condition is true

# ---------------------------------------------------------------------------
# Settings: the only part you normally change
# ---------------------------------------------------------------------------
PAGES_PER_SITE = 15           # listing pages per retailer: 15 gives about 500 frames in total (~15 min)
OUTPUT_FILE = "data/raw_products.csv"   # where the raw results are saved

# For each retailer:
#   "url"  = address of a listing page; {page} is replaced by 1, 2, 3 ...
#            (found by clicking "next page" on the site and looking at the address bar)
#   "tile" = CSS selector of ONE product box on that page
#            (found by right-clicking a product in Chrome -> Inspect)
SITES = {
    "Glasses.com": {
        "url": "https://www.glasses.com/gl-us/eyeglasses?pageNumber={page}",
        "tile": "a.product-tile",       # each product is an <a> link with class "product-tile"
    },
    "FramesDirect.com": {
        "url": "https://www.framesdirect.com/eyeglasses/?p={page}",
        "tile": "div.prod-holder",      # each product is a <div> with class "prod-holder"
    },
}


# ===========================================================================
# PART 1 - SELENIUM: open the browser and load pages
# ===========================================================================
def start_browser():
    """Start Chrome. Selenium (4.6+) downloads the matching driver by itself,
    so you never need to install or update 'chromedriver' manually."""
    options = webdriver.ChromeOptions()
    options.add_argument("--window-size=1400,1000")   # a normal desktop-sized window

    # These two settings hide the "Chrome is being controlled by automated
    # software" flags, so simple bot checks treat it like a normal visitor.
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])

    return webdriver.Chrome(options=options)          # opens the Chrome window


def load_page(driver, url, tile_selector):
    """Open a page, wait for the products to appear, scroll so every
    product loads, and return the page's HTML (or None if it failed)."""
    driver.get(url)   # go to the page, like typing the address into Chrome

    # Products are added by JavaScript a moment AFTER the page opens.
    # So we wait (up to 20 seconds) until at least one product tile exists.
    # This is better than a fixed time.sleep(): it continues as soon as they appear.
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, tile_selector))
        )
    except TimeoutException:
        # No products after 20 s. Usually the site is showing a
        # "verify you are human" page. Give the user 60 s to complete it.
        print("   Products did not load. If the browser shows a check, complete it now (60 s)...")
        try:
            WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, tile_selector))
            )
        except TimeoutException:
            return None   # still nothing: tell main() this page failed

    # Some products/images only load when you scroll to them ("lazy loading").
    # Scroll down 8 times, 900 pixels each, pausing half a second each time.
    for _ in range(8):
        driver.execute_script("window.scrollBy(0, 900);")
        time.sleep(0.5)

    return driver.page_source   # the full HTML of the page, now with all products in it


# ===========================================================================
# PART 2 - BEAUTIFULSOUP: helper functions
# ===========================================================================
def get_text(tile, selector):
    """Return the text of the first element inside `tile` that matches the
    CSS selector, or '' if there is none. Returning '' instead of crashing
    means one missing field never stops the whole scrape."""
    element = tile.select_one(selector)                       # find the element
    return element.get_text(" ", strip=True) if element else ""  # its text, without extra spaces


def to_price(text):
    """Turn price text into a number:  '$ 1,154.00' -> 1154.0  |  '' -> None"""
    # The pattern \d[\d,]*\.?\d* means: a digit, then more digits or commas,
    # then optionally a decimal point and more digits.
    match = re.search(r"\d[\d,]*\.?\d*", text or "")
    return float(match.group().replace(",", "")) if match else None   # remove commas, convert to number


# ===========================================================================
# PART 3 - BEAUTIFULSOUP: one parser per retailer
# Each site uses different HTML, so each needs its own selectors.
# Both return a list of dictionaries with the SAME keys, so the data can be
# combined into one table later.
# ===========================================================================
def parse_glasses_com(html):
    soup = BeautifulSoup(html, "html.parser")   # turn the HTML text into a searchable structure
    products = []

    # Loop over every product tile on the page
    for tile in soup.select("a.product-tile"):
        # The tile itself is the link, e.g. /gl-us/ray-ban/8053672552898
        url = urljoin("https://www.glasses.com", tile.get("href", ""))

        # Colours are shown as text like "3 colors": pull out the number
        colors = re.search(r"(\d+)\s*colou?rs?", get_text(tile, ".product-colors"))

        products.append({
            "retailer": "Glasses.com",
            "product_id": url.rstrip("/").split("/")[-1],        # last part of the URL = UPC barcode
            "brand": get_text(tile, ".product-brand"),           # e.g. "Ray-Ban"
            "model": get_text(tile, ".product-code"),            # e.g. "RB7075"
            "list_price": to_price(get_text(tile, ".product-list-price")),   # crossed-out original price
            "sale_price": to_price(get_text(tile, ".product-offer-price")),  # price the customer pays
            "colors_available": int(colors.group(1)) if colors else None,
            "color_name": None,           # not shown on Glasses.com listing pages
            "frame_shape": None,          # not shown on Glasses.com listing pages
            "frame_material": None,       # not shown on Glasses.com listing pages
            "gender": None,               # not shown on Glasses.com listing pages
            "includes_lenses": "including lenses" in tile.get_text(" ").lower(),  # True/False
            "product_url": url,
            "image_url": (tile.select_one("img") or {}).get("src", ""),   # first picture in the tile
        })
    return products


def parse_framesdirect(html):
    soup = BeautifulSoup(html, "html.parser")
    products = []

    for tile in soup.select("div.prod-holder"):
        # Every real product tile contains a hidden details block (.prod-details)
        # holding brand, model, UPC, prices, shape and material as plain values.
        # Advert/banner tiles use the same "prod-holder" class but have no
        # details block, so this line skips them.
        if not tile.select_one(".prod-details"):
            continue

        link = tile.select_one(".prod-image-holder a[href]")   # the link around the product picture

        # Colours: count the colour swatches, plus the "+6" that means 6 more colours
        swatches = len(tile.select("a.color-selection"))
        extra = re.search(r"\+\s*(\d+)", get_text(tile, ".swatch-holder"))

        products.append({
            "retailer": "FramesDirect.com",
            "product_id": get_text(tile, ".prodUPC"),            # UPC barcode
            "brand": get_text(tile, ".prodBrand"),
            "model": get_text(tile, ".prodName"),
            "list_price": to_price(get_text(tile, ".retailPriceID")),  # original price
            "sale_price": to_price(get_text(tile, ".salePriceID")),    # current price
            "colors_available": swatches + (int(extra.group(1)) if extra else 0),
            "color_name": get_text(tile, "[id^='dvSelectedColorName']"),  # colour shown, e.g. "Matte Black (5196)"
            "frame_shape": get_text(tile, ".prod-shape"),        # e.g. "Rectangular"
            "frame_material": get_text(tile, ".prod-material"),  # e.g. "Acetate"
            "gender": get_text(tile, ".prod-gender"),            # e.g. "Men,Unisex,Women"
            "includes_lenses": False,     # FramesDirect prices are for the frame only
            "product_url": urljoin("https://www.framesdirect.com", link["href"]) if link else "",
            "image_url": (tile.select_one("img") or {}).get("src", ""),
        })
    return products


# Lets the main loop pick the right parser by the retailer's name
PARSERS = {"Glasses.com": parse_glasses_com, "FramesDirect.com": parse_framesdirect}


# ===========================================================================
# PART 4 - MAIN LOOP: visit the pages, collect products, save them
# ===========================================================================
def main():
    driver = start_browser()
    all_products = []

    # try ... finally makes sure Chrome is closed even if something goes wrong
    try:
        for retailer, site in SITES.items():           # first Glasses.com, then FramesDirect.com
            seen_ids = set()                            # product IDs already collected from this site

            for page in range(1, PAGES_PER_SITE + 1):   # page 1, 2, ... PAGES_PER_SITE
                url = site["url"].format(page=page)     # put the page number into the address
                print(f"{retailer} - page {page}: {url}")

                html = load_page(driver, url, site["tile"])   # SELENIUM: get the page HTML
                if html is None:
                    print("   Could not load this page, moving on to the next retailer.")
                    break

                products = PARSERS[retailer](html)            # BEAUTIFULSOUP: extract the products

                # Keep only products we haven't seen yet. Glasses.com repeats the
                # earlier pages' products on each new page, so this avoids duplicates.
                new = [p for p in products if p["product_id"] not in seen_ids]
                print(f"   {len(products)} products on page, {len(new)} new")

                if not new:          # nothing new means we've reached the end of the catalogue
                    break

                for p in new:
                    seen_ids.add(p["product_id"])
                    p["page"] = page                                   # which page it came from
                    p["scraped_at"] = time.strftime("%Y-%m-%d %H:%M:%S")  # when it was collected
                all_products.extend(new)

                # Wait 2-5 seconds before the next page so we don't overload the
                # website (a random gap also looks more like a real visitor).
                time.sleep(random.uniform(2, 5))
    finally:
        driver.quit()   # close Chrome

    # Save everything as a table (one row per product) in a CSV file
    os.makedirs("data", exist_ok=True)   # create the data folder if it doesn't exist
    pd.DataFrame(all_products).to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved {len(all_products)} products to {OUTPUT_FILE}")


# Run main() only when this file is started directly ("python scraper.py")
if __name__ == "__main__":
    main()
