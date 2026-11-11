from __future__ import annotations

import copy
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any, Callable, Mapping

from ..tools.qa_check import FAIL, WARN, qa_check

MAX_DENY_ROUNDS = 2
GLOBAL_MAX_ROUNDS = 8
DEFAULT_TIMEOUT_SECONDS = 60.0
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "reviewer.md"


class ReviewTimeoutError(RuntimeError):
    pass


class ReviewRoundLimitError(RuntimeError):
    pass


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


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
    raise TypeError(f"spec 必须是 Mapping 或 pydantic 模型，实际为 {type(value)!r}")


def apply_spec_patch(spec: Any, patch: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(_mapping(spec))
    for path, value in patch.items():
        parts = [part for part in str(path).split(".") if part]
        if not parts:
            continue
        cursor = result
        for part in parts[:-1]:
            child = cursor.get(part)
            if not isinstance(child, dict):
                child = {}
                cursor[part] = child
            cursor = child
        cursor[parts[-1]] = copy.deepcopy(value)
    return result


def _merge_data_summary(spec: dict[str, Any], data_summary: Any) -> dict[str, Any]:
    if not data_summary:
        return spec
    merged = copy.deepcopy(spec)
    health = merged.setdefault("data_health", {})
    if isinstance(data_summary, Mapping):
        if "nan_count" in data_summary:
            health["nan_count"] = data_summary["nan_count"]
        if "missing_count" in data_summary:
            health.setdefault("nan_count", data_summary["missing_count"])
        for key in ("min", "max"):
            if key in data_summary:
                health[key] = data_summary[key]
        if data_summary.get("summary"):
            health["summary"] = str(data_summary["summary"])
    else:
        health["summary"] = str(data_summary)
    return merged


def _normalize_soft(result: Any) -> tuple[list[dict[str, Any]], str]:
    if result is None:
        return [], ""
    if isinstance(result, str):
        return [], result.strip()
    if not isinstance(result, Mapping):
        return [], ""

    issues: list[dict[str, Any]] = []
    for index, raw in enumerate(result.get("issues") or [], start=1):
        if not isinstance(raw, Mapping):
            continue
        rule = str(raw.get("rule") or f"S{index:02d}")
        severity = str(raw.get("severity") or WARN).lower()
        if severity not in (WARN, FAIL):
            severity = WARN
        issues.append(
            {
                "rule": rule,
                "severity": WARN if severity == FAIL else severity,
                "message": str(raw.get("message") or ""),
                "fix_spec_patch": dict(raw.get("fix_spec_patch") or {}),
                "source": "llm",
            }
        )
    return issues, str(result.get("summary") or "").strip()


def _call_soft_review(
    llm_callable: Callable[[str, dict[str, Any]], Any],
    payload: dict[str, Any],
    timeout: float,
) -> Any:
    if timeout <= 0:
        raise ReviewTimeoutError("审查超时：LLM 软判前已无可用时间")
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(llm_callable, load_system_prompt(), payload)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            raise ReviewTimeoutError(f"审查超时：LLM 软判超过 {timeout:.1f} 秒") from exc
    finally:
        pool.shutdown(wait=False)


def review(
    spec: Any,
    png: Any = None,
    data_summary: Any = None,
    round_no: int = 1,
    llm_callable: Callable[[str, dict[str, Any]], Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    try:
        current_round = int(round_no)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"round_no 必须是正整数，实际为 {round_no!r}") from exc
    if current_round < 1:
        raise ValueError(f"round_no 必须是正整数，实际为 {current_round}")

    if current_round > GLOBAL_MAX_ROUNDS:
        message = f"已达全局最大轮次 {GLOBAL_MAX_ROUNDS}，按兜底直接出图"
        return {
            "passed": False,
            "round": current_round,
            "issues": [
                {
                    "rule": "LOOP",
                    "severity": FAIL,
                    "message": message,
                    "fix_spec_patch": {},
                }
            ],
            "summary": message + "；审查未完成，附已有问题清单。",
            "allow_render": True,
            "remaining_denials": 0,
            "deterministic_passed": False,
            "timeout_seconds": float(timeout),
        }

    started = time.monotonic()
    merged = _merge_data_summary(_mapping(spec), data_summary)
    deterministic = qa_check(merged, png=png)
    issues = [dict(issue) for issue in deterministic["issues"]]

    soft_summary = ""
    if llm_callable is not None:
        elapsed = time.monotonic() - started
        remaining = float(timeout) - elapsed
        if remaining <= 0:
            raise ReviewTimeoutError(f"审查超时：确定性规则已耗时 {elapsed:.1f} 秒，超过 {timeout:.1f} 秒上限")
        try:
            payload = {
                "round": current_round,
                "spec": merged,
                "png": str(png) if png else None,
                "deterministic_result": deterministic,
            }
            soft_result = _call_soft_review(llm_callable, payload, remaining)
            soft_issues, soft_summary = _normalize_soft(soft_result)
            issues.extend(soft_issues)
        except ReviewTimeoutError:
            raise
        except Exception as exc:
            soft_summary = f"LLM 软判不可用（{type(exc).__name__}），本轮以确定性规则结果为准。"

    failed_rules = [issue["rule"] for issue in issues if issue["severity"] == FAIL]
    passed = bool(deterministic["passed"])
    allow_render = passed or current_round >= MAX_DENY_ROUNDS
    used_denials = 0 if passed else min(current_round, MAX_DENY_ROUNDS)
    remaining_denials = MAX_DENY_ROUNDS - used_denials

    if passed:
        summary = f"第 {current_round} 轮审查通过：确定性规则 R01-R10 无 fail。"
    elif allow_render:
        summary = (
            f"第 {current_round} 轮审查未通过：{'、'.join(failed_rules)}。"
            f"已用完 {MAX_DENY_ROUNDS} 轮否决，按协议允许出图并附审查意见。"
        )
    else:
        summary = (
            f"第 {current_round} 轮审查未通过：{'、'.join(failed_rules)}。"
            f"按协议最多否决 {MAX_DENY_ROUNDS} 轮，本轮返工修改 spec 后再审。"
        )
    if soft_summary:
        summary = summary + soft_summary

    return {
        "passed": passed,
        "round": current_round,
        "issues": issues,
        "summary": summary,
        "allow_render": allow_render,
        "remaining_denials": remaining_denials,
        "deterministic_passed": bool(deterministic["passed"]),
        "deterministic_summary": deterministic["summary"],
        "timeout_seconds": float(timeout),
    }