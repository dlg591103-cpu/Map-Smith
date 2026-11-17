"""联网预热：批量把 quotsoft 全国站点日数据下载到 demo_data/air/。

用途：比赛/演示前联网跑一次，把需要的日期缓存到本地；现场用默认离线模式即可。

用法（项目根目录）：
    python warmup_data.py                    # 最近 7 天（截至前天，quotsoft 凌晨才更新前一日）
    python warmup_data.py --days 14          # 最近 14 天
    python warmup_data.py --from 20261101 --to 20261110
    python warmup_data.py 20261101 20261102  # 指定若干日期

已存在的文件会跳过，不重复下载；失败会逐个打印原因，不影响其他日期。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AIR_DIR = ROOT / "src" / "mapsmith" / "demo_data" / "air"
URL = "https://quotsoft.net/air/data/china_sites_{date}.csv"


def _parse_day(text: str) -> date:
    if len(text) != 8 or not text.isdigit():
        raise SystemExit(f"日期格式应为 YYYYMMDD，实际为 {text!r}")
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))


def _fetch(day: str, timeout: float) -> bool:
    target = AIR_DIR / f"china_sites_{day}.csv"
    if target.exists() and target.stat().st_size > 0:
        print(f"  跳过 {day}（已存在 {target.stat().st_size / 1024:.0f} KB）")
        return True
    try:
        import requests
    except ImportError:
        print("  需要 requests：pip install requests")
        return False
    try:
        resp = requests.get(URL.format(date=day), timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - 单日失败不影响整体
        print(f"  {day}: 请求失败 {type(exc).__name__}: {exc}")
        return False
    if resp.status_code != 200:
        print(f"  {day}: HTTP {resp.status_code}")
        return False
    if len(resp.content) < 1000:
        print(f"  {day}: 返回内容过小（{len(resp.content)} B），该日可能尚未发布")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(resp.content)
    print(f"  {day}: 已保存 {len(resp.content) / 1024:.0f} KB")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 quotsoft 站点数据到 demo_data/air/")
    parser.add_argument("dates", nargs="*", help="指定日期 YYYYMMDD，可多个")
    parser.add_argument("--days", type=int, default=7, help="最近 N 天（截至前天），默认 7")
    parser.add_argument("--from", dest="start", help="起始日期 YYYYMMDD")
    parser.add_argument("--to", dest="end", help="结束日期 YYYYMMDD")
    parser.add_argument("--timeout", type=float, default=120.0, help="单日下载超时秒数")
    args = parser.parse_args()

    if args.dates:
        days = list(args.dates)
    elif args.start and args.end:
        cur, end = _parse_day(args.start), _parse_day(args.end)
        days = []
        while cur <= end:
            days.append(cur.strftime("%Y%m%d"))
            cur += timedelta(days=1)
    else:
        # quotsoft 每日凌晨 2 点后更新前一日，故默认截止到「前天」，避免拿到空文件
        cut = date.today() - timedelta(days=2)
        days = [(cut - timedelta(days=i)).strftime("%Y%m%d") for i in range(args.days - 1, -1, -1)]

    print(f"目标目录: {AIR_DIR}")
    print(f"待下载 {len(days)} 个日期: {', '.join(days)}")
    ok = sum(1 for d in days if _fetch(d, args.timeout))
    print(f"\n完成：成功 {ok}/{len(days)}")
    return 0 if ok == len(days) else 1


if __name__ == "__main__":
    sys.exit(main())
