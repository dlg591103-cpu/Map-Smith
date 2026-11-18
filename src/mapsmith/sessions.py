"""历史会话：一个会话一个 JSON 文件，落在 `<output_dir>/sessions/` 下。

只持久化展示所需字段（角色、文本、错误与结果）；`stage` 这类过程态、CRS 弹窗
与上传附件都不落盘——追问上下文由前端从最后一条消息重新推导。文件名即会话 ID，
写入走「临时文件 + os.replace」，避免进程中断留下半个 JSON。
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

SESSION_ID_RE = re.compile(r"^s_[A-Za-z0-9_]+$")
PLACEHOLDER_TITLE = "新对话"
TITLE_CHARS = 24
MAX_MESSAGES = 200
MAX_BYTES = 2 * 1024 * 1024
KEPT_FIELDS = ("id", "role", "text", "error", "result")


class SessionError(ValueError):
    """会话参数不合法：调用方应转成 400/404，而不是 500。"""


def sessions_root(output_dir: str | Path) -> Path:
    """会话目录跟着产物目录走，容器里挂载 out/ 即可一起持久化。"""
    return Path(output_dir) / "sessions"


def new_session_id(now: float | None = None) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
    return f"s_{stamp}_{uuid.uuid4().hex[:6]}"


def _now_text() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def empty_session(session_id: str) -> dict[str, Any]:
    """「新建对话」时的空壳：不落盘，第一条消息保存时才真正创建文件。"""
    now = _now_text()
    return {
        "id": session_id,
        "title": PLACEHOLDER_TITLE,
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
        "messages": [],
    }


def _path(root: Path, session_id: str) -> Path:
    if not isinstance(session_id, str) or not SESSION_ID_RE.match(session_id):
        raise SessionError("会话 ID 不合法")
    return root / f"{session_id}.json"


def _clean_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        raise SessionError("messages 必须是数组")
    cleaned: list[dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, dict):
            raise SessionError("messages 的每一项都必须是对象")
        role = item.get("role")
        if role not in ("user", "assistant"):
            raise SessionError("消息角色只能是 user 或 assistant")
        kept = {key: item[key] for key in KEPT_FIELDS if key in item}
        kept["role"] = role
        kept.setdefault("text", "")
        if not isinstance(kept.get("text"), str):
            raise SessionError("消息文本必须是字符串")
        cleaned.append(kept)
    # 只留最近若干条：早期轮次对恢复展示价值有限，也避免文件无限膨胀。
    return cleaned[-MAX_MESSAGES:]


def _title_from(messages: list[dict[str, Any]]) -> str:
    """取首条用户原话去掉附件行后截断，作为列表里的会话名。"""
    for message in messages:
        if message.get("role") != "user":
            continue
        text = str(message.get("text") or "")
        head = " ".join(text.split("\n📎")[0].split())
        if head:
            return head[:TITLE_CHARS]
    return PLACEHOLDER_TITLE


def _meta(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": payload.get("id"),
        "title": payload.get("title") or PLACEHOLDER_TITLE,
        "created_at": payload.get("created_at") or "",
        "updated_at": payload.get("updated_at") or "",
        "message_count": len(payload.get("messages") or []),
    }


def _read(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _dump(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except ValueError as exc:
        raise SessionError("会话内容包含无法保存的数值（如 NaN）") from exc


def _shrink(payload: dict[str, Any]) -> dict[str, Any]:
    """超过体积上限时从最旧的消息开始丢弃，至少保留最新一轮。"""
    messages = payload.get("messages") or []
    while len(messages) > 2 and len(_dump(payload).encode("utf-8")) > MAX_BYTES:
        messages.pop(0)
    return payload


def save_session(
    root: Path,
    session_id: str,
    messages: Any,
    title: str | None = None,
) -> dict[str, Any]:
    """写入（或覆盖）一个会话，返回不含 messages 的元信息。"""
    path = _path(root, session_id)
    cleaned = _clean_messages(messages)
    previous = _read(path) or {}
    now = _now_text()

    custom = (title or "").strip()[:TITLE_CHARS]
    former = previous.get("title") if isinstance(previous.get("title"), str) else ""
    if custom:
        final_title = custom
    elif former and former != PLACEHOLDER_TITLE:
        # 首轮定下的标题不随后续轮次改写；占位标题则升级为首条用户原话。
        final_title = former
    else:
        final_title = _title_from(cleaned)

    payload = _shrink(
        {
            "id": session_id,
            "title": final_title,
            "created_at": previous.get("created_at") or now,
            "updated_at": now,
            "messages": cleaned,
        }
    )

    root.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(_dump(payload), encoding="utf-8")
    os.replace(tmp, path)
    return _meta(payload)


def load_session(root: Path, session_id: str) -> dict[str, Any] | None:
    payload = _read(_path(root, session_id))
    if payload is None:
        return None
    payload.setdefault("id", session_id)
    payload["title"] = payload.get("title") or PLACEHOLDER_TITLE
    if not isinstance(payload.get("messages"), list):
        payload["messages"] = []
    return payload


def list_sessions(root: Path) -> list[dict[str, Any]]:
    """按最近更新时间倒序；损坏文件直接跳过，不影响其它会话。"""
    if not root.is_dir():
        return []
    metas: list[dict[str, Any]] = []
    for path in root.glob("*.json"):
        if not SESSION_ID_RE.match(path.stem):
            continue
        payload = _read(path)
        if payload is None:
            continue
        payload.setdefault("id", path.stem)
        metas.append(_meta(payload))
    metas.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return metas


def delete_session(root: Path, session_id: str) -> bool:
    path = _path(root, session_id)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise SessionError("会话文件无法删除，请关闭占用它的程序后重试") from exc
    return True