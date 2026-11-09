"""T08 上传解析的用例。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point

from mapsmith.io.models import CrsNotDeclared, DataError
from mapsmith.io.uploads import ensure_crs, parse_upload

GEOJSON_NO_CRS = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"name": "测试点"},
            "geometry": {"type": "Point", "coordinates": [117.1, 34.2]},
        }
    ],
}

GEOJSON_WITH_CRS = {
    "type": "FeatureCollection",
    "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
    "features": GEOJSON_NO_CRS["features"],
}


def _write_csv(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_csv_points_without_crs_needs_confirmation(tmp_path) -> None:
    path = tmp_path / "sites.csv"
    _write_csv(path, "站点名,经度,纬度,PM2_5_24h\n徐州站,117.1,34.2,88\n")

    layer = parse_upload(path)

    assert layer.kind == "point"
    assert layer.count == 1
    assert layer.meta["crs_status"] == "missing"
    assert "确认" in layer.summary
    with pytest.raises(CrsNotDeclared):
        ensure_crs(layer)


def test_csv_points_with_confirmed_crs_passes_gate(tmp_path) -> None:
    path = tmp_path / "sites.csv"
    _write_csv(path, "站点名,经度,纬度,PM2_5_24h\n徐州站,117.1,34.2,88\n")

    layer = parse_upload(path, crs="EPSG:4326")

    assert layer.meta["crs_status"] == "declared"
    assert layer.crs == "EPSG:4326"
    assert ensure_crs(layer) is layer


def test_csv_without_coordinates_is_a_table(tmp_path) -> None:
    path = tmp_path / "stats.csv"
    _write_csv(path, "城市,PM2_5_24h\n徐州,88\n")

    layer = parse_upload(path)

    assert layer.kind == "table"
    assert layer.gdf is None
    assert layer.meta["crs_status"] == "not_applicable"
    assert ensure_crs(layer) is layer


def test_csv_drops_rows_with_invalid_coordinates(tmp_path) -> None:
    path = tmp_path / "sites.csv"
    _write_csv(path, "名称,lon,lat,值\nA,117.1,34.2,1\nB,abc,34.3,2\n")

    layer = parse_upload(path, crs="EPSG:4326")

    assert layer.count == 1
    assert layer.meta["invalid_coordinates"] == 1


def test_geojson_without_crs_member_is_marked(tmp_path) -> None:
    path = tmp_path / "layer.geojson"
    path.write_text(json.dumps(GEOJSON_NO_CRS), encoding="utf-8")

    layer = parse_upload(path)

    assert layer.meta["crs_status"] == "missing"
    assert layer.meta["suggested_crs"] == "EPSG:4326"


def test_geojson_with_crs_member_is_declared(tmp_path) -> None:
    path = tmp_path / "layer.geojson"
    path.write_text(json.dumps(GEOJSON_WITH_CRS), encoding="utf-8")

    layer = parse_upload(path)

    assert layer.meta["crs_status"] == "declared"


def _make_shapefile(tmp_path) -> Path:
    gdf = gpd.GeoDataFrame(
        {"name": ["A"]},
        geometry=[Point(117.1, 34.2)],
        crs="EPSG:4326",
    )
    shp_path = tmp_path / "layer.shp"
    gdf.to_file(shp_path)
    return shp_path


def test_shapefile_zip_without_dbf_is_rejected(tmp_path) -> None:
    shp_path = _make_shapefile(tmp_path)
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(shp_path, "layer.shp")
        archive.write(shp_path.with_suffix(".shx"), "layer.shx")

    with pytest.raises(DataError) as excinfo:
        parse_upload(archive_path)

    assert "缺少" in str(excinfo.value)


def test_shapefile_zip_with_prj_is_declared(tmp_path) -> None:
    shp_path = _make_shapefile(tmp_path)
    archive_path = tmp_path / "good.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for suffix in (".shp", ".shx", ".dbf", ".prj"):
            file_path = shp_path.with_suffix(suffix)
            archive.write(file_path, file_path.name)

    layer = parse_upload(archive_path)

    assert layer.kind == "point"
    assert layer.count == 1
    assert layer.meta["crs_status"] == "declared"
    assert layer.meta["has_prj"] is True


def test_unsupported_suffix_is_rejected(tmp_path) -> None:
    path = tmp_path / "notes.docx"
    path.write_bytes(b"not a map")

    with pytest.raises(DataError) as excinfo:
        parse_upload(path)

    assert "不支持的文件类型" in str(excinfo.value)


def test_point_geojson_is_marked_as_point_layer(tmp_path) -> None:
    """点数据若被标成 admin，插值体检会直接拒绝。"""
    path = tmp_path / "points.geojson"
    path.write_text(json.dumps(GEOJSON_NO_CRS), encoding="utf-8")

    layer = parse_upload(path)

    assert layer.kind == "point"


def test_point_shapefile_zip_is_marked_as_point_layer(tmp_path) -> None:
    shp_path = _make_shapefile(tmp_path)
    archive_path = tmp_path / "points.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for suffix in (".shp", ".shx", ".dbf", ".prj"):
            file_path = shp_path.with_suffix(suffix)
            archive.write(file_path, file_path.name)

    layer = parse_upload(archive_path)

    assert layer.kind == "point"