from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PASS = "pass"
WARN = "warn"
FAIL = "fail"

RULES_PATH = Path(__file__).resolve().parents[1] / "kb" / "reviewer_rules.json"

FORBIDDEN_SCHEMES = ("jet", "rainbow", "hsv", "gist_rainbow", "nipy_spectral", "gist_ncar", "turbo")
DIVERGING_HINTS = ("div", "rdbu", "rdylbu", "rdylgn", "puor", "brbg", "seismic", "coolwarm", "bwr", "spectral")
AQI_SCHEMES = ("aqi6", "aqi", "cn_aqi", "china_aqi", "national_aqi")
AQI_COLORS = ("#00E400", "#FFFF00", "#FF7E00", "#FF0000", "#8F3F97", "#7E0023")
MISSING_KEYWORDS = ("缺失", "缺测", "插补", "插值", "空值", "无效值", "nan", "none", "补齐", "填充")

DATE_PATTERNS = (
    re.compile(r"\d{4}-\d{1,2}-\d{1,2}"),
    re.compile(r"\d{4}/\d{1,2}/\d{1,2}"),
    re.compile(r"\d{4}\.\d{1,2}\.\d{1,2}"),
    re.compile(r"\d{4}年\d{1,2}月(?:\d{1,2}日)?"),
    re.compile(r"\d{4}-\d{1,2}(?!\d)"),
)

REGION_PATTERN = re.compile(r"[\u4e00-\u9fa5]{2,}(?:省|市|区|县|州|盟|旗|自治区|特别行政区)")

UNIT_PATTERN = re.compile(
    r"(?:μg/m³|µg/m³|mg/m³|ppm|ppb|%|℃|°C|mm|km|m/s|m³|平方米|公顷|人|户|元|dB)",
    re.IGNORECASE,
)

_RULES_CACHE: dict[str, Any] | None = None


def _load_rules() -> dict[str, Any]:
    global _RULES_CACHE
    if _RULES_CACHE is None:
        try:
            with RULES_PATH.open(encoding="utf-8") as handle:
                data = json.load(handle)
            _RULES_CACHE = {str(item.get("id")): item for item in data.get("rules", [])}
        except (OSError, ValueError, AttributeError):
            _RULES_CACHE = {}
    return _RULES_CACHE


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump())
    legacy = getattr(value, "dict", None)
    if callable(legacy):
        try:
            return dict(legacy())
        except TypeError:
            return {}
    return {}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _has_date(text: str) -> bool:
    return any(pattern.search(text) for pattern in DATE_PATTERNS)


def _extract_date(text: str) -> str:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return ""


def _region_token(extent: dict[str, Any]) -> str:
    return _text(extent.get("name") or extent.get("region") or extent.get("adcode"))


def _title_metric_ok(title: str, region: str) -> bool:
    cleaned = title
    if region:
        cleaned = cleaned.replace(region, "")
    for pattern in DATE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"[（）()\s:：,，、/\\\-—]", "", cleaned)
    return len(re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]", cleaned)) >= 2


def _has_unit(spec: dict[str, Any], title: str) -> bool:
    classification = _mapping(spec.get("classification"))
    legend = _mapping(spec.get("legend"))
    candidates = (
        classification.get("unit"),
        legend.get("unit"),
        spec.get("unit"),
        classification.get("label_unit"),
    )
    if any(_text(item) for item in candidates):
        return True
    return bool(UNIT_PATTERN.search(title))


def _indicator_text(spec: dict[str, Any]) -> str:
    parts = [_text(spec.get("title"))]
    for layer in _as_list(spec.get("layers")):
        layer_map = _mapping(layer)
        parts.append(_text(layer_map.get("field")))
        parts.append(_text(layer_map.get("metric")))
    annotation = _mapping(spec.get("annotation"))
    parts.append(_text(annotation.get("label_field")))
    return " ".join(part for part in parts if part)


