"""T22 界面冒烟：用 streamlit.testing.v1.AppTest 跑一次 app.py，断言无异常、关键控件存在。"""

from __future__ import annotations

from pathlib import Path

import pytest

APP_PATH = Path(__file__).resolve().parents[1] / "mapsmith" / "app.py"


@pytest.fixture(scope="module")
def app_test():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH))
    at.run(timeout=60)
    return at


def test_app_runs_without_exception(app_test) -> None:
    assert not app_test.exception, [str(e.value) for e in app_test.exception]


def test_app_has_key_controls(app_test) -> None:
    # 侧边栏：图种、分级方法、配色、级数等关键控件存在。
    labels = [sb.label for sb in app_test.selectbox]
    assert "图种" in labels
    assert "分级方法" in labels
    assert "指标字段" in labels
    assert "配色方案" in labels

    sliders = [sl.label for sl in app_test.slider]
    assert "级数" in sliders

    buttons = [b.label for b in app_test.button]
    assert "生成地图" in buttons


def test_app_buffer_overlay_disabled_note(app_test) -> None:
    # buffer / overlay 禁用并写明原因（caption 说明）。
    captions = [c.value for c in app_test.caption]
    assert any("buffer / overlay 尚未实现" in c for c in captions)

    labels = [sb.label for sb in app_test.selectbox]
    assert "buffer" not in labels
    assert "overlay" not in labels