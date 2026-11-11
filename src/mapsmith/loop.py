"""编排：数据 → 制图 → 渲染 → 审查 → 返工 / 兜底出图（T21）。

契约见 `docs/Spec/T20-T21-编排契约.md`。本模块只负责串流程与轮次控制，
不直接调用 LLM、不做真实渲染：这些能力通过参数注入，便于测试与后续界面复用。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from .agents.reviewer import ReviewTimeoutError, apply_spec_patch
from .config import get_settings

REQUIRED_FIELDS: tuple[str, ...] = ("place", "time", "metric")

FIELD_QUESTIONS: dict[str, str] = {
    "place": "想画哪个城市或区县？",
    "time": "要哪一天的数据？（格式 YYYY-MM-DD）",
    "metric": "画哪个指标？例如 PM2.5、PM10、AQI。",
}

REJECT_QUESTION = "当前区域与指标的有效站数不足 3 个，换一个指标或换一个区域再试。"


@dataclass
class LoopResult:
    """一次编排的完整结果；`status` 只有三种终止态。"""

    status: Literal["rendered", "needs_input", "failed"]
    round_no: int = 0
    elapsed: float = 0.0
    spec: dict[str, Any] | None = None
    png: Path | None = None
    review: dict[str, Any] | None = None
    questions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    decision: str | None = None
    summary: str = ""


def missing_fields(request: Mapping[str, Any]) -> list[str]:
    """返回缺失的必填字段，顺序固定为区域、时间、指标。"""

    missing: list[str] = []
    for name in REQUIRED_FIELDS:
        value = request.get(name)
        if value is None or not str(value).strip():
            missing.append(name)
    return missing


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    if hasattr(value, "dict"):
        return dict(value.dict())
    raise TypeError(f"无法转换为字典：{type(value).__name__}")


def _summary_of(loaded: Any) -> str:
    if isinstance(loaded, Mapping):
        return str(loaded.get("summary", ""))
    return str(getattr(loaded, "summary", ""))


def _decision_of(loaded: Any) -> str | None:
    raw = loaded.get("decision") if isinstance(loaded, Mapping) else getattr(loaded, "decision", None)
    if raw is None:
        return None
    value = getattr(raw, "value", raw)
    return str(value)


def _first_patch(verdict: Mapping[str, Any]) -> dict[str, Any] | None:
    for issue in verdict.get("issues") or []:
        patch = issue.get("fix_spec_patch") if isinstance(issue, Mapping) else None
        if patch:
            return dict(patch)
    return None


def run(
    request: Mapping[str, Any],
    *,
    load_fn: Callable[[Mapping[str, Any]], Any],
    map_fn: Callable[[Any], Any],
    render_fn: Callable[[Mapping[str, Any]], Path],
    review_fn: Callable[..., Mapping[str, Any]] | None = None,
    clock: Callable[[], float] = time.monotonic,
    timeout: float | None = None,
    max_rounds: int | None = None,
    deny_limit: int | None = None,
) -> LoopResult:
    """跑一次完整编排。

    `review_fn` 为空时只做「加载 → 制图 → 渲染」，用于界面预览或单元测试。
    任何分支都不返回空白图：超时或审查失败仍返回当前 spec 的渲染结果。
    """

    settings = get_settings()
    limit_s = settings.global_timeout_s if timeout is None else float(timeout)
    round_cap = settings.max_global_rounds if max_rounds is None else int(max_rounds)
    deny_cap = settings.max_rework_rounds if deny_limit is None else int(deny_limit)

    started = clock()

    def elapsed() -> float:
        return round(clock() - started, 3)

    def remaining() -> float:
        return limit_s - (clock() - started)

    missing = missing_fields(request)
    if missing:
        questions = [FIELD_QUESTIONS[name] for name in missing]
        return LoopResult(
            status="needs_input",
            elapsed=elapsed(),
            questions=questions[: settings.max_clarify_questions],
            summary="信息不足，需要先补齐：" + "、".join(missing),
        )

    try:
        loaded = load_fn(request)
    except Exception as exc:  # noqa: BLE001 - 对外只暴露原因，不吞错
        return LoopResult(
            status="failed",
            elapsed=elapsed(),
            notes=[f"数据加载失败：{type(exc).__name__}: {exc}"],
            summary="数据加载失败",
        )

    data_summary = _summary_of(loaded)
    decision = _decision_of(loaded)
    notes: list[str] = []
    if data_summary:
        notes.append(data_summary)

    if decision == "reject":
        return LoopResult(
            status="needs_input",
            elapsed=elapsed(),
            questions=[REJECT_QUESTION],
            notes=notes,
            decision=decision,
            summary="数据不足，无法成图",
        )

    try:
        spec = _as_mapping(map_fn(loaded))
    except Exception as exc:  # noqa: BLE001
        return LoopResult(
            status="failed",
            elapsed=elapsed(),
            notes=notes + [f"制图失败：{type(exc).__name__}: {exc}"],
            decision=decision,
            summary="制图失败",
        )

    png: Path | None = None
    verdict: dict[str, Any] | None = None
    round_no = 0

    while round_no < round_cap:
        if remaining() <= 0:
            notes.append("审查未完成（超时）：已用尽总时长。")
            break

        round_no += 1
        try:
            png = render_fn(spec)
        except Exception as exc:  # noqa: BLE001
            return LoopResult(
                status="failed",
                round_no=round_no,
                elapsed=elapsed(),
                spec=spec,
                notes=notes + [f"渲染失败：{type(exc).__name__}: {exc}"],
                decision=decision,
                summary="渲染失败",
            )

        if review_fn is None:
            break

        try:
            verdict = dict(
                review_fn(
                    spec,
                    png=png,
                    data_summary=data_summary,
                    round_no=round_no,
                    timeout=max(remaining(), 0.0),
                )
            )
        except ReviewTimeoutError as exc:
            notes.append(f"审查未完成（超时）：{exc}")
            break

        if verdict.get("passed") or verdict.get("allow_render"):
            break

        if round_no >= deny_cap:
            notes.append(f"已用完 {deny_cap} 轮否决，按协议出图并附审查意见。")
            break

        patch = _first_patch(verdict)
        if patch is None:
            notes.append("审查未通过且没有可应用的修复补丁，停止返工。")
            break
        spec = apply_spec_patch(spec, patch)
        notes.append(f"第 {round_no} 轮返工：应用 {len(patch)} 个字段修复。")

    if png is None:
        try:
            png = render_fn(spec)
        except Exception as exc:  # noqa: BLE001
            return LoopResult(
                status="failed",
                round_no=round_no,
                elapsed=elapsed(),
                spec=spec,
                notes=notes + [f"兜底渲染失败：{type(exc).__name__}: {exc}"],
                decision=decision,
                summary="兜底渲染失败",
            )

    if verdict is not None and verdict.get("summary"):
        summary = str(verdict["summary"])
    elif round_no == 0:
        summary = f"审查未完成（超时），已按当前 spec 出图。"
    else:
        summary = "已出图"

    return LoopResult(
        status="rendered",
        round_no=round_no,
        elapsed=elapsed(),
        spec=spec,
        png=Path(png) if png is not None else None,
        review=verdict,
        notes=notes,
        decision=decision,
        summary=summary,
    )