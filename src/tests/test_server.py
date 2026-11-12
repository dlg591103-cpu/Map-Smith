"""T22 第二段：FastAPI 接口测试（TestClient，不启动真实服务）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mapsmith import flow, server
from mapsmith.config import Settings
from mapsmith.loop import LoopResult


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    settings = Settings(output_dir=tmp_path, project_root=tmp_path)
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