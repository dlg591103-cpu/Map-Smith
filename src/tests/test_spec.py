import copy

import pytest
from pydantic import ValidationError

from mapsmith.spec import Classification, Extent, Layout, MapSpec

# docs/facts/05-MapSpec与工具契约.md 中的示例，逐字段照录。
BASE = {
    "title": "徐州市 PM2.5 24 小时均值分布图（2026-11-01）",
    "map_type": "idw",
    "extent": {"adcode": "320300", "bbox": [116.2, 34.1, 118.6, 34.9]},
    "layers": [
        {"id": "base", "kind": "admin", "style": {"fill": "#f7f7f7", "edge": "#999999"}},
        {"id": "data", "kind": "idw", "field": "PM2_5_24h", "source": "quotsoft_20261101"},
    ],
    "classification": {"method": "quantile", "n": 5, "breaks": [35, 55, 75, 115, 150]},
    "palette": {"scheme": "YlOrRd", "reverse": False},
    "annotation": {"label_field": "站点名", "show": True},
    "layout": {
        "size": [10, 8],
        "dpi": 300,
        "legend": True,
        "scale_bar": True,
        "north_arrow": True,
        "source_note": True,
        "crs_note": True,
    },
    "data_source_note": "数据来源：全国城市空气质量实时发布平台（quotsoft.net）",
    "crs": "EPSG:4490",
    "notes": ["2 个站点缺测，已按空间邻近插补"],
}


def make(**overrides):
    data = copy.deepcopy(BASE)
    data.update(overrides)
    return data


def test_facts_example_valid():
    spec = MapSpec.model_validate(BASE)
    assert spec.map_type == "idw"
    assert spec.extent.bbox == (116.2, 34.1, 118.6, 34.9)
    assert spec.classification.method == "quantile"
    assert spec.classification.breaks == [35, 55, 75, 115, 150]
    assert spec.crs == "EPSG:4490"


def test_roundtrip():
    spec = MapSpec.model_validate(BASE)
    again = MapSpec.from_json(spec.to_json())
    assert again == spec
    assert again.to_json() == spec.to_json()


def test_frozen():
    spec = MapSpec.model_validate(BASE)
    with pytest.raises(ValidationError):
        spec.title = "改名"


def test_extra_field_rejected():
    data = make()
    data["agent_reasoning"] = "模型自由发挥"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MapSpec.model_validate(data)


def test_missing_title_rejected():
    data = make()
    data.pop("title")
    with pytest.raises(ValidationError):
        MapSpec.model_validate(data)


def test_invalid_map_type_rejected():
    with pytest.raises(ValidationError):
        MapSpec.model_validate(make(map_type="heatmap"))


def test_bbox_order_rejected():
    with pytest.raises(ValidationError, match="bbox"):
        Extent.model_validate({"bbox": [118.6, 34.1, 116.2, 34.9]})
    with pytest.raises(ValidationError, match="bbox"):
        Extent.model_validate({"bbox": [116.2, 34.9, 118.6, 34.1]})


def test_adcode_rejected():
    with pytest.raises(ValidationError, match="adcode"):
        Extent.model_validate({"adcode": "32030", "bbox": [116.2, 34.1, 118.6, 34.9]})


def test_empty_layers_rejected():
    with pytest.raises(ValidationError):
        MapSpec.model_validate(make(layers=[]))


def test_duplicate_layer_id_rejected():
    layers = copy.deepcopy(BASE["layers"])
    layers.append({"id": "data", "kind": "point"})
    with pytest.raises(ValidationError, match="id 必须唯一"):
        MapSpec.model_validate(make(layers=layers))


def test_idw_layer_requires_field():
    layers = [{"id": "data", "kind": "idw"}]
    with pytest.raises(ValidationError, match="field"):
        MapSpec.model_validate(make(layers=layers))


def test_map_type_requires_matching_layer():
    layers = [{"id": "base", "kind": "admin"}]
    with pytest.raises(ValidationError, match="kind=idw"):
        MapSpec.model_validate(make(layers=layers))


@pytest.mark.parametrize(
    "map_type,layer",
    [
        ("choropleth", {"id": "data", "kind": "choropleth", "field": "PM2_5"}),
        ("point", {"id": "data", "kind": "point"}),
        ("buffer", {"id": "data", "kind": "buffer"}),
        ("overlay", {"id": "data", "kind": "overlay"}),
    ],
)
def test_other_map_types_minimal(map_type, layer):
    spec = MapSpec.model_validate(
        make(map_type=map_type, layers=[{"id": "base", "kind": "admin"}, layer])
    )
    assert spec.map_type == map_type


def test_breaks_count_must_equal_n():
    with pytest.raises(ValidationError, match="breaks 数量"):
        Classification.model_validate({"method": "quantile", "n": 5, "breaks": [35, 55, 75, 115]})


def test_breaks_must_increase():
    with pytest.raises(ValidationError, match="严格递增"):
        Classification.model_validate({"method": "quantile", "n": 3, "breaks": [35, 35, 75]})
    with pytest.raises(ValidationError, match="严格递增"):
        Classification.model_validate({"method": "quantile", "n": 3, "breaks": [75, 55, 35]})


def test_custom_allows_null_last():
    # AQI 国标六级：0–50 / 51–100 / 101–150 / 151–200 / 201–300 / >300
    cls = Classification.model_validate(
        {"method": "custom", "n": 6, "breaks": [50, 100, 150, 200, 300, None]}
    )
    assert cls.breaks[-1] is None
    assert cls.breaks[:5] == [50, 100, 150, 200, 300]


def test_custom_rejects_null_in_middle():
    with pytest.raises(ValidationError, match="最后一项"):
        Classification.model_validate(
            {"method": "custom", "n": 3, "breaks": [50, None, 150]}
        )


def test_non_custom_rejects_null():
    with pytest.raises(ValidationError, match="不允许 null"):
        Classification.model_validate({"method": "jenks", "n": 3, "breaks": [50, 100, None]})


@pytest.mark.parametrize("n", [1, 10])
def test_n_out_of_range(n):
    with pytest.raises(ValidationError):
        Classification.model_validate({"method": "jenks", "n": n, "breaks": [1] * n})


def test_dpi_must_be_positive():
    with pytest.raises(ValidationError):
        Layout.model_validate({"dpi": 0})


def test_size_must_be_positive():
    with pytest.raises(ValidationError, match="size"):
        Layout.model_validate({"size": [10, 0]})


def test_invalid_crs_rejected():
    with pytest.raises(ValidationError, match="坐标系"):
        MapSpec.model_validate(make(crs="EPSG:ABC"))


def test_rainbow_palette_rejected():
    for scheme in ["jet", "rainbow", "HSV"]:
        with pytest.raises(ValidationError, match="彩虹"):
            MapSpec.model_validate(make(palette={"scheme": scheme}))