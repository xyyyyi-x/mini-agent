"""Context（上下文）管理：消息历史 + 滚动摘要压缩。

设计要点（README 的"召回时机与放置方式"对应这里）：
- entries：按时间顺序的消息（user / assistant / Observation-as-user）。
- summary：当历史过长时，把旧消息压缩成的一段累加摘要。
- build_messages()：拼成 [system_prompt] + [摘要(若有)] + 最近 entries。
- compress_if_needed()：超过阈值时驱逐旧 entries、调 LLM 生成/更新摘要。
"""

from __future__ import annotations

from typing import Optional

from ..config import Config, CONFIG
from ..utils import now_utc_iso as _now


class Context:
    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or CONFIG
        self.entries: list[dict] = []
        self.summary: Optional[str] = None

    # ---- 写入 ----
    def add_user_message(self, text: str) -> None:
        self.entries.append({"role": "user", "content": text, "ts": _now()})

    def add_assistant_message(self, text: str) -> None:
        self.entries.append({"role": "assistant", "content": text, "ts": _now()})

    def add_observation(self, tool: str, observation: str) -> None:
        # Observation 作为 user 消息注入，让模型把它当作环境反馈
        self.entries.append(
            {"role": "user", "content": f"Observation({tool}): {observation}", "tool": tool, "ts": _now()}
        )

    # ---- 读取 ----
    def _est_tokens(self) -> int:
        # GLM 没有易用的本地 tokenizer，用 字符数/4 粗估 token。
        # summary 也计入，否则累加式摘要越长越占 token，硬上限却只看 entries、不会触发丢弃。
        total = sum(len(e["content"]) for e in self.entries)
        if self.summary:
            total += len(self.summary)
        return total // 4

    def build_messages(self, system_prompt: str) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": system_prompt}]
        if self.summary:
            msgs.append({"role": "system", "content": f"之前对话的摘要：\n{self.summary}"})
        for entry in self.entries:
            msgs.append({"role": entry["role"], "content": entry["content"]})
        return msgs

    # ---- 压缩 ----
    def compress_if_needed(self, llm) -> None:
        """超过阈值则压缩。阈值以下为 no-op。"""
        below_count = len(self.entries) < self.cfg.COMPRESS_AT_MESSAGES
        below_tokens = self._est_tokens() < self.cfg.COMPRESS_AT_TOKENS
        if below_count and below_tokens:
            return  # 还不长，无需压缩
        if len(self.entries) <= self.cfg.KEEP_RECENT:
            return  # 消息太少，没必要压缩

        to_evict = self.entries[: -self.cfg.KEEP_RECENT]
        self.entries = self.entries[-self.cfg.KEEP_RECENT:]

        transcript = self._format_entries(to_evict)
        self.summary = llm.summarize(transcript, prev_summary=self.summary)

        # 硬上限保护：若仍超长，逐条丢弃最旧消息
        while self.entries and self._est_tokens() > self.cfg.HARD_TOKEN_CEILING:
            self.entries.pop(0)

    @staticmethod
    def _format_entries(entries: list[dict]) -> str:
        return "\n".join(f"[{e['role']}] {e['content']}" for e in entries)

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        return {"summary": self.summary, "entries": self.entries}

    @classmethod
    def from_dict(cls, data: dict, cfg: Optional[Config] = None) -> "Context":
        ctx = cls(cfg=cfg)
        ctx.summary = data.get("summary")
        ctx.entries = data.get("entries") or []
        return ctx
