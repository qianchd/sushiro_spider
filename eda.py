import pandas as pd

file_path = "data/sushiro_2026-04-30.parquet"
df = pd.read_parquet(file_path, engine="pyarrow")