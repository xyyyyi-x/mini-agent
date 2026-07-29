"""weather 工具：天气查询的 mock 版本。

按城市名在内置数据里查天气。要接入真实天气（如和风天气、OpenWeatherMap），
只需替换 ``run()`` 内部数据来源。
"""

from __future__ import annotations

from .base import Tool, ToolContext

# 内置的假天气数据
_FAKE_WEATHER = {
    "北京": ("晴", 32),
    "上海": ("多云", 29),
    "广州": ("雷阵雨", 33),
    "深圳": ("多云", 31),
    "杭州": ("晴", 30),
    "成都": ("阴", 27),
}


class Weather(Tool):
    name = "weather"
    description = (
        "查询城市天气（当前为 mock 数据）。输入城市名，返回天气状况与温度。"
    )
    schema = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名，例如 北京、上海",
            }
        },
        "required": ["city"],
    }

    def run(self, action_input: dict, ctx: ToolContext) -> str:
        city = (action_input.get("city") or "").strip()
        if not city:
            return "Error: 缺少参数 city（城市名）。"
        info = _FAKE_WEATHER.get(city)
        if not info:
            known = "、".join(_FAKE_WEATHER.keys())
            return f"（mock）暂无「{city}」的天气数据。目前已知城市：{known}。"
        condition, temp = info
        return f"{city}：{condition}，气温 {temp}°C。"