def _value_range(spec: dict[str, Any]) -> tuple[float, float] | None:
    sources: list[Mapping[str, Any]] = [
        _mapping(spec.get("data_health")),
        _mapping(spec.get("stats")),
    ]
    for layer in _as_list(spec.get("layers")):
        sources.append(_mapping(_mapping(layer).get("stats")))

    for source in sources:
        low = _to_float(source.get("min"))
        high = _to_float(source.get("max"))
        if low is not None and high is not None:
            return low, high

    raw_range = spec.get("value_range")
    if isinstance(raw_range, (list, tuple)) and len(raw_range) == 2:
        low = _to_float(raw_range[0])
        high = _to_float(raw_range[1])
        if low is not None and high is not None:
            return low, high
    return None


def _nan_count(spec: dict[str, Any]) -> int | None:
    for source in (_mapping(spec.get("data_health")), _mapping(spec.get("stats"))):
        count = _to_int(source.get("nan_count", source.get("missing_count")))
        if count is not None:
            return count
    return None


def _is_diverging(palette: dict[str, Any], scheme: str) -> bool:
    declared = _text(palette.get("type")).lower()
    if declared == "diverging" or palette.get("diverging") is True:
        return True
    return any(hint in scheme for hint in DIVERGING_HINTS)


def _aqi_colors_ok(colors: Any) -> bool:
    normalized = [str(color).strip().upper() for color in _as_list(colors)]
    return normalized[: len(AQI_COLORS)] == [color.upper() for color in AQI_COLORS]


