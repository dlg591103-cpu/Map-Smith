"""T09 GeoTIFF 离线底图的用例。"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from mapsmith.io.models import DataError
from mapsmith.io.raster import load_geotiff

GEO_TAGS = {
    33550: (0.01, 0.01, 0.0),  # ModelPixelScale
    33922: (0.0, 0.0, 0.0, 116.0, 34.0, 0.0),  # ModelTiepoint
    34735: (1, 1, 0, 1, 2048, 0, 1, 4490),  # GeoKeyDirectory：GeographicTypeGeoKey=4490
}


def test_geotiff_extent_and_crs(tmp_path) -> None:
    path = tmp_path / "underlay.tif"
    Image.new("L", (20, 10)).save(path, tiffinfo=GEO_TAGS)

    underlay = load_geotiff(path)

    assert underlay.crs == "EPSG:4490"
    assert underlay.width == 20
    assert underlay.height == 10
    assert underlay.extent == pytest.approx((116.0, 116.2, 33.9, 34.0))
    assert underlay.array.shape == (10, 20)
    assert "不做栅格分析与重投影" in underlay.summary


def test_plain_tiff_without_georeference_is_rejected(tmp_path) -> None:
    path = tmp_path / "plain.tif"
    Image.fromarray(np.zeros((5, 5), dtype=np.uint8)).save(path)

    with pytest.raises(DataError) as excinfo:
        load_geotiff(path)

    assert "地理参考" in str(excinfo.value)


def test_same_crs_can_overlay_directly(tmp_path) -> None:
    path = tmp_path / "underlay.tif"
    Image.new("L", (10, 10)).save(path, tiffinfo=GEO_TAGS)

    underlay = load_geotiff(path.rename(tmp_path / "a.tif"))
    ok, message = underlay.check_crs("EPSG:4490")

    assert ok is True
    assert "一致" in message


def test_different_crs_warns_without_reprojecting(tmp_path) -> None:
    path = tmp_path / "underlay.tif"
    Image.new("L", (10, 10)).save(path, tiffinfo=GEO_TAGS)

    underlay = load_geotiff(path)
    ok, message = underlay.check_crs("EPSG:4548")

    assert ok is False
    assert "不做自动配准与重投影" in message