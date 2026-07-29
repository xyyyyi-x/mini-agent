"""工具与注册机制测试（题目：工具相关 + 注册机制）。"""

import pytest

from mini_agent.config import Config
from mini_agent.session.manager import Session, SessionManager
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.calculator import Calculator, safe_eval
from mini_agent.tools.search import Search
from mini_agent.tools.todo import Todo
from mini_agent.tools.weather import Weather


def _ctx(session):
    return ToolContext(session=session)


# ---------- 注册机制 ----------
def test_registry_register_and_get():
    reg = ToolRegistry()
    reg.register(Calculator())
    reg.register(Search())
    assert set(reg.names()) == {"calculator", "search"}
    assert reg.get("calculator").name == "calculator"
    assert reg.get("not_exist") is None
    assert reg.get(None) is None


def test_registry_exposes_schema():
    reg = ToolRegistry()
    reg.register(Calculator())
    tool = reg.get("calculator")
    # 每个工具自带 name / description / schema
    assert tool.name == "calculator"
    assert isinstance(tool.description, str) and tool.description
    assert tool.schema["type"] == "object"
    assert "expr" in tool.schema["properties"]
    assert tool.schema["required"] == ["expr"]


# ---------- calculator ----------
def test_calculator_basic_and_precedence():
    calc = Calculator()
    ctx = _ctx(None)
    assert "= 14" in calc.run({"expr": "2 + 3 * 4"}, ctx)
    assert "= 20" in calc.run({"expr": "(2 + 3) * 4"}, ctx)
    assert "= 42" in calc.run({"expr": "6 * 7"}, ctx)
    assert "= 391" in calc.run({"expr": "17 * 23"}, ctx)


def test_calculator_safe_eval_directly():
    assert safe_eval("1 + 2") == 3
    assert safe_eval("2 ** 10") == 1024
    assert safe_eval("10 / 4") == 2.5


def test_calculator_errors_never_raise():
    calc = Calculator()
    ctx = _ctx(None)
    # 除零
    assert "Error" in calc.run({"expr": "1 / 0"}, ctx)
    # 缺参数
    assert "Error" in calc.run({}, ctx)
    # 垃圾输入
    assert "Error" in calc.run({"expr": "你好"}, ctx)
    assert "Error" in calc.run({"expr": "__import__('os')"}, ctx)
    # 非法表达式（注入尝试应被拒绝）
    assert "Error" in calc.run({"expr": "open('x')"}, ctx)


# ---------- search (mock) ----------
def test_search_mock_returns_hits():
    s = Search()
    ctx = _ctx(None)
    out = s.run({"query": "python"}, ctx)
    assert "Python" in out
    out2 = s.run({"query": "agent"}, ctx)
    assert "Agent" in out2 or "agent" in out2
    # 无匹配时给占位结果，不报错
    out3 = s.run({"query": "量子纠缠"}, ctx)
    assert "mock" in out3
    assert "Error" in s.run({}, ctx)


# ---------- weather (mock) ----------
def test_weather_mock():
    w = Weather()
    ctx = _ctx(None)
    out = w.run({"city": "北京"}, ctx)
    assert "北京" in out and "°C" in out
    unknown = w.run({"city": "月球"}, ctx)
    assert "mock" in unknown  # 未知城市友好提示
    assert "Error" in w.run({}, ctx)


# ---------- todo (会话级，多 session 独立) ----------
def test_todo_crud_within_session(tmp_path):
    cfg = Config(SESSIONS_DIR=str(tmp_path), LOGS_DIR=str(tmp_path))
    mgr = SessionManager(cfg=cfg)
    session = mgr.load("u", "w")
    todo = Todo()
    ctx = _ctx(session)

    assert "为空" in todo.run({"command": "list"}, ctx)
    assert "已添加待办 #1" in todo.run({"command": "add", "text": "买牛奶"}, ctx)
    assert "已添加待办 #2" in todo.run({"command": "add", "text": "写周报"}, ctx)

    listing = todo.run({"command": "list"}, ctx)
    assert "买牛奶" in listing and "写周报" in listing

    assert "已完成待办 #1" in todo.run({"command": "complete", "id": 1}, ctx)
    # complete 后状态持久化到 session.tool_state
    items = session.tool_state["todo"]["items"]
    assert items[0]["done"] is True

    assert "已删除待办 #2" in todo.run({"command": "delete", "id": 2}, ctx)
    assert len(session.tool_state["todo"]["items"]) == 1

    # 找不到的 id
    assert "Error" in todo.run({"command": "complete", "id": 999}, ctx)
    # 未知 command
    assert "Error" in todo.run({"command": "fly"}, ctx)
    # add 缺 text
    assert "Error" in todo.run({"command": "add"}, ctx)


