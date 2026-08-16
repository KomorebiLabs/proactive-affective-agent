"""pytest 全局配置"""
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，确保 `from src.xxx import ...` 可正常工作
sys.path.insert(0, str(Path(__file__).parent.parent))