def _r01(spec: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    title = _text(spec.get("title"))
    extent = _mapping(spec.get("extent"))
    layout = _mapping(spec.get("layout"))
    missing_fields: list[str] = []
    if not title:
        missing_fields.append("title")
    if not extent or not extent.get("bbox"):
        missing_fields.append("extent")
    if not layout:
        missing_fields.append("layout")
    if missing_fields:
        patch = {field: "待补全" for field in missing_fields}
        return FAIL, "缺少必需字段：" + "、".join(missing_fields), patch

    region = _region_token(extent)
    has_region = bool(region and region in title) or bool(REGION_PATTERN.search(title))
    has_time = _has_date(title)
    has_metric = _title_metric_ok(title, region)

    missing: list[str] = []
    if not has_region:
        missing.append("区域")
    if not has_metric:
        missing.append("指标")
    if not has_time:
        missing.append("时间")
    if missing:
        return FAIL, "图名缺少" + "、".join(missing) + "要素", {"title": "<区域><指标><时间>图"}
    return PASS, "图名包含区域、指标与时间", {}


def _r02(spec: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    layout = _mapping(spec.get("layout"))
    classification = _mapping(spec.get("classification"))
    title = _text(spec.get("title"))
    if layout.get("legend") is not True:
        return FAIL, "图例未启用（layout.legend 必须为 true）", {"layout.legend": True}
    breaks = _as_list(classification.get("breaks"))
    if not breaks:
        return FAIL, "图例缺少分级断点（classification.breaks 为空）", {"classification.breaks": "由 classify 计算后填写"}
    if not _has_unit(spec, title):
        return FAIL, "图例缺少单位", {"classification.unit": "μg/m³"}
    return PASS, "图例包含分级断点与单位", {}


def _layout_element(
    spec: dict[str, Any],
    key: str,
    label: str,
    png: Any,
) -> tuple[str, str, dict[str, Any]]:
    layout = _mapping(spec.get("layout"))
    if not layout:
        return FAIL, f"缺少 layout 字段，无法确认{label}", {"layout": {key: True}}
    if layout.get(key) is not True:
        return FAIL, f"{label}未启用（layout.{key} 必须为 true）", {f"layout.{key}": True}
    render_meta = _mapping(spec.get("render_meta"))
    if render_meta.get(key) is False:
        return FAIL, f"渲染层未绘制{label}", {f"layout.{key}": True}
    if render_meta.get(key) is not True and png is None:
        return WARN, f"{label}已声明，但没有渲染回执或成图可核对", {}
    return PASS, f"{label}已声明并绘制", {}


def _r03(spec: dict[str, Any], png: Any) -> tuple[str, str, dict[str, Any]]:
    return _layout_element(spec, "scale_bar", "比例尺", png)


def _r04(spec: dict[str, Any], png: Any) -> tuple[str, str, dict[str, Any]]:
    return _layout_element(spec, "north_arrow", "指北针", png)


def _r05(spec: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    note = _text(spec.get("data_source_note"))
    known_date = _extract_date(_text(spec.get("title"))) or "<YYYY-MM-DD>"
    if not note:
        return FAIL, "缺少 data_source_note", {
            "data_source_note": f"数据来源：<来源名称>；更新时间：{known_date}",
        }
    if not _has_date(note):
        return FAIL, "data_source_note 缺少更新时间或日期", {
            "data_source_note": note + f"；更新时间：{known_date}",
        }
    return PASS, "数据来源包含更新时间或日期", {}


def _r06(spec: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    classification = _mapping(spec.get("classification"))
    if not classification:
        return FAIL, "缺少 classification 字段", {"classification.method": "quantile", "classification.n": 5}
    method = _text(classification.get("method"))
    if not method:
        return FAIL, "未声明分级方法（classification.method）", {"classification.method": "quantile"}
    n = _to_int(classification.get("n"))
    if n is None or n < 2:
        return FAIL, "分级级数 n 未声明或小于 2", {"classification.n": 5}

    breaks = _as_list(classification.get("breaks"))
    if not breaks:
        return PASS, "分级方法与级数已声明", {}

    numbers = [_to_float(item) for item in breaks]
    if any(number is None for number in numbers):
        return FAIL, "分级断点含非数值", {"classification.breaks": "由 classify 计算后填写"}
    numeric = [number for number in numbers if number is not None]
    if len(numeric) not in (n - 1, n):
        return FAIL, f"断点数量 {len(numeric)} 与级数 n={n} 不自洽", {"classification.breaks": "由 classify 重新计算"}
    if any(later <= earlier for earlier, later in zip(numeric, numeric[1:])):
        return FAIL, "分级断点未严格递增", {"classification.breaks": "由 classify 重新计算"}
    return PASS, "分级方法、级数与断点自洽", {}


def _r07(spec: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    crs = _text(spec.get("crs"))
    if not crs:
        return FAIL, "未声明 crs", {"crs": "EPSG:4490"}
    normalized = crs.upper().replace(" ", "")
    supported = (
        normalized in {"EPSG:4326", "EPSG:4490"}
        or normalized == "CGCS2000"
        or normalized.startswith("CGCS2000/")
    )
    if not supported:
        return FAIL, f"crs 不受支持（{crs}），须为 EPSG:4326 或 CGCS2000", {"crs": "EPSG:4490"}
    return PASS, "坐标系为 EPSG:4326 或 CGCS2000", {}


def _r08(spec: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    palette = _mapping(spec.get("palette"))
    scheme = _text(palette.get("scheme")).lower()
    indicator = _indicator_text(spec)
    is_aqi = "aqi" in indicator.lower() or "空气质量指数" in indicator

    if any(forbidden in scheme for forbidden in FORBIDDEN_SCHEMES):
        return FAIL, f"配色使用了禁用的彩虹或高饱和色阶（{scheme}）", {"palette.scheme": "YlOrRd"}

    if is_aqi:
        if scheme in AQI_SCHEMES or _aqi_colors_ok(palette.get("colors")):
            return PASS, "AQI 使用国标六级固定色阶", {}
        return FAIL, "AQI 未使用国标六级固定色阶", {
            "palette.scheme": "AQI6",
            "palette.colors": list(AQI_COLORS),
        }

    value_range = _value_range(spec)
    crosses_zero = bool(value_range and value_range[0] < 0 < value_range[1])

    if crosses_zero:
        if _is_diverging(palette, scheme):
            return PASS, "跨零数据使用发散配色", {}
        return FAIL, "跨零数据必须使用发散配色", {"palette.scheme": "RdBu", "palette.type": "diverging"}

    if not scheme:
        return FAIL, "连续量未声明配色方案", {"palette.scheme": "YlOrRd"}
    if _is_diverging(palette, scheme):
        return WARN, "连续量使用发散配色，语义有偏移但未违反禁用规则", {"palette.scheme": "YlOrRd"}
    return PASS, "连续量使用单色渐变且未使用彩虹色", {}


def _r09(spec: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    font = _mapping(spec.get("font")) or _mapping(spec.get("fonts"))
    render_meta = _mapping(spec.get("render_meta"))
    sans = font.get("sans_serif") or font.get("sans-serif") or render_meta.get("font_sans_serif")
    unicode_minus = font.get("unicode_minus")
    if unicode_minus is None:
        unicode_minus = font.get("axes.unicode_minus")
    if unicode_minus is None:
        unicode_minus = render_meta.get("unicode_minus")

    if sans is None and unicode_minus is None:
        return WARN, "未提供字体配置证据，无法确认中文显示设置", {
            "font.sans_serif": ["Microsoft YaHei", "SimHei"],
            "font.unicode_minus": False,
        }

    sans_list = [_text(item) for item in _as_list(sans)]
    if not any(item in {"Microsoft YaHei", "SimHei"} for item in sans_list):
        return FAIL, "font.sans-serif 未包含 Microsoft YaHei 或 SimHei", {
            "font.sans_serif": ["Microsoft YaHei", "SimHei"],
            "font.unicode_minus": False,
        }
    if unicode_minus is not False:
        return FAIL, "axes.unicode_minus 必须为 false", {"font.unicode_minus": False}
    return PASS, "中文字体与负号设置正确", {}


def _r10(spec: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    nan_count = _nan_count(spec)
    if nan_count is None:
        return WARN, "未提供缺失值统计，无法判定 R10", {}

    notes_value = spec.get("notes")
    if isinstance(notes_value, (list, tuple)):
        notes_text = " ".join(_text(item) for item in notes_value)
    else:
        notes_text = _text(notes_value)
    health_summary = _text(_mapping(spec.get("data_health")).get("summary"))
    combined = (notes_text + " " + health_summary).lower()

    if nan_count == 0:
        return PASS, "无缺失值", {}
    if any(keyword in combined for keyword in MISSING_KEYWORDS):
        return PASS, "缺失值处理已在 notes 中说明", {}
    return FAIL, f"存在 {nan_count} 个缺失值，但 notes 未说明缺失或插补策略", {
        "notes": [f"{nan_count} 个站点缺测，按<方法>插补"],
    }


def _build_check(rule: str, result: tuple[str, str, dict[str, Any]]) -> dict[str, Any]:
    status, message, patch = result
    title = _text(_load_rules().get(rule, {}).get("title"))
    text = message if status == PASS or not title else f"{title}：{message}"
    return {
        "rule": rule,
        "status": status,
        "message": text,
        "fix_spec_patch": dict(patch or {}),
    }


def qa_check(spec: Any, png: Any = None) -> dict[str, Any]:
    data = _mapping(spec)
    checks = [
        _build_check("R01", _r01(data)),
        _build_check("R02", _r02(data)),
        _build_check("R03", _r03(data, png)),
        _build_check("R04", _r04(data, png)),
        _build_check("R05", _r05(data)),
        _build_check("R06", _r06(data)),
        _build_check("R07", _r07(data)),
        _build_check("R08", _r08(data)),
        _build_check("R09", _r09(data)),
        _build_check("R10", _r10(data)),
    ]

    failed = [check for check in checks if check["status"] == FAIL]
    warned = [check for check in checks if check["status"] == WARN]
    issues = [
        {
            "rule": check["rule"],
            "severity": check["status"],
            "message": check["message"],
            "fix_spec_patch": check["fix_spec_patch"],
        }
        for check in failed + warned
    ]

    if failed:
        summary = "确定性规则未通过：" + "；".join(
            f"{check['rule']} {check['message']}" for check in failed
        )
    elif warned:
        summary = "确定性规则 R01-R10 无 fail，仍有待确认项：" + "；".join(
            f"{check['rule']} {check['message']}" for check in warned
        )
    else:
        summary = "确定性规则 R01-R10 全部通过。"

    return {
        "passed": not failed,
        "issues": issues,
        "checks": checks,
        "rule_results": {check["rule"]: check["status"] for check in checks},
        "summary": summary,
        "rules_version": "1.0",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }