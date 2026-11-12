"""T22 第二段：flow 装配测试。

大部分用构造图层与替身 LLM，少量用 demo_data 验证真实加载；不启动网络与浏览器。
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

from mapsmith import flow
from mapsmith.io.models import CrsNotDeclared, DataError, DataLayer, FieldMissing
from mapsmith.io.uploads import parse_upload
from mapsmith.tools.inspect import DataProfile
from mapsmith.ui import RenderResult


def make_admin() -> DataLayer:
    gdf = gpd.GeoDataFrame(
        {"name": ["徐州市"], "geometry": [box(117.1, 34.1, 117.5, 34.4)]},
        crs="EPSG:4326",
    )
    return DataLayer(
        kind="admin",
        name="徐州市行政边界",
        source="demo_data",
        summary="徐州市行政边界：1 个面要素",
        gdf=gdf,
        crs="EPSG:4326",
        meta={"adcode": "320300"},
    )


def make_points() -> DataLayer:
    coords = [(117.18, 34.22), (117.22, 34.28), (117.28, 34.24), (117.33, 34.31), (117.40, 34.26)]
    gdf = gpd.GeoDataFrame(
        {
            "station_name": ["A", "B", "C", "D", "E"],
            "PM2_5_24h": [45.0, 58.0, 51.0, 49.0, 55.0],
        },
        geometry=[Point(x, y) for x, y in coords],
        crs="EPSG:4326",
    )
    return DataLayer(
        kind="point",
        name="徐州站点",
        source="upload 站点.csv",
        summary="徐州站点：5 个点",
        gdf=gdf,
        crs="EPSG:4326",
        meta={"adcode": "320300"},
    )


def make_profile(decision: str = "degrade") -> DataProfile:
    return DataProfile(
        n_valid=5,
        total=10,
        completeness=0.5,
        decision=decision,  # type: ignore[arg-type]
        cover=0.02,
        reason_lines=(
            "站数：有效 5 个（成面阈值 ≥10）",
            "覆盖度：2%（成面阈值 ≥50%）",
            "结论：降级为点图 / 气泡图 + 城市面底色，不做插值",
        ),
        summary="徐州站点：PM2_5_24h 有效值 5 个（共 10 个站点，完整度 50%），最高 58.0、最低 45.0。",
    )


def make_loaded(decision: str = "degrade") -> dict:
    points = make_points()
    admin = make_admin()
    return {
        "summary": make_profile(decision).summary,
        "decision": decision,
        "reason_lines": list(make_profile(decision).reason_lines),
        "profile": make_profile(decision),
        "admin": admin,
        "points": points,
        "layer": points,
        "field": "PM2_5_24h",
        "date": "2026-11-01",
        "place": "徐州",
    }


def request(**overrides) -> dict[str, str]:
    values = {"place": "徐州", "time": "2026-11-01", "metric": "PM2_5_24h"}
    values.update(overrides)
    return values


# --- 解析 -----------------------------------------------------------------


def test_normalize_time_accepts_common_formats():
    assert flow.normalize_time("20261101") == "2026-11-01"
    assert flow.normalize_time("2026-11-01") == "2026-11-01"
    assert flow.normalize_time("2026/11/1") == "2026-11-01"
    assert flow.normalize_time("2026.11.01") == "2026-11-01"
    assert flow.normalize_time("2026年11月1日") == "2026-11-01"


def test_normalize_time_rejects_unparseable_value():
    assert flow.normalize_time("最近几天") == ""
    assert flow.normalize_time(None) == ""
    assert flow.normalize_time("2026-02-30") == ""


def test_map_metric_maps_aliases_and_keeps_unknown():
    assert flow.map_metric("PM2.5") == "PM2_5_24h"
    assert flow.map_metric("pm2_5_24h") == "PM2_5_24h"
    assert flow.map_metric("PM10") == "PM10_24h"
    assert flow.map_metric("O3") == "O3_8h_24h"
    assert flow.map_metric("AQI") == "AQI"
    assert flow.map_metric("能见度") == "能见度"


def test_normalize_parse_does_not_invent_defaults():
    parsed = flow.normalize_parse({"place": "", "time": "", "metric": ""})

    assert parsed.request == {"place": "", "time": "", "metric": ""}
    assert len(parsed.questions) == 2
    assert parsed.questions[0] == "想画哪个城市或区县？"


def test_normalize_parse_prefers_model_questions_and_limits_to_two():
    parsed = flow.normalize_parse(
        {
            "place": "徐州",
            "time": "",
            "metric": "",
            "questions": ["要哪一天的？", "画哪个指标？", "第三个多余问题"],
        }
    )

    assert parsed.questions == ["要哪一天的？", "画哪个指标？"]


def test_parse_request_uses_data_steward_prompt():
    captured: dict = {}

    def fake_llm(system_prompt: str, payload):
        captured["system"] = system_prompt
        captured["payload"] = payload
        return {"place": "徐州", "time": "20261101", "metric": "PM2.5"}

    parsed = flow.parse_request("徐州 20261101 的 PM2.5", fake_llm)

    assert "DataSteward" in captured["system"]
    assert captured["payload"]["user_text"] == "徐州 20261101 的 PM2.5"
    assert parsed.request == {"place": "徐州", "time": "2026-11-01", "metric": "PM2_5_24h"}
    assert parsed.questions == []


def test_parse_request_empty_text_asks_without_calling_model():
    def fake_llm(*args, **kwargs):
        raise AssertionError("空输入不应调用模型")

    parsed = flow.parse_request("   ", fake_llm)
    assert parsed.questions


# --- 制图 -----------------------------------------------------------------


def test_compose_spec_forces_map_type_and_computes_breaks_locally():
    loaded = make_loaded("degrade")
    draft = {
        "title": "旧标题",
        "map_type": "choropleth",
        "classification": {"method": "quantile", "n": 3, "breaks": [1, 2, 3, 4, 5]},
        "palette": {"scheme": "jet", "reverse": True},
        "notes": ["模型补充"],
    }

    spec = flow._compose_spec(request(), loaded, draft)

    assert spec.map_type == "point"
    assert spec.classification is not None
    assert spec.classification.n == 3
    assert len(spec.classification.breaks) == 3
    assert spec.classification.breaks != [1, 2, 3, 4, 5]
    assert spec.palette.scheme == "YlOrRd"
    assert spec.palette.reverse is True
    assert spec.title == "徐州市 PM2.5 分布图（2026-11-01，μg/m³）"
    assert spec.data_source_note.endswith("更新时间：2026-11-01")
    assert spec.notes[0] == loaded["reason_lines"][0]
    assert any("禁用彩虹色" in note for note in spec.notes)
    assert spec.extent.bbox == (117.1, 34.1, 117.5, 34.4)


def test_compose_spec_uses_idw_when_decision_is_idw():
    loaded = make_loaded("idw")
    spec = flow._compose_spec(request(), loaded, {"classification": {"method": "jenks", "n": 5}})
    assert spec.map_type == "idw"


def test_compose_spec_raises_field_missing():
    loaded = make_loaded()
    with pytest.raises(FieldMissing):
        flow._compose_spec(request(metric="NO2_24h"), loaded, {})


def test_form_spec_rejects_mismatched_layer_type():
    loaded = make_loaded()
    loaded["admin"] = None
    with pytest.raises(DataError, match="choropleth 需要面数据"):
        flow._form_spec(flow.RequestParse(request()), {"map_type": "choropleth"}, loaded)


def test_form_spec_rejects_forbidden_palette():
    loaded = make_loaded()
    with pytest.raises(DataError, match="彩虹"):
        flow._form_spec(
            flow.RequestParse(request()),
            {"map_type": "point", "method": "quantile", "n": 5, "palette_scheme": "rainbow"},
            loaded,
        )


def test_form_spec_builds_point_spec():
    loaded = make_loaded()
    spec = flow._form_spec(
        flow.RequestParse(request()),
        {"map_type": "point", "method": "equal_interval", "n": 3, "palette_scheme": "YlGnBu"},
        loaded,
    )
    assert spec.map_type == "point"
    assert spec.classification is not None
    assert spec.classification.method == "equal_interval"
    assert spec.palette.scheme == "YlGnBu"


# --- 渲染分派 -------------------------------------------------------------


def test_render_frame_uses_points_for_point_map():
    loaded = make_loaded()
    spec = flow._form_spec(
        flow.RequestParse(request()), {"map_type": "point", "method": "quantile", "n": 3}, loaded
    )
    frame = flow._render_frame(spec, loaded)
    assert frame is loaded["points"].gdf


def test_render_frame_aggregates_points_to_admin_for_choropleth():
    loaded = make_loaded()
    spec = flow._form_spec(
        flow.RequestParse(request()), {"map_type": "choropleth", "method": "quantile", "n": 3}, loaded
    )
    frame = flow._render_frame(spec, loaded)

    assert len(frame) == len(loaded["admin"].gdf)
    assert "PM2_5_24h" in frame.columns


def test_to_mapspec_filters_review_patch_fields():
    loaded = make_loaded()
    spec = flow._compose_spec(request(), loaded, {"classification": {"method": "quantile", "n": 3}})
    data = spec.model_dump()
    data["classification"]["unit"] = "μg/m³"
    data["palette"] = {"scheme": "AQI6", "reverse": False}

    restored = flow._to_mapspec(data)
    assert restored.classification is not None
    assert restored.classification.unit == "μg/m³"
    assert restored.palette.scheme == "AQI6"


# --- 加载 -----------------------------------------------------------------


def test_load_layers_from_demo_data():
    loaded = flow._load_layers(request(), upload=None)

    assert loaded["admin"].kind == "admin"
    assert loaded["points"].kind == "point"
    assert loaded["decision"] in {"degrade", "idw", "reject"}
    assert loaded["field"] == "PM2_5_24h"


def test_upload_without_crs_is_blocked_until_confirmed(tmp_path: Path):
    csv = tmp_path / "sites.csv"
    csv.write_text("station_name,lon,lat,PM2_5_24h\nA,117.18,34.22,45\nB,117.22,34.28,58\n", encoding="utf-8")
    upload = flow.UploadRecord(upload_id="u1", path=csv, name=csv.name)

    with pytest.raises(CrsNotDeclared):
        flow._load_layers(request(), upload)


def test_upload_point_with_confirmed_crs_is_profiled(tmp_path: Path):
    csv = tmp_path / "sites.csv"
    csv.write_text("station_name,lon,lat,PM2_5_24h\nA,117.18,34.22,45\nB,117.22,34.28,58\n", encoding="utf-8")
    upload = flow.UploadRecord(upload_id="u1", path=csv, name=csv.name, confirmed_crs="EPSG:4326")

    loaded = flow._load_layers(request(), upload)

    assert loaded["points"].kind == "point"
    assert loaded["points"].gdf is not None
    assert loaded["decision"] == "reject"


def test_upload_surface_layer_uses_choropleth_profile(tmp_path: Path):
    areas = gpd.GeoDataFrame(
        {
            "name": ["A", "B"],
            "PM2_5_24h": [40.0, 60.0],
            "geometry": [box(117.1, 34.1, 117.2, 34.2), box(117.2, 34.2, 117.3, 34.3)],
        },
        crs="EPSG:4326",
    )
    path = tmp_path / "areas.geojson"
    areas.to_file(path, driver="GeoJSON")
    upload = flow.UploadRecord(upload_id="u2", path=path, name=path.name, confirmed_crs="EPSG:4326")

    loaded = flow._load_layers(request(), upload)

    assert loaded["decision"] == "choropleth"
    assert loaded["points"] is None
    assert loaded["profile"].n_valid == 2
    assert "有效面" in loaded["summary"]


# --- 端到端（替身 LLM + 替身渲染） ----------------------------------------


class FakeRender:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.calls: list[Any] = []

    def __call__(self, spec, gdf, out_dir, *, name="map", **kwargs):
        self.calls.append(
            {
                "spec": spec,
                "rows": len(gdf),
                "out_dir": Path(out_dir),
                "name": name,
                "background": kwargs.get("background_gdf") is not None,
            }
        )
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        png = out / f"{name}.png"
        pdf = out / f"{name}.pdf"
        png.write_bytes(b"png")
        pdf.write_bytes(b"%PDF")
        return RenderResult(png_path=png, pdf_path=pdf, report=None)


def test_run_form_goes_through_loop(monkeypatch, tmp_path: Path):
    loaded = make_loaded()
    fake_render = FakeRender(tmp_path)
    monkeypatch.setattr(flow, "_load_layers", lambda _request, _upload: loaded)
    monkeypatch.setattr(flow, "run_render", fake_render)

    run = flow.run_form(
        {
            "place": "徐州",
            "time": "20261101",
            "metric": "PM2.5",
            "map_type": "point",
            "method": "quantile",
            "n": 3,
            "palette_scheme": "YlOrRd",
        },
        output_dir=tmp_path,
        request_id="r_test",
    )

    assert run.result.status == "rendered"
    assert run.result.round_no == 1
    assert run.result.png is not None
    assert run.result.png.exists()
    assert fake_render.calls[0]["rows"] == 5


def test_run_one_sentence_parses_then_runs_loop(monkeypatch, tmp_path: Path):
    loaded = make_loaded()
    fake_render = FakeRender(tmp_path)
    monkeypatch.setattr(flow, "_load_layers", lambda _request, _upload: loaded)
    monkeypatch.setattr(flow, "run_render", fake_render)

    calls: list[str] = []

    def fake_llm(system_prompt: str, payload):
        if "DataSteward" in system_prompt:
            calls.append("parse")
            return {"place": "徐州", "time": "20261101", "metric": "PM2.5"}
        calls.append("map")
        assert payload["data_profile"]["decision"] == "degrade"
        assert payload["user_request"]["metric"] == "PM2_5_24h"
        return {
            "title": "徐州市 PM2.5 24 小时均值分布图（2026-11-01）",
            "classification": {"method": "quantile", "n": 3},
            "palette": {"scheme": "YlOrRd"},
        }

    run = flow.run_one_sentence(
        "徐州 20261101 的 PM2.5",
        llm_callable=fake_llm,
        output_dir=tmp_path,
        request_id="r_test2",
    )

    assert calls == ["parse", "map"]
    assert run.result.status == "rendered"
    assert run.result.spec is not None
    assert run.result.spec["map_type"] == "point"


def test_run_one_sentence_missing_field_returns_questions_without_loading(monkeypatch):
    loaded_calls: list[int] = []
    monkeypatch.setattr(flow, "_load_layers", lambda *_args: loaded_calls.append(1) or make_loaded())

    def fake_llm(system_prompt: str, payload):
        return {"place": "徐州"}

    run = flow.run_one_sentence("徐州的数据", llm_callable=fake_llm)

    assert run.result.status == "needs_input"
    assert len(run.result.questions) <= 2
    assert loaded_calls == []


def test_run_one_sentence_reject_returns_needs_input(monkeypatch, tmp_path: Path):
    loaded = make_loaded("reject")
    monkeypatch.setattr(flow, "_load_layers", lambda *_args: loaded)
    monkeypatch.setattr(flow, "run_render", FakeRender(tmp_path))

    def fake_llm(system_prompt: str, payload):
        if "DataSteward" in system_prompt:
            return {"place": "徐州", "time": "20261101", "metric": "PM2.5"}
        raise AssertionError("reject 不应调用制图")

    run = flow.run_one_sentence(
        "徐州 20261101 的 PM2.5",
        llm_callable=fake_llm,
        output_dir=tmp_path,
    )

    assert run.result.status == "needs_input"
    assert run.result.decision == "reject"


def test_compose_spec_forces_aqi_national_six_classes():
    loaded = make_loaded()
    points = loaded["points"]
    points.gdf["AQI"] = [45.0, 58.0, 120.0, 210.0, 320.0]
    loaded["layer"] = points
    loaded["field"] = "AQI"

    spec = flow._compose_spec(
        request(metric="AQI"),
        loaded,
        {"classification": {"method": "quantile", "n": 3}, "palette": {"scheme": "YlOrRd"}},
    )

    assert spec.classification is not None
    assert spec.classification.method == "custom"
    assert spec.classification.n == 6
    assert spec.classification.breaks == [50.0, 100.0, 150.0, 200.0, 300.0, None]
    assert spec.classification.unit == "无量纲"
    assert spec.palette.scheme == "AQI6"

    verdict = flow.review_fn(spec, png="not-none")
    assert verdict["passed"] is True