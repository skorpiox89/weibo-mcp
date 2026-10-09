"""微博 MCP Server（只读 · Cookie 认证）

把自己发过的微博捞出来：时间线、关键词搜索、单条详情（长文/图片/视频）、全量导出。
只做读取，不做任何发博/转发/点赞等写操作。

接口（微博网页端内部 API，Cookie 登录态）：
    whoami        GET https://weibo.com/ajax/profile/info?uid=...
    我的微博      GET https://weibo.com/ajax/statuses/mymblog?uid=...&page=...&feature=0
    我的微博搜索  GET https://weibo.com/ajax/statuses/searchProfile?uid=...&q=...&page=...
    单条详情      GET https://weibo.com/ajax/statuses/show?id=...
    长文正文      GET https://weibo.com/ajax/statuses/longtext?id=...

运行前提：
    1. venv/bin/pip install "mcp>=1.2.0,<2"
    2. 浏览器登录 weibo.com，从任意 XHR 请求头里复制整段 Cookie 到 cookie.txt
       （或 cp cookie.txt.example cookie.txt 后编辑）
    3. venv/bin/python server.py  （stdio 传输）
"""

import html as _html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weibo")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_FILE = os.path.join(BASE_DIR, "cookie.txt")
EXPORT_DIR = os.path.join(BASE_DIR, "export")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_uid_cache = {"uid": ""}


# ---------- Cookie ----------

def _cookie() -> str:
    cookie = os.environ.get("WEIBO_COOKIE", "").strip()
    # 兼容 pi mcp.json 里 "!cat /path/cookie.txt" 的写法
    if cookie.startswith("!"):
        m = re.search(r"cat\s+(\S+)", cookie)
        if m and os.path.exists(m.group(1)):
            cookie = open(m.group(1), encoding="utf-8").read().strip()
        else:
            cookie = ""
    if not cookie and os.path.exists(COOKIE_FILE):
        cookie = open(COOKIE_FILE, encoding="utf-8").read().strip()
    if not cookie or cookie.startswith("#"):
        raise RuntimeError(
            "未配置微博 Cookie：请登录 weibo.com 后，把任意 XHR 请求头里的整段 Cookie "
            f"写入 {COOKIE_FILE}（或设置 WEIBO_COOKIE 环境变量）"
        )
    return cookie


# ---------- HTTP ----------

