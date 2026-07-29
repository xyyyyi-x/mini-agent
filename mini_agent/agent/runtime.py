"""核心 Agent Runtime —— 从零手写的 Agent 主循环。

对应题目要求的 4 步循环：
    Step 1 接收用户输入
    Step 2 判断直接回复还是调用工具
    Step 3 调用工具
    Step 4 根据工具结果判断继续 loop 还是返回结果给用户

不使用任何 Agent 框架；只依赖自实现的 parser / context / tools / trace。
"""

from __future__ import annotations

import json
from typing import Optional

from ..config import Config, CONFIG
from ..tools.base import ToolContext, ToolRegistry
from ..trace import Trace
from . import parser
from .prompt import build_system_prompt


def _truncate(text: Optional[str], max_chars: int) -> str:
    if text is None:
        return ""
    s = str(text)
    return s if len(s) <= max_chars else s[:max_chars] + "…"


class AgentRuntime:
    def __init__(self, llm, registry: ToolRegistry, session, trace: Trace,
                 cfg: Optional[Config] = None):
        self.llm = llm
        self.registry = registry
        self.session = session
        self.trace = trace
        self.cfg = cfg or session.context.cfg or CONFIG
        # 工具表在运行期不变，system prompt 只构造一次；把模型名传进去写明身份
        self.system_prompt = build_system_prompt(registry, self.cfg.MODEL)

    def handle_user_message(self, user_text: str) -> str:
        """处理一次用户输入，返回给用户的最终回答字符串。"""
        user_text = user_text or ""
        # 整个 turn 串行化：Gradio 默认并发，同一窗口连点两次"发送"也不会让
        # context.entries / display_history 的修改交错或损坏（不同窗口是不同
        # Session 实例，天然不互相阻塞）。锁是可重入的，内部 session.save() 可再次获取。
        with self.session._lock:
            turn = self.trace.begin_turn(self.session.session_id, user_text)
            # ---- Step 1：接收用户输入 ----
            self.session.context.add_user_message(user_text)
            seen_calls = set()  # 用于重复调用检测：(action, action_input)

            try:
                for i in range(self.cfg.MAX_INNER_ITERATIONS):
                    # 每轮重建 context 并按需压缩（阈值以下为 no-op）
                    self.session.context.compress_if_needed(self.llm)
                    messages = self.session.context.build_messages(self.system_prompt)

                    # ---- Step 2：调用 LLM，判断直接回复还是调用工具 ----
                    raw = self.llm.chat(
                        messages,
                        temperature=0.2,
                        response_format={"type": "json_object"},
                    )
                    parsed = parser.parse(raw)  # 永不抛异常
                    # 记下模型本轮的输出，供下一轮参考（完整 ReAct 轨迹）
                    self.session.context.add_assistant_message(parser.render(parsed))
                    turn.add_iteration(i, parsed)

                    # 分支 A：已有最终答案 → 返回给用户
                    if parsed.action is None and parsed.final_answer is not None:
                        # ---- Step 4（路径 A）：返回结果给用户 ----
                        answer = parsed.final_answer
                        turn.finalize(answer, error=None)
                        self.session.display_history.append([user_text, answer])
                        self.session.save()
                        return answer

                    # 分支 B：需要调用工具
                    call_key = (
                        parsed.action,
                        json.dumps(parsed.action_input or {}, sort_keys=True, ensure_ascii=False),
                    )
                    if call_key in seen_calls:
                        # ---- 重复调用检测：防止死循环 ----
                        observation = (
                            f"Error: 你已经用完全相同的参数调用过 {parsed.action}。"
                            f"请换一种思路，或直接给出 final_answer。"
                        )
                    else:
                        seen_calls.add(call_key)
                        tool = self.registry.get(parsed.action)
                        if tool is None:
                            observation = (
                                f"Error: 未知工具 '{parsed.action}'。"
                                f"可用工具：{self.registry.names()}"
                            )
                        else:
                            # ---- Step 3：调用工具 ----
                            try:
                                observation = tool.run(
                                    parsed.action_input or {},
                                    ToolContext(session=self.session),
                                )
                            except Exception as e:  # 工具异常转成 observation，循环继续
                                observation = f"Error executing {parsed.action}: {e!r}"

                    observation = _truncate(observation, self.cfg.OBSERVATION_MAX_CHARS)
                    # ---- Step 4（路径 B）：把 observation 喂回去，继续 loop ----
                    self.session.context.add_observation(parsed.action, observation)
                    turn.add_observation(observation)
                    self.session.save()

                # 循环上限耗尽：兜底回复
                fallback = (
                    "我已经尝试了多次工具调用，但仍未能在限定轮次内得到最终答案。"
                    "可以换个说法再试一次吗？"
                )
                turn.finalize(fallback, error="MAX_ITERATIONS_EXCEEDED")
                self.session.display_history.append([user_text, fallback])
                self.session.save()
                return fallback

            except Exception as e:
                # 基本异常处理：给用户固定可读文案（不回显内部 repr，避免泄漏细节），
                # 真实错误信息写进 trace 的 error 字段供排查。
                msg = "抱歉，处理时出了点问题，请稍后重试。"
                turn.finalize(None, error=repr(e))
                self.session.save()
                return msg