def test_todo_isolated_between_sessions(tmp_path):
    """关键：两个 session 的待办互相独立（题目 session 管理要求）。"""
    cfg = Config(SESSIONS_DIR=str(tmp_path), LOGS_DIR=str(tmp_path))
    mgr = SessionManager(cfg=cfg)
    s1 = mgr.load("userA", "window1")
    s2 = mgr.load("userA", "window2")
    todo = Todo()

    todo.run({"command": "add", "text": "窗口1的待办"}, _ctx(s1))
    todo.run({"command": "add", "text": "窗口2的待办"}, _ctx(s2))

    list1 = todo.run({"command": "list"}, _ctx(s1))
    list2 = todo.run({"command": "list"}, _ctx(s2))
    assert "窗口1的待办" in list1 and "窗口2的待办" not in list1
    assert "窗口2的待办" in list2 and "窗口1的待办" not in list2


# ---------- calculator 资源上限（DoS 防护，M1）----------
def test_calculator_rejects_runaway_power():
    """9**9**9 会算出 3 亿多位数字、可挂死进程；现在应被指数上限立即拦下。"""
    calc = Calculator()
    ctx = _ctx(None)
    assert "Error" in calc.run({"expr": "9**9**9"}, ctx)
    assert "Error" in calc.run({"expr": "2**100000"}, ctx)
    # 普通幂运算不受影响
    assert "= 1024" in calc.run({"expr": "2**10"}, ctx)


def test_safe_eval_rejects_runaway_power():
    with pytest.raises(ValueError):
        safe_eval("9**9**9")
    with pytest.raises(ValueError):
        safe_eval("2**100000")
    assert safe_eval("2**10") == 1024


# ---------- todo id 类型（M4）----------
def test_todo_accepts_string_id(tmp_path):
    """LLM 可能传字符串 "1"；complete/delete 应能正常工作而非静默失败。"""
    cfg = Config(SESSIONS_DIR=str(tmp_path), LOGS_DIR=str(tmp_path))
    session = SessionManager(cfg=cfg).load("u", "w")
    todo = Todo()
    ctx = _ctx(session)
    todo.run({"command": "add", "text": "任务A"}, ctx)

    assert "已完成待办 #1" in todo.run({"command": "complete", "id": "1"}, ctx)
    assert session.tool_state["todo"]["items"][0]["done"] is True
    assert "已删除待办 #1" in todo.run({"command": "delete", "id": 1}, ctx)
    # 非数字 id 给明确错误
    assert "Error" in todo.run({"command": "complete", "id": "abc"}, ctx)


def test_todo_add_multiple_items(tmp_path):
    """一次传多条（逗号/顿号/换行分隔）应拆成多条分别记录，不能只记最后一条。"""
    cfg = Config(SESSIONS_DIR=str(tmp_path), LOGS_DIR=str(tmp_path))
    session = SessionManager(cfg=cfg).load("u", "w")
    todo = Todo()
    ctx = _ctx(session)

    out = todo.run({"command": "add", "text": "早上跑步，下午面试，晚上学python"}, ctx)
    items = session.tool_state["todo"]["items"]
    assert [i["text"] for i in items] == ["早上跑步", "下午面试", "晚上学python"]
    assert "#1" in out and "#2" in out and "#3" in out

    # 顿号、换行也能拆；单条不受影响
    session2 = SessionManager(cfg=Config(SESSIONS_DIR=str(tmp_path) + "2", LOGS_DIR=str(tmp_path))).load("u", "w2")
    out2 = todo.run({"command": "add", "text": "A、B\nC"}, _ctx(session2))
    assert [i["text"] for i in session2.tool_state["todo"]["items"]] == ["A", "B", "C"]
    out3 = todo.run({"command": "add", "text": "只有一条"}, _ctx(session2))
    assert "已添加待办 #4" in out3  # 接着上面的编号
