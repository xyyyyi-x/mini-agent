"""对真实 LLM（智谱 GLM）的最小封装。

只用 ``openai`` SDK 作为 HTTP 通道，指向智谱的 OpenAI 兼容端点。
不引入任何 Agent 框架。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .config import Config, CONFIG

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - 仅在未装 openai 时给出友好提示
    OpenAI = None  # type: ignore


SUMMARIZE_SYSTEM_PROMPT = (
    "你是对话压缩助手。请把下方对话压缩成不超过 200 字的摘要，"
    "务必保留：用户的真实目标、已做出的决定、工具调用及其结果、以及任何列表/状态信息（例如待办事项）。"
    "如果给定了上一次的摘要，请把它合并进新摘要。只输出摘要本身。"
)


class LLMClient:
    """统一的 LLM 接口：``chat()`` 走对话，``summarize()`` 走压缩。"""

    def __init__(self, cfg: Optional[Config] = None, api_key: Optional[str] = None,
                 base_url: Optional[str] = None, model: Optional[str] = None):
        self.cfg = cfg or CONFIG
        self.api_key = api_key or self.cfg.ZHIPU_API_KEY
        self.base_url = base_url or self.cfg.BASE_URL
        self.model = model or self.cfg.MODEL
        if not self.api_key:
            raise ValueError(
                "缺少 LLM API Key。请在 .env 中设置 LLM_API_KEY"
                "（或厂商专用变量 ZHIPU_API_KEY / GLM_API_KEY）。"
            )
        if OpenAI is None:  # pragma: no cover
            raise RuntimeError("未安装 openai 包，请先 pip install openai")
        # 关闭 openai SDK 自带的隐藏重试（它默认会指数退避重试 429，会让单次调用偷偷拖到几十秒）；
        # 重试改由本类的 chat() 用更短、可控的策略处理。
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=0)

    def chat(self, messages: list[dict], temperature: float = 0.2,
             response_format: Optional[dict] = None, max_retries: int = 1) -> str:
        """调用对话接口，返回模型输出的纯文本。

        - 优先带 ``response_format``（JSON 模式）；若被拒绝则去掉该参数重试。
        - 对异常/空内容做**少量快速重试**（默认 1 次、固定 1 秒退避），目的是抓瞬时抖动；
          若持续失败（如限流）则尽快抛出，让上层给用户"请重试"的提示——
          避免长时间阻塞导致前端"连接断开"。
        """
        base_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        # 先尝试带 response_format 的配置，再退回到不带的配置
        attempt_configs = []
        if response_format:
            attempt_configs.append({**base_kwargs, "response_format": response_format})
        attempt_configs.append(base_kwargs)

        last_err: Optional[Exception] = None
        for kwargs in attempt_configs:
            for attempt in range(max_retries + 1):
                try:
                    resp = self.client.chat.completions.create(**kwargs)
                    content = (resp.choices[0].message.content or "").strip()
                    if content:
                        return content
                    # 空内容（限流软失败/模型空生成）对 Agent 不合法，按瞬时错误处理
                    last_err = RuntimeError("LLM 返回空内容")
                except Exception as e:  # noqa: BLE001 - 统一兜底，向上抛出可读错误
                    last_err = e
                # 走到这里说明没拿到有效内容（异常或空），短暂退避后重试；这组配置用尽则换下一组
                if attempt < max_retries:
                    time.sleep(1.0)
                else:
                    break
        raise RuntimeError(f"LLM 调用失败：{last_err!r}") from last_err

    def summarize(self, transcript: str, prev_summary: Optional[str] = None) -> str:
        """把一段对话轨迹压缩成摘要（压缩 context 时调用）。"""
        messages = [
            {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"上一次的摘要：{prev_summary or '无'}\n\n"
                    f"需要压缩的对话：\n{transcript}"
                ),
            },
        ]
        # 摘要不需要 JSON 模式
        return self.chat(messages, temperature=0.2, response_format=None)
