"""测试辅助：FakeLLM 与一个开箱即用的 runtime 工厂。

FakeLLM 与真实 LLMClient 接口一致（chat / summarize），但脚本化返回、记录调用，
使全套循环测试零网络、零花费、确定可复现。
"""

from __future__ import annotations

from typing import Callable, Optional, Union

from .agent.runtime import AgentRuntime
from .config import Config
from .session.manager import SessionManager
from .tools.base import ToolRegistry
from .tools.calculator import Calculator
from .tools.search import Search
from .tools.todo import Todo
from .tools.weather import Weather
from .trace import Trace

Scriptable = Union[list[str], Callable[[list[dict]], str]]


class FakeLLM:
    """假 LLM：按队列返回脚本化回复，同时记录每次被发送的 messages。"""

    def __init__(self, scripted: Optional[Scriptable] = None):
        self._callable: Optional[Callable[[list[dict]], str]] = None
        self._queue: list[str] = []
        if callable(scripted) and not isinstance(scripted, list):
            self._callable = scripted
        elif isinstance(scripted, list):
            self._queue = list(scripted)
        # 默认兜底回复：直接给出 final_answer，避免测试中queue耗尽时报错
        self._default = (
            '{"thought":"(fake)","action":null,"action_input":null,'
            '"final_answer":"(no more scripted responses)"}'
        )
        self.calls: list[list[dict]] = []  # 每次 chat 收到的 messages
        self.summarize_calls: list[tuple[str, Optional[str]]] = []

    def chat(self, messages: list[dict], temperature: float = 0.2,
             response_format: Optional[dict] = None) -> str:
        self.calls.append(messages)
        if self._callable is not None:
            return self._callable(messages)
        if self._queue:
            return self._queue.pop(0)
        return self._default

    def summarize(self, transcript: str, prev_summary: Optional[str] = None) -> str:
        self.summarize_calls.append((transcript, prev_summary))
        return "FAKE SUMMARY: " + (transcript or "")[:80]


def build_runtime(
    scripted: Optional[Scriptable] = None,
    cfg: Optional[Config] = None,
    user_id: str = "u",
    window_id: str = "w",
    tools: Optional[list] = None,
) -> tuple[AgentRuntime, FakeLLM, Trace, "object"]:
    """快速构造一个用 FakeLLM 的 runtime，供测试使用。"""
    if cfg is None:
        raise ValueError("请传入 cfg（建议用临时目录与小阈值）")
    llm = FakeLLM(scripted)
    manager = SessionManager(cfg=cfg)
    session = manager.load(user_id, window_id)
    registry = ToolRegistry()
    for tool_cls in (tools or [Calculator, Search, Weather, Todo]):
        registry.register(tool_cls())
    trace = Trace(cfg=cfg)
    runtime = AgentRuntime(llm, registry, session, trace, cfg=cfg)
    return runtime, llm, trace, session
