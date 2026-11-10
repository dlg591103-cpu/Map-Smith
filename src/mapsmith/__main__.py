"""命令行入口：`python -m mapsmith`。

T02 只提供版本与配置查询；真正的运行入口分别由 T22（Streamlit）与 T23（一键启动脚本）提供。
"""

from __future__ import annotations

import argparse
import json

from . import __version__
from .config import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mapsmith",
        description="Map Smith 命令行入口（T02 骨架，仅支持版本与配置查询）",
    )
    parser.add_argument("--version", action="version", version=f"mapsmith {__version__}")
    parser.add_argument("--config", action="store_true", help="打印当前配置后退出")
    parser.add_argument("--json", action="store_true", help="与 --config 一起使用，输出 JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.config:
        data = get_settings().as_dict()
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            width = max(len(key) for key in data)
            for key, value in data.items():
                print(f"{key.ljust(width)} : {value}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())