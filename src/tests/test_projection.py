import pytest

from mapsmith.projection import (
    TransformChain,
    choose_measurement_crs,
    ensure_measure_allowed,
    gk_band_from_epsg,
    is_output_allowed,
    plan_transform,
    resolve_output_crs,
    select_gk_band,
    select_utm_band,
)


def test_xuzhou_selects_4548():
    band = select_gk_band(117.18)
    assert band.epsg == "EPSG:4548"
    assert band.zone == 39
    assert band.central_meridian == 117
    assert band.with_zone_prefix is False
    assert band.false_easting == 500_000.0
    text = band.describe()
    assert "中央经线 117°E" in text
    assert "EPSG:4548" in text


def test_zone_prefix_variant():
    band = select_gk_band(117.18, with_zone_prefix=True)
    assert band.epsg == "EPSG:4527"
    assert band.false_easting == 39_500_000.0
    assert "带号前缀" in band.describe()


def test_band_boundary_rounds_up():
    assert select_gk_band(115.5).central_meridian == 117
    assert select_gk_band(114.0).central_meridian == 114


def test_other_bands():
    assert select_gk_band(121.47).epsg == "EPSG:4549"  # CM 120E
    assert select_gk_band(87.6).epsg == "EPSG:4538"  # CM 87E


def test_out_of_coverage_rejected():
    with pytest.raises(ValueError, match="覆盖范围"):
        select_gk_band(10.0)


def test_gk_band_from_epsg():
    band = gk_band_from_epsg("EPSG:4548")
    assert band.zone == 39
    assert band.central_meridian == 117

    with pytest.raises(ValueError, match="高斯-克吕格"):
        gk_band_from_epsg("EPSG:4490")


def test_measurement_single_band_xuzhou():
    decision = choose_measurement_crs((116.2, 34.1, 118.6, 34.9))
    assert decision.kind == "gk"
    assert decision.crs == "EPSG:4548"
    assert decision.zone == 39
    text = decision.describe()
    assert "中央经线 117°E" in text
    assert "EPSG:4548" in text


def test_measurement_cross_band_uses_albers():
    decision = choose_measurement_crs((114.0, 30.0, 120.0, 35.0))
    assert decision.kind == "albers"
    assert "Albers" in decision.describe()


def test_measurement_rejects_bad_bbox():
    with pytest.raises(ValueError, match="bbox"):
        choose_measurement_crs((118.6, 34.1, 116.2, 34.9))


def test_output_whitelist():
    for crs in [
        "EPSG:4490",
        "EPSG:3857",
        "EPSG:4548",
        "EPSG:4527",
        "EPSG:32650",
        "EPSG:32750",
    ]:
        assert is_output_allowed(crs), crs

    for crs in ["EPSG:4326", "EPSG:32661", "EPSG:32761"]:
        assert not is_output_allowed(crs), crs


def test_default_output_is_cgcs2000():
    assert resolve_output_crs(None) == "EPSG:4490"
    assert resolve_output_crs("  ") == "EPSG:4490"
    assert resolve_output_crs("EPSG:4548") == "EPSG:4548"


def test_non_whitelisted_output_rejected():
    with pytest.raises(ValueError, match="白名单"):
        resolve_output_crs("EPSG:4326")


def test_web_mercator_cannot_measure():
    with pytest.raises(ValueError, match="禁止用于量算"):
        ensure_measure_allowed("EPSG:3857")
    ensure_measure_allowed("EPSG:4548")


def test_utm_bands():
    assert select_utm_band(117.18, northern=True) == "EPSG:32650"
    assert select_utm_band(117.18, northern=False) == "EPSG:32750"


def test_transform_chain_records_datum_change():
    step = plan_transform("EPSG:4326", "EPSG:4548")
    chain = TransformChain().add(step)
    text = chain.describe()
    assert "EPSG:4326" in text
    assert "EPSG:4548" in text
    assert step.datum_change is True
    assert chain.to_dict()[0]["datum_change"] is True


def test_transform_same_datum():
    step = plan_transform("EPSG:4490", "EPSG:4548")
    assert step.datum_change is False


def test_empty_chain():
    assert TransformChain().describe() == "未发生坐标变换。"