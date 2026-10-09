#!/usr/bin/env python3
"""全量导出我发过的微博（命令行版，不受 MCP 调用时长限制）。

用法：
    ./venv/bin/python export.py               # 全部导出（含长文正文）
    ./venv/bin/python export.py --no-longtext # 不抓长文，快很多
    ./venv/bin/python export.py --pages 5     # 只导前 5 页（约 100 条）
    ./venv/bin/python export.py --feature 1   # 只要原创（0=全部 1=原创 2=视频 3=图片）

输出：export/weibo_<时间>.json 和 export/weibo_<时间>.md
"""

import argparse
import json
import sys
import time

import server


def main() -> int:
    ap = argparse.ArgumentParser(description="导出我发过的微博")
    ap.add_argument("--pages", type=int, default=0, help="最多页数，0=全部（默认）")
    ap.add_argument("--start-page", type=int, default=1, help="起始页码，默认 1")
    ap.add_argument("--feature", type=int, default=0, help="0=全部 1=原创 2=视频 3=图片")
    ap.add_argument("--no-longtext", action="store_true", help="不抓长微博完整正文")
    args = ap.parse_args()

    try:
        uid = server._own_uid()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    pages = args.pages if args.pages > 0 else 10**9
    print(f"开始导出 uid={uid}（最多 {pages} 页，"
          f"长文抓取={'否' if args.no_longtext else '是'}）…", file=sys.stderr)
    t0 = time.time()
    result = json.loads(server.export_my_posts(
        max_pages=pages,
        start_page=max(1, args.start_page),
        feature=args.feature,
        fetch_longtext=not args.no_longtext,
    ))
    print(f"完成：{result['fetched']} 条 / 账号共约 {result['total']} 条，"
          f"耗时 {time.time() - t0:.0f}s", file=sys.stderr)
    print(f"JSON: {result['json']}")
    print(f"Markdown: {result['markdown']}")
    if result.get("next_start_page"):
        print(f"注意：可能还有更多，续跑请加 --start-page {result['next_start_page']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
