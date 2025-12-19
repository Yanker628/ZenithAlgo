import time
import pandas as pd
from pathlib import Path

def main():
    base_dir = Path(__file__).parent.parent
    csv_path = base_dir / "tests/fixtures/golden/BTCUSDT_1h.csv"
    
    if not csv_path.exists():
        print(f"Error: {csv_path} does not exist.")
        return

    print(f"Reading CSV from {csv_path}...")
    start_time = time.time()
    df = pd.read_csv(csv_path)
    csv_time = time.time() - start_time
    print(f"CSV Read Time: {csv_time:.6f} seconds")
    print(f"DataFrame Shape: {df.shape}")

    # 转换为 Parquet 格式，并使用 Snappy 压缩算法以平衡速度与体积
    parquet_path = csv_path.with_suffix(".parquet")
    print(f"\nWriting Parquet to {parquet_path} (Snappy compression)...")
    df.to_parquet(parquet_path, engine="pyarrow", compression="snappy")

    # 对比读取回来的速度
    print(f"Reading Parquet from {parquet_path}...")
    start_time = time.time()
    df_pq = pd.read_parquet(parquet_path, engine="pyarrow")
    parquet_time = time.time() - start_time
    print(f"Parquet Read Time: {parquet_time:.6f} seconds")
    
    if csv_time > 0:
        speedup = csv_time / parquet_time
        print(f"\nSpeedup: {speedup:.2f}x")
    
    # Cleanup (optional, keeping it for now as per user instruction to 'convert' implies keeping it maybe? 
    # But usually a test script might clean up. The user said 'convert... and contrast reading time'. 
    # I will leave the parquet file there as it might be useful or requested.)

if __name__ == "__main__":
    main()
