"""Agent 内部的共享数据类型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedOutput:
    """解析 LLM 输出后的标准化结果。

    - action 为 None 且 final_answer 非 None：直接回复用户。
    - action 非 None：本轮要调用工具（此时 final_answer 一定为 None）。
    """

    thought: str
    action: Optional[str]
    action_input: Optional[dict]
    final_answer: Optional[str]
    raw: str  # LLM 的原始输出，便于排查
