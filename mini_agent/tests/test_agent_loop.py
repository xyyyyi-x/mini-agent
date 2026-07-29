"""核心循环测试（题目：基本循环 + context + 追问 + 异常 + trace）。

全部用 FakeLLM，零网络、确定可复现。
"""

import json

from mini_agent.config import Config
from mini_agent.tools.base import Tool, ToolContext
from mini_agent.testing import FakeLLM, build_runtime


def _cfg(tmp_path, **over):
    base = dict(SESSIONS_DIR=str(tmp_path), LOGS_DIR=str(tmp_path))
    base.update(over)
    return Config(**base)


def _all_text(messages):
    return "\n".join(m.get("content", "") for m in messages)


def _json(thought, action=None, action_input=None, final=None):
    return json.dumps({
        "thought": thought,
        "action": action,
        "action_input": action_input,
        "final_answer": final,
    }, ensure_ascii=False)


# ---------- Step 2 分支：直接回复 vs 工具 ----------
def test_direct_reply_no_tool(tmp_path):
    scripted = [_json("打招呼", final="你好！有什么可以帮你？")]
    rt, llm, trace, _ = build_runtime(scripted, cfg=_cfg(tmp_path))
    answer = rt.handle_user_message("你好")
    assert "你好" in answer
    assert len(llm.calls) == 1  # 只调一次 LLM，没有工具
    assert all(it["action"] is None for it in trace.last_turn["iterations"])
    assert trace.last_turn["observations"] == []


def test_single_tool_then_answer(tmp_path):
    scripted = [
        _json("用计算器", action="calculator", action_input={"expr": "6*7"}),
        _json("结果是42", final="6 乘以 7 等于 42。"),
    ]
    rt, llm, trace, _ = build_runtime(scripted, cfg=_cfg(tmp_path))
    answer = rt.handle_user_message("6*7=?")
    assert "42" in answer
    # 第二次调用 LLM 时，消息里应带上第一次的工具结果（带工具的上下文）
    assert "42" in _all_text(llm.calls[1])
    assert len(trace.last_turn["iterations"]) == 2


def test_multi_step_tools(tmp_path):
    scripted = [
        _json("先算", action="calculator", action_input={"expr": "2*3"}),
        _json("再搜", action="search", action_input={"query": "agent"}),
        _json("综合回答", final="算出来6，并搜到了 agent 资料。"),
    ]
    rt, llm, trace, _ = build_runtime(scripted, cfg=_cfg(tmp_path))
    answer = rt.handle_user_message("帮我算2*3并搜一下agent")
    assert "6" in answer
    assert len(trace.last_turn["iterations"]) == 3
    assert len(trace.last_turn["observations"]) == 2


# ---------- 异常处理 ----------
class _BoomTool(Tool):
    name = "boom"
    description = "测试用：总是抛异常的工具。"
    schema = {"type": "object", "properties": {}}

    def run(self, action_input, ctx):
        raise RuntimeError("boom!")


def test_unknown_tool_gives_error_observation(tmp_path):
    scripted = [
        _json("调一个不存在的", action="nonsense"),
        _json("好吧", final="我搞不定。"),
    ]
    rt, llm, trace, _ = build_runtime(scripted, cfg=_cfg(tmp_path))
    rt.handle_user_message("test")
    assert "未知工具" in trace.last_turn["observations"][0]
    assert "calculator" in trace.last_turn["observations"][0]  # 列出可用工具


def test_tool_exception_continues_loop(tmp_path):
    scripted = [
        _json("调用boom", action="boom"),
        _json("出错了我换个方式", final="我换种方式回答。"),
    ]
    # 只注册 boom 工具即可（脚本里只调用 boom）
    rt, llm, trace, _ = build_runtime(scripted, cfg=_cfg(tmp_path), tools=[_BoomTool])
    answer = rt.handle_user_message("test")
    assert "Error executing boom" in trace.last_turn["observations"][0]
    assert "换种方式" in answer


# ---------- 上限与防死循环 ----------
def test_max_iterations_cap(tmp_path):
    # FakeLLM 永远只调用计算器
    def always_calc(_messages):
        return _json("再算", action="calculator", action_input={"expr": "1+1"})

    cfg = _cfg(tmp_path, MAX_INNER_ITERATIONS=3)
    rt, llm, trace, _ = build_runtime(always_calc, cfg=cfg)
    answer = rt.handle_user_message("死循环测试")
    assert "限定轮次" in answer
    assert trace.last_turn["error"] == "MAX_ITERATIONS_EXCEEDED"
    assert len(trace.last_turn["iterations"]) == 3


def test_repeated_call_detection(tmp_path):
    scripted = [
        _json("算6*7", action="calculator", action_input={"expr": "6*7"}),
        _json("再算一遍", action="calculator", action_input={"expr": "6*7"}),
        _json("好了", final="结果是42。"),
    ]
    rt, llm, trace, _ = build_runtime(scripted, cfg=_cfg(tmp_path))
    answer = rt.handle_user_message("test")
    assert "42" in answer
    # 第二次相同调用应被检测到
    assert "已经" in trace.last_turn["observations"][1] or "相同参数" in trace.last_turn["observations"][1]


# ---------- 落盘续聊 ----------
def test_persistence_across_turns_and_restart(tmp_path):
    cfg = _cfg(tmp_path)
    rt1, _, _, _ = build_runtime([_json("ok", final="第一次回答。")], cfg=cfg)
    rt1.handle_user_message("第一轮")

    # 模拟“重启”：用全新的 runtime 从磁盘加载同一 session
    rt2, llm2, _, _ = build_runtime([_json("记得", final="我记着你说过。")], cfg=cfg)
    rt2.handle_user_message("第二轮")
    # 第二轮发给 LLM 的消息里应包含第一轮的内容（跨重启记忆）
    assert "第一轮" in _all_text(llm2.calls[0]) or "第一次回答" in _all_text(llm2.calls[0])


# ---------- 追问 ----------
def test_tool_aware_followup(tmp_path):
    cfg = _cfg(tmp_path)
    rt, llm, trace, _ = build_runtime(
        [_json("记待办", action="todo", action_input={"command": "add", "text": "买牛奶"}),
         _json("记好了", final="已帮你记下。")],
        cfg=cfg,
    )
    rt.handle_user_message("帮我记个待办：买牛奶")

    n_before = len(llm.calls)
    # 第二轮：让 FakeLLM 直接回答；断言它能看到第一轮工具产生的 observation
    llm._queue.append(_json("回忆", final="你刚记了买牛奶。"))
    rt.handle_user_message("我刚才记了什么？")
    turn2_messages = _all_text(llm.calls[n_before])
    assert "买牛奶" in turn2_messages  # 带工具的追问能拿到上轮工具结果


def test_pure_conversation_followup(tmp_path):
    cfg = _cfg(tmp_path)
    rt, llm, _, _ = build_runtime([_json("记下", final="好的 Bob。")], cfg=cfg)
    rt.handle_user_message("我叫 Bob")

    n_before = len(llm.calls)
    llm._queue.append(_json("回忆", final="你叫 Bob。"))
    rt.handle_user_message("我叫什么名字？")
    turn2_messages = _all_text(llm.calls[n_before])
    assert "Bob" in turn2_messages  # 纯对话追问能记住上轮信息


def test_display_history_records_turns(tmp_path):
    cfg = _cfg(tmp_path)
    rt, _, _, session = build_runtime([_json("ok", final="你好。")], cfg=cfg)
    rt.handle_user_message("你好")
    assert session.display_history == [["你好", "你好。"]]
