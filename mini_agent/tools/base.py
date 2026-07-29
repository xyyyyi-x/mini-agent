"""工具基类、工具注册表、工具运行上下文。

每个工具自带 name / description / 参数 schema；注册表把它们汇总，
LLM 基于 schema 自主决策调用哪一个。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Optional

if TYPE_CHECKING:  # 避免循环导入
    from ..session.manager import Session


@dataclass
class ToolContext:
    """工具运行时的上下文。

    无状态工具（calculator/search/weather）接收但忽略它；
    有状态工具（todo）通过 ``ctx.session.tool_state`` 读写会话级状态。
    """

    session: "Session"


class Tool(ABC):
    """所有工具的基类。子类需设置 name / description / schema 并实现 run()。"""

    name: str = ""
    description: str = ""
    # JSON Schema，描述 action_input 的结构。这是类级配置，请在子类整体覆盖，
    # 不要原地修改实例的 schema（ClassVar 标注提醒它不是实例字段，避免可变默认值陷阱）。
    schema: ClassVar[dict] = {}

    @abstractmethod
    def run(self, action_input: dict, ctx: ToolContext) -> str:
        """执行工具，返回给 Agent 的 observation 字符串（出错也返回错误字符串，不要抛异常）。"""
        raise NotImplementedError


class ToolRegistry:
    """工具注册表：按名字存取，并导出 schema 给 system prompt。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if not tool.name:
            raise ValueError("工具必须设置 name")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: Optional[str]) -> Optional[Tool]:
        if not name:
            return None
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def all(self) -> list[Tool]:
        return list(self._tools.values())
