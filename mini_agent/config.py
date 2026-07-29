"""集中式配置：所有阈值/常量/路径都在这里，避免散落的魔法数字。

提供：
- ``Config`` dataclass：可实例化（测试时传入临时目录、小阈值）。
- ``CONFIG``：默认实例，供 app.py 等直接使用。
- 一个极简的 ``.env`` 加载器（无需 python-dotenv 依赖）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _load_env_file() -> None:
    """读取项目根目录下的 .env（若存在），把键值写入 os.environ（已存在的键不覆盖）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.normpath(os.path.join(here, "..", ".env"))
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except Exception as e:
        # 读 .env 失败不应阻断程序，环境变量仍可由系统直接提供；
        # 但打一条警告，否则用户把 .env 写错格式时会毫无线索。
        import sys
        print(f"[warn] 解析 .env 失败，已忽略：{e!r}", file=sys.stderr)


# 必须在读取环境变量之前加载 .env
_load_env_file()


def _default_api_key() -> str:
    # 厂商中立：优先 LLM_API_KEY，兼容旧的 ZHIPU_API_KEY / GLM_API_KEY
    return os.getenv("LLM_API_KEY") or os.getenv("ZHIPU_API_KEY") or os.getenv("GLM_API_KEY") or ""


def _default_base_url() -> str:
    # 优先 LLM_BASE_URL；默认智谱常规 OpenAI 兼容端点
    return (
        os.getenv("LLM_BASE_URL")
        or os.getenv("ZHIPU_BASE_URL")
        or os.getenv("GLM_BASE_URL")
        or "https://open.bigmodel.cn/api/paas/v4/"
    )


def _default_model() -> str:
    # 优先 LLM_MODEL；默认 glm-4.5（指令跟随稳定、能输出 JSON）
    return os.getenv("LLM_MODEL") or os.getenv("ZHIPU_MODEL") or os.getenv("GLM_MODEL") or "glm-4.5"


@dataclass
class Config:
    """所有可调参数。测试时可构造自定义实例（临时目录、更小的阈值）。"""

    # ---- LLM ----
    ZHIPU_API_KEY: str = field(default_factory=_default_api_key)
    BASE_URL: str = field(default_factory=_default_base_url)  # 可用 .env 的 ZHIPU_BASE_URL 覆盖
    MODEL: str = field(default_factory=_default_model)  # 可用 .env 的 ZHIPU_MODEL 覆盖

    # ---- Agent 循环上限（防死循环）----
    MAX_INNER_ITERATIONS: int = 8  # 单轮（一次用户输入）最多工具调用次数

    # ---- Context 压缩 ----
    KEEP_RECENT: int = 8  # 压缩时保留最近多少条消息原文
    COMPRESS_AT_MESSAGES: int = 20  # 消息条数达到该值触发压缩
    COMPRESS_AT_TOKENS: int = 3000  # 估算 token（字符/4）达到该值触发压缩
    HARD_TOKEN_CEILING: int = 6000  # 硬上限，超出则逐条丢弃最旧消息

    # ---- 工具输出 ----
    OBSERVATION_MAX_CHARS: int = 1500  # 工具输出截断长度，防止撑爆上下文

    # ---- 存储 ----
    SESSIONS_DIR: str = "sessions"  # 会话 JSON 文件目录
    LOGS_DIR: str = "logs"  # trace 日志目录


# 默认实例
CONFIG = Config()
