"""T06 / T07 `load_layer` 的用例（全程离线，使用临时数据）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from mapsmith.config import get_settings
from mapsmith.io.models import DataError, FieldMissing
from mapsmith.tools.load_layer import load_admin, load_air
from mapsmith.tools.resolve_place import PlaceResult

STATIONS = [
    ("S001", "徐州监测站", "徐州", 117.10, 34.22),
    ("S002", "大庙站", "徐州", 117.15, 34.25),
    ("S003", "铜山站", "徐州", 117.20, 34.22),
    ("S004", "贾汪站", "徐州", 117.12, 34.28),
    ("S005", "泉山站", "徐州", 117.18, 34.30),
    ("S006", "云龙站", "徐州", 117.22, 34.27),
    ("S007", "新城区站", "徐州", 117.08, 34.26),
    ("S008", "沛县站", "徐州", 117.24, 34.24),
    ("S009", "丰县站", "徐州", 117.14, 34.32),
    ("N001", "南京站", "南京", 118.78, 32.06),
]


def _write_sites(path: Path) -> None:
    lines = ["监测点编码,监测点名称,城市,经度,纬度"]
    lines += [",".join([code, name, city, str(lon), str(lat)]) for code, name, city, lon, lat in STATIONS]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_air(path: Path, day: str = "20261101") -> None:
    header = ["date", "hour", "type"] + [code for code, *_ in STATIONS]
    rows = [",".join(header)]
    for hour in (22, 23):
        values = [f"{30 + index + hour}" for index in range(len(STATIONS))]
        rows.append(",".join([day, str(hour), "PM2.5_24h", *values]))
    # 1 小时值用于验证聚合口径不同。
    rows.append(",".join([day, "23", "PM2.5"] + ["50"] * len(STATIONS)))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_load_air_returns_nine_xuzhou_stations(tmp_path) -> None:
    sites = tmp_path / "sites.csv"
    air = tmp_path / "china_sites_20261101.csv"
    _write_sites(sites)
    _write_air(air)

    layer = load_air(
        "徐州",
        "20261101",
        field="PM2_5_24h",
        sites_path=sites,
        data_path=air,
        online=False,
    )

    assert layer.kind == "point"
    assert layer.count == 9
    assert layer.meta["station_total"] == 9
    assert layer.meta["station_valid"] == 9
    assert layer.meta["completeness"] == 1.0
    assert layer.meta["aggregate"] == "取当日最后一个有效观测"
    assert "PM2_5_24h" in layer.gdf.columns
    assert "value" not in layer.gdf.columns
    assert "有效值 9 个" in layer.summary
    assert "完整度 100%" in layer.summary


def test_load_air_uses_daily_mean_for_hourly_field(tmp_path) -> None:
    sites = tmp_path / "sites.csv"
    air = tmp_path / "china_sites_20261101.csv"
    _write_sites(sites)
    _write_air(air)

    layer = load_air(
        "徐州",
        "20261101",
        field="PM2_5",
        sites_path=sites,
        data_path=air,
        online=False,
    )

    assert layer.meta["aggregate"] == "取当日有效小时均值"
    assert layer.meta["value_max"] == 50.0


def test_load_air_rejects_unknown_field(tmp_path) -> None:
    sites = tmp_path / "sites.csv"
    air = tmp_path / "china_sites_20261101.csv"
    _write_sites(sites)
    _write_air(air)

    with pytest.raises(FieldMissing) as excinfo:
        load_air(
            "徐州",
            "20261101",
            field="NO2_24h",
            sites_path=sites,
            data_path=air,
            online=False,
        )

    assert "NO2_24h" in str(excinfo.value)
    assert "PM2.5_24h" in str(excinfo.value)


def test_load_air_without_city_match_reports_clearly(tmp_path) -> None:
    sites = tmp_path / "sites.csv"
    air = tmp_path / "china_sites_20261101.csv"
    _write_sites(sites)
    _write_air(air)
    suzhou = PlaceResult(
        name="苏州",
        full_name="苏州市",
        adcode="320500",
        level="city",
        parent="江苏省",
        bbox=(120.0, 30.8, 121.4, 32.1),
        bbox_source="测试构造",
        source="测试构造",
        summary="测试构造",
    )

    with pytest.raises(DataError) as excinfo:
        load_air(
            suzhou,
            "20261101",
            sites_path=sites,
            data_path=air,
            online=False,
        )

    assert "没有匹配" in str(excinfo.value)


@pytest.fixture
def isolated_demo_dir(tmp_path, monkeypatch):
    """把 demo_data 指到临时目录，避免测试依赖仓库里的演示文件。"""
    original = get_settings().demo_data_dir
    shutil.copy(original / "places.json", tmp_path / "places.json")
    monkeypatch.setenv("MAPSMITH_DEMO_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        yield tmp_path
    finally:
        get_settings.cache_clear()


def test_load_admin_prefers_local_boundary(isolated_demo_dir) -> None:
    boundary_dir = isolated_demo_dir / "boundaries"
    boundary_dir.mkdir()
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "铜山区", "adcode": "320312"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[116.9, 34.2], [117.4, 34.2], [117.4, 34.6], [116.9, 34.6], [116.9, 34.2]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"name": "鼓楼区", "adcode": "320302"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[117.1, 34.2], [117.3, 34.2], [117.3, 34.3], [117.1, 34.3], [117.1, 34.2]]],
                },
            },
        ],
    }
    (boundary_dir / "320300_full.json").write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")

    layer = load_admin("徐州", online=False)

    assert layer.kind == "admin"
    assert layer.count == 2
    assert layer.meta["name_field"] == "name"
    assert layer.meta["code_field"] == "adcode"
    assert layer.crs == "EPSG:4326"
    assert "2 个面要素" in layer.summary


def test_load_admin_without_local_or_network_is_explicit(isolated_demo_dir) -> None:
    with pytest.raises(DataError) as excinfo:
        load_admin("徐州", online=False)

    assert "离线边界文件" in str(excinfo.value)


def test_gdf_bbox_helper_is_consistent_with_boundary() -> None:
    gdf = gpd.GeoDataFrame(geometry=[box(116.2, 34.1, 118.6, 34.9)], crs="EPSG:4326")
    from mapsmith.io.models import DataLayer

    layer = DataLayer(kind="admin", name="test", source="test", summary="test", gdf=gdf, crs="EPSG:4326")

    assert layer.bbox_wgs84() == (116.2, 34.1, 118.6, 34.9)


def test_missing_station_keeps_row_with_null(tmp_path) -> None:
    """缺测站不能从点图层里消失，否则体检会算成「完整度 100%」。"""
    sites = tmp_path / "sites.csv"
    air = tmp_path / "china_sites_20261101.csv"
    _write_sites(sites)
    header = ["date", "hour", "type", "S001"] + [code for code, *_ in STATIONS[1:]]
    rows = [",".join(header)]
    for hour in (22, 23):
        # S001 整列留空，其余站点有值：缺测站必须保留在图层里。
        values = [""] + [str(40 + index) for index in range(len(STATIONS) - 1)]
        rows.append(",".join(["20261101", str(hour), "PM2.5_24h", *values]))
    air.write_text("\n".join(rows) + "\n", encoding="utf-8")

    layer = load_air(
        "徐州",
        "20261101",
        field="PM2_5_24h",
        sites_path=sites,
        data_path=air,
        online=False,
    )

    assert layer.meta["station_total"] == 9
    assert layer.meta["station_valid"] == 8
    assert layer.count == 9
    assert int(layer.gdf["PM2_5_24h"].isna().sum()) == 1


def test_hour_order_is_respected_for_last_observation(tmp_path) -> None:
    """文件里 hour 乱序时，取最后有效观测必须按小时排序，而不是按行序。"""
    sites = tmp_path / "sites.csv"
    air = tmp_path / "china_sites_20261101.csv"
    _write_sites(sites)
    header = ["date", "hour", "type"] + [code for code, *_ in STATIONS]
    rows = [",".join(header)]
    rows.append(",".join(["20261101", "23", "PM2.5_24h"] + ["80"] * len(STATIONS)))
    rows.append(",".join(["20261101", "22", "PM2.5_24h"] + ["40"] * len(STATIONS)))
    air.write_text("\n".join(rows) + "\n", encoding="utf-8")

    layer = load_air(
        "徐州",
        "20261101",
        field="PM2_5_24h",
        sites_path=sites,
        data_path=air,
        online=False,
    )

    assert layer.meta["value_max"] == 80.0

