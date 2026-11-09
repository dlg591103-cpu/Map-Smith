"""T10 真实离线数据的集成用例。

数据文件在 `demo_data/`，属于交付物；缺失时跳过，不把「没下数据」当成通过。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapsmith.config import get_settings
from mapsmith.tools.inspect import profile_points
from mapsmith.tools.load_layer import load_admin, load_air

REFERENCE_FILES = [
    Path("boundaries") / "320300_full.json",
    Path("sites") / "sites.csv",
    Path("air") / "china_sites_20261101.csv",
]


def _missing() -> list[str]:
    root = get_settings().demo_data_dir
    return [str(item) for item in REFERENCE_FILES if not (root / item).exists()]


@pytest.mark.skipif(bool(_missing()), reason=f"demo_data 缺少：{_missing()}")
def test_xuzhou_20261101_end_to_end() -> None:
    air = load_air("徐州", "20261101", field="PM2_5_24h", online=False)
    admin = load_admin("徐州", online=False)

    assert admin.count == 10
    assert air.meta["station_crs"] == "EPSG:4326"
    assert "PM2_5_24h" in air.gdf.columns

    profile = profile_points(air, field_name="PM2_5_24h", study_area=admin)

    # 2026-11-01 徐州：列表 11 站，数据列 10 站，其中 5 站整日缺测。
    assert profile.total == 10
    assert profile.n_valid == 5
    assert profile.decision == "degrade"
    assert profile.cover is not None and profile.cover < 0.5
    assert profile.measurement_crs == "EPSG:4548"
    assert len(profile.reason_lines) == 3