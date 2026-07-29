"""Session 管理：每个会话一个 JSON 文件，原子写入，跨重启可续聊。

会话 key = (user_id, window_id) → 文件 sessions/{user_id}__{window_id}.json。
同一用户的两个窗口是两个不同文件，天然独立。
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from typing import Optional

from ..agent.context import Context
from ..config import Config, CONFIG
from ..utils import now_utc_iso as _now


def _validate_ids(user_id: str, window_id: str) -> None:
    """校验 user_id / window_id 不含路径分隔符或 ..，防止路径穿越/任意覆盖文件。"""
    for name, value in (("user_id", user_id), ("window_id", window_id)):
        if not isinstance(value, str) or value == "":
            raise ValueError(f"{name} 不能为空")
        if re.search(r"[\\/]", value) or ".." in value:
            raise ValueError(f"{name} 含非法字符（禁止路径分隔符和 '..'）")


class Session:
    def __init__(self, session_id: str, user_id: str, window_id: str,
                 manager: Optional["SessionManager"] = None, cfg: Optional[Config] = None):
        self.session_id = session_id
        self.user_id = user_id
        self.window_id = window_id
        self.created_at = _now()
        self.updated_at = self.created_at
        self.context = Context(cfg=cfg)
        self.tool_state: dict = {}  # 会话级工具状态，例如 todo
        self.display_history: list[list[str]] = []  # [[user, answer], ...] 仅供 UI 展示
        self._manager = manager
        # 用可重入锁：runtime 会在整个 turn 持锁，期间还会调用 session.save()
        # （包括 todo 工具内部），同一线程需要能再次获取锁。
        self._lock = threading.RLock()

    def save(self) -> None:
        """落盘（若由 SessionManager 创建，则委托给它做原子写）。"""
        self.updated_at = _now()
        if self._manager is not None:
            self._manager.save(self)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "window_id": self.window_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "context": self.context.to_dict(),
            "tool_state": self.tool_state,
            "display_history": self.display_history,
        }


class SessionManager:
    def __init__(self, sessions_dir: Optional[str] = None, cfg: Optional[Config] = None):
        self.cfg = cfg or CONFIG
        self.sessions_dir = sessions_dir or self.cfg.SESSIONS_DIR
        os.makedirs(self.sessions_dir, exist_ok=True)

    @staticmethod
    def _key(user_id: str, window_id: str) -> str:
        return f"{user_id}__{window_id}"

    def _path(self, session_id: str) -> str:
        return os.path.join(self.sessions_dir, f"{session_id}.json")

    def load(self, user_id: str, window_id: str) -> Session:
        _validate_ids(user_id, window_id)
        session_id = self._key(user_id, window_id)
        path = self._path(session_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return self._from_dict(data)
            except Exception as e:
                # 文件损坏则退回新会话，避免一次坏文件让整个程序起不来
                print(f"[warn] 会话文件 {path} 损坏，已回退到新会话：{e!r}", file=sys.stderr)
        return Session(session_id, user_id, window_id, manager=self, cfg=self.cfg)

    def _from_dict(self, data: dict) -> Session:
        s = Session(
            session_id=data["session_id"],
            user_id=data.get("user_id", ""),
            window_id=data.get("window_id", ""),
            manager=self,
            cfg=self.cfg,
        )
        s.created_at = data.get("created_at", s.created_at)
        s.updated_at = data.get("updated_at", s.updated_at)
        s.context = Context.from_dict(data.get("context", {}), cfg=self.cfg)
        s.tool_state = data.get("tool_state", {})
        s.display_history = data.get("display_history", [])
        return s

    def save(self, session: Session) -> None:
        """原子写：先写 .tmp 再 os.replace，避免半写文件。"""
        with session._lock:
            data = session.to_dict()
            path = self._path(session.session_id)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)

    def list_sessions(self, user_id: Optional[str] = None) -> list[tuple[str, str, str]]:
        """列出已有会话，返回 [(user_id, window_id, session_id), ...]。"""
        out = []
        if not os.path.isdir(self.sessions_dir):
            return out
        for fn in os.listdir(self.sessions_dir):
            if not fn.endswith(".json"):
                continue
            session_id = fn[:-5]
            uid, _, wid = session_id.partition("__")
            if user_id and uid != user_id:
                continue
            out.append((uid, wid, session_id))
        return out

    def path_for(self, user_id: str, window_id: str) -> str:
        """返回某会话的文件路径（先做合法性校验）。"""
        _validate_ids(user_id, window_id)
        return self._path(self._key(user_id, window_id))

    def delete(self, user_id: str, window_id: str) -> None:
        """删除某会话的 JSON 文件（不存在则静默忽略）。"""
        _validate_ids(user_id, window_id)
        path = self._path(self._key(user_id, window_id))
        if os.path.exists(path):
            os.remove(path)
