import requests
import time
import logging
import sys
import pandas as pd
import os

# Set working directory to the script's directory (good practice to keep it consistent with the main program)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://sushiro.chinatsu1124.com/"
}

# API Endpoint configuration
REGIONS_API = "https://sushiro.chinatsu1124.com/api/regions"
STORES_API = "https://sushiro.chinatsu1124.com/api/stores"
STORE_FILE = "sushiro_stores.csv"

def fetch_regions() -> list:
    """Dynamically fetch the latest list of regions from the server"""
    logging.info("Requesting the latest list of regions...")
    try:
        res = requests.get(REGIONS_API, headers=HEADERS, timeout=10)
        res.raise_for_status()
        data = res.json()
        regions = data.get("regions", [])

        if regions:
            logging.info(f"Successfully fetched {len(regions)} regions: {', '.join(regions)}")
        return regions
    except Exception as e:
        logging.error(f"Failed to fetch regions list: {e}")
        return []

def fetch_all_stores():
    # 1. Dynamically fetch regions
    regions = fetch_regions()

    # Safety net: If fetching the region list fails, terminate the program directly to prevent clearing the old store file
    if not regions:
        logging.error("Region list is empty or failed to fetch. For safety, terminating store update operation.")
        sys.exit(1)

    all_stores = []

    # 2. Iterate through the dynamically fetched regions
    for region in regions:
        logging.info(f"Fetching store list for [{region}]...")
        try:
            res = requests.get(STORES_API, params={"region": region}, headers=HEADERS, timeout=10)
            res.raise_for_status()
            stores = res.json().get("stores", [])
            all_stores.extend(stores)
        except Exception as e:
            logging.error(f"Failed to fetch stores for [{region}]: {e}")

        time.sleep(1.5)  # Polite delay

    # 3. Data cleaning and saving
    if all_stores:
        # Convert to DataFrame and save
        df = pd.DataFrame(all_stores)
        # Extract useful columns and rename them to keep it clean
        df = df[['id', 'name', 'region', 'address']]
        df.rename(columns={'id': 'store_id', 'name': 'store_name'}, inplace=True)

        df.to_csv(STORE_FILE, index=False, encoding="utf-8-sig")
        logging.info(f"🎉 Successfully fetched {len(df)} stores nationwide, overwritten and saved to {STORE_FILE}!")
    else:
        logging.warning("Failed to fetch any store information, skipping file save.")

if __name__ == "__main__":
    fetch_all_stores()