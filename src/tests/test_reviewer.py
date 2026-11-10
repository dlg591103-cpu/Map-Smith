from mapsmith.agents.reviewer import apply_spec_patch, review
from mapsmith.tools.qa_check import qa_check


def compliant_spec():
    return {
        "title": "徐州市 PM2.5 24小时均值分布图（2026-11-01）",
        "map_type": "idw",
        "extent": {
            "adcode": "320300",
            "name": "徐州市",
            "bbox": [116.2, 34.1, 118.6, 34.9],
        },
        "layers": [
            {"id": "base", "kind": "admin"},
            {"id": "data", "kind": "idw", "field": "PM2_5_24h", "source": "quotsoft_20261101"},
        ],
        "classification": {
            "method": "quantile",
            "n": 5,
            "breaks": [35, 55, 75, 115],
            "unit": "μg/m³",
        },
        "palette": {"scheme": "YlOrRd", "type": "sequential", "reverse": False},
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
        "data_source_note": "数据来源：全国城市空气质量实时发布平台（quotsoft.net），更新时间 2026-11-01",
        "crs": "EPSG:4490",
        "notes": ["2 个站点缺测，已按空间邻近插补"],
        "data_health": {"nan_count": 2, "min": 0, "max": 118},
        "font": {"sans_serif": ["Microsoft YaHei", "SimHei"], "unicode_minus": False},
        "render_meta": {"scale_bar": True, "north_arrow": True},
    }


def failed_rules(result):
    return [item["rule"] for item in result["issues"] if item["severity"] == "fail"]


def test_compliant_spec_passes():
    result = qa_check(compliant_spec())
    assert result["passed"], result["summary"]
    assert failed_rules(result) == []


def test_all_ten_rules_are_reported():
    result = qa_check(compliant_spec())
    assert list(result["rule_results"]) == [f"R{index:02d}" for index in range(1, 11)]
    assert set(result["rule_results"].values()) <= {"pass", "warn", "fail"}


def test_missing_data_source_note_fails_r05():
    spec = compliant_spec()
    spec.pop("data_source_note")
    result = qa_check(spec)
    assert result["passed"] is False
    assert "R05" in failed_rules(result)


def test_aqi_rainbow_palette_fails_r08():
    spec = compliant_spec()
    spec["title"] = "徐州市 AQI 日报图（2026-11-01）"
    spec["layers"][1]["field"] = "AQI"
    spec["palette"] = {"scheme": "rainbow", "type": "sequential"}
    result = qa_check(spec)
    assert result["passed"] is False
    assert "R08" in failed_rules(result)


def test_cross_zero_sequential_palette_fails_r08():
    spec = compliant_spec()
    spec["title"] = "徐州市 气温距平分布图（2026-11-01）"
    spec["layers"][1]["field"] = "temp_anomaly"
    spec["palette"] = {"scheme": "Blues", "type": "sequential"}
    spec["data_health"] = {"nan_count": 2, "min": -6.5, "max": 8.2}
    result = qa_check(spec)
    assert result["passed"] is False
    assert "R08" in failed_rules(result)


def test_second_round_still_failing_allows_render():
    spec = compliant_spec()
    spec.pop("data_source_note")

    first = review(spec, round_no=1)
    assert first["passed"] is False
    assert first["allow_render"] is False
    assert first["remaining_denials"] == 1

    second = review(spec, round_no=2)
    assert second["passed"] is False
    assert second["allow_render"] is True
    assert second["remaining_denials"] == 0


def test_round_beyond_global_limit_still_returns_image_permission():
    spec = compliant_spec()
    spec.pop("data_source_note")
    result = review(spec, round_no=9)
    assert result["passed"] is False
    assert result["allow_render"] is True
    assert result["issues"][0]["rule"] == "LOOP"


def test_fix_spec_patch_can_be_applied():
    spec = compliant_spec()
    spec.pop("data_source_note")
    result = qa_check(spec)
    patch = next(item["fix_spec_patch"] for item in result["issues"] if item["rule"] == "R05")
    patched = apply_spec_patch(spec, patch)
    assert "data_source_note" in patched
    assert qa_check(patched)["passed"] is True


def test_review_output_contract_fields():
    result = review(compliant_spec(), round_no=1)
    assert set(result) >= {"passed", "round", "issues", "summary"}
    assert result["passed"] is True
    assert result["round"] == 1
    assert isinstance(result["issues"], list)
    assert isinstance(result["summary"], str)