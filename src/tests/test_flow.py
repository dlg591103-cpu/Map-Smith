"""T22 第二段：flow 装配测试。

大部分用构造图层与替身 LLM，少量用 demo_data 验证真实加载；不启动网络与浏览器。
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402

from mapsmith import flow
from mapsmith.io.models import CrsNotDeclared, DataError, DataLayer, FieldMissing
from mapsmith.io.uploads import parse_upload
from mapsmith.render.choropleth import render_choropleth
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


def test_normalize_time_accepts_year_less_dates():
    """口语里「11月1日」不带年份很常见，必须补当年而不是留空。

    早先只认 4 位年份，「11月1日」永远解析为空，系统会反复追问同一天。
    """
    year = flow.datetime.now().year  # noqa: SLF001 - 直接取模块里已导入的 datetime
    assert flow.normalize_time("11月1日") == f"{year}-11-01"
    assert flow.normalize_time("11月1号") == f"{year}-11-01"
    assert flow.normalize_time("11/1") == f"{year}-11-01"
    assert flow.normalize_time("11-01") == f"{year}-11-01"


def test_normalize_time_rejects_unparseable_value():
    assert flow.normalize_time("最近几天") == ""
    assert flow.normalize_time(None) == ""
    assert flow.normalize_time("2026-02-30") == ""


def test_allow_online_defaults_on_and_offline_env_disables(monkeypatch):
    """联网默认开启（离线优先语义），MAPSMITH_OFFLINE=1 才强制离线。

    「离线优先」指本地有数据就绝不联网，只有本地缺该日期/边界时才回落下载；
    与之配套的关闭开关是 MAPSMITH_OFFLINE，不是旧的 MAPSMITH_ALLOW_ONLINE。
    """
    monkeypatch.delenv("MAPSMITH_OFFLINE", raising=False)
    assert flow._allow_online() is True

    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("MAPSMITH_OFFLINE", value)
        assert flow._allow_online() is False

    monkeypatch.setenv("MAPSMITH_OFFLINE", "0")
    assert flow._allow_online() is True


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


def test_normalize_parse_ignores_questions_when_fields_complete():
    """三项齐全时不再反问：模型多余的 questions 不应阻断出图（T25）。"""
    parsed = flow.normalize_parse(
        {
            "place": "徐州",
            "time": "2026-11-01",
            "metric": "PM2.5",
            "questions": ["想画哪个城市或区县？", "要哪一天的数据？"],
        }
    )

    assert parsed.request == {"place": "徐州", "time": "2026-11-01", "metric": "PM2_5_24h"}
    assert parsed.questions == []


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


def test_parse_request_merges_history_into_user_text():
    """多轮追问：之前的原话要拼进 user_text，否则模型每轮只看半句、反复追问。

    复现路径：先说「徐州 pm2.5 分布图」（缺时间）→ 追问 → 再说「11月1日」。
    若不带 history，模型只看到「11月1日」，会重新问区域与指标，形成死循环。
    """
    captured: dict = {}

    def fake_llm(system_prompt: str, payload):
        captured["payload"] = payload
        return {"place": "徐州", "time": "11月1日", "metric": "PM2.5"}

    parsed = flow.parse_request(
        "11月1日",
        fake_llm,
        history=["徐州 pm2.5 分布图"],
    )

    assert captured["payload"]["multi_turn"] is True
    assert captured["payload"]["user_text"] == "徐州 pm2.5 分布图\n11月1日"
    assert parsed.questions == []
    # 「11月1日」缺年份也要解析出日期（补当年）
    assert parsed.request["time"].endswith("-11-01")


def test_parse_request_without_history_keeps_single_turn():
    captured: dict = {}

    def fake_llm(system_prompt: str, payload):
        captured["payload"] = payload
        return {"place": "徐州", "time": "20261101", "metric": "PM2.5"}

    flow.parse_request("徐州 20261101 的 PM2.5", fake_llm)
    assert captured["payload"]["multi_turn"] is False
    assert "\n" not in captured["payload"]["user_text"]


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


def test_form_spec_builds_buffer_spec():
    """T25：buffer 走确定性分析，spec 字段为 buffer_value，结果面图层交给渲染。"""
    loaded = make_loaded()
    spec = flow._form_spec(
        flow.RequestParse(request()),
        {"map_type": "buffer", "buffer_km": "5", "method": "quantile", "n": 5},
        loaded,
    )

    assert spec.map_type == "buffer"
    assert spec.layers[0].kind == "buffer"
    assert spec.layers[0].field == "buffer_value"
    assert loaded["analysis_layer"].kind == "buffer"
    assert any("缓冲距离" in note for note in spec.notes)


def test_compose_spec_uses_buffer_when_draft_asks():
    """T25：一句话模式下制图师可指定 buffer，系统做确定性分析并写回字段。"""
    loaded = make_loaded()
    spec = flow._compose_spec(
        request(),
        loaded,
        {
            "map_type": "buffer",
            "buffer_km": 5,
            "title": "徐州市PM2.5 2026-11-01图",
            "classification": {"method": "quantile", "n": 5},
            "palette": {"scheme": "YlOrRd"},
        },
    )

    assert spec.map_type == "buffer"
    assert spec.layers[0].kind == "buffer"
    assert spec.layers[0].field == "buffer_value"
    assert loaded["analysis_layer"].kind == "buffer"
    assert any("缓冲距离" in note for note in spec.notes)


def test_form_spec_rejects_overlay_without_face_layer():
    loaded = make_loaded()
    with pytest.raises(DataError, match="上传面图层"):
        flow._form_spec(
            flow.RequestParse(request()),
            {"map_type": "overlay", "overlay_op": "clip"},
            loaded,
        )


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


def test_load_overlay_base_returns_demo_boundary() -> None:
    """T25：上传面作为主体时，第二图层应取自 demo_data 边界。"""
    base = flow._load_overlay_base("徐州")
    assert base is not None
    assert base.kind == "admin"
    assert "徐州市" in base.name
    assert flow._load_overlay_base("不存在的城市") is None


def test_form_spec_overlay_reports_demo_as_second_layer() -> None:
    loaded = make_loaded()
    surface = DataLayer(
        kind="admin",
        name="上传面",
        source="upload",
        summary="2 个面",
        gdf=gpd.GeoDataFrame(
            {"name": ["面A", "面B"], "PM2_5_24h": [50.0, 60.0]},
            geometry=[
                box(117.1, 34.1, 117.25, 34.25),
                box(117.25, 34.25, 117.4, 34.4),
            ],
            crs="EPSG:4326",
        ),
        crs="EPSG:4326",
        meta={"adcode": "320300"},
    )
    loaded["layer"] = surface
    loaded["admin"] = surface
    loaded["overlay_base"] = make_admin()

    spec = flow._form_spec(
        flow.RequestParse(request()),
        {"map_type": "overlay", "overlay_op": "clip", "method": "quantile", "n": 2},
        loaded,
    )

    assert any("第二图层：徐州市行政边界" in note for note in spec.notes)


def test_buffer_legend_title_includes_radius_and_sites() -> None:
    """SPEC 3.1：buffer 图的图例需注明半径与参与站点数。"""
    loaded = make_loaded()
    spec = flow._form_spec(
        flow.RequestParse(request()),
        {"map_type": "buffer", "buffer_km": "5", "method": "quantile", "n": 2},
        loaded,
    )

    render_choropleth(spec, loaded["analysis_layer"].gdf, field="buffer_value")
    legend = plt.gcf().axes[0].get_legend()
    assert legend is not None
    title = legend.get_title().get_text()
    assert "缓冲距离 5 km" in title
    assert "面含站点" in title
    plt.close("all")


def test_map_type_hint_reads_buffer_distance_from_text() -> None:
    assert flow._map_type_hint("用徐州 2026-11-01 的 PM2.5 做 5 公里缓冲区分析") == (
        "buffer",
        {"buffer_km": 5.0},
    )
    assert flow._map_type_hint("做 3.5km 缓冲区") == ("buffer", {"buffer_km": 3.5})
    assert flow._map_type_hint("画徐州点图") is None


def test_map_type_hint_reads_overlay_operation() -> None:
    assert flow._map_type_hint("做裁剪叠加分析") == ("overlay", {"overlay_op": "clip"})
    assert flow._map_type_hint("做 intersection 相交分析") == (
        "overlay",
        {"overlay_op": "intersection"},
    )


def test_llm_map_fn_overrides_map_type_by_user_text() -> None:
    """原话点名缓冲时，即使模型输出 point，也要按 buffer 出图。"""

    def fake_llm(_prompt, _payload):
        return {
            "map_type": "point",
            "classification": {"method": "quantile", "n": 2},
            "palette": {"scheme": "YlOrRd"},
        }

    loaded = make_loaded()
    map_fn = flow._make_llm_map_fn(
        flow.RequestParse(request()),
        llm_callable=fake_llm,
        user_text="用徐州 2026-11-01 的 PM2.5 做 5 公里缓冲区分析",
    )
    spec = map_fn(loaded)

    assert spec.map_type == "buffer"
    assert loaded["analysis_layer"].kind == "buffer"


# --- T25 复验：图幅范围与体检结论注记 ---------------------------------------


def make_surface() -> DataLayer:
    """上传面作为 overlay 主体：只覆盖局部小面。"""
    return DataLayer(
        kind="admin",
        name="上传面",
        source="upload",
        summary="2 个面",
        gdf=gpd.GeoDataFrame(
            {"name": ["面A", "面B"], "PM2_5_24h": [50.0, 60.0]},
            geometry=[box(117.12, 34.15, 117.2, 34.22), box(117.25, 34.25, 117.33, 34.32)],
            crs="EPSG:4326",
        ),
        crs="EPSG:4326",
        meta={"adcode": "320300"},
    )


def test_form_spec_buffer_notes_drop_point_degrade_conclusion():
    """buffer 按用户图种渲染，注记不应写「降级为点图」。"""
    loaded = make_loaded()
    spec = flow._form_spec(
        flow.RequestParse(request()),
        {"map_type": "buffer", "buffer_km": "5", "method": "quantile", "n": 2},
        loaded,
    )

    assert not any("降级为点图" in note for note in spec.notes)
    assert any("站数" in note for note in spec.notes)
    assert any("缓冲距离" in note for note in spec.notes)


def test_form_spec_choropleth_notes_drop_point_degrade_conclusion():
    loaded = make_loaded()
    spec = flow._form_spec(
        flow.RequestParse(request()),
        {"map_type": "choropleth", "method": "quantile", "n": 3},
        loaded,
    )

    assert spec.map_type == "choropleth"
    assert not any("降级为点图" in note for note in spec.notes)


def test_form_spec_point_keeps_degrade_conclusion():
    """点图确实由 degrade 决定，结论行保留。"""
    loaded = make_loaded()
    spec = flow._form_spec(
        flow.RequestParse(request()),
        {"map_type": "point", "method": "quantile", "n": 3},
        loaded,
    )

    assert any("降级为点图" in note for note in spec.notes)


def test_compose_spec_buffer_drops_point_degrade_conclusion():
    """一句话点名缓冲时，结论行同样不应写「降级为点图」。"""
    loaded = make_loaded()
    spec = flow._compose_spec(
        request(),
        loaded,
        {
            "map_type": "buffer",
            "buffer_km": 5,
            "classification": {"method": "quantile", "n": 2},
            "palette": {"scheme": "YlOrRd"},
        },
    )

    assert not any("降级为点图" in note for note in spec.notes)


def test_overlay_spec_uses_region_extent_not_upload_extent():
    """overlay 图幅取第二图层范围，不随局部上传主体缩到满幅。"""
    loaded = make_loaded()
    surface = make_surface()
    loaded["layer"] = surface
    loaded["admin"] = surface
    loaded["overlay_base"] = make_admin()

    spec = flow._form_spec(
        flow.RequestParse(request()),
        {"map_type": "overlay", "overlay_op": "clip", "method": "quantile", "n": 2},
        loaded,
    )

    assert spec.extent.bbox == loaded["overlay_base"].bbox_wgs84()
    assert not any("降级为点图" in note for note in spec.notes)


def test_ensure_title_requires_region_suffix_for_r01():
    """R01 要求区域带行政区后缀；模型只写「徐州」时回退本地标题。"""
    assert (
        flow._ensure_title("徐州 PM2.5 分布图（2026-11-01）", "徐州", "PM2_5_24h", "2026-11-01")
        == "徐州市 PM2.5 分布图（2026-11-01，μg/m³）"
    )
    kept = "徐州市 PM2.5 分布图（2026-11-01，μg/m³）"
    assert flow._ensure_title(kept, "徐州", "PM2_5_24h", "2026-11-01") == kept

# --- 上传统计表自动关联行政区（2026-11-18）--------------------------------


def _admin_layer_4_districts():
    """4 个方形区县，name 列用于关联。"""
    import pandas as pd
    from mapsmith.io.models import DataLayer

    gdf = gpd.GeoDataFrame(
        {"name": ["鼓楼区", "云龙区", "泉山区", "铜山区"], "adcode": [320302, 320303, 320311, 320312]},
        geometry=[box(117.0, 34.2, 117.1, 34.3), box(117.1, 34.2, 117.2, 34.3),
                  box(117.2, 34.2, 117.3, 34.3), box(117.3, 34.2, 117.4, 34.3)],
        crs="EPSG:4326",
    )
    return DataLayer(kind="admin", name="测试边界", source="test", summary="4 面", gdf=gdf)


def test_pick_table_key_finds_district_column():
    import pandas as pd

    stats = pd.DataFrame({"district": ["鼓楼区", "云龙区"], "gdp": [1.0, 2.0]})
    admin = _admin_layer_4_districts()
    assert flow._pick_table_key(stats, admin.gdf) == "district"


def test_pick_table_key_returns_none_when_no_match():
    import pandas as pd

    stats = pd.DataFrame({"city": ["南京", "无锡"], "gdp": [1.0, 2.0]})
    admin = _admin_layer_4_districts()
    assert flow._pick_table_key(stats, admin.gdf) is None


def test_pick_table_value_prefers_form_field_then_sole_numeric():
    import pandas as pd

    stats = pd.DataFrame({"district": ["a", "b"], "gdp": [1.0, 2.0], "population": [3.0, 4.0]})
    # 表单选的指标不在表里 → 按线索词挑到 gdp
    assert flow._pick_table_value(stats, "district", "PM2_5_24h") == "gdp"
    # 表单选的就是表里的列 → 直接用它
    assert flow._pick_table_value(stats, "district", "population") == "population"
    # 只有一个数值列时无歧义
    solo = pd.DataFrame({"district": ["a"], "value": [1.0]})
    assert flow._pick_table_value(solo, "district", "PM2_5_24h") == "value"


def test_join_upload_table_produces_admin_layer_with_value():
    import pandas as pd
    from mapsmith.io.models import DataLayer

    stats = pd.DataFrame({"district": ["鼓楼区", "云龙区"], "gdp": [520.5, 610.2]})
    table = DataLayer(kind="table", name="gdp.csv", source="test", summary="2 行", table=stats)
    admin = _admin_layer_4_districts()

    joined, field = flow._join_upload_table(table, admin, "PM2_5_24h")

    assert field == "gdp"
    assert joined.kind == "admin"
    assert joined.gdf is not None
    assert int(joined.gdf["gdp"].notna().sum()) == 2
    assert "自动关联" in joined.summary


def test_join_upload_table_raises_when_no_admin_name_match():
    import pandas as pd
    from mapsmith.io.models import DataLayer

    stats = pd.DataFrame({"district": ["不存在区", "另一个区"], "gdp": [1.0, 2.0]})
    table = DataLayer(kind="table", name="bad.csv", source="test", summary="2 行", table=stats)
    admin = _admin_layer_4_districts()

    with pytest.raises(Exception):
        flow._join_upload_table(table, admin, "PM2_5_24h")


def test_allow_online_stats_search_defaults_off(monkeypatch):
    """联网搜索统计数据是实验性能力，默认关闭（免费搜索通道实测不可靠）。"""
    monkeypatch.delenv("MAPSMITH_SEARCH_ONLINE", raising=False)
    assert flow._allow_online_stats_search() is False

    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("MAPSMITH_SEARCH_ONLINE", value)
        assert flow._allow_online_stats_search() is True

    monkeypatch.setenv("MAPSMITH_SEARCH_ONLINE", "0")
    assert flow._allow_online_stats_search() is False
