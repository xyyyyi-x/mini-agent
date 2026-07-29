"""Context 管理测试（题目：context 有效管理 + 压缩）。"""

from mini_agent.agent.context import Context
from mini_agent.config import Config
from mini_agent.testing import FakeLLM


def _cfg(**over):
    base = dict(KEEP_RECENT=4, COMPRESS_AT_MESSAGES=10, COMPRESS_AT_TOKENS=3000,
                HARD_TOKEN_CEILING=6000)
    base.update(over)
    return Config(**base)


def test_build_messages_ordering():
    ctx = Context(cfg=_cfg())
    ctx.add_user_message("你好")
    ctx.add_assistant_message("Thought: t\nFinal Answer: 你好！")
    msgs = ctx.build_messages("SYS")
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1]["role"] == "user" and msgs[1]["content"] == "你好"
    assert msgs[2]["role"] == "assistant"
    # 没有摘要时不该出现摘要消息
    assert len([m for m in msgs if m["content"].startswith("之前对话的摘要")]) == 0


def test_summary_inserted_when_present():
    ctx = Context(cfg=_cfg())
    ctx.summary = "用户曾问天气"
    msgs = ctx.build_messages("SYS")
    assert any("用户曾问天气" in m["content"] for m in msgs if m["role"] == "system")


def test_compress_noop_below_threshold():
    cfg = _cfg()
    ctx = Context(cfg=cfg)
    llm = FakeLLM()
    for i in range(5):  # 低于阈值
        ctx.add_user_message(f"msg {i}")
    ctx.compress_if_needed(llm)
    assert len(ctx.entries) == 5
    assert llm.summarize_calls == []  # 没调用压缩
    assert ctx.summary is None


def test_compress_triggers_and_keeps_recent():
    cfg = _cfg(KEEP_RECENT=4, COMPRESS_AT_MESSAGES=10, COMPRESS_AT_TOKENS=1)
    ctx = Context(cfg=cfg)
    llm = FakeLLM()
    for i in range(12):
        ctx.add_user_message(f"消息编号 {i}")
    ctx.compress_if_needed(llm)
    # 触发压缩：保留最近 KEEP_RECENT 条
    assert len(ctx.entries) == cfg.KEEP_RECENT
    assert ctx.summary is not None and "FAKE SUMMARY" in ctx.summary
    assert len(llm.summarize_calls) == 1
    # 保留的是最后 4 条
    assert "消息编号 11" in ctx.entries[-1]["content"]


def test_compress_summary_is_cumulative():
    cfg = _cfg(KEEP_RECENT=2, COMPRESS_AT_MESSAGES=4, COMPRESS_AT_TOKENS=1)
    ctx = Context(cfg=cfg)
    llm = FakeLLM()
    ctx.summary = "旧摘要"
    for i in range(6):
        ctx.add_user_message(f"m{i}")
    ctx.compress_if_needed(llm)
    # 第二次摘要应把上一次摘要并入（传给 summarize 的 prev_summary == "旧摘要"）
    assert llm.summarize_calls[-1][1] == "旧摘要"


def test_est_tokens_includes_summary():
    """summary 也计入 token 估算（L5），否则越压越长的摘要无人管。"""
    ctx = Context(cfg=_cfg())
    ctx.add_user_message("hi")  # 2 字符 → 0 token
    assert ctx._est_tokens() == 0
    ctx.summary = "X" * 400  # 400 字符 → 100 token
    assert ctx._est_tokens() == 100


def test_hard_token_ceiling_drops_oldest():
    # HARD_TOKEN_CEILING 设在“大于摘要、小于 KEEP_RECENT 条消息”之间，
    # 这样压缩后会因硬上限继续丢弃，最终条数低于 KEEP_RECENT。
    cfg = _cfg(KEEP_RECENT=4, COMPRESS_AT_MESSAGES=4, COMPRESS_AT_TOKENS=1,
               HARD_TOKEN_CEILING=100)
    ctx = Context(cfg=cfg)
    llm = FakeLLM()
    for i in range(6):
        ctx.add_user_message("X" * 200)  # 每条 50 token
    ctx.compress_if_needed(llm)
    # 硬上限迫使丢到 ceiling 以内（或 entries 为空、无法再丢）
    assert ctx._est_tokens() <= cfg.HARD_TOKEN_CEILING or ctx.entries == []
    # 且确实被压到了 KEEP_RECENT 以下
    assert len(ctx.entries) < cfg.KEEP_RECENT
