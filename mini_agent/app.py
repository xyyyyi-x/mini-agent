"""Gradio 网页 UI —— 可新建/切换/删除会话的真实版。

左侧：当前用户的会话列表（新建 / 切换 / 删除）；
右侧：当前会话的聊天框 + trace 面板。

每个会话是一个独立 JSON 文件，互不干扰、重启后仍在，可随时接着聊。
（对照用的"双窗口并排"最小演示见 app_demo.py）

启动：python -m mini_agent.app
"""

from __future__ import annotations

import os
from typing import Optional

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

USER_ID = "userA"  # 演示用单一用户；接登录态即可扩展为多用户


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for tool_cls in (Calculator, Search, Weather, Todo):
        reg.register(tool_cls())
    return reg


# ---- 全局单例：注册表 / 会话管理器 / LLM / runtime 缓存 ----
_REGISTRY = build_default_registry()
_MGR = SessionManager(cfg=CONFIG)
_LLM: Optional[LLMClient] = None
_RUNTIMES: dict[str, AgentRuntime] = {}  # session_id -> runtime


def _get_llm() -> LLMClient:
    global _LLM
    if _LLM is None:
        _LLM = LLMClient(cfg=CONFIG)
    return _LLM


def _sid(window_id: str) -> str:
    return f"{USER_ID}__{window_id}"


def get_runtime(window_id: str) -> AgentRuntime:
    """按 window_id 取（首次则新建并缓存）对应的 runtime。"""
    sid = _sid(window_id)
    if sid not in _RUNTIMES:
        session = _MGR.load(USER_ID, window_id)
        _RUNTIMES[sid] = AgentRuntime(_get_llm(), _REGISTRY, session, Trace(cfg=CONFIG), cfg=CONFIG)
    return _RUNTIMES[sid]


def _auto_name() -> str:
    existing = set(list_windows())
    n = 1
    while f"会话{n}" in existing:
        n += 1
    return f"会话{n}"


def list_windows() -> list[str]:
    """当前用户已有的会话名，按“最近更新”在前。"""
    windows = [wid for _, wid, _ in _MGR.list_sessions(USER_ID)]

    def _mtime(wid: str) -> float:
        try:
            return os.path.getmtime(_MGR.path_for(USER_ID, wid))
        except Exception:
            return 0.0

    return sorted(windows, key=_mtime, reverse=True)


def _to_messages(history) -> list[dict]:
    """把会话历史转成 Gradio 6 Chatbot 要求的 messages 格式。

    内部存储用 [[user, answer], ...]（成对）；Gradio 6 的 Chatbot 只接受
    [{"role": "user"|"assistant", "content": "..."}]。
    本函数兼容两种输入，统一输出 messages 格式。
    """
    msgs: list[dict] = []
    for item in (history or []):
        if isinstance(item, dict):
            msgs.append(item)  # 已是 messages 格式
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            msgs.append({"role": "user", "content": item[0]})
            msgs.append({"role": "assistant", "content": item[1]})
    return msgs


# ---------- 事件处理（纯函数，便于离线测试） ----------
def on_new(name: str):
    """新建会话并选中它。返回: state_window, 会话列表, 聊天记录, trace, 清空输入框。"""
    name = (name or "").strip() or _auto_name()
    rt = get_runtime(name)
    rt.session.save()  # 落盘，使其进入列表
    windows = list_windows()
    return name, gr.update(choices=windows, value=name), _to_messages(rt.session.display_history), rt.trace.last_turn, ""


def on_select(window: Optional[str]):
    """切换到选中的会话，读回它的历史。"""
    if not window:
        return window, [], None
    rt = get_runtime(window)
    return window, _to_messages(rt.session.display_history), rt.trace.last_turn


