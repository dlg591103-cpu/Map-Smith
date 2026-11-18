"""历史会话落盘（sessions 模块）：CRUD、损坏容错与容量上限。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mapsmith import sessions


def test_new_session_id_format():
    sid = sessions.new_session_id()
    assert re.fullmatch(r"s_\d{8}_\d{6}_[0-9a-f]{6}", sid)


def test_empty_session_shell_is_not_written(tmp_path: Path):
    root = sessions.sessions_root(tmp_path)
    sid = sessions.new_session_id()

    shell = sessions.empty_session(sid)

    assert shell["messages"] == []
    assert shell["message_count"] == 0
    assert not (root / f"{sid}.json").exists()
    assert sessions.list_sessions(root) == []
    assert sessions.load_session(root, sid) is None


def test_save_and_load_roundtrip(tmp_path: Path):
    root = sessions.sessions_root(tmp_path)
    sid = sessions.new_session_id()
    messages = [
        {"id": "a", "role": "user", "text": "徐州 2026-11-01 的 PM2.5", "stage": "解析中"},
        {
            "id": "b",
            "role": "assistant",
            "text": "",
            "crs": {"upload_id": "u_1"},
            "result": {"status": "rendered", "png": "/api/output/r_x/web_map.png"},
        },
    ]

    meta = sessions.save_session(root, sid, messages)

    assert meta["title"] == "徐州 2026-11-01 的 PM2.5"
    assert meta["message_count"] == 2

    loaded = sessions.load_session(root, sid)
    assert loaded is not None
    assert [item["role"] for item in loaded["messages"]] == ["user", "assistant"]
    # 过程态（stage）与瞬时弹窗状态（crs）不落盘
    assert "stage" not in loaded["messages"][0]
    assert "crs" not in loaded["messages"][1]
    assert loaded["messages"][1]["result"]["png"].endswith("web_map.png")
    assert loaded["created_at"] == loaded["updated_at"]
    # 原子写不留临时文件
    assert not list(root.glob("*.tmp"))


def test_title_is_fixed_after_first_round(tmp_path: Path):
    root = sessions.sessions_root(tmp_path)
    sid = sessions.new_session_id()
    sessions.save_session(root, sid, [{"role": "user", "text": "画徐州 PM2.5"}])

    meta = sessions.save_session(
        root,
        sid,
        [
            {"role": "user", "text": "画徐州 PM2.5"},
            {"role": "assistant", "text": "好的"},
            {"role": "user", "text": "换个配色"},
        ],
    )

    assert meta["title"] == "画徐州 PM2.5"


def test_placeholder_title_upgrades_and_custom_title_wins(tmp_path: Path):
    root = sessions.sessions_root(tmp_path)
    sid = sessions.new_session_id()

    assert sessions.save_session(root, sid, [])["title"] == sessions.PLACEHOLDER_TITLE
    assert sessions.save_session(root, sid, [{"role": "user", "text": "江苏 GDP"}])["title"] == "江苏 GDP"
    assert sessions.save_session(root, sid, [{"role": "user", "text": "江苏 GDP"}], title="自定义名")["title"] == "自定义名"


def test_title_drops_attachment_line(tmp_path: Path):
    root = sessions.sessions_root(tmp_path)
    meta = sessions.save_session(
        root,
        sessions.new_session_id(),
        [{"role": "user", "text": "徐州 2026-11-01 的 PM2.5\n📎 sites.csv"}],
    )
    assert meta["title"] == "徐州 2026-11-01 的 PM2.5"


def test_list_sessions_sorted_and_skips_broken_files(tmp_path: Path):
    root = sessions.sessions_root(tmp_path)
    old = sessions.new_session_id()
    sessions.save_session(root, old, [{"role": "user", "text": "旧会话"}])
    new = sessions.new_session_id()
    sessions.save_session(root, new, [{"role": "user", "text": "新会话"}])

    # 把旧会话的更新时间改早，模拟真实时间先后（同一次测试里两者可能同秒）
    path = root / f"{old}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["updated_at"] = "2000-01-01T00:00:00"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    (root / "s_20260101_000000_broken.json").write_text("{不是 JSON", encoding="utf-8")
    (root / "note.txt").write_text("无关文件", encoding="utf-8")

    listed = sessions.list_sessions(root)

    assert [item["id"] for item in listed] == [new, old]
    assert all(item["message_count"] == 1 for item in listed)


def test_list_sessions_on_missing_dir(tmp_path: Path):
    assert sessions.list_sessions(tmp_path / "不存在") == []


def test_message_cap_keeps_latest(tmp_path: Path):
    root = sessions.sessions_root(tmp_path)
    sid = sessions.new_session_id()
    messages = [{"role": "user", "text": f"第{index}句"} for index in range(sessions.MAX_MESSAGES + 5)]

    meta = sessions.save_session(root, sid, messages)

    assert meta["message_count"] == sessions.MAX_MESSAGES
    loaded = sessions.load_session(root, sid)
    assert loaded is not None
    assert loaded["messages"][-1]["text"] == f"第{sessions.MAX_MESSAGES + 4}句"
    assert loaded["messages"][0]["text"] == "第5句"


@pytest.mark.parametrize(
    "messages",
    [
        "不是数组",
        [{"role": "system", "text": "x"}],
        [{"role": "user", "text": 123}],
        ["纯字符串"],
    ],
)
def test_save_rejects_bad_payload(tmp_path: Path, messages):
    root = sessions.sessions_root(tmp_path)
    with pytest.raises(sessions.SessionError):
        sessions.save_session(root, sessions.new_session_id(), messages)


def test_save_rejects_nan(tmp_path: Path):
    root = sessions.sessions_root(tmp_path)
    with pytest.raises(sessions.SessionError):
        sessions.save_session(
            root,
            sessions.new_session_id(),
            [{"role": "assistant", "text": "", "result": {"value": float("nan")}}],
        )


@pytest.mark.parametrize("session_id", ["../escape", "s_../x", "", "s-2026", "..\\..\\x", "s_ok/../x"])
def test_bad_session_id_is_rejected(tmp_path: Path, session_id: str):
    root = sessions.sessions_root(tmp_path)
    with pytest.raises(sessions.SessionError):
        sessions.save_session(root, session_id, [])
    with pytest.raises(sessions.SessionError):
        sessions.load_session(root, session_id)
    with pytest.raises(sessions.SessionError):
        sessions.delete_session(root, session_id)


def test_delete_session(tmp_path: Path):
    root = sessions.sessions_root(tmp_path)
    sid = sessions.new_session_id()
    sessions.save_session(root, sid, [{"role": "user", "text": "要删的会话"}])

    assert sessions.delete_session(root, sid) is True
    assert sessions.load_session(root, sid) is None
    assert sessions.delete_session(root, sid) is False