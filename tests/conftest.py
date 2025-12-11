import sys
from pathlib import Path

# 确保项目根目录在 sys.path，便于测试内直接以顶层包名导入
ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)
