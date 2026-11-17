"""T19 审图员规则库的补丁护栏：fix_spec_patch 不得含模板占位符。

来源：T24 端到端验收发现的真实缺陷。R01 的 fix_spec_patch 曾是
``{"title": "<区域><指标><时间>图"}``，返工时该字符串被原样写入 spec.title，
第 2 轮渲染出的图上直接印着占位符 —— 返工流程反而把图改坏了。

修复历程：
- T25 先在 `apply_spec_patch` 里过滤 ``<...>``，占位符不再进入 spec；
- 2026-11-17 把 R01/R05/R10 的 fix_spec_patch 置为 null —— 这三条的修复内容
  依赖实际区域/指标/日期/来源/缺测数，静态模板给不出正确值。置 null 后 loop
  检测到无可用补丁会「停止返工 + 写明原因 + 重渲染」，比空转更诚实。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mapsmith.agents.reviewer import apply_spec_patch

RULES_PATH = Path(__file__).resolve().parents[1] / "mapsmith" / "kb" / "reviewer_rules.json"

_PLACEHOLDER = re.compile(r"<[^<>]+>")


def load_rules() -> list[dict]:
    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else raw.get("rules", [])


def placeholder_rules() -> set[str]:
    """返回 fix_spec_patch 中仍含 ``<...>`` 模板占位符的规则 id。"""
    found: set[str] = set()
    for rule in load_rules():
        patch = rule.get("fix_spec_patch") or {}
        if _PLACEHOLDER.search(json.dumps(patch, ensure_ascii=False)):
            found.add(str(rule.get("id")))
    return found


def test_no_placeholder_rules() -> None:
    """规则库中不得残留任何占位符补丁（2026-11-17 已全部修正）。"""
    assert placeholder_rules() == set(), (
        f"规则库仍有占位符补丁：{sorted(placeholder_rules())}。"
        "需要实际上下文的规则（图名/来源/缺测说明）应把 fix_spec_patch 置为 null，"
        "由 loop 停止返工并写明原因，而不是写静态模板。"
    )


def test_context_dependent_rules_have_no_patch() -> None:
    """R01/R05/R10 依赖实际内容，必须没有静态补丁（否则返工空转或污染 spec）。"""
    for rule_id in ("R01", "R05", "R10"):
        rule = next(r for r in load_rules() if r.get("id") == rule_id)
        assert rule.get("fix_spec_patch") in (None, {}), (
            f"{rule_id} 的 fix_spec_patch 应为 null（需要实际上下文），实际为 "
            f"{rule.get('fix_spec_patch')!r}"
        )


def test_apply_spec_patch_skips_placeholder() -> None:
    """T25 修复后的回归：占位符补丁不得写入 spec，原标题保留。

    修复前本用例锁定的是「缺陷确实存在」；T25 在 `apply_spec_patch` 中过滤
    ``<...>`` 占位符后，改为护栏断言，防止占位符再次进入 spec.title。
    """
    spec = {"title": "原标题", "map_type": "point"}
    patched = apply_spec_patch(spec, {"title": "<区域><指标><时间>图"})
    assert patched["title"] == "原标题"
    assert not _PLACEHOLDER.search(patched["title"])


def test_apply_spec_patch_keeps_real_values() -> None:
    """把占位符换成真实值后，补丁应正常写入（确认缺陷来源是规则库而非打补丁逻辑）。"""
    spec = {"title": "原标题", "notes": []}
    patched = apply_spec_patch(
        spec, {"title": "徐州市 PM2.5 24 小时均值分布图（2026-11-01）"}
    )
    assert patched["title"] == "徐州市 PM2.5 24 小时均值分布图（2026-11-01）"
    assert not _PLACEHOLDER.search(patched["title"])


@pytest.mark.parametrize("rule_id", ["R02", "R03", "R04", "R06", "R07", "R08", "R09"])
def test_clean_rules_stay_clean(rule_id: str) -> None:
    """其余规则补丁不含占位符，不得倒退。"""
    rule = next(r for r in load_rules() if r.get("id") == rule_id)
    patch = rule.get("fix_spec_patch") or {}
    assert not _PLACEHOLDER.search(json.dumps(patch, ensure_ascii=False))
