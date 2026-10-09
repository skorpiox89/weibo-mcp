#!/usr/bin/env bash
# 检查 cookie.txt 中的微博登录态是否有效。
# 用法：./check-cookie.sh
# 退出码：0 = 有效；1 = 失效/出错（需要重新复制 cookie）
cd "$(dirname "$0")" || exit 1
exec ./venv/bin/python - <<'PY'
import json
import sys

import server


def fail(e):
    print(f"FAIL: {e}", file=sys.stderr)
    print("请重新登录 weibo.com，把请求头里的整段 Cookie 更新到 cookie.txt", file=sys.stderr)
    sys.exit(1)


try:
    me = json.loads(server.check_auth())
except Exception as e:  # noqa: BLE001
    fail(e)
print(f"OK: cookie 有效，登录账号 {me['uid']} / {me.get('screen_name') or '?'}"
      f"（微博 {me.get('statuses_count')} 条，粉丝 {me.get('followers_count')}）")

try:
    r = json.loads(server.list_my_posts(page=1))
except Exception as e:  # noqa: BLE001
    fail(e)
print(f"第一页可读：{r['count']} 条（账号共约 {r['total']} 条）")
for p in r["posts"][:3]:
    print(f"  - {p['created_at']}  {p['text'][:50]!r}")
PY
