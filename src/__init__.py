"""GitHub 精选专题合集自动化生产引擎.

零依赖实现: 仅使用 Python 标准库 (3.9+).
分层: gh_client (数据) -> compliance (过滤) -> downloader (落地)
      -> packer (标准化目录) -> listing (商品与发货文案) -> cli (编排).
"""
from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["gh_client", "compliance", "downloader", "packer", "listing", "pan", "scheduler", "cli"]
