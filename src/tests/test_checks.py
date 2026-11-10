"""checks.py 像素级版式判据的单元测试。"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from mapsmith.render.checks import (  # noqa: E402
    element_overlaps_content,
    frame_content_ratio,
    labels_overlap,
)


# --- frame_content_ratio ---

def test_frame_content_ratio_blank_figure() -> None:
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.set_axis_off()
    ratio = frame_content_ratio(fig)
    assert ratio == pytest.approx(0.0, abs=0.01)
    plt.close(fig)


def test_frame_content_ratio_full_fill() -> None:
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.set_axis_off()
    ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, facecolor="black"))
    ratio = frame_content_ratio(fig)
    assert ratio > 0.9
    plt.close(fig)


def test_frame_content_ratio_partial_fill() -> None:
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.set_axis_off()
    ax.add_patch(plt.Rectangle((0.2, 0.2), 0.3, 0.3, transform=ax.transAxes, facecolor="black"))
    ratio = frame_content_ratio(fig)
    assert 0.01 < ratio < 0.5
    plt.close(fig)


def test_frame_content_ratio_returns_float_in_unit_range() -> None:
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.scatter([0.3, 0.7], [0.3, 0.7], s=200)
    ratio = frame_content_ratio(fig)
    assert isinstance(ratio, float)
    assert 0.0 <= ratio <= 1.0
    plt.close(fig)


# --- labels_overlap ---

def test_labels_overlap_no_overlap() -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.text(0.1, 0.1, "AAA", transform=ax.transAxes)
    ax.text(0.8, 0.8, "BBB", transform=ax.transAxes)
    overlaps = labels_overlap(ax)
    assert overlaps == []
    plt.close(fig)


def test_labels_overlap_detects_overlap() -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.text(0.5, 0.5, "AAA", transform=ax.transAxes, fontsize=20)
    ax.text(0.5, 0.5, "BBB", transform=ax.transAxes, fontsize=20)
    overlaps = labels_overlap(ax)
    assert len(overlaps) == 1
    texts_in_overlap = set(overlaps[0])
    assert texts_in_overlap == {"AAA", "BBB"}
    plt.close(fig)


def test_labels_overlap_empty_axes() -> None:
    fig, ax = plt.subplots(figsize=(4, 3))
    overlaps = labels_overlap(ax)
    assert overlaps == []
    plt.close(fig)


def test_labels_overlap_multiple_pairs() -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.text(0.3, 0.3, "X", transform=ax.transAxes, fontsize=24)
    ax.text(0.3, 0.3, "Y", transform=ax.transAxes, fontsize=24)
    ax.text(0.7, 0.7, "Z", transform=ax.transAxes, fontsize=24)
    ax.text(0.7, 0.7, "W", transform=ax.transAxes, fontsize=24)
    overlaps = labels_overlap(ax)
    assert len(overlaps) == 2
    plt.close(fig)


# --- element_overlaps_content ---

def test_element_overlaps_content_no_overlap() -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.text(0.9, 0.9, "N", transform=ax.transAxes, fontsize=12)
    ax.text(0.1, 0.1, "站点A", transform=ax.transAxes, fontsize=8)
    result = element_overlaps_content(ax, ["N"])
    assert result == []
    plt.close(fig)


def test_element_overlaps_content_detects_overlap() -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.text(0.5, 0.5, "N", transform=ax.transAxes, fontsize=16)
    ax.text(0.5, 0.5, "站点A", transform=ax.transAxes, fontsize=10)
    result = element_overlaps_content(ax, ["N"])
    assert "N" in result
    plt.close(fig)


def test_element_overlaps_content_empty_elements() -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.text(0.5, 0.5, "站点A", transform=ax.transAxes)
    result = element_overlaps_content(ax, [])
    assert result == []


def test_element_overlaps_content_empty_content() -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.text(0.9, 0.9, "N", transform=ax.transAxes)
    result = element_overlaps_content(ax, ["N"])
    assert result == []


def test_element_overlaps_content_multiple_elements() -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.text(0.5, 0.5, "N", transform=ax.transAxes, fontsize=16)
    ax.text(0.05, 0.05, "5 km", transform=ax.transAxes, fontsize=10)
    ax.text(0.5, 0.5, "站点A", transform=ax.transAxes, fontsize=10)
    ax.text(0.05, 0.05, "站点B", transform=ax.transAxes, fontsize=10)
    result = element_overlaps_content(ax, ["N", "5 km"])
    assert "N" in result
    assert "5 km" in result
    plt.close(fig)