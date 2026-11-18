"""T22 第二段：FastAPI 接口测试（TestClient，不启动真实服务）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mapsmith import flow, server
from mapsmith.config import Settings
from mapsmith.loop import LoopResult


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    # T25 起 config 默认走本机 Ollama；这里显式清空三项，恢复「未配置模型」的前提，
    # 供 health 与 chat 的未配置分支使用。需要模型已配置的用例各自 monkeypatch。
    settings = Settings(
        output_dir=tmp_path,
        project_root=tmp_path,
        llm_base_url=None,
        llm_api_key=None,
        llm_model=None,
    )
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    server.UPLOAD_REGISTRY.clear()
    return TestClient(server.app)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event = "message"
        data = "{}"
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        events.append((event, json.loads(data)))
    return events


def test_health_reports_llm_configuration(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm_configured"] is False
    assert body["version"] == "V0.1"


def test_index_returns_build_hint_when_dist_missing(client):
    response = client.get("/")
    assert response.status_code == 503
    assert "前端未构建" in response.text


def test_settings_get_masks_secrets(client, monkeypatch, tmp_path: Path):
    """GET /api/settings 只回显脱敏密钥，绝不返回完整值。"""
    settings = Settings(
        output_dir=tmp_path,
        project_root=tmp_path,
        llm_base_url="https://api.example.com/v1",
        llm_api_key="sk-test-1234567890abcdef",
        llm_model="test-model",
    )
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    monkeypatch.setenv("MAPSMITH_STATS_API_KEY", "ghk_abcdef1234567890")

    response = client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["llm"]["api_key_configured"] is True
    assert data["llm"]["api_key_masked"] == "sk-t…cdef"
    assert data["stats"]["api_key_configured"] is True
    assert data["stats"]["api_key_masked"] == "ghk_…7890"
    # 完整密钥不得出现（base_url / model 是明文配置项，允许回显）
    blob = json.dumps(data, ensure_ascii=False)
    assert "1234567890abcdef" not in blob
    assert "ghk_abcdef1234567890" not in blob


def test_settings_put_updates_only_given_fields(client, monkeypatch, tmp_path: Path):
    """PUT 只更新非空字段，写回 .env 并保留未提供的密钥。"""
    settings = Settings(
        output_dir=tmp_path,
        project_root=tmp_path,
        llm_base_url="https://api.example.com/v1",
        llm_api_key="sk-test-1234567890abcdef",
        llm_model="test-model",
    )
    monkeypatch.setattr(server, "get_settings", lambda: settings)

    # 空 patch：保持原值
    response = client.put("/api/settings", json={})
    assert response.status_code == 200
    assert response.json()["llm"]["api_key_configured"] is True

    # 只改 model：key 保留，环境变量与 .env 都要更新
    response = client.put("/api/settings", json={"llm_model": "new-model"})
    assert response.status_code == 200
    data = response.json()
    assert data["llm"]["api_key_configured"] is True
    assert os.environ.get("MAPSMITH_LLM_MODEL") == "new-model"

    env_file = tmp_path / ".env"
    assert env_file.exists()
    content = env_file.read_text(encoding="utf-8")
    assert "MAPSMITH_LLM_MODEL=new-model" in content
    # 未提供的字段不该出现在 .env（或不被改动）
    assert "MAPSMITH_LLM_API_KEY=" not in content


def test_settings_put_writes_stats_key_to_env(client, monkeypatch, tmp_path: Path):
    """数据 API Key 也能通过设置窗口写入 .env 并立即生效。"""
    settings = Settings(output_dir=tmp_path, project_root=tmp_path)
    monkeypatch.setattr(server, "get_settings", lambda: settings)

    response = client.put("/api/settings", json={"stats_api_key": "ghk_newkey123456"})
    assert response.status_code == 200
    assert response.json()["stats"]["api_key_configured"] is True

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "MAPSMITH_STATS_API_KEY=ghk_newkey123456" in content


def test_upload_point_without_crs(client):
    response = client.post(
        "/api/upload",
        files={"file": ("sites.csv", b"station_name,lon,lat,PM2_5_24h\nA,117.18,34.22,45\n", "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "point"
    assert body["crs_status"] == "missing"
    assert body["suggested_crs"] == "EPSG:4326"


def test_upload_rejects_unsupported_type(client):
    response = client.post("/api/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400
    assert "不支持的文件类型" in response.json()["detail"]


def test_chat_requires_crs_before_running(client):
    upload = client.post(
        "/api/upload",
        files={"file": ("sites.csv", b"station_name,lon,lat,PM2_5_24h\nA,117.18,34.22,45\n", "text/csv")},
    ).json()

    response = client.post("/api/chat", json={"message": "徐州 20261101 的 PM2.5", "upload_id": upload["upload_id"]})
    events = parse_sse(response.text)

    assert ("crs_required",) == (events[0][0],)
    assert events[0][1]["upload_id"] == upload["upload_id"]
    assert events[-1][0] == "done"


def test_confirm_crs_updates_upload_record(client):
    upload = client.post(
        "/api/upload",
        files={"file": ("sites.csv", b"station_name,lon,lat,PM2_5_24h\nA,117.18,34.22,45\n", "text/csv")},
    ).json()

    response = client.post(f"/api/upload/{upload['upload_id']}/crs", json={"crs": "EPSG:4326"})

    assert response.status_code == 200
    assert response.json()["crs_status"] == "declared"
    assert server.UPLOAD_REGISTRY[upload["upload_id"]].confirmed_crs == "EPSG:4326"


def test_chat_without_model_returns_error(client):
    response = client.post("/api/chat", json={"message": "徐州 20261101 的 PM2.5"})
    events = parse_sse(response.text)

    assert events[0][0] == "error"
    assert "未配置模型" in events[0][1]["message"]
    assert events[-1][0] == "done"


def test_chat_streams_stages_and_result(client, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(server, "configured", lambda _settings: True)

    def fake_run_one_sentence(message, *, on_stage=None, **_kwargs):
        if on_stage:
            on_stage("parsing", "解析需求")
            on_stage("loading", "加载数据")
            on_stage("mapping", "生成制图方案")
            on_stage("rendering", "渲染地图")
            on_stage("reviewing", "审查地图")
        png = tmp_path / "web" / "r_fake" / "web_map.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(b"png")
        return flow.FlowRun(
            parse=flow.RequestParse({"place": "徐州", "time": "2026-11-01", "metric": "PM2_5_24h"}),
            result=LoopResult(
                status="rendered",
                round_no=1,
                spec={"title": "徐州市 PM2.5 分布图（2026-11-01）"},
                png=png,
                summary="已出图",
                notes=["站数：有效 5 个"],
                review={"passed": True},
                decision="degrade",
            ),
        )

    monkeypatch.setattr(server.flow, "run_one_sentence", fake_run_one_sentence)

    response = client.post("/api/chat", json={"message": "徐州 20261101 的 PM2.5"})
    events = parse_sse(response.text)
    names = [name for name, _ in events]

    assert names[:5] == ["stage"] * 5
    assert [data["stage"] for name, data in events if name == "stage"] == [
        "parsing",
        "loading",
        "mapping",
        "rendering",
        "reviewing",
    ]
    result = [data for name, data in events if name == "result"][0]
    assert result["status"] == "rendered"
    assert result["png"].startswith("/api/output/")
    assert result["summary"] == "已出图"
    assert events[-1][0] == "done"


def test_chat_reports_data_error_as_sse_error(client, monkeypatch):
    monkeypatch.setattr(server, "configured", lambda _settings: True)

    def fake_run_one_sentence(*_args, **_kwargs):
        raise flow.DataError("字段「PM2.5」不存在；可用字段：PM2_5_24h")

    monkeypatch.setattr(server.flow, "run_one_sentence", fake_run_one_sentence)

    events = parse_sse(client.post("/api/chat", json={"message": "x"}).text)

    assert events[0][0] == "error"
    assert "PM2_5_24h" in events[0][1]["message"]


def test_form_streams_result(client, monkeypatch, tmp_path: Path):
    def fake_run_form(form, *, on_stage=None, **_kwargs):
        if on_stage:
            on_stage("loading", "加载数据")
        return flow.FlowRun(
            parse=flow.RequestParse({"place": "徐州", "time": "2026-11-01", "metric": "PM2_5_24h"}),
            result=LoopResult(status="rendered", round_no=1, spec={}, png=None, summary="ok"),
        )

    monkeypatch.setattr(server.flow, "run_form", fake_run_form)

    events = parse_sse(
        client.post(
            "/api/form",
            json={"place": "徐州", "time": "20261101", "metric": "PM2.5", "map_type": "point"},
        ).text
    )

    assert [name for name, _ in events] == ["stage", "result", "done"]


def test_output_download_and_path_guard(client, tmp_path: Path):
    target_dir = tmp_path / "web" / "r_20261110_abc123"
    target_dir.mkdir(parents=True)
    (target_dir / "web_map.png").write_bytes(b"png")

    ok = client.get("/api/output/r_20261110_abc123/web_map.png")
    assert ok.status_code == 200
    assert ok.content == b"png"

    missing = client.get("/api/output/r_20261110_abc123/other.png")
    assert missing.status_code == 404

    traversal = client.get("/api/output/r_20261110_abc123/..%2F..%2Fsecret.png")
    assert traversal.status_code in (403, 404)


def test_static_file_serves_built_asset(client, tmp_path: Path):
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>MapSmith</html>", encoding="utf-8")
    (dist / "app.js").write_text("console.log(1)", encoding="utf-8")

    root = client.get("/")
    assert root.status_code == 200
    assert "MapSmith" in root.text

    asset = client.get("/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text


def test_session_crud_roundtrip(client):
    created = client.post("/api/sessions")
    assert created.status_code == 200
    shell = created.json()
    session_id = shell["id"]
    assert shell["message_count"] == 0
    # 新建的空会话不落盘，列表里不应出现空条目
    assert client.get("/api/sessions").json()["sessions"] == []

    saved = client.put(
        f"/api/sessions/{session_id}",
        json={"messages": [{"id": "a", "role": "user", "text": "徐州 PM2.5 分布图"}]},
    )
    assert saved.status_code == 200
    assert saved.json()["title"] == "徐州 PM2.5 分布图"
    assert saved.json()["message_count"] == 1

    listed = client.get("/api/sessions").json()["sessions"]
    assert [item["id"] for item in listed] == [session_id]

    loaded = client.get(f"/api/sessions/{session_id}")
    assert loaded.status_code == 200
    assert loaded.json()["messages"][0]["text"] == "徐州 PM2.5 分布图"

    assert client.delete(f"/api/sessions/{session_id}").json() == {"ok": True}
    assert client.get(f"/api/sessions/{session_id}").status_code == 404
    assert client.get("/api/sessions").json()["sessions"] == []


def test_session_rejects_bad_id_and_payload(client):
    assert client.get("/api/sessions/s_bad-id").status_code == 404
    assert client.delete("/api/sessions/s_bad-id").status_code == 404

    session_id = client.post("/api/sessions").json()["id"]
    bad = client.put(
        f"/api/sessions/{session_id}",
        json={"messages": [{"role": "system", "text": "不合法角色"}]},
    )
    assert bad.status_code == 400
    assert "角色" in bad.json()["detail"]

def test_form_body_accepts_numeric_buffer_km_and_bool_confirm_cost():
    """回归防护：表单请求体的两个类型坑。

    1. `buffer_km` 来自 `<input type="number">`，Vue 3 会转成数字；后端若只声明
       `str`，整个请求会 422（用户实测踩到）。
    2. `confirm_cost` 只接受布尔；模板写成 `@click="submit"` 时会把 MouseEvent
       当参数传进去，序列化成对象后 422。
    """
    from mapsmith.server import FormBody

    body = FormBody(
        place="江苏",
        time="20261101",
        metric="城镇化率",
        map_type="choropleth",
        method="quantile",
        n=5,
        palette_scheme="YlOrRd",
        buffer_km=5,
        overlay_op="clip",
        confirm_cost=False,
    )
    assert body.buffer_km == 5
    assert body.confirm_cost is False

    # 字符串形式的 buffer_km 也要能接受（表单未勾选/手填时）
    assert FormBody(buffer_km="5").buffer_km == "5"


def test_form_body_rejects_non_boolean_confirm_cost():
    """confirm_cost 传对象必须被拒，而不是静默当成 truthy。"""
    import pytest
    from pydantic import ValidationError

    from mapsmith.server import FormBody

    with pytest.raises(ValidationError):
        FormBody(confirm_cost={})
