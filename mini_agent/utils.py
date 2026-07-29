"""零散小工具，供多个模块复用，避免重复定义。"""

from __future__ import annotations

from datetime import datetime, timezone


def now_utc_iso() -> str:
    """当前 UTC 时间的 ISO8601 字符串（用于时间戳/排序）。"""
    return datetime.now(timezone.utc).isoformat()
