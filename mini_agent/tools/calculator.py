"""calculator 工具：安全地求值数学表达式。

使用 ``ast`` 解析 + 白名单运算符，禁止 ``eval`` 任意代码。
"""

from __future__ import annotations

import ast
import operator

from .base import Tool, ToolContext

# 允许的二元运算符
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

# 允许的一元运算符（正负号）
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


# ---- 资源上限：防止单次工具调用耗尽 CPU/内存（DoS 防护）----
# 白名单只限制了"运算符种类"，这里再限制"操作数/结果大小"，
# 否则 9**9**9 这类合法表达式会算出 3 亿多位数字、直接卡死整个进程。
_MAX_RESULT_DIGITS = 10000   # 结果十进制位数上限
_MAX_POW_EXPONENT = 1000     # 幂运算指数绝对值上限
_MAX_EXPR_LEN = 2000         # 表达式字符长度上限
_MAX_DEPTH = 40              # AST 递归深度上限（防超深嵌套）


def _check_size(value) -> None:
    """结果（或操作数）过大则拒绝，覆盖大幂运算 / 大连乘的结果。"""
    if isinstance(value, int) and len(str(abs(value))) > _MAX_RESULT_DIGITS:
        raise ValueError("计算结果过大，已拒绝（防止资源耗尽）")


def _eval_node(node: ast.AST, depth: int = 0):
    """递归求值，遇到非白名单节点或超限即抛 ValueError。"""
    if depth > _MAX_DEPTH:
        raise ValueError("表达式嵌套过深")
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, depth + 1)
    if isinstance(node, ast.BinOp):
        op_func = _BIN_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"不支持的运算符：{type(node.op).__name__}")
        left = _eval_node(node.left, depth + 1)
        right = _eval_node(node.right, depth + 1)
        # 幂运算单独设限：指数过大直接拒绝，避免一开始计算就不可收拾
        if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)):
            if abs(right) > _MAX_POW_EXPONENT:
                raise ValueError(f"指数过大（上限 {_MAX_POW_EXPONENT}）")
        result = op_func(left, right)
        _check_size(result)
        return result
    if isinstance(node, ast.UnaryOp):
        op_func = _UNARY_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"不支持的一元运算符：{type(node.op).__name__}")
        result = op_func(_eval_node(node.operand, depth + 1))
        _check_size(result)
        return result
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            _check_size(node.value)
            return node.value
        raise ValueError("仅支持数字常量")
    raise ValueError(f"不支持的表达式节点：{type(node).__name__}")


def safe_eval(expr: str):
    """对外暴露的安全求值函数（也便于单元测试）。

    注意：仅支持四则/幂运算的白名单求值，并对操作数大小、结果位数、
    嵌套深度、表达式长度设了上限，防止 ``9**9**9`` 这类合法但会耗尽
    资源的表达式卡死进程。
    """
    if len(expr) > _MAX_EXPR_LEN:
        raise ValueError("表达式过长")
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree)


class Calculator(Tool):
    name = "calculator"
    description = (
        "数学计算器。输入一个数学表达式（支持 + - * / // % ** 与括号、整数和小数），"
        "返回计算结果。适合任何需要精确算术的场景。"
    )
    schema = {
        "type": "object",
        "properties": {
            "expr": {
                "type": "string",
                "description": "数学表达式，例如 (2+3)*4 或 17*23",
            }
        },
        "required": ["expr"],
    }

    def run(self, action_input: dict, ctx: ToolContext) -> str:
        expr = action_input.get("expr")
        if expr is None or str(expr).strip() == "":
            return "Error: 缺少参数 expr（数学表达式）。"
        expr = str(expr).strip()
        try:
            result = safe_eval(expr)
            return f"{expr} = {result}"
        except ZeroDivisionError:
            return f"Error: 除零错误（表达式：{expr}）。"
        except Exception as e:  # noqa: BLE001 - 任何解析/求值错误都转成可读字符串
            return f"Error: 无法计算 '{expr}'：{e}"
