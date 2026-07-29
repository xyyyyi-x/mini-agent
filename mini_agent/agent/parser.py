"""LLM 输出解析器（题目重点："需实现 LLM 输出的解析逻辑"）。

约定模型输出单个 JSON 对象：
    {"thought": "...", "action": "<工具名>|null",
     "action_input": {...}|null, "final_answer": "...|null"}

``parse()`` 永不抛异常：逐级降级，最差把整段原文当作 final_answer。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .types import ParsedOutput

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _try_json(text: str) -> Optional[dict]:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _brace_substring(text: str) -> Optional[str]:
    i, j = text.find("{"), text.rfind("}")
    if i != -1 and j != -1 and j > i:
        return text[i : j + 1]
    return None


def _safe_literal_eval(s: str) -> Optional[dict]:
    """用 ast.literal_eval 兜底解析“近似 JSON”。

    相比“无差别把单引号替换成双引号”，literal_eval 能正确处理单引号字典、
    尾逗号，并且不会破坏字符串内部的撇号（例如 ``"it's me"``）。
    它只解析字面量，遇到调用/导入/属性访问会抛异常，因此是安全的。
    局限：无法识别 JSON 的 null/true/false（Python 用 None/True/False），
    因此放在 _cheap_repair 之前先试，失败再退到后者。
    """
    try:
        import ast
        value = ast.literal_eval(s)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _cheap_repair(s: str) -> Optional[dict]:
    """最后兜底：无差别单引号→双引号 + 去尾逗号，再 json.loads。

    能救回含 null/true/false 的单引号字典，但会破坏字符串内部的撇号
    （如 ``"it's me"`` → ``"it"s me"``），所以只在 literal_eval 失败后才尝试。
    """
    try:
        repaired = s.replace("'", '"')
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        data = json.loads(repaired)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


_FINAL_ANSWER_RE = re.compile(
    r"(?:final[ _]answer|最终答案|最终回答|最终答复|答案)\s*[:：]\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)


def _extract_final_answer_from_text(text: str) -> str:
    """模型有时不遵守 JSON 约定，直接输出 ``Thought: ... Final Answer: X`` 纯文本。

    此时把 ``X`` 抽出来作为最终答案，避免把 "Thought:/Final Answer:" 前缀
    漏给用户。没有匹配则返回原文。
    """
    m = _FINAL_ANSWER_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def parse(raw: str) -> ParsedOutput:
    """把 LLM 的原始文本输出解析为标准化的 ParsedOutput。永不抛异常。"""
    text = raw or ""
    stripped = text.strip()

    data: Optional[dict] = None

    # 1) 严格 JSON
    if data is None:
        data = _try_json(stripped)

    # 2) ```json ... ``` 围栏块
    if data is None:
        m = _FENCE_RE.search(text)
        if m:
            data = _try_json(m.group(1))

    # 3) 取最外层 { ... } 子串
    if data is None:
        sub = _brace_substring(text)
        if sub:
            data = _try_json(sub)

    # 4) 近似 JSON 兜底：先 ast.literal_eval（保留撇号），再退到廉价替换（救 null/true/false）
    if data is None:
        sub = _brace_substring(text)
        if sub:
            data = _safe_literal_eval(sub) or _cheap_repair(sub)

    # 5) 全部失败：模型可能用了 "Thought: ... Final Answer: X" 纯文本格式，
    #    尽量抽出 X 作为最终答案；抽不到就把原文当回复。
    if not isinstance(data, dict):
        answer = _extract_final_answer_from_text(text)
        return ParsedOutput(
            thought=text, action=None, action_input=None, final_answer=answer, raw=text
        )

    thought = data.get("thought") or ""
    action = data.get("action")
    action_input = data.get("action_input")
    final_answer = data.get("final_answer")

    # 归一化 action：工具名只能是字符串；非字符串（None/数字/列表）一律视为无工具调用
    if isinstance(action, str):
        action = action.strip() or None
    else:
        action = None

    # 归一化 action_input
    if action:
        if action_input is None:
            action_input = {}
        elif isinstance(action_input, str):
            parsed_input = _try_json(action_input)
            action_input = parsed_input if isinstance(parsed_input, dict) else {"_raw": action_input}
        elif not isinstance(action_input, dict):
            action_input = {}
    else:
        action_input = None

    # 都缺失 → 视为直接回复，把原文塞进 final_answer
    if not action and final_answer is None:
        final_answer = text
    # 同时出现 action 与 final_answer → 以工具调用为准，丢弃 final_answer
    if action and final_answer is not None:
        final_answer = None

    return ParsedOutput(
        thought=thought,
        action=action,
        action_input=action_input,
        final_answer=final_answer,
        raw=text,
    )


def render(parsed: ParsedOutput) -> str:
    """把 ParsedOutput 渲染成可读的 assistant 消息，写进 context 供下一轮参考。"""
    parts = []
    if parsed.thought:
        parts.append(f"Thought: {parsed.thought}")
    if parsed.action:
        parts.append(f"Action: {parsed.action}")
        parts.append(f"Action Input: {json.dumps(parsed.action_input or {}, ensure_ascii=False)}")
    elif parsed.final_answer is not None:
        parts.append(f"Final Answer: {parsed.final_answer}")
    return "\n".join(parts) if parts else parsed.raw
