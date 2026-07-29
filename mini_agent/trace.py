"""Trace：每一轮的工具调用过程日志（题目要求"工具调用 trace 或执行日志"）。

每轮记录：session_id、用户输入、每一轮迭代的 thought/action/action_input、
所有 observation、最终答案、错误（默认 None）。
落盘到 logs/trace.jsonl（每轮一行），同时在内存保留 last_turn 供 UI 展示。
"""

from __future__ import annotations

import json
import os
import sys
import threading
from typing import Optional

from .config import Config, CONFIG
from .utils import now_utc_iso as _now


class Turn:
    """一次用户输入对应的一次完整 Agent 运行。"""

    def __init__(self, trace: "Trace", session_id: str, user_input: str):
        self.trace = trace
        self.session_id = session_id
        self.input = user_input
        self.started_at = _now()
        self.iterations: list[dict] = []  # [{idx, thought, action, action_input}]
        self.observations: list[str] = []
        self.final_answer: Optional[str] = None
        self.error: Optional[str] = None
        self.ended_at: Optional[str] = None

    def add_iteration(self, idx: int, parsed) -> None:
        self.iterations.append(
            {
                "idx": idx,
                "thought": parsed.thought,
                "action": parsed.action,
                "action_input": parsed.action_input,
            }
        )

    def add_observation(self, observation: str) -> None:
        self.observations.append(observation)

    def finalize(self, final_answer: Optional[str], error: Optional[str] = None) -> None:
        self.final_answer = final_answer
        self.error = error
        self.ended_at = _now()
        self.trace._commit(self)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "input": self.input,
            "started_at": self.started_at,
            "iterations": self.iterations,
            "observations": self.observations,
            "final_answer": self.final_answer,
            "error": self.error,
            "ended_at": self.ended_at,
        }


class Trace:
    # 类级共享锁：多个 Trace 实例（如两个窗口）写同一个 trace.jsonl 时，
    # 必须共用同一把锁，否则并发追加可能导致 JSONL 行交错/损坏。
    _FILE_LOCK = threading.Lock()

    def __init__(self, logs_dir: Optional[str] = None, cfg: Optional[Config] = None):
        self.cfg = cfg or CONFIG
        self.logs_dir = logs_dir or self.cfg.LOGS_DIR
        os.makedirs(self.logs_dir, exist_ok=True)
        self.path = os.path.join(self.logs_dir, "trace.jsonl")
        self._counter = 0
        self.last_turn: Optional[dict] = None

    def begin_turn(self, session_id: str, user_input: str) -> Turn:
        return Turn(self, session_id, user_input)

    def _commit(self, turn: Turn) -> None:
        with Trace._FILE_LOCK:
            self._counter += 1
            data = turn.to_dict()
            data["turn_id"] = self._counter
            self.last_turn = data
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(data, ensure_ascii=False) + "\n")
            except Exception as e:
                # 日志写失败不应影响主流程，但留一条线索便于排障
                print(f"[warn] trace 写入失败：{e!r}", file=sys.stderr)
