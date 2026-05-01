import os
import pandas as pd
from pathlib import Path

# Set working directory to the script's directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

def convert_csv_to_parquet():
    data_dir = Path("data")
    if not data_dir.exists():
        print("Data folder not found!")
        return

    # Iterate through all date folders under the data directory
    for date_dir in data_dir.iterdir():
        if not date_dir.is_dir() or not date_dir.name.startswith("202"):
            continue

        date_str = date_dir.name
        parquet_file = data_dir / f"sushiro_{date_str}.parquet"

        # Skip directly if already converted
        if parquet_file.exists():
            print(f"⏩ Skipped: {parquet_file.name} already exists")
            continue

        dfs = []
        # Iterate through all store CSVs in this date folder
        for csv_file in date_dir.glob("*.csv"):
            # Parse the original filename: Region_StoreID_StoreName.csv
            parts = csv_file.stem.split("_", 2)
            if len(parts) < 3:
                continue
            region, store_id, store_name = parts[0], int(parts[1]), parts[2]

            df = pd.read_csv(csv_file)
            # Insert identity columns at the very beginning
            df.insert(0, 'store_name', store_name)
            df.insert(0, 'store_id', store_id)
            df.insert(0, 'region', region)

            dfs.append(df)

        if dfs:
            # Concatenate all store data for that day
            merged_df = pd.concat(dfs, ignore_index=True)

            # Strictly enforce data types (native support for Nulls)
            if 'wait_data' in merged_df.columns: merged_df['wait_data'] = merged_df['wait_data'].astype('Int64')
            if 'actual_wait_data' in merged_df.columns: merged_df['actual_wait_data'] = merged_df['actual_wait_data'].astype('Int64')
            if 'calls_data' in merged_df.columns: merged_df['calls_data'] = merged_df['calls_data'].astype('Float64')
            if 'new_tickets_data' in merged_df.columns: merged_df['new_tickets_data'] = merged_df['new_tickets_data'].astype('Float64')

            # Export as Parquet
            merged_df.to_parquet(parquet_file, index=False, engine="pyarrow")
            print(f"✅ Conversion successful: {parquet_file.name} (Merged {len(dfs)} stores, total {len(merged_df)} records)")

    print("🎉 All existing CSV data has been successfully converted to Parquet format! (You can now safely delete those old date folders)")

if __name__ == "__main__":
    convert_csv_to_parquet()