"""双引擎收益模型入口 (模型实现已迁至 src/economics.py).

保留 `python scripts/economics.py` 命令与既有导入路径兼容.
"""
from __future__ import annotations

import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from src.economics import *  # noqa: F401,F403
from src.economics import main  # noqa: F401,E402

if __name__ == "__main__":
    raise SystemExit(main())
