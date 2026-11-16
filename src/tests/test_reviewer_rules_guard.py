"""T19 审图员规则库的补丁护栏：fix_spec_patch 不得把模板占位符写进 spec。

来源：T24 端到端验收发现的真实缺陷。R01 的 fix_spec_patch 是
``{"title": "<区域><指标><时间>图"}``，返工时该字符串被原样写入 spec.title，
第 2 轮渲染出的图上直接印着占位符 —— 返工流程反而把图改坏了。

本用例只做护栏，不修规则库：kb/reviewer_rules.json 的归属是审图员窗口。
规则库未修正前，R01/R05/R10 的既有问题由 ``test_known_placeholder_rules_are_tracked``
显式登记，修正后该用例应连同登记一起删除。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mapsmith.agents.reviewer import apply_spec_patch

RULES_PATH = Path(__file__).resolve().parents[1] / "mapsmith" / "kb" / "reviewer_rules.json"

# 已登记、尚未修正的规则（T19 归属）。修正后从该集合移除。
KNOWN_PLACEHOLDER_RULES = {"R01", "R05", "R10"}

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


def test_placeholder_rules_match_known_registry() -> None:
    """残留的占位符规则必须与登记表一致：修正了就要从表里删掉，不能悄悄消失。"""
    assert placeholder_rules() == KNOWN_PLACEHOLDER_RULES, (
        "规则库的占位符补丁与登记表不一致："
        f"实际 {sorted(placeholder_rules())}，登记 {sorted(KNOWN_PLACEHOLDER_RULES)}。"
        "若已修正请同步移除登记；若新增了占位符，请先修规则库而非扩展登记表。"
    )


def test_apply_spec_patch_writes_placeholder_verbatim() -> None:
    """复现缺陷：apply_spec_patch 不校验补丁内容，占位符会原样进入 spec。

    本用例锁定当前行为，便于修正规则库后回归对比；
    它断言的是「缺陷确实存在」，不是「行为正确」。
    """
    spec = {"title": "原标题", "map_type": "point"}
    patched = apply_spec_patch(spec, {"title": "<区域><指标><时间>图"})
    assert patched["title"] == "<区域><指标><时间>图"
    assert _PLACEHOLDER.search(patched["title"])


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
