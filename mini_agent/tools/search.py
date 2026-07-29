"""search 工具：联网搜索的 mock 版本。

按查询关键词在一份内置假数据里匹配，返回若干条结果。
要接入真实搜索（DuckDuckGo / SerpAPI 等），只需替换 ``run()`` 内部的数据来源，
接口保持不变。
"""

from __future__ import annotations

from .base import Tool, ToolContext

# 内置的假“互联网”
_FAKE_DB = {
    "python": [
        "Python 3.13 发布，解释器性能进一步提升约 10%。",
        "如何用 Python 从零写一个 Agent：ReAct 范式入门。",
    ],
    "agent": [
        "什么是 AI Agent：能感知环境、自主决策、调用工具完成任务的系统。",
        "ReAct = Reasoning + Acting：让大模型边推理边调用工具。",
    ],
    "glm": [
        "智谱 GLM-4 系列模型支持 function calling 与 JSON 模式。",
    ],
    "天气": [
        "如何获取实时天气：开放气象 API 使用指南。",
    ],
}


class Search(Tool):
    name = "search"
    description = (
        "联网搜索（当前为 mock 数据）。输入查询关键词，返回若干条相关结果。"
        "用于回答你自身知识之外、或需要外部信息的问题。"
    )
    schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词，例如 'Python Agent' 或 'GLM 模型'",
            }
        },
        "required": ["query"],
    }

    def run(self, action_input: dict, ctx: ToolContext) -> str:
        query = (action_input.get("query") or "").strip()
        if not query:
            return "Error: 缺少参数 query（搜索关键词）。"
        q_lower = query.lower()
        hits: list[str] = []
        for key, items in _FAKE_DB.items():
            if key in q_lower or q_lower in key.lower():
                hits.extend(items)
        if not hits:
            hits = [f"（mock）未找到与「{query}」强相关的结果，这是一条占位搜索结果。"]
        lines = "\n".join(f"- {h}" for h in hits[:5])
        return f"搜索「{query}」的结果：\n{lines}"
