import os
import sys
import time
import random
import logging
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Set working directory to the script's directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ==================== Logging Configuration ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ==================== Global Constants ====================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://sushiro.chinatsu1124.com/"
}

DATA_API = "https://sushiro.chinatsu1124.com/api/data"
STORE_FILE = "sushiro_stores.csv"
OPEN_DATES_FILE = "store_open_dates.csv"  # File recording the earliest crawlable date for each store

# ==================== Local Dimension Tables & Cache Loading ====================

def load_stores_from_local() -> list:
    file_path = Path(STORE_FILE)
    if not file_path.exists():
        logging.error(f"Cannot find store file {STORE_FILE}! Please run the store update script first.")
        sys.exit(1)
    df = pd.read_csv(file_path)
    return df.to_dict('records')

def load_open_dates() -> dict:
    file_path = Path(OPEN_DATES_FILE)
    if not file_path.exists():
        return {}
    try:
        df = pd.read_csv(file_path)
        return dict(zip(df['store_id'], df['earliest_date']))
    except Exception:
        return {}

def save_open_dates(new_open_dates: dict):
    if not new_open_dates:
        return
    file_path = Path(OPEN_DATES_FILE)
    local_dates = {}
    if file_path.exists():
        try:
            df_local = pd.read_csv(file_path)
            local_dates = dict(zip(df_local['store_id'], df_local['earliest_date']))
        except Exception:
            pass

    for store_id, new_date in new_open_dates.items():
        if store_id not in local_dates or new_date < local_dates[store_id]:
            local_dates[store_id] = new_date

    df_final = pd.DataFrame(list(local_dates.items()), columns=['store_id', 'earliest_date'])
    df_final = df_final.sort_values(by='store_id')
    df_final.to_csv(file_path, index=False, encoding="utf-8-sig")

