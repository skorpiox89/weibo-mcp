# weibo-mcp

微博 MCP Server（只读 · Cookie 认证）。

把自己发过的微博捞出来：时间线、关键词搜索、单条详情（长文/图片/视频）、全量导出为 JSON + Markdown。

只做读取，不做任何发博/转发/点赞等写操作。

## 特性

- 🔐 Cookie 登录态，可读取自己账号的微博时间线
- 📄 长微博自动抓取完整正文（`longText`）
- 🔎 在自己的微博里按关键词搜索
- 🖼️ 图片、视频、转发原文一并导出
- 📦 全量导出 JSON（结构化）+ Markdown（人类可读）
- 🚦 翻页自带间隔，降低触发风控的概率

## 快速开始

```bash
git clone git@github.com:skorpiox89/weibo-mcp.git
cd weibo-mcp
python3 -m venv venv
venv/bin/pip install "mcp>=1.2.0,<2"

# 配置 Cookie（见下文）
cp cookie.txt.example cookie.txt && chmod 600 cookie.txt
# 编辑 cookie.txt，粘贴整段 Cookie

./check-cookie.sh   # 自检登录态
```

### 获取 Cookie

1. 浏览器登录 <https://weibo.com>
2. F12 → Network → 随便点一个请求 → Request Headers → 复制 **Cookie** 一整行的值
3. 覆盖写入 `cookie.txt`（单行；`#` 开头的行会被忽略）

Cookie 有效期一般数天到数周；接口报 HTTP 403/432 时重新复制即可。

## 接入 MCP 客户端

stdio 传输，`command` 指向 venv 里的 Python，`args` 指向 `server.py`。不设置 `WEIBO_COOKIE` 时会自动读 `server.py` 同目录的 `cookie.txt`。

```json
{
  "mcpServers": {
    "weibo": {
      "command": "/path/to/weibo-mcp/venv/bin/python",
      "args": ["/path/to/weibo-mcp/server.py"],
      "env": { "WEIBO_COOKIE": "!cat /path/to/weibo-mcp/cookie.txt" }
    }
  }
}
```

> `!cat ...` 是 pi 的环境变量取值写法；其他客户端直接用文件读取即可（留空 `env`）。

## MCP 工具

| 工具 | 说明 |
| --- | --- |
| `check_auth` | 检查 Cookie，返回登录账号资料 |
| `list_my_posts(page, feature, fetch_longtext)` | 我的微博列表，每页约 20 条；`feature`: 0=全部 1=原创 2=视频 3=图片 |
| `search_my_posts(keyword, page)` | 在我的微博里按关键词搜索 |
| `get_post(post_id)` | 单条完整内容（长文正文、图片、视频、转发原文） |
| `export_my_posts(max_pages, start_page, feature, fetch_longtext)` | 导出 JSON + Markdown 到 `export/`，翻页次数多时分批调用 |

## 全量导出（命令行）

不受 MCP 调用时长限制，推荐大账号使用：

```bash
# 全部导出（含长文正文）
./venv/bin/python export.py

# 不抓长文，快很多
./venv/bin/python export.py --no-longtext

# 只导前 5 页 / 只要原创
./venv/bin/python export.py --pages 5
./venv/bin/python export.py --feature 1
```

输出：`export/weibo_<时间>.json`（含图片/视频/转发原文/可见性字段）和 `export/weibo_<时间>.md`（含图片链接，人类可读）。

## 说明

- 接口来自微博网页端内部 API（`weibo.com/ajax/...`），**非官方开放平台**，抓取时每页间隔约 1.2s、长文间隔 0.4s。
- `visible` 字段为微博原始可见性编码（`0` 公开；其他值可能是仅自己可见/好友圈，原样保留未做映射）。
- 账号 uid 默认从微博首页自动解析；解析失败时可设置环境变量 `WEIBO_UID`。
- 仅供个人备份自己的微博数据使用，请勿用于批量爬取他人内容。
