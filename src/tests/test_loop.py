"""T21 编排测试：状态机、轮次与超时兜底。

不依赖 LLM、网络与真实渲染，全部通过注入的替身函数驱动。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapsmith.agents.reviewer import ReviewTimeoutError
from mapsmith.loop import missing_fields, run

REQUEST = {"place": "徐州", "time": "2026-11-01", "metric": "PM2.5"}
PNG = Path("out/map.png")


def profile(decision: str = "idw", summary: str = "有效站数 12、覆盖 62%，可插值成面。"):
    return {"summary": summary, "decision": decision}


def spec() -> dict:
    return {"title": "旧标题", "extent": {"adcode": "320300"}, "notes": []}


def render(_spec) -> Path:
    return PNG


def verdict(passed: bool = False, allow_render: bool = False, patch: dict | None = None) -> dict:
    issues = [] if patch is None else [
        {"rule": "R05", "severity": "fail", "message": "缺少日期", "fix_spec_patch": patch}
    ]
    return {"passed": passed, "allow_render": allow_render, "issues": issues, "summary": "审查结果"}


class ReviewStub:
    def __init__(self, verdicts: list[dict]):
        self.verdicts = verdicts
        self.calls: list[dict] = []

    def __call__(self, spec, *, png, data_summary, round_no, timeout):
        self.calls.append({"round": round_no, "spec": dict(spec), "timeout": timeout})
        index = min(round_no - 1, len(self.verdicts) - 1)
        return self.verdicts[index]


class Clock:
    def __init__(self, step: float = 0.0):
        self.value = 0.0
        self.step = step

    def __call__(self) -> float:
        current = self.value
        self.value += self.step
        return current


def test_missing_fields_keep_fixed_order():
    assert missing_fields({"time": "2026-11-01"}) == ["place", "metric"]
    assert missing_fields({}) == ["place", "time", "metric"]
    assert missing_fields({"place": " ", "time": "2026-11-01", "metric": "PM2.5"}) == ["place"]


def test_needs_input_stops_before_loading():
    loaded: list[int] = []

    def load(_request):
        loaded.append(1)
        return profile()

    result = run(
        {"time": "2026-11-01", "metric": "PM2.5"},
        load_fn=load,
        map_fn=lambda _p: spec(),
        render_fn=render,
    )

    assert result.status == "needs_input"
    assert result.questions == ["想画哪个城市或区县？"]
    assert loaded == []
    assert result.png is None


def test_clarify_questions_limited_to_two():
    result = run({}, load_fn=lambda _r: profile(), map_fn=lambda _p: spec(), render_fn=render)

    assert result.status == "needs_input"
    assert len(result.questions) == 2


def test_happy_path_renders_on_first_round():
    review = ReviewStub([verdict(passed=True)])
    result = run(
        REQUEST,
        load_fn=lambda _r: profile(),
        map_fn=lambda _p: spec(),
        render_fn=render,
        review_fn=review,
    )

    assert result.status == "rendered"
    assert result.round_no == 1
    assert result.png == PNG
    assert result.spec == spec()
    assert review.calls[0]["round"] == 1


def test_rework_applies_fix_patch_then_passes():
    review = ReviewStub([
        verdict(patch={"title": "徐州市 PM2.5 24 小时均值分布图（2026-11-01）"}),
        verdict(passed=True),
    ])

    result = run(
        REQUEST,
        load_fn=lambda _r: profile(),
        map_fn=lambda _p: spec(),
        render_fn=render,
        review_fn=review,
    )

    assert result.round_no == 2
    assert result.spec["title"].startswith("徐州市")
    assert any("返工" in note for note in result.notes)


def test_second_round_fail_still_renders():
    review = ReviewStub([
        verdict(patch={"title": "修正标题"}),
        verdict(allow_render=True),
    ])

    result = run(
        REQUEST,
        load_fn=lambda _r: profile(),
        map_fn=lambda _p: spec(),
        render_fn=render,
        review_fn=review,
    )

    assert result.status == "rendered"
    assert result.round_no == 2
    assert result.review is not None
    assert result.review["allow_render"] is True


def test_timeout_before_first_round_renders_current_spec():
    result = run(
        REQUEST,
        load_fn=lambda _r: profile(),
        map_fn=lambda _p: spec(),
        render_fn=render,
        review_fn=ReviewStub([verdict(passed=True)]),
        clock=Clock(step=10.0),
        timeout=5.0,
    )

    assert result.status == "rendered"
    assert result.round_no == 0
    assert result.png == PNG
    assert any("超时" in note for note in result.notes)


def test_review_timeout_falls_back_to_render():
    def review(*args, **kwargs):
        raise ReviewTimeoutError("审查超时：超过 0.5 秒上限")

    result = run(
        REQUEST,
        load_fn=lambda _r: profile(),
        map_fn=lambda _p: spec(),
        render_fn=render,
        review_fn=review,
        timeout=5.0,
    )

    assert result.status == "rendered"
    assert result.round_no == 1
    assert any("审查未完成（超时）" in note for note in result.notes)


def test_load_failure_returns_failed():
    def load(_request):
        raise FileNotFoundError("demo_data/sites/sites.csv 不存在")

    result = run(REQUEST, load_fn=load, map_fn=lambda _p: spec(), render_fn=render)

    assert result.status == "failed"
    assert any("数据加载失败" in note for note in result.notes)
    assert result.png is None


def test_reject_decision_asks_instead_of_mapping():
    mapped: list[int] = []

    def map_(_profile):
        mapped.append(1)
        return spec()

    result = run(
        REQUEST,
        load_fn=lambda _r: profile("reject", "有效站数 2 个，放弃该指标。"),
        map_fn=map_,
        render_fn=render,
    )

    assert result.status == "needs_input"
    assert len(result.questions) == 1
    assert mapped == []
    assert result.decision == "reject"


def test_render_failure_returns_failed_without_blank_image():
    def failing_render(_spec):
        raise RuntimeError("matplotlib 后端不可用")

    result = run(
        REQUEST,
        load_fn=lambda _r: profile(),
        map_fn=lambda _p: spec(),
        render_fn=failing_render,
    )

    assert result.status == "failed"
    assert result.png is None
    assert any("渲染失败" in note for note in result.notes)


def test_without_reviewer_only_loads_maps_and_renders():
    result = run(
        REQUEST,
        load_fn=lambda _r: profile(),
        map_fn=lambda _p: spec(),
        render_fn=render,
    )

    assert result.status == "rendered"
    assert result.round_no == 1
    assert result.review is None
    assert result.png == PNG