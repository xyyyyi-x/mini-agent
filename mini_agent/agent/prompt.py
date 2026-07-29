"""System prompt 构造：把工具 schema 注入提示词，并给出输出契约与示例。"""

from __future__ import annotations

import json

from ..tools.base import ToolRegistry


def friendly_identity(model: str) -> str:
    """把模型名转成人话身份，用于在提示词里写明，避免模型"自报家门"时瞎编。"""
    m = (model or "").lower()
    if "deepseek" in m:
        return "DeepSeek（由深度求索开发）"
    if "glm" in m:
        return "智谱 GLM"
    if "gpt" in m or "openai" in m:
        return "OpenAI GPT"
    if "qwen" in m or "tongyi" in m:
        return "通义千问"
    if "kimi" in m or "moonshot" in m:
        return "Moonshot Kimi"
    if "claude" in m:
        return "Claude"
    return model or "大模型"


def build_system_prompt(registry: ToolRegistry, model: str = "") -> str:
    """根据注册表里的工具，动态拼出 system prompt。"""
    tool_blocks = []
    for tool in registry.all():
        schema_str = json.dumps(tool.schema, ensure_ascii=False, indent=2)
        tool_blocks.append(
            f"### 工具：{tool.name}\n"
            f"描述：{tool.description}\n"
            f"参数 schema（action_input 必须符合）：\n{schema_str}"
        )
    tools_section = "\n\n".join(tool_blocks) if tool_blocks else "（暂无工具）"
    available = ", ".join(registry.names()) if registry.names() else "（无）"
    identity = friendly_identity(model)

    return f"""你是一个乐于助人、会使用工具的 Agent，由 {identity} 大模型驱动。
当用户问你的身份、模型或所用 API 时，必须如实回答：你是基于 {identity} 的助手（不要说成别的厂商/模型）。
为了回答用户，你可以调用工具，也可以直接回答。

【输出契约】你必须且只能输出【一个 JSON 对象】，不要输出 markdown 代码块标记，也不要输出任何额外文字。JSON 字段如下：
{{
  "thought": "一两句思考过程：你在想什么、为什么要这么做",
  "action": "<要调用的工具名，或者 null>",
  "action_input": {{ "参数名": "参数值" }},
  "final_answer": "<给用户的最终回答，或者 null>"
}}

【规则】
1. 如果需要调用工具：把 action 设为工具名，action_input 设为符合该工具参数 schema 的 JSON 对象，final_answer 设为 null。
2. 如果不需要工具就能回答：把 action 和 action_input 都设为 null，final_answer 设为你的回答。
3. 在你调用工具之后，系统会把工具结果以 "Observation(工具名): ..." 的形式告诉你。随后你要么继续调用工具，要么给出 final_answer。
4. action_input 必须是 JSON 对象，不能是字符串。
5. 用与用户相同的语言回答。
6. 【最重要】无论是调用工具还是给出最终答案，你的回复都必须是【一个 JSON 对象】。绝对不要输出 "Thought:" / "Final Answer:" 这样的纯文字格式，最终答案也只能放在 final_answer 字段里。

【可用工具】（action 只能从这些名字里选：{available}）
{tools_section}

【示例 1：需要工具】
用户：6 乘以 7 等于多少？
你的输出：{{"thought":"用户问乘法，用计算器","action":"calculator","action_input":{{"expr":"6*7"}},"final_answer":null}}
系统返回：Observation(calculator): 6*7 = 42
你的输出：{{"thought":"结果是 42","action":null,"action_input":null,"final_answer":"6 乘以 7 等于 42。"}}

【示例 2：不需要工具】
用户：你好呀
你的输出：{{"thought":"只是打招呼，直接回复","action":null,"action_input":null,"final_answer":"你好！有什么可以帮你的吗？"}}
"""