def _http(url: str, params: dict | None = None,
          referer: str = "https://weibo.com/", accept: str = "application/json, text/plain, */*") -> bytes:
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Cookie": _cookie(),
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    last_err = None
    for attempt in range(2):  # GET 幂等，网络抖动重试一次
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code in (403, 414, 418, 432):
                raise RuntimeError(
                    f"HTTP {exc.code}（Cookie 过期或触发风控，请重新登录 weibo.com 更新 cookie.txt）"
                    f" {url.split('?')[0]} {body[:150]}"
                ) from exc
            if exc.code >= 500 and attempt == 0:
                last_err = exc
                time.sleep(1.5)
                continue
            raise RuntimeError(f"HTTP {exc.code} {url}: {body[:200]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = exc
            if attempt == 0:
                time.sleep(1.5)
                continue
    raise RuntimeError(f"无法连接微博接口: {getattr(last_err, 'reason', last_err)}")


def _get_json(url: str, params: dict | None = None, referer: str = "https://weibo.com/"):
    raw = _http(url, params, referer=referer)
    text = raw.decode("utf-8", "replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"返回不是 JSON（可能被登录页/风控拦截）：{text[:200]}") from None
    if isinstance(data, dict) and data.get("ok") == 0:
        raise RuntimeError(f"微博接口返回错误：{json.dumps(data, ensure_ascii=False)[:300]}")
    return data


def _get_text(url: str, referer: str = "https://weibo.com/") -> str:
    return _http(url, referer=referer, accept="text/html,application/xhtml+xml").decode("utf-8", "replace")


# ---------- 账号 ----------

def _own_uid() -> str:
    """当前登录账号 uid：优先 WEIBO_UID 环境变量，否则从微博首页 $CONFIG 解析"""
    if _uid_cache["uid"]:
        return _uid_cache["uid"]
    env_uid = (os.environ.get("WEIBO_UID") or "").strip()
    if env_uid.isdigit():
        _uid_cache["uid"] = env_uid
        return env_uid
    page = _get_text("https://weibo.com/")
    for pat in (r"\$CONFIG\['uid'\]\s*=\s*'(\d+)'", r'"uid"\s*:\s*"?(\d{5,})'):
        m = re.search(pat, page)
        if m:
            _uid_cache["uid"] = m.group(1)
            return m.group(1)
    raise RuntimeError("无法自动识别当前账号 uid：请设置环境变量 WEIBO_UID（你主页地址里的数字 id）")


# ---------- 数据清洗 ----------

_TAG_RE = re.compile(r"<[^>]+>")


def _plain(s) -> str:
    return _html.unescape(_TAG_RE.sub("", s or "")).strip()


def _pics(mb: dict) -> list:
    out = []

    def add(u):
        if u and u not in out:
            out.append(u)

    for p in mb.get("pics") or []:
        if isinstance(p, dict):
            add((p.get("large") or {}).get("url") or p.get("url"))
    for info in (mb.get("pic_infos") or {}).values():
        if isinstance(info, dict):
            add(((info.get("largest") or {}).get("url"))
                or ((info.get("large") or {}).get("url")))
    return out


def _videos(mb: dict) -> list:
    out = []
    pi = mb.get("page_info") or {}
    if isinstance(pi, dict) and pi.get("object_type") == "video":
        mi = pi.get("media_info") or {}
        for k in ("stream_url_hd", "stream_url", "mp4_720p_mp4", "mp4_hd_url", "mp4_sd_url"):
            u = mi.get(k)
            if u and u not in out:
                out.append(u)
            break
        for u in (pi.get("urls") or {}).values():
            if isinstance(u, str) and u.startswith("http") and u not in out:
                out.append(u)
    for k in ("stream_url", "stream_url_hd"):
        u = mb.get(k)
        if u and u not in out:
            out.append(u)
    return out


def _norm(mb: dict, uid: str) -> dict:
    long_txt = ""
    lt = mb.get("longText")
    if isinstance(lt, dict):
        long_txt = _plain(lt.get("longTextContent"))
    text = long_txt or _plain(mb.get("text_raw")) or _plain(mb.get("text"))
    mid = mb.get("mid") or mb.get("id")
    item = {
        "id": str(mb.get("idstr") or mb.get("id") or ""),
        "created_at": mb.get("created_at"),
        "text": text,
        "pics": _pics(mb),
        "videos": _videos(mb),
        "source": _plain(mb.get("source")),
        "reposts_count": mb.get("reposts_count"),
        "comments_count": mb.get("comments_count"),
        "attitudes_count": mb.get("attitudes_count"),
        "visible": mb.get("visible"),
        "is_long_text": bool(mb.get("isLongText")) or bool(long_txt),
        "url": f"https://weibo.com/{uid}/{mid}" if uid and mid else f"https://m.weibo.cn/detail/{mb.get('id')}",
    }
    rt = mb.get("retweeted_status")
    if isinstance(rt, dict):
        item["retweeted"] = {
            "id": str(rt.get("idstr") or rt.get("id") or ""),
            "user": (rt.get("user") or {}).get("screen_name"),
            "text": _plain(rt.get("text_raw")) or _plain(rt.get("text")),
            "pics": _pics(rt),
        }
    return item


# ---------- 接口封装 ----------

def _fetch_longtext(post_id: str) -> str:
    for url in ("https://weibo.com/ajax/statuses/longtext",
                "https://m.weibo.cn/statuses/longtext"):
        try:
            data = _get_json(url, {"id": str(post_id)})
        except Exception:  # noqa: BLE001 - 换下一个接口
            continue
        content = ((data.get("data") or {}).get("longTextContent")
                   if isinstance(data.get("data"), dict) else None) \
            or data.get("longTextContent") or ""
        if content:
            return _plain(content)
    return ""


def _fetch_page(uid: str, page: int, feature: int = 0, with_longtext: bool = False):
    params = {"uid": uid, "page": page, "feature": feature}
    if with_longtext:
        params["isGetLongText"] = "true"
    data = _get_json("https://weibo.com/ajax/statuses/mymblog", params,
                     referer=f"https://weibo.com/u/{uid}")
    d = data.get("data") or {}
    posts = d.get("list") or d.get("statuses") or []
    return posts, d


def _apply_longtext(item: dict, mb: dict) -> None:
    if not item["is_long_text"] or not mb.get("isLongText"):
        return
    if isinstance(mb.get("longText"), dict) and mb["longText"].get("longTextContent"):
        return
    text = _fetch_longtext(item["id"])
    if text:
        item["text"] = text


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


# ---------- MCP 工具 ----------

@mcp.tool()
def check_auth() -> str:
    """检查 Cookie 是否有效，返回当前登录微博账号的资料（uid、昵称、粉丝数等）"""
    uid = _own_uid()
    data = _get_json("https://weibo.com/ajax/profile/info", {"uid": uid},
                     referer=f"https://weibo.com/u/{uid}")
    user = ((data.get("data") or {}).get("user")) or {}
    return _dumps({
        "uid": uid,
        "screen_name": user.get("screen_name"),
        "description": user.get("description"),
        "followers_count": user.get("followers_count"),
        "friends_count": user.get("friends_count"),
        "statuses_count": user.get("statuses_count"),
        "verified": user.get("verified_reason") or None,
    })


@mcp.tool()
def list_my_posts(page: int = 1, feature: int = 0, fetch_longtext: bool = False) -> str:
    """列出我发过的微博（按时间倒序，每页约 20 条）

    Args:
        page: 页码，从 1 开始
        feature: 0=全部（含转发，默认），1=原创，2=视频，3=图片
        fetch_longtext: 长微博是否抓取完整正文（会慢一些）
    """
    uid = _own_uid()
    posts, d = _fetch_page(uid, int(page), int(feature), bool(fetch_longtext))
    items = []
    for mb in posts:
        if not isinstance(mb, dict):
            continue
        item = _norm(mb, uid)
        if fetch_longtext:
            _apply_longtext(item, mb)
            if item["is_long_text"]:
                time.sleep(0.4)
        items.append(item)
    return _dumps({
        "uid": uid,
        "page": int(page),
        "count": len(items),
        "total": d.get("total"),
        "posts": items,
    })


@mcp.tool()
def get_post(post_id: str) -> str:
    """获取单条微博的完整内容（长文正文、图片、视频、转发原文）

    Args:
        post_id: 微博 ID（list_my_posts 返回的 id）
    """
    uid = _own_uid()
    data = None
    for url in ("https://weibo.com/ajax/statuses/show",
                "https://m.weibo.cn/statuses/show"):
        try:
            data = _get_json(url, {"id": str(post_id)})
            if isinstance(data.get("data"), dict) or data.get("idstr") or data.get("id"):
                break
        except Exception:  # noqa: BLE001 - 换下一个接口
            data = None
    if not data:
        raise RuntimeError(f"获取微博 {post_id} 失败（接口无数据或 cookie 失效）")
    mb = data.get("data") if isinstance(data.get("data"), dict) else data
    item = _norm(mb, uid)
    _apply_longtext(item, mb)
    return _dumps(item)


@mcp.tool()
def search_my_posts(keyword: str, page: int = 1) -> str:
    """在我的微博里按关键词搜索

    Args:
        keyword: 搜索词
        page: 页码，从 1 开始
    """
    uid = _own_uid()
    data = _get_json("https://weibo.com/ajax/statuses/searchProfile",
                     {"uid": uid, "q": keyword, "page": int(page)},
                     referer=f"https://weibo.com/u/{uid}")
    d = data.get("data") or {}
    posts = d.get("list") or d.get("statuses") or []
    items = [_norm(mb, uid) for mb in posts if isinstance(mb, dict)]
    return _dumps({
        "uid": uid,
        "keyword": keyword,
        "page": int(page),
        "count": len(items),
        "total": d.get("total"),
        "posts": items,
    })


@mcp.tool()
def export_my_posts(max_pages: int = 20, start_page: int = 1,
                    feature: int = 0, fetch_longtext: bool = True) -> str:
    """把我的微博导出成 JSON + Markdown 文件（保存在 weibo-mcp/export/ 下）

    Args:
        max_pages: 本次最多翻多少页（每页约 20 条），默认 20；要全部导出可分批多次调用
        start_page: 从第几页开始（分批导出用，上一次返回的 next_start_page）
        feature: 0=全部（默认），1=原创，2=视频，3=图片
        fetch_longtext: 是否抓取长微博完整正文（默认是）
    """
    uid = _own_uid()
    os.makedirs(EXPORT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    all_posts, seen = [], set()
    total = None
    page = max(1, int(start_page))
    last_page = page - 1
    more = False
    for i in range(max(1, int(max_pages))):
        posts, d = _fetch_page(uid, page, int(feature), bool(fetch_longtext))
        if total is None:
            total = d.get("total")
        if not posts:
            break
        added = 0
        for mb in posts:
            if not isinstance(mb, dict):
                continue
            item = _norm(mb, uid)
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            added += 1
            if fetch_longtext:
                _apply_longtext(item, mb)
                if item["is_long_text"]:
                    time.sleep(0.4)
            all_posts.append(item)
        last_page = page
        if added == 0:
            break
        if total and len(seen) >= total:
            break
        if i == max(1, int(max_pages)) - 1:
            more = True  # 是翻页次数用完停的，可能还有
            break
        page += 1
        time.sleep(1.2)
    json_path = os.path.join(EXPORT_DIR, f"weibo_{ts}.json")
    md_path = os.path.join(EXPORT_DIR, f"weibo_{ts}.md")
    payload = {"uid": uid, "exported_at": ts, "fetched": len(all_posts),
               "total": total, "posts": all_posts}
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 微博导出（uid {uid}）· {ts}\n\n")
        f.write(f"本次导出 {len(all_posts)} 条 / 账号共约 {total} 条\n\n")
        for it in all_posts:
            f.write(f"## {it['created_at']} · [{it['id']}]({it['url']})\n\n")
            f.write(f"{it['text']}\n\n")
            for u in it["pics"]:
                f.write(f"![]({u})\n\n")
            for u in it["videos"]:
                f.write(f"[视频]({u})\n\n")
    return _dumps({
        "json": json_path,
        "markdown": md_path,
        "fetched": len(all_posts),
        "total": total,
        "pages": f"{start_page}-{last_page}" if all_posts else "",
        "next_start_page": last_page + 1 if more and all_posts else None,
    })


if __name__ == "__main__":
    mcp.run(transport="stdio")
