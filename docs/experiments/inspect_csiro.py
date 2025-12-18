import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATASET_DIR = BASE_DIR / "datasets" / "csiro_ahu_fdd"

def inspect_parquet(file_name: str):
    path = DATASET_DIR / file_name
    print(f"\n--- Inspecting {file_name} ---")

    df = pd.read_parquet(path)

    print("Shape:", df.shape)
    print("Columns:")
    for col in df.columns:
        print(f"  - {col} ({df[col].dtype})")

    print("\nHead:")
    print(df.head(3))

    print("\nTail:")
    print(df.tail(3))


if __name__ == "__main__":
    inspect_parquet("AHU9.parquet")
    inspect_parquet("AHU10.parquet")
    inspect_parquet("fault-experiments.parquet")
