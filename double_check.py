import os
import random
import requests
import logging
import math
import pandas as pd
from pathlib import Path

# Set working directory to the script's directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ==================== Logging Configuration ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ==================== Configuration ====================
SAMPLE_DAYS = 5              # Number of random days to check (n_days)
SAMPLE_STORES_PER_DAY = 10   # Number of random stores to check per selected day (n_stores)
DATA_DIR = Path("data")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://sushiro.chinatsu1124.com/"
}
DATA_API = "https://sushiro.chinatsu1124.com/api/data"

# ==================== Core Logic ====================

def fetch_single_day(store_id: int, target_date: str) -> dict:
    """Fetch single day data from API as the ultimate source of truth."""
    params = {"store_id": store_id, "start_date": target_date, "end_date": target_date}
    try:
        res = requests.get(DATA_API, params=params, headers=HEADERS, timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        logging.error(f"Failed to fetch single day data [{store_id} | {target_date}]: {e}")
        return None

def is_value_equal(v1, v2) -> bool:
    """
    Robust value comparison handling NaNs, Nones, and type casting differences (e.g., 16 vs 16.0).
    """
    # 1. Null checks
    is_v1_null = v1 is None or pd.isna(v1) or str(v1).lower() == 'nan' or str(v1) == '<NA>'
    is_v2_null = v2 is None or pd.isna(v2) or str(v2).lower() == 'nan' or str(v2) == '<NA>'

    if is_v1_null and is_v2_null: return True
    if is_v1_null != is_v2_null: return False

    # 2. Value checks
    try:
        return math.isclose(float(v1), float(v2), rel_tol=1e-5)
    except (ValueError, TypeError):
        # Fallback to string comparison (e.g., for time strings like "10:05")
        return str(v1) == str(v2)

def check_store_day(df_local: pd.DataFrame, store_id: int, region: str, store_name: str, target_date: str) -> bool:
    """Compare a specific store's local data slice against the live API response."""
    logging.info(f"🔍 Checking Target: {region} [{store_name}] (ID: {store_id}) @ {target_date}")

    # 1. Fetch real API data for that single day
    api_data = fetch_single_day(store_id, target_date)

    if not api_data or not api_data.get("times"):
        logging.error(f"  ❌ API returned empty, but local Parquet has data! Ghost data detected.")
        return False

    api_times = api_data["times"]
    api_wait = api_data.get("wait_data", [None]*len(api_times))
    api_actual = api_data.get("actual_wait_data", [None]*len(api_times))
    api_calls = api_data.get("calls_data", [None]*len(api_times))
    api_tickets = api_data.get("new_tickets_data", [None]*len(api_times))

    # 2. Length validation
    if len(df_local) != len(api_times):
        logging.error(f"  ❌ Length mismatch! Local has {len(df_local)} rows, API returned {len(api_times)} rows.")
        return False

    # 3. Row-by-row validation
    for idx in range(len(df_local)):
        local_row = df_local.iloc[idx]

        t_local, t_api = local_row.get("time"), api_times[idx]
        w_local, w_api = local_row.get("wait_data"), api_wait[idx]
        aw_local, aw_api = local_row.get("actual_wait_data"), api_actual[idx]
        c_local, c_api = local_row.get("calls_data"), api_calls[idx]
        nt_local, nt_api = local_row.get("new_tickets_data"), api_tickets[idx]

        if not is_value_equal(t_local, t_api):
            logging.error(f"  ❌ Timestamp mismatch! Row {idx}: Local '{t_local}' != API '{t_api}'")
            return False
        if not is_value_equal(w_local, w_api):
            logging.error(f"  ❌ wait_data mismatch! Time {t_api}: Local {w_local} != API {w_api}")
            return False
        if not is_value_equal(aw_local, aw_api):
            logging.error(f"  ❌ actual_wait_data mismatch! Time {t_api}: Local {aw_local} != API {aw_api}")
            return False
        if not is_value_equal(c_local, c_api):
            logging.error(f"  ❌ calls_data mismatch! Time {t_api}: Local {c_local} != API {c_api}")
            return False
        if not is_value_equal(nt_local, nt_api):
            logging.error(f"  ❌ new_tickets_data mismatch! Time {t_api}: Local {nt_local} != API {nt_api}")
            return False

    logging.info(f"  ✅ Perfect match! Compared {len(api_times)} records successfully.")
    return True

def main():
    if not DATA_DIR.exists():
        logging.error(f"Cannot find {DATA_DIR} directory! Please run the spider first.")
        return

    # 1. Gather all Parquet files (representing available days)
    all_parquet_files = list(DATA_DIR.glob("sushiro_*.parquet"))
    if not all_parquet_files:
        logging.error("No Parquet files found!")
        return

    # 2. Randomly sample N days
    sampled_days_count = min(SAMPLE_DAYS, len(all_parquet_files))
    sampled_files = random.sample(all_parquet_files, sampled_days_count)

    logging.info(f"=== Starting Double Check Audit ===")
    logging.info(f"Configuration: Checking {sampled_days_count} random days, up to {SAMPLE_STORES_PER_DAY} stores per day.")

    pass_count = 0
    fail_count = 0

    # 3. Iterate over the sampled days
    for file_path in sampled_files:
        # Extract date from filename (e.g., sushiro_2026-04-30.parquet -> 2026-04-30)
        target_date = file_path.stem.split("_")[1]

        logging.info(f"\n📂 Opening Parquet File for Date: {target_date}")
        try:
            df_day = pd.read_parquet(file_path, engine="pyarrow")
        except Exception as e:
            logging.error(f"Failed to read {file_path.name}: {e}")
            continue

        # Extract unique stores present in this day's file
        unique_stores = df_day[['store_id', 'store_name', 'region']].drop_duplicates().to_dict('records')

        # 4. Randomly sample N stores from this specific day
        sampled_stores_count = min(SAMPLE_STORES_PER_DAY, len(unique_stores))
        sampled_stores = random.sample(unique_stores, sampled_stores_count)

        for store in sampled_stores:
            store_id = store['store_id']
            region = store['region']
            store_name = store['store_name']

            # 5. Isolate the specific store's data from the daily Parquet block
            df_store_local = df_day[df_day['store_id'] == store_id].reset_index(drop=True)

            # 6. Run the rigorous cross-check
            if check_store_day(df_store_local, store_id, region, store_name, target_date):
                pass_count += 1
            else:
                fail_count += 1

    # 7. Final Audit Report
    total_audits = pass_count + fail_count
    logging.info("\n=========================================")
    logging.info(f"Audit Report: Tested {total_audits} store-day blocks in total.")
    logging.info(f"✅ Passed: {pass_count}")

    if fail_count > 0:
        logging.warning(f"❌ Failed: {fail_count}  <-- WARNING! Please check the data pipeline.")
    else:
        logging.info(f"🎉 All clear! The Parquet extraction pipeline is extremely reliable.")

if __name__ == "__main__":
    main()