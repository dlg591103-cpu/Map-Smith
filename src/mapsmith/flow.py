"""T22 第二段：一句话 / 表单到 `loop.run` 的装配层。

只负责把界面输入整理成 `loop.run` 需要的四个注入函数，并做确定性补齐：
- 解析：DataSteward prompt → `place / time / metric`。
- 加载：demo_data 或上传文件 → `DataProfile` + 图层。
- 制图：Cartographer prompt 只产出决策；bbox、breaks、来源注记由本地计算。
- 渲染：按图种选图层，交给 `ui.run_render`。
- 审查：`agents.reviewer.review` 的确定性规则。

契约见 `docs/Spec/T22-一句话入口与loop接入.md`。
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

import matplotlib
import pandas as pd

from .agents.llm import LLMError, default_llm_callable
from .agents.reviewer import review
from .config import Settings, get_settings
from .io.models import DataError, DataLayer, FieldMissing
from .io.uploads import ensure_crs, parse_upload
from .loop import FIELD_QUESTIONS, LoopResult
from .loop import run as loop_run
from .spec import MapSpec
from .tools.inspect import DataProfile, profile_points
from .tools.load_layer import load_admin
from .ui import (
    SUPPORTED_METHODS,
    aggregate_points_to_admin,
    build_spec,
    compute_breaks,
    resolve_inputs,
    run_render,
)

PROMPT_DIR = Path(__file__).resolve().parent / "agents" / "prompts"
MAX_QUESTIONS = 2
FORBIDDEN_SCHEMES = {"jet", "rainbow", "hsv", "gist_rainbow", "nipy_spectral", "gist_ncar", "turbo"}

METRIC_LABELS: dict[str, str] = {
    "PM2_5_24h": "PM2.5",
    "PM10_24h": "PM10",
    "NO2_24h": "NO2",
    "SO2_24h": "SO2",
    "O3_8h_24h": "O3",
    "CO_24h": "CO",
    "AQI": "AQI",
}

METRIC_UNITS: dict[str, str] = {
    "PM2_5_24h": "μg/m³",
    "PM10_24h": "μg/m³",
    "NO2_24h": "μg/m³",
    "SO2_24h": "μg/m³",
    "O3_8h_24h": "μg/m³",
    "CO_24h": "mg/m³",
    "AQI": "",
}

# 统一按「去掉点、下划线、空格、连字符」后的小写做键，PM2.5 / pm2_5 / PM2_5_24h 都能命中。
_METRIC_ALIASES: dict[str, str] = {
    "pm25": "PM2_5_24h",
    "pm2524h": "PM2_5_24h",
    "pm10": "PM10_24h",
    "pm1024h": "PM10_24h",
    "no2": "NO2_24h",
    "no224h": "NO2_24h",
    "so2": "SO2_24h",
    "so224h": "SO2_24h",
    "o3": "O3_8h_24h",
    "o38h": "O3_8h_24h",
    "o38h24h": "O3_8h_24h",
    "co": "CO_24h",
    "co24h": "CO_24h",
    "aqi": "AQI",
}

_TIME_PATTERNS = (
    re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"),
    re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$"),
    re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})$"),
    re.compile(r"^(\d{4})(\d{2})(\d{2})$"),
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"),
)


@dataclass(frozen=True)
class RequestParse:
    """一次一句话解析的结果；`questions` 非空即先反问，不进入 loop。"""

    request: dict[str, str]
    questions: list[str] = field(default_factory=list)
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class SurfaceProfile:
    """面图层体检结果；字段与 `DataProfile` 保持同名，方便统一序列化。"""

    n_valid: int
    total: int
    completeness: float
    decision: str
    reason_lines: tuple[str, str, str]
    summary: str
    value_min: float | None = None
    value_max: float | None = None
    value_mean: float | None = None


@dataclass
class UploadRecord:
    """一次上传在服务进程内的记录；重启后失效，符合本段范围。"""

    upload_id: str
    path: Path
    name: str
    kind: str = ""
    crs_status: str = ""
    suggested_crs: str | None = None
    confirmed_crs: str | None = None


@dataclass
class FlowRun:
    """一次界面请求的完整结果，供 SSE / JSON 回包。"""

    parse: RequestParse
    result: LoopResult
    render_result: Any = None


def load_prompt(name: str) -> str:
    """读取 `agents/prompts/<name>.md`；缺文件时给出中文错误。"""
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise DataError(f"缺少 prompt 文件：{path.name}")
    return path.read_text(encoding="utf-8")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"none", "null", "nan", "未知", "不详", "无"}:
        return ""
    return text


def normalize_time(value: Any) -> str:
    """把常见日期写法归一为 `YYYY-MM-DD`；无法识别返回空串。"""
    text = _clean(value)
    if not text:
        return ""
    for pattern in _TIME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return ""
    return ""


def _metric_key(value: Any) -> str:
    return re.sub(r"[._\-\s]", "", str(value or "")).lower()


def map_metric(value: Any) -> str:
    """把用户/模型给的指标名映射到标准字段；无法映射时保留原文。"""
    text = _clean(value)
    if not text:
        return ""
    return _METRIC_ALIASES.get(_metric_key(text), text)


def normalize_parse(raw: Mapping[str, Any] | None) -> RequestParse:
    """把模型输出整理成 `RequestParse`；本地不补默认值。"""
    data = dict(raw or {})
    request = {
        "place": _clean(data.get("place")),
        "time": normalize_time(data.get("time")),
        "metric": map_metric(data.get("metric")),
    }
    missing = [name for name in ("place", "time", "metric") if not request[name]]

    model_questions = [_clean(item) for item in (data.get("questions") or []) if _clean(item)]
    questions = model_questions[:MAX_QUESTIONS]
    needed = min(len(missing), MAX_QUESTIONS)
    if len(questions) < needed:
        defaults = [FIELD_QUESTIONS[name] for name in missing if FIELD_QUESTIONS[name] not in questions]
        questions = (questions + defaults)[:MAX_QUESTIONS]

    return RequestParse(request=request, questions=questions[:MAX_QUESTIONS], raw=data or None)


def parse_request(text: str, llm_callable: Callable[[str, Mapping[str, Any]], Any]) -> RequestParse:
    """一句话 → DataSteward prompt → `RequestParse`。"""
    if not _clean(text):
        return RequestParse(
            request={"place": "", "time": "", "metric": ""},
            questions=["请说一下区域、时间和指标，例如：徐州 2026-11-01 的 PM2.5。"],
        )
    payload = {
        "user_text": str(text).strip(),
        "known_fields": {"place": "", "time": "", "metric": ""},
    }
    raw = llm_callable(load_prompt("data_steward"), payload)
    if not isinstance(raw, Mapping):
        raise LLMError("数据管家返回的不是 JSON 对象")
    return normalize_parse(raw)


def _numeric_columns(layer: DataLayer) -> list[str]:
    if layer.gdf is None:
        return []
    return [
        str(column)
        for column in layer.gdf.columns
        if column != layer.gdf.geometry.name and pd.api.types.is_numeric_dtype(layer.gdf[column])
    ]


def _require_field(layer: DataLayer, field_name: str) -> None:
    if layer.gdf is not None and field_name in layer.gdf.columns:
        return
    raise FieldMissing(field_name, _numeric_columns(layer))


def _surface_profile(layer: DataLayer, field_name: str) -> SurfaceProfile:
    if layer.gdf is None:
        raise DataError(f"{layer.name} 没有几何，无法做面图层体检")
    _require_field(layer, field_name)
    values = pd.to_numeric(layer.gdf[field_name], errors="coerce")
    total = int(len(layer.gdf))
    valid = values.dropna()
    n_valid = int(len(valid))
    completeness = n_valid / total if total else 0.0
    vmin = float(valid.min()) if n_valid else None
    vmax = float(valid.max()) if n_valid else None
    vmean = float(valid.mean()) if n_valid else None

    reasons = (
        f"面数：{total} 个",
        f"有效面：{n_valid} 个（完整度 {completeness:.0%}）",
        "结论：按面图层分级设色，不做插值",
    )
    if n_valid:
        summary = (
            f"{layer.name}：{field_name} 有效面 {n_valid} 个（共 {total} 个），"
            f"最高 {vmax:.1f}、最低 {vmin:.1f}。按面图层分级设色。"
        )
    else:
        summary = f"{layer.name}：{field_name} 全部缺测（{total} 个面）。"
    return SurfaceProfile(
        n_valid=n_valid,
        total=total,
        completeness=completeness,
        decision="choropleth",
        reason_lines=reasons,
        summary=summary,
        value_min=vmin,
        value_max=vmax,
        value_mean=vmean,
    )


def _load_layers(request: Mapping[str, str], upload: UploadRecord | None) -> dict[str, Any]:
    place = request["place"]
    date = request["time"]
    field_name = request["metric"]

    if upload is not None:
        layer = parse_upload(upload.path, crs=upload.confirmed_crs)
        layer = ensure_crs(layer, confirmed_crs=upload.confirmed_crs)
        if layer.kind == "point":
            admin = load_admin(place, online=False)
            profile = profile_points(layer, field_name=field_name, study_area=admin)
            return {
                "summary": profile.summary,
                "decision": profile.decision,
                "reason_lines": list(profile.reason_lines),
                "profile": profile,
                "admin": admin,
                "points": layer,
                "layer": layer,
                "field": field_name,
                "date": date,
                "place": place,
            }
        if layer.kind == "admin":
            _require_field(layer, field_name)
            profile = _surface_profile(layer, field_name)
            return {
                "summary": profile.summary,
                "decision": profile.decision,
                "reason_lines": list(profile.reason_lines),
                "profile": profile,
                "admin": layer,
                "points": None,
                "layer": layer,
                "field": field_name,
                "date": date,
                "place": place,
            }
        raise DataError("统计表需要关联行政区后才能成图；请先转成点位或面图层再上传")

    admin, points = resolve_inputs(place, date, field_name, online=False)
    profile = profile_points(points, field_name=field_name, study_area=admin)
    return {
        "summary": profile.summary,
        "decision": profile.decision,
        "reason_lines": list(profile.reason_lines),
        "profile": profile,
        "admin": admin,
        "points": points,
        "layer": points,
        "field": field_name,
        "date": date,
        "place": place,
    }


def _profile_payload(profile: Any) -> dict[str, Any]:
    if is_dataclass(profile) and not isinstance(profile, type):
        return asdict(profile)
    if isinstance(profile, Mapping):
        return dict(profile)
    return {"summary": str(profile)}


def _clamp_int(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _region_label(place: str) -> str:
    """图名里的区域要素：审查要求带行政区后缀，缺省时补「市」。"""
    if re.search(r"(省|市|区|县|自治州|自治区|特别行政区|盟|旗)$", place):
        return place
    return place + "市"


def _local_title(place: str, field_name: str, date: str) -> str:
    label = METRIC_LABELS.get(field_name, field_name)
    unit = METRIC_UNITS.get(field_name)
    suffix = f"，{unit}" if unit else ""
    return f"{_region_label(place)} {label} 分布图（{date}{suffix}）"


def _ensure_title(draft_title: Any, place: str, field_name: str, date: str) -> str:
    title = _clean(draft_title)
    local = _local_title(place, field_name, date)
    if not title:
        return local
    required = [place, date, METRIC_LABELS.get(field_name, field_name)]
    if not all(part and part in title for part in required):
        return local
    unit = METRIC_UNITS.get(field_name)
    if unit and unit not in title:
        return local
    return title


def _merge_notes(base: Any, extra: Any) -> list[str]:
    merged: list[str] = []
    for source in (base, extra):
        for item in source or []:
            text = _clean(item)
            if text and text not in merged:
                merged.append(text)
    return merged


def _bbox_for(loaded: Mapping[str, Any], map_type: str) -> tuple[float, float, float, float] | None:
    layer = loaded["layer"]
    if map_type == "choropleth":
        admin = loaded.get("admin")
        if admin is not None:
            bbox = admin.bbox_wgs84()
            if bbox is not None:
                return bbox
        return layer.bbox_wgs84()
    admin = loaded.get("admin")
    if admin is not None:
        bbox = admin.bbox_wgs84()
        if bbox is not None:
            return bbox
    return layer.bbox_wgs84()


def _breaks_for(gdf: Any, field_name: str, method: str, n: int) -> list[float | None]:
    if gdf is None or field_name not in gdf.columns:
        available = (
            [
                str(column)
                for column in gdf.columns
                if column != gdf.geometry.name and pd.api.types.is_numeric_dtype(gdf[column])
            ]
            if gdf is not None
            else []
        )
        raise FieldMissing(field_name, available)
    values = pd.to_numeric(gdf[field_name], errors="coerce").dropna().tolist()
    if not values:
        raise DataError(f"字段「{field_name}」没有有效数值，无法分级")
    return compute_breaks(values, method, n)


def _palette_from(draft_palette: Any) -> tuple[str, bool, str | None]:
    palette = draft_palette if isinstance(draft_palette, Mapping) else {}
    scheme = _clean(palette.get("scheme")) or "YlOrRd"
    note: str | None = None
    if scheme.lower() in FORBIDDEN_SCHEMES:
        note = f"模型给出的配色 {scheme} 属于禁用彩虹色，已改为 YlOrRd。"
        scheme = "YlOrRd"
    return scheme, bool(palette.get("reverse", False)), note


def _annotation_from(draft_annotation: Any) -> tuple[str | None, bool]:
    annotation = draft_annotation if isinstance(draft_annotation, Mapping) else {}
    label = _clean(annotation.get("label_field")) or None
    return label, bool(annotation.get("show", False))


def _compose_spec(request: Mapping[str, str], loaded: Mapping[str, Any], draft: Mapping[str, Any]) -> MapSpec:
    """把 Cartographer 的决策与本地确定性字段合成合法 MapSpec。"""
    place = request["place"]
    date = request["time"]
    field_name = request["metric"]
    decision = str(loaded["decision"])

    if decision == "idw":
        map_type = "idw"
    elif decision == "choropleth":
        map_type = "choropleth"
    else:
        map_type = "point"

    layer = loaded["layer"]
    gdf = layer.gdf
    if gdf is None:
        raise DataError("图层没有几何，无法制图")

    classification = draft.get("classification") if isinstance(draft.get("classification"), Mapping) else {}
    method = _clean(classification.get("method")) or "quantile"
    if method not in SUPPORTED_METHODS:
        method = "quantile"
    n = _clamp_int(classification.get("n"), default=5, low=2, high=9)
    breaks = _breaks_for(gdf, field_name, method, n)

    scheme, reverse, palette_note = _palette_from(draft.get("palette"))
    label_field, show_label = _annotation_from(draft.get("annotation"))
    notes = _merge_notes(
        loaded.get("reason_lines"),
        list(draft.get("notes") or []) + ([palette_note] if palette_note else []),
    )

    return build_spec(
        {
            "title": _ensure_title(draft.get("title"), place, field_name, date),
            "map_type": map_type,
            "adcode": loaded.get("admin", layer).meta.get("adcode"),
            "bbox": _bbox_for(loaded, map_type),
            "field": field_name,
            "method": method,
            "n": n,
            "breaks": breaks,
            "palette_scheme": scheme,
            "palette_reverse": reverse,
            "label_field": label_field,
            "show_label": show_label,
            "data_source_note": f"{layer.source}；更新时间：{date}",
            "crs": "EPSG:4490",
            "notes": notes,
        }
    )


def _form_spec(parse: RequestParse, form: Mapping[str, Any], loaded: Mapping[str, Any]) -> MapSpec:
    """表单路径：图种、方法、级数、配色全部由用户指定。"""
    request = parse.request
    place = request["place"]
    date = request["time"]
    field_name = request["metric"]
    layer = loaded["layer"]
    gdf = layer.gdf
    if gdf is None:
        raise DataError("图层没有几何，无法制图")

    map_type = _clean(form.get("map_type")) or "point"
    if map_type not in {"choropleth", "point", "idw"}:
        raise DataError(f"图种 {map_type!r} 不受支持；可用 choropleth / point / idw")
    if map_type == "choropleth":
        if loaded.get("admin") is None or loaded["admin"].gdf is None:
            raise DataError("choropleth 需要面数据：请上传面图层或使用 demo_data 边界")
    else:
        if loaded.get("points") is None:
            raise DataError(f"{map_type} 需要点数据：请上传点位数据或使用 demo_data 站点")

    method = _clean(form.get("method")) or "quantile"
    if method not in SUPPORTED_METHODS:
        raise DataError(f"分级方法 {method!r} 不受支持；可用：{'、'.join(SUPPORTED_METHODS)}")
    n = _clamp_int(form.get("n"), default=5, low=2, high=9)
    breaks = _breaks_for(gdf, field_name, method, n)

    scheme = _clean(form.get("palette_scheme")) or "YlOrRd"
    if scheme.lower() in FORBIDDEN_SCHEMES:
        raise DataError(f"配色 {scheme!r} 属于禁用彩虹色；请换用单色渐变")

    notes = _merge_notes(loaded.get("reason_lines"), [])
    return build_spec(
        {
            "title": _local_title(place, field_name, date),
            "map_type": map_type,
            "adcode": loaded["admin"].meta.get("adcode") if loaded.get("admin") else None,
            "bbox": _bbox_for(loaded, map_type),
            "field": field_name,
            "method": method,
            "n": n,
            "breaks": breaks,
            "palette_scheme": scheme,
            "palette_reverse": bool(form.get("palette_reverse", False)),
            "label_field": form.get("label_field"),
            "show_label": bool(form.get("show_label", False)),
            "data_source_note": f"{layer.source}；更新时间：{date}",
            "crs": "EPSG:4490",
            "notes": notes,
        }
    )


STAGE_LABELS: dict[str, str] = {
    "parsing": "解析需求",
    "loading": "加载数据",
    "mapping": "生成制图方案",
    "rendering": "渲染地图",
    "reviewing": "审查地图",
}


def _make_emitter(on_stage: Callable[[str, str], None] | None) -> Callable[[str], None]:
    """每个阶段只通知一次，避免返工轮次把同一个 stage 重复推给前端。"""
    seen: set[str] = set()

    def emit(stage: str) -> None:
        if on_stage is None or stage in seen:
            return
        seen.add(stage)
        on_stage(stage, STAGE_LABELS.get(stage, stage))

    return emit


def _review_with_stage(emit: Callable[[str], None]) -> Callable[..., dict[str, Any]]:
    def review_stage(
        spec: Any,
        *,
        png: Any = None,
        data_summary: Any = None,
        round_no: int = 1,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        emit("reviewing")
        return review(spec, png=png, data_summary=data_summary, round_no=round_no, timeout=timeout)

    return review_stage


def _make_load_fn(
    parse: RequestParse,
    *,
    upload: UploadRecord | None,
    state: dict[str, Any],
    on_stage: Callable[[str], None] | None = None,
) -> Callable:
    request = dict(parse.request)
    emit = on_stage or (lambda _stage: None)

    def load(_request: Mapping[str, Any]) -> dict[str, Any]:
        emit("loading")
        loaded = _load_layers(request, upload)
        state["loaded"] = loaded
        return loaded

    return load


def _make_llm_map_fn(
    parse: RequestParse,
    *,
    llm_callable: Callable[[str, Mapping[str, Any]], Any],
    on_stage: Callable[[str], None] | None = None,
) -> Callable:
    prompt = load_prompt("cartographer")
    emit = on_stage or (lambda _stage: None)

    def map_(loaded: Mapping[str, Any]) -> MapSpec:
        emit("mapping")
        payload = {
            "user_request": dict(parse.request),
            "data_profile": _profile_payload(loaded["profile"]),
            "decision": loaded["decision"],
            "layer_kind": loaded["layer"].kind,
        }
        draft = llm_callable(prompt, payload)
        if not isinstance(draft, Mapping):
            raise LLMError("制图师返回的不是 JSON 对象")
        return _compose_spec(parse.request, loaded, draft)

    return map_


def _make_form_map_fn(
    parse: RequestParse,
    form: Mapping[str, Any],
    *,
    on_stage: Callable[[str], None] | None = None,
) -> Callable:
    emit = on_stage or (lambda _stage: None)

    def map_(loaded: Mapping[str, Any]) -> MapSpec:
        emit("mapping")
        return _form_spec(parse, form, loaded)

    return map_


def _to_mapspec(spec: Any) -> MapSpec:
    """返工后的 spec 是 dict，可能带审查补丁字段；渲染前过滤成 MapSpec。"""
    if isinstance(spec, MapSpec):
        return spec
    data = dict(spec) if isinstance(spec, Mapping) else {}
    allowed = {
        "title",
        "map_type",
        "extent",
        "layers",
        "classification",
        "palette",
        "annotation",
        "layout",
        "data_source_note",
        "crs",
        "notes",
    }
    clean = {key: value for key, value in data.items() if key in allowed}

    classification = clean.get("classification")
    if isinstance(classification, Mapping):
        clean["classification"] = {
            key: value
            for key, value in classification.items()
            if key in {"method", "n", "breaks"}
        }

    palette = clean.get("palette")
    palette_map = palette if isinstance(palette, Mapping) else {}
    scheme = _clean(palette_map.get("scheme")) or "YlOrRd"
    if scheme.lower() in FORBIDDEN_SCHEMES or scheme not in matplotlib.colormaps:
        scheme = "YlOrRd"
    clean["palette"] = {"scheme": scheme, "reverse": bool(palette_map.get("reverse", False))}

    return MapSpec(**clean)


def _render_frame(map_spec: MapSpec, loaded: Mapping[str, Any]) -> Any:
    points = loaded.get("points")
    layer = loaded.get("layer")
    field_name = map_spec.layers[0].field

    if map_spec.map_type == "choropleth":
        admin = loaded.get("admin")
        points = loaded.get("points")
        if admin is None or admin.gdf is None:
            raise DataError("choropleth 缺少面数据")
        gdf = admin.gdf
        if field_name and field_name not in gdf.columns:
            if points is None:
                raise FieldMissing(str(field_name), _numeric_columns(admin))
            gdf = aggregate_points_to_admin(admin.gdf, points.gdf, str(field_name))
        return gdf

    if points is None or points.gdf is None:
        raise DataError(f"{map_spec.map_type} 需要点数据")
    return points.gdf


def _make_render_fn(
    state: dict[str, Any],
    *,
    output_dir: Path | str,
    request_id: str,
    on_stage: Callable[[str], None] | None = None,
) -> Callable:
    out_dir = Path(output_dir) / "web" / request_id
    emit = on_stage or (lambda _stage: None)

    def render_(spec: Any) -> Path:
        emit("rendering")
        loaded = state.get("loaded")
        if not loaded:
            raise DataError("渲染前没有加载结果")
        map_spec = _to_mapspec(spec)
        gdf = _render_frame(map_spec, loaded)
        result = run_render(map_spec, gdf, out_dir, name="web_map")
        state["render"] = result
        if result.png_path is None:
            raise DataError("渲染没有返回 PNG 路径")
        return result.png_path

    return render_


def review_fn(spec: Any, *, png: Any = None, data_summary: Any = None, round_no: int = 1, timeout: float = 60.0) -> dict[str, Any]:
    """只跑确定性规则；不接 LLM 软判。"""
    return review(spec, png=png, data_summary=data_summary, round_no=round_no, timeout=timeout)


def new_request_id() -> str:
    return "r_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def _needs_input(parse: RequestParse, summary: str = "信息不足，需要先补齐") -> FlowRun:
    return FlowRun(
        parse=parse,
        result=LoopResult(
            status="needs_input",
            questions=list(parse.questions)[:MAX_QUESTIONS],
            summary=summary,
        ),
    )


def run_one_sentence(
    text: str,
    *,
    llm_callable: Callable[[str, Mapping[str, Any]], Any] | None = None,
    upload: UploadRecord | None = None,
    output_dir: Path | str | None = None,
    request_id: str | None = None,
    settings: Settings | None = None,
    timeout: float | None = None,
    clock: Callable[[], float] | None = None,
    on_stage: Callable[[str, str], None] | None = None,
) -> FlowRun:
    """一句话 → 解析 → `loop.run`；缺项时直接反问，不加载数据。"""
    current = settings or get_settings()
    emit = _make_emitter(on_stage)
    emit("parsing")
    caller = llm_callable or default_llm_callable(settings=current)
    parse = parse_request(text, caller)
    if parse.questions:
        return _needs_input(parse)

    state: dict[str, Any] = {}
    result = loop_run(
        parse.request,
        load_fn=_make_load_fn(parse, upload=upload, state=state, on_stage=emit),
        map_fn=_make_llm_map_fn(parse, llm_callable=caller, on_stage=emit),
        render_fn=_make_render_fn(
            state,
            output_dir=output_dir or current.output_dir,
            request_id=request_id or new_request_id(),
            on_stage=emit,
        ),
        review_fn=_review_with_stage(emit),
        clock=clock if clock is not None else time.monotonic,
        timeout=timeout,
    )
    return FlowRun(parse=parse, result=result, render_result=state.get("render"))


def run_form(
    form: Mapping[str, Any],
    *,
    upload: UploadRecord | None = None,
    output_dir: Path | str | None = None,
    request_id: str | None = None,
    settings: Settings | None = None,
    timeout: float | None = None,
    clock: Callable[[], float] | None = None,
    on_stage: Callable[[str, str], None] | None = None,
) -> FlowRun:
    """表单 → `loop.run`；不调用模型。"""
    current = settings or get_settings()
    emit = _make_emitter(on_stage)
    request = {
        "place": _clean(form.get("place")),
        "time": normalize_time(form.get("time")),
        "metric": map_metric(form.get("metric")),
    }
    parse = RequestParse(request=request, questions=[], raw=None)
    missing = [name for name in ("place", "time", "metric") if not request[name]]
    if missing:
        return _needs_input(parse, "表单缺少必填项：" + "、".join(missing))

    state: dict[str, Any] = {}
    result = loop_run(
        request,
        load_fn=_make_load_fn(parse, upload=upload, state=state, on_stage=emit),
        map_fn=_make_form_map_fn(parse, form, on_stage=emit),
        render_fn=_make_render_fn(
            state,
            output_dir=output_dir or current.output_dir,
            request_id=request_id or new_request_id(),
            on_stage=emit,
        ),
        review_fn=_review_with_stage(emit),
        clock=clock if clock is not None else time.monotonic,
        timeout=timeout,
    )
    return FlowRun(parse=parse, result=result, render_result=state.get("render"))