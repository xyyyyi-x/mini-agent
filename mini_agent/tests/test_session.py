"""Session 管理测试（题目：session 管理 + 持久化 + 两窗口独立）。"""

import json
import os

import pytest

from mini_agent.config import Config
from mini_agent.session.manager import SessionManager


def _cfg(tmp_path):
    return Config(SESSIONS_DIR=str(tmp_path), LOGS_DIR=str(tmp_path))


def test_load_nonexistent_returns_fresh(tmp_path):
    mgr = SessionManager(cfg=_cfg(tmp_path))
    s = mgr.load("userA", "window1")
    assert s.session_id == "userA__window1"
    assert s.context.entries == []
    assert s.tool_state == {}
    assert s.display_history == []


def test_save_load_roundtrip(tmp_path):
    mgr = SessionManager(cfg=_cfg(tmp_path))
    s = mgr.load("userA", "window1")
    s.context.add_user_message("你好")
    s.context.add_assistant_message("Final Answer: 你好！")
    s.context.summary = "打过招呼"
    s.tool_state = {"todo": {"next_id": 2, "items": [{"id": 1, "text": "买奶", "done": False}]}}
    s.display_history = [["你好", "你好！"]]
    s.save()

    # 重新加载
    s2 = SessionManager(cfg=_cfg(tmp_path)).load("userA", "window1")
    assert len(s2.context.entries) == 2
    assert s2.context.summary == "打过招呼"
    assert s2.tool_state["todo"]["items"][0]["text"] == "买奶"
    assert s2.display_history == [["你好", "你好！"]]


def test_two_windows_are_independent_files(tmp_path):
    mgr = SessionManager(cfg=_cfg(tmp_path))
    s1 = mgr.load("userA", "window1")
    s2 = mgr.load("userA", "window2")
    s1.tool_state = {"todo": {"items": [{"id": 1, "text": "w1", "done": False}]}}
    s2.tool_state = {"todo": {"items": [{"id": 1, "text": "w2", "done": False}]}}
    s1.save()
    s2.save()

    # 两个不同的文件
    assert os.path.basename(s1.session_id + ".json") in os.listdir(tmp_path)
    files = os.listdir(tmp_path)
    assert any("window1" in f for f in files)
    assert any("window2" in f for f in files)

    # 互不影响
    fresh = SessionManager(cfg=_cfg(tmp_path))
    r1 = fresh.load("userA", "window1")
    r2 = fresh.load("userA", "window2")
    assert r1.tool_state["todo"]["items"][0]["text"] == "w1"
    assert r2.tool_state["todo"]["items"][0]["text"] == "w2"


def test_atomic_write_leaves_no_tmp(tmp_path):
    mgr = SessionManager(cfg=_cfg(tmp_path))
    s = mgr.load("u", "w")
    s.save()
    files = os.listdir(tmp_path)
    assert not any(f.endswith(".tmp") for f in files)
    assert "u__w.json" in files


def test_list_sessions(tmp_path):
    mgr = SessionManager(cfg=_cfg(tmp_path))
    mgr.load("userA", "window1").save()
    mgr.load("userA", "window2").save()
    mgr.load("userB", "window1").save()
    all_sessions = mgr.list_sessions()
    assert len(all_sessions) == 3
    a_sessions = mgr.list_sessions(user_id="userA")
    assert len(a_sessions) == 2
    assert all(uid == "userA" for uid, _, _ in a_sessions)


def test_corrupt_file_falls_back_to_fresh(tmp_path):
    cfg = _cfg(tmp_path)
    path = os.path.join(str(tmp_path), "userA__window1.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ 这不是合法 json")
    mgr = SessionManager(cfg=cfg)
    s = mgr.load("userA", "window1")  # 不应抛异常
    assert s.context.entries == []


def test_invalid_ids_rejected(tmp_path):
    """user_id/window_id 含路径分隔符或 .. 应被拒绝，防路径穿越（M2）。"""
    mgr = SessionManager(cfg=_cfg(tmp_path))
    bad_cases = [("a/b", "w"), ("a", "w\\x"), ("..", "w"), ("a", ".."), ("", "w"), ("a", "")]
    for user_id, window_id in bad_cases:
        with pytest.raises(ValueError):
            mgr.load(user_id, window_id)
    # 合法 id 不受影响
    mgr.load("userA", "window1")
