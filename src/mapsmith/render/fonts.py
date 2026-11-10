"""中文字体加载：用 `font_manager.addfont` 显式注册 `render/fonts/` 下的字体文件。

规则来源：docs/facts/07-制图规范与审查.md 第 9 条（中文无乱码）。
不依赖系统字体路径，把字体文件随包分发，保证断网 / 无系统中文字体的机器也能出图。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
from matplotlib import font_manager

from ..io.models import DataError

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

# 优先思源黑体 / Noto Sans CJK 系列，其次微软雅黑 / 黑体。
_PREFERRED = (
    "Noto Sans SC",
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "Source Han Sans SC",
    "Microsoft YaHei",
    "SimHei",
)


def _available_fonts() -> set[str]:
    return {font.name for font in font_manager.fontManager.ttflist}


def load_chinese_font() -> str:
    """显式注册 `fonts/` 下的字体文件，并设置 matplotlib 默认中文字体。

    返回实际采用的字体名。找不到任何可用中文字体时抛 `DataError`，
    不静默回退到系统默认（否则会出方框乱码）。
    """
    if FONTS_DIR.is_dir():
        for path in sorted(FONTS_DIR.glob("*")):
            if path.suffix.lower() in (".ttf", ".otf", ".ttc"):
                try:
                    font_manager.fontManager.addfont(str(path))
                except Exception:
                    # 单个字体文件注册失败不致命，继续尝试其余文件与系统字体。
                    continue

    available = _available_fonts()
    chosen: str | None = None
    for name in _PREFERRED:
        if name in available:
            chosen = name
            break
    if chosen is None:
        for name in sorted(available):
            if any(keyword in name for keyword in ("CJK", "SC", "Hei", "YaHei")):
                chosen = name
                break
    if chosen is None:
        raise DataError("未找到可用中文字体；请把字体文件放入 render/fonts/ 后再出图")

    matplotlib.rcParams["font.sans-serif"] = [chosen, *matplotlib.rcParams["font.sans-serif"]]
    matplotlib.rcParams["axes.unicode_minus"] = False
    return chosen