def on_send(text: str, window: Optional[str], history):
    """在当前会话里发一条消息。"""
    text = (text or "").strip()
    if not text or not window:
        return _to_messages(history), "", None
    rt = get_runtime(window)
    answer = rt.handle_user_message(text)
    msgs = _to_messages(history)
    msgs.append({"role": "user", "content": text})
    msgs.append({"role": "assistant", "content": answer})
    return msgs, "", rt.trace.last_turn


def on_delete(window: Optional[str]):
    """删除当前会话，并切到列表里的下一个。"""
    if window:
        try:
            _MGR.delete(USER_ID, window)
        except Exception:
            pass
        _RUNTIMES.pop(_sid(window), None)
    windows = list_windows()
    if windows:
        cur = windows[0]
        rt = get_runtime(cur)
        return cur, gr.update(choices=windows, value=cur), _to_messages(rt.session.display_history), rt.trace.last_turn
    return None, gr.update(choices=windows, value=None), [], None


def on_init():
    """页面首次加载：列出已有会话；若一个都没有，就建一个默认会话。"""
    windows = list_windows()
    if not windows:
        get_runtime(_auto_name()).session.save()
        windows = list_windows()
    cur = windows[0]
    rt = get_runtime(cur)
    return cur, gr.update(choices=windows, value=cur), _to_messages(rt.session.display_history), rt.trace.last_turn


def build_demo():
    with gr.Blocks(title="Mini Agent (GLM)") as demo:
        gr.Markdown(
            "# Mini Agent —— 从零实现的最小可用 Agent\n"
            f"左侧管理 **{USER_ID}** 的会话（新建 / 切换 / 删除）。"
            "每个会话相互独立、重启后仍在，可随时接着聊。"
        )
        with gr.Row():
            with gr.Column(scale=1, min_width=220):
                gr.Markdown("### 📂 会话")
                session_list = gr.Radio(choices=[], label=f"{USER_ID} 的会话", value=None)
                new_name = gr.Textbox(placeholder="新会话名（留空自动命名）", show_label=False)
                new_btn = gr.Button("➕ 新建会话")
                del_btn = gr.Button("🗑 删除当前会话", variant="stop")
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(height=460, label="对话")
                msg = gr.Textbox(placeholder="问天气 / 记待办 / 算数……（回车或点发送）", show_label=False)
                send_btn = gr.Button("发送")
        with gr.Accordion("🔍 Trace —— 当前会话最近一轮的工具调用过程", open=False):
            trace_view = gr.JSON(label="trace")

        state_window = gr.State(value=None)

        # 事件绑定
        new_btn.click(on_new, [new_name],
                      [state_window, session_list, chatbot, trace_view, new_name], api_name="new")
        del_btn.click(on_delete, [state_window],
                      [state_window, session_list, chatbot, trace_view], api_name="delete")
        session_list.change(on_select, [session_list], [state_window, chatbot, trace_view])
        send_btn.click(on_send, [msg, state_window, chatbot],
                       [chatbot, msg, trace_view], api_name="send")
        msg.submit(on_send, [msg, state_window, chatbot],
                   [chatbot, msg, trace_view], api_name="send")
        demo.load(on_init, None, [state_window, session_list, chatbot, trace_view])

    return demo


def _find_free_port(start: int) -> int:
    """从 start 开始找一个可绑定的端口（避免端口冲突启动失败）。"""
    import socket
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def main():
    import traceback
    try:
        demo = build_demo()
        port = _find_free_port(int(os.getenv("PORT", "7860")))
        # 用醒目方式打印地址，方便手动复制到浏览器
        print("\n" + "=" * 52)
        print(f"  Mini Agent 已启动，请在浏览器打开：")
        print(f"      http://127.0.0.1:{port}")
        print("=" * 52 + "\n", flush=True)
        demo.launch(server_name=os.getenv("HOST", "127.0.0.1"),
                    server_port=port, inbrowser=True, show_error=True)
    except Exception:
        traceback.print_exc()
        input("\n[启动失败] 上面是完整报错。把它截图/复制发给开发者。按回车退出...")


if __name__ == "__main__":
    main()