def get_date_chunks(start_str: str, end_str: str, chunk_size: int) -> list:
    start_dt = datetime.strptime(start_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_str, "%Y-%m-%d")
    chunks = []
    current = start_dt
    while current <= end_dt:
        chunk_end = current + timedelta(days=chunk_size - 1)
        if chunk_end > end_dt:
            chunk_end = end_dt
        chunks.append((current.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
        current = chunk_end + timedelta(days=1)
    return chunks

def get_saved_store_ids(target_date: str) -> set:
    """[Core Refactoring]: Read Parquet file to extract only the successfully saved store_id set"""
    file_path = Path("data") / f"sushiro_{target_date}.parquet"
    if not file_path.exists():
        return set()
    try:
        # Read only the store_id column to greatly improve speed and save memory
        df = pd.read_parquet(file_path, columns=['store_id'], engine="pyarrow")
        return set(df['store_id'].unique())
    except Exception as e:
        logging.error(f"Failed to read {file_path.name} (file may be corrupted), will retry data for this day: {e}")
        return set()

# ==================== Core Scraping & Slicing Flow ====================

def fetch_batch_data(store_id: int, start_date: str, end_date: str) -> dict:
    params = {"store_id": store_id, "start_date": start_date, "end_date": end_date}
    try:
        res = requests.get(DATA_API, params=params, headers=HEADERS, timeout=15)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        logging.error(f"Failed to fetch data [{store_id} | {start_date}~{end_date}]: {e}")
        return None

def parse_time_to_minutes(time_str: str) -> int:
    try:
        h, m = map(int, time_str.split(":"))
        return h * 60 + m
    except:
        return -1

def split_data_by_day(batch_data: dict, start_date_str: str, end_date_str: str) -> dict:
    times = batch_data.get("times", [])
    if not times:
        return {}

    daily_chunks = {}
    current_date = datetime.strptime(end_date_str, "%Y-%m-%d")

    length = len(times)
    w_data = batch_data.get("wait_data", [None] * length)
    aw_data = batch_data.get("actual_wait_data", [None] * length)
    c_data = batch_data.get("calls_data", [None] * length)
    nt_data = batch_data.get("new_tickets_data", [None] * length)

    def create_empty_day():
        return {"time": [], "wait_data": [], "actual_wait_data": [], "calls_data": [], "new_tickets_data": []}

    curr_day = create_empty_day()
    last_mins = -1

    for i in range(length - 1, -1, -1):
        t_str = times[i]
        curr_mins = parse_time_to_minutes(t_str)

        if last_mins != -1 and curr_mins > last_mins:
            for k in curr_day: curr_day[k].reverse()
            daily_chunks[current_date.strftime("%Y-%m-%d")] = curr_day
            current_date -= timedelta(days=1)
            curr_day = create_empty_day()

        curr_day["time"].append(t_str)
        curr_day["wait_data"].append(w_data[i])
        curr_day["actual_wait_data"].append(aw_data[i])
        curr_day["calls_data"].append(c_data[i])
        curr_day["new_tickets_data"].append(nt_data[i])
        last_mins = curr_mins

    if curr_day["time"]:
        for k in curr_day: curr_day[k].reverse()
        daily_chunks[current_date.strftime("%Y-%m-%d")] = curr_day

    return daily_chunks

# ==================== Main Program ====================

def main():
    # ================= Configuration Area =================
    tz_bjt = timezone(timedelta(hours=8))
    now_bjt = datetime.now(tz_bjt)

    # Calculate yesterday by default
    yesterday = now_bjt - timedelta(days=1)
    target_date = yesterday.strftime("%Y-%m-%d")

    START_DATE = target_date
    END_DATE = target_date
    CALL_DATES = 1      # Keep single-day requests
    MODE = "full"
    # ==========================================

    stores = load_stores_from_local()
    open_dates = load_open_dates()
    date_chunks = get_date_chunks(START_DATE, END_DATE, CALL_DATES)
    date_chunks.reverse()

    logging.info(f"Mode: [{MODE.upper()}] | Stores: {len(stores)} | Step: {CALL_DATES} days/chunk")
    logging.info(f"Planned order: {date_chunks[0][1]} backwards to {date_chunks[-1][0]}")

    # In-memory data buffer pool
    daily_buffer = {}

    # Create a date cache dictionary to avoid repeatedly reading the same Parquet file
    date_saved_stores_cache = {}

    for store in stores:
        store_id = store['store_id']
        store_name = store['store_name']
        region = store['region']

        logging.info(f"=== Processing store: [{region}] {store_name} ===")
        # [Redundancy Cleanup]: Completely removed the unused dead_stores_this_run set
        oldest_found_this_run = None

        for chunk_start, chunk_end in date_chunks:

            # ================= Parquet Fine-grained Resumption Check =================
            if chunk_start not in date_saved_stores_cache:
                date_saved_stores_cache[chunk_start] = get_saved_store_ids(chunk_start)

            already_saved_ids = date_saved_stores_cache[chunk_start]

            if store_id in already_saved_ids:
                logging.info(f"  [Precise Skip] 📦 Data for this store on {chunk_start} already exists in Parquet.")
                oldest_found_this_run = chunk_start
                continue
            # ==========================================================

            # [Fastscan Acceleration]: Completely trust the local opening dates dimension table, skip network requests
            if MODE == "fastscan" and store_id in open_dates:
                known_earliest = open_dates[store_id]
                if chunk_end < known_earliest:
                    logging.info(f"  [History Skip] Record shows earliest {known_earliest}, skipping {chunk_start}~{chunk_end}")
                    break # [Key Action]: Break out of the historical loop for this store directly

            # Note: In FULL mode, the above is ignored, and network requests are made
            logging.info(f"  [Fetching from Network] {chunk_start} ~ {chunk_end} ...")
            batch_data = fetch_batch_data(store_id, chunk_start, chunk_end)

            # [Physical Wall Detection]: Empty network response indicates the physical boundary (store not open yet)
            if not batch_data or not batch_data.get("times"):
                logging.warning(f"  [Empty Data] No return for this time chunk.")
                if oldest_found_this_run:
                    if store_id not in open_dates or oldest_found_this_run < open_dates[store_id]:
                        open_dates[store_id] = oldest_found_this_run
                        logging.info(f"  🎯 [Anchor Established] Opening cliff detected! Absolute opening date set to: {oldest_found_this_run}")

                # [Core Fix]: Whether Fastscan or Full, tracing must stop immediately upon hitting a true wall!
                logging.warning(f"  🛑 [Stop Tracing] Confirmed physical boundary of closure, terminating earlier requests for this store.")
                break # [Core Action]: Break immediately! Proceed to the next store!

            daily_chunks = split_data_by_day(batch_data, chunk_start, chunk_end)

            if daily_chunks:
                chunk_oldest = min(daily_chunks.keys())
                oldest_found_this_run = chunk_oldest

                if chunk_oldest > chunk_start:
                    if store_id not in open_dates or chunk_oldest < open_dates[store_id]:
                        open_dates[store_id] = chunk_oldest
                        logging.info(f"  🎯 [Anchor Established] Intra-chunk opening cliff detected! Absolute opening date set to: {chunk_oldest}")

            # Load data into the in-memory buffer pool
            for date_str, day_data in daily_chunks.items():
                df = pd.DataFrame(day_data)
                df.insert(0, 'store_name', store_name)
                df.insert(0, 'store_id', store_id)
                df.insert(0, 'region', region)

                if date_str not in daily_buffer:
                    daily_buffer[date_str] = []
                daily_buffer[date_str].append(df)

            logging.info(f"  [Buffer Success] Loaded into memory pool.")
            time.sleep(random.uniform(0, 1))

        # Save dimension tables
        save_open_dates(open_dates)

    # ================= Unified Merge & Save Operation (Supports Incremental Append) =================
    logging.info("\n================ Starting Merge and Persistent Saving ================")
    save_dir = Path("data")
    save_dir.mkdir(parents=True, exist_ok=True)

    for date_str, dfs in daily_buffer.items():
        if not dfs: continue

        parquet_file = save_dir / f"sushiro_{date_str}.parquet"
        new_df = pd.concat(dfs, ignore_index=True)

        # [Core Refactoring]: If there is an old Parquet locally, read it first and merge with new data
        if parquet_file.exists():
            try:
                old_df = pd.read_parquet(parquet_file, engine="pyarrow")
                merged_df = pd.concat([old_df, new_df], ignore_index=True)
                # Deduplicate using store and time as keys to ensure absolute data purity
                merged_df.drop_duplicates(subset=['store_id', 'time'], keep='last', inplace=True)
                logging.info(f"  [Incremental Merge] Found history file, appended {len(new_df)} newly scraped records.")
            except Exception as e:
                logging.error(f"  [Merge Failed] Cannot read old file, will overwrite directly: {e}")
                merged_df = new_df
        else:
            merged_df = new_df

        # Forced format normalization (Parquet engine is type-sensitive)
        if 'wait_data' in merged_df.columns: merged_df['wait_data'] = merged_df['wait_data'].astype('Int64')
        if 'actual_wait_data' in merged_df.columns: merged_df['actual_wait_data'] = merged_df['actual_wait_data'].astype('Int64')
        if 'calls_data' in merged_df.columns: merged_df['calls_data'] = merged_df['calls_data'].astype('Float64')
        if 'new_tickets_data' in merged_df.columns: merged_df['new_tickets_data'] = merged_df['new_tickets_data'].astype('Float64')

        # Write out all at once
        merged_df.to_parquet(parquet_file, index=False, engine="pyarrow")
        logging.info(f"📦 [Save Success] Successfully generated {parquet_file.name} (Contains {len(merged_df['store_id'].unique())} stores, total {len(merged_df)} records)")

    logging.info("🎉 All store aggregated data scraping and Parquet generation tasks completed successfully!")

if __name__ == "__main__":
    main()