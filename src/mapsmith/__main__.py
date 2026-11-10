"""命令行入口：`python -m mapsmith`。

默认启动 Web 服务（FastAPI + Vue 构建产物）；`--config` 打印配置后退出。
T23 的一键启动脚本复用本入口。
"""

from __future__ import annotations

import argparse
import json

from . import __version__
from .config import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mapsmith",
        description="Map Smith：自然语言专题制图智能体（默认启动 Web 服务）",
    )
    parser.add_argument("--version", action="version", version=f"mapsmith {__version__}")
    parser.add_argument("--config", action="store_true", help="打印当前配置后退出")
    parser.add_argument("--json", action="store_true", help="与 --config 一起使用，输出 JSON")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8501, help="监听端口，默认 8501")
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

    import uvicorn

    from .server import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())