"""todo 工具：会话级待办事项管理。

通过 ``ctx.session.tool_state["todo"]`` 读写**当前会话**的待办列表，
并在每次变更后 ``session.save()`` 持久化。
不同会话（不同窗口）的待办天然独立。
"""

from __future__ import annotations

import re

from .base import Tool, ToolContext

# 待办分隔符：中英文逗号、顿号、分号、换行（斜杠太容易误伤，不用）
_ITEM_SEP_RE = re.compile(r"[，,、；;\n]+")


def _split_items(text) -> list[str]:
    """把一段文本拆成多条待办。

    用户/大模型可能一次给多条（如"早上跑步，下午面试，晚上学python"），
    这里按常见分隔符拆开，避免只记到最后一条、前面的丢掉。
    也兼容直接传进来的 list。
    """
    if text is None:
        return []
    if isinstance(text, list):
        return [str(t).strip() for t in text if str(t).strip()]
    if not isinstance(text, str):
        text = str(text)
    return [p.strip() for p in _ITEM_SEP_RE.split(text) if p.strip()]


def _empty_state() -> dict:
    return {"next_id": 1, "items": []}


def _format_items(items: list[dict]) -> str:
    lines = []
    for it in items:
        mark = "x" if it.get("done") else " "
        lines.append(f"  #{it['id']} [{mark}] {it['text']}")
    return "\n".join(lines)


def _as_int_id(value):
    """把待办 id 规范成 int。

    存储里的 id 是 int，但 LLM 在 JSON 模式降级时可能传字符串 "1"。
    这里统一强转，避免 ``int == str`` 静默匹配失败（complete/delete 永远找不到）。
    返回 (int, None) 或 (None, 错误字符串)。
    """
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, "Error: id 必须是整数。"


class Todo(Tool):
    name = "todo"
    description = (
        "管理当前会话的待办事项（每个会话的待办互相独立）。"
        "command 可选：add（需 text 新增）、list（列出全部）、"
        "complete（需 id 标记完成）、delete（需 id 删除一条）。"
        "add 的 text 可以是一条，也可以是多条用逗号/顿号/换行分隔（会自动拆成多条分别记录）。"
    )
    schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["add", "list", "complete", "delete"],
                "description": "要执行的操作",
            },
            "text": {
                "type": "string",
                "description": "待办内容（command=add 时必填）；多条可用逗号/顿号/换行分隔，会自动拆开分别记录",
            },
            "id": {"type": "integer", "description": "待办编号（command=complete/delete 时必填）"},
        },
        "required": ["command"],
    }

    def run(self, action_input: dict, ctx: ToolContext) -> str:
        session = ctx.session
        state = session.tool_state.setdefault("todo", _empty_state())
        command = action_input.get("command")

        if command == "add":
            items = _split_items(action_input.get("text"))
            if not items:
                return "Error: add 操作需要 text（待办内容）。"
            added = []
            for it_text in items:
                tid = state["next_id"]
                state["next_id"] += 1
                state["items"].append({"id": tid, "text": it_text, "done": False})
                added.append(f"#{tid}：{it_text}")
            session.save()
            return "已添加待办 " + "；".join(added)

        if command == "list":
            items = state["items"]
            if not items:
                return "当前待办列表为空。"
            return "待办列表：\n" + _format_items(items)

        if command == "complete":
            tid, err = _as_int_id(action_input.get("id"))
            if err:
                return err
            for it in state["items"]:
                if it["id"] == tid:
                    it["done"] = True
                    session.save()
                    return f"已完成待办 #{tid}：{it['text']}"
            return f"Error: 找不到待办 #{tid}。"

        if command == "delete":
            tid, err = _as_int_id(action_input.get("id"))
            if err:
                return err
            before = len(state["items"])
            state["items"] = [it for it in state["items"] if it["id"] != tid]
            if len(state["items"]) == before:
                return f"Error: 找不到待办 #{tid}。"
            session.save()
            return f"已删除待办 #{tid}。"

        return f"Error: 未知 command '{command}'。可选：add / list / complete / delete。"
