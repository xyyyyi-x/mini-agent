"""真实 LLM API 冒烟测试（题目：需要使用真实的 LLM Api）。

无 ZHIPU_API_KEY / GLM_API_KEY 时自动跳过，不消耗额度、不阻塞 CI。
"""

import os

import pytest

from mini_agent.agent.runtime import AgentRuntime
from mini_agent.config import Config
from mini_agent.session.manager import SessionManager
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.calculator import Calculator
from mini_agent.tools.search import Search
from mini_agent.tools.todo import Todo
from mini_agent.tools.weather import Weather
from mini_agent.trace import Trace

_HAS_KEY = bool(os.getenv("LLM_API_KEY") or os.getenv("ZHIPU_API_KEY") or os.getenv("GLM_API_KEY"))
pytestmark = pytest.mark.skipif(not _HAS_KEY, reason="未设置 ZHIPU_API_KEY，跳过真实 API 测试")


def _build(tmp_path):
    cfg = Config(SESSIONS_DIR=str(tmp_path), LOGS_DIR=str(tmp_path))
    from mini_agent.llm_client import LLMClient
    llm = LLMClient(cfg=cfg)
    mgr = SessionManager(cfg=cfg)
    session = mgr.load("smoke_user", "smoke_window")
    reg = ToolRegistry()
    for cls in (Calculator, Search, Weather, Todo):
        reg.register(cls())
    trace = Trace(cfg=cfg)
    return AgentRuntime(llm, reg, session, trace, cfg=cfg), trace


def test_calculator_via_real_api(tmp_path):
    rt, trace = _build(tmp_path)
    answer = rt.handle_user_message("请用计算器算一下 17 乘以 23 等于多少？")
    assert "391" in answer
    # trace 应记录至少一次 calculator 工具调用
    actions = [it["action"] for it in trace.last_turn["iterations"] if it["action"]]
    assert "calculator" in actions


def test_weather_via_real_api(tmp_path):
    rt, trace = _build(tmp_path)
    answer = rt.handle_user_message("北京今天天气怎么样？")
    assert "北京" in answer and "°C" in answer
    actions = [it["action"] for it in trace.last_turn["iterations"] if it["action"]]
    assert "weather" in actions
