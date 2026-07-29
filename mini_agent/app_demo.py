"""Gradio 演示页（对照版）：两个固定并排窗口，直观展示“会话独立性”。

这是早期用来一眼看清“两个窗口互不干扰”的最小演示。
完整的“可新建/切换会话”版本在 app.py。

启动：python -m mini_agent.app_demo
"""

from __future__ import annotations

import os

import gradio as gr

from .agent.runtime import AgentRuntime
from .config import CONFIG
from .llm_client import LLMClient
from .session.manager import SessionManager
from .tools.base import ToolRegistry
from .tools.calculator import Calculator
from .tools.search import Search
from .tools.todo import Todo
from .tools.weather import Weather
from .trace import Trace

USER_ID = "userA"


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for tool_cls in (Calculator, Search, Weather, Todo):
        reg.register(tool_cls())
    return reg


def _to_messages(history) -> list[dict]:
    """转成 Gradio 6 Chatbot 要求的 messages 格式（兼容成对历史）。"""
    msgs: list[dict] = []
    for item in (history or []):
        if isinstance(item, dict):
            msgs.append(item)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            msgs.append({"role": "user", "content": item[0]})
            msgs.append({"role": "assistant", "content": item[1]})
    return msgs


def make_runtime(window_id: str, llm: LLMClient):
    mgr = SessionManager(cfg=CONFIG)
    session = mgr.load(USER_ID, window_id)
    trace = Trace(cfg=CONFIG)
    runtime = AgentRuntime(llm, build_default_registry(), session, trace, cfg=CONFIG)
    return runtime, session


def make_send(runtime: AgentRuntime):
    def send(text: str, history):
        text = (text or "").strip()
        if not text:
            return _to_messages(history), "", runtime.trace.last_turn
        answer = runtime.handle_user_message(text)
        msgs = _to_messages(history)
        msgs.append({"role": "user", "content": text})
        msgs.append({"role": "assistant", "content": answer})
        return msgs, "", runtime.trace.last_turn

    return send


def build_demo():
    llm = LLMClient(cfg=CONFIG)
    rt1, sess1 = make_runtime("window1", llm)
    rt2, sess2 = make_runtime("window2", llm)
    send1 = make_send(rt1)
    send2 = make_send(rt2)

    with gr.Blocks(title="Mini Agent (GLM) - demo") as demo:
        gr.Markdown(
            "# Mini Agent —— 双窗口独立性演示（对照版）\n"
            "完整可新建/切换会话的版本见 app.py。"
        )
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 🪟 窗口1 · weather + todo")
                chat1 = gr.Chatbot(value=_to_messages(sess1.display_history), height=460, label="window1")
                txt1 = gr.Textbox(placeholder="北京天气？ / 记待办：买牛奶", label="窗口1 输入")
                btn1 = gr.Button("发送（窗口1）")
            with gr.Column():
                gr.Markdown("### 🪟 窗口2 · 周报 + todo")
                chat2 = gr.Chatbot(value=_to_messages(sess2.display_history), height=460, label="window2")
                txt2 = gr.Textbox(placeholder="算17*23 / 记待办：周五开会", label="窗口2 输入")
                btn2 = gr.Button("发送（窗口2）")
        with gr.Accordion("🔍 Trace（最近一轮）", open=False):
            trace_view = gr.JSON(value=None)

        btn1.click(send1, [txt1, chat1], [chat1, txt1, trace_view])
        txt1.submit(send1, [txt1, chat1], [chat1, txt1, trace_view])
        btn2.click(send2, [txt2, chat2], [chat2, txt2, trace_view])
        txt2.submit(send2, [txt2, chat2], [chat2, txt2, trace_view])

    return demo


def main():
    demo = build_demo()
    demo.launch(server_name=os.getenv("HOST", "127.0.0.1"),
                server_port=int(os.getenv("PORT", "7860")), inbrowser=True)


if __name__ == "__main__":
    main()
