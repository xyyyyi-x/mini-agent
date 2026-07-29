"""终端交互模式 —— 不依赖浏览器/端口/防火墙，最稳。

和网页版用的是同一套引擎（runtime / 工具 / session / trace），只是界面换成终端。
题目接受"终端操作录屏"，所以用这个交付也完全合规。

启动：python -m mini_agent.cli
"""

from __future__ import annotations

import sys

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


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for tool_cls in (Calculator, Search, Weather, Todo):
        reg.register(tool_cls())
    return reg


def _make_runtime(llm, reg, mgr, window):
    return AgentRuntime(llm, reg, mgr.load(USER_ID, window), Trace(cfg=CONFIG), cfg=CONFIG)


def main():
    # Windows 控制台默认 GBK，中文输出会乱码；强制 stdout/stderr 用 UTF-8。
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    try:
        llm = LLMClient(cfg=CONFIG)
    except Exception as e:
        print(f"[启动失败] {e}")
        print("请检查 .env 里的 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 是否正确。")
        return

    reg = build_registry()
    mgr = SessionManager(cfg=CONFIG)
    window = "会话1"
    rt = _make_runtime(llm, reg, mgr, window)

    print("=" * 56)
    print("  Mini Agent 终端模式（与网页版同一套引擎）")
    print("  命令：")
    print("    /new [名字]     新建会话     /switch 名字   切换会话")
    print("    /list           列出会话     /quit          退出")
    print(f"  当前会话：{window}")
    print("=" * 56)
    print('试着问：北京天气？ / 帮我记个待办：买牛奶 / 算一下 17*23')

    while True:
        try:
            text = input("\n你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        # 防御：Windows 下中文可能被读成无效"代理字符"，导致发往 LLM 时 UTF-8 编码失败。
        # 用 replace 清洗掉这类字符，保证不会因为编码崩溃。
        try:
            text = text.encode("utf-8", "replace").decode("utf-8")
        except Exception:
            pass

        if not text:
            continue
        if text in ("/quit", "/exit", "/q"):
            print("再见！")
            break

        if text == "/list":
            windows = [w for _, w, _ in mgr.list_sessions(USER_ID)]
            print("已有会话：", windows or "(无)")
            continue

        if text.startswith("/new"):
            name = text[4:].strip()
            if not name:
                existing = len(mgr.list_sessions(USER_ID))
                name = f"会话{existing + 1}"
            try:
                window = name
                rt = _make_runtime(llm, reg, mgr, window)
                print(f"[已新建并切换到会话：{window}]")
            except Exception as e:
                print(f"[新建失败] {e}（会话名不要含 / \\ .. ）")
            continue

        if text.startswith("/switch"):
            name = text[7:].strip()
            if not name:
                print("用法：/switch 会话名")
                continue
            try:
                window = name
                rt = _make_runtime(llm, reg, mgr, window)
                print(f"[已切换到会话：{window}]（历史已从磁盘读回）")
            except Exception as e:
                print(f"[切换失败] {e}")
            continue

        # 普通对话
        try:
            answer = rt.handle_user_message(text)
            print(f"Agent > {answer}")
            last = rt.trace.last_turn or {}
            actions = [it["action"] for it in last.get("iterations", []) if it["action"]]
            if actions:
                print(f"  ↳ 本轮工具调用：{actions}")
        except Exception as e:
            print(f"[处理出错] {e!r}，请重试。")


if __name__ == "__main__":
    main()
