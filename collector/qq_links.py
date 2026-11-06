#!/usr/bin/env python
"""qq_links.py — 读取群消息里的链接正文（小红书 / 微信公众号 / 普通网页）。

用途：把「链接里说了什么」也当成消息来源，喂给即时提醒与周报。
  ・小红书短链 xhslink.cn/o/xxx → 跳转到带 xsec_token 的笔记页 → og:title / og:description 就是标题与正文
  ・微信公众号 mp.weixin.qq.com → og 标签 + #js_content 正文
  ・普通网页 → og:title / og:description / <title>

缓存：qq/link_cache.json（7 天），同一链接不重复抓。
失败静默：拿不到就记 note，不抛异常、不阻塞提醒。

用法:
    python qq_links.py <url> [<url> ...]
"""
import html
import json
import os
import re
import time
import urllib.request

QQDIR = r"D:\Hermes\profiles\muelsyse-us\workspace\qq"
CACHE = os.path.join(QQDIR, "link_cache.json")
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
TIMEOUT = 20
TTL = 7 * 86400
MAX_LEN = 1500

URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fff，。、；）)】」\"'<>]+")


def find_urls(text):
    """从一段消息文本里取出链接（去重、保序）。"""
    out = []
    for u in URL_RE.findall(text or ""):
        u = u.rstrip(".,;:")
        if u not in out:
            out.append(u)
    return out


def _load_cache():
    try:
        return json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(c):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(c, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)


def _get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
        return r.geturl(), raw.decode("utf-8", "replace")


def _metas(h):
    """把 <meta property/name=... content=...> 全部收进 dict（不依赖属性顺序）。"""
    out = {}
    for tag in re.findall(r"<meta\b[^>]*>", h, re.I):
        p = re.search(r'(?:property|name)\s*=\s*"([^"]+)"', tag, re.I)
        c = re.search(r'content\s*=\s*"([^"]*)"', tag, re.I)
        if p and c:
            out.setdefault(p.group(1).lower(), c.group(1))
    return out


def _title_tag(h):
    m = re.search(r"<title[^>]*>(.*?)</title>", h, re.I | re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def _wechat_body(h):
    """公众号正文：抓 #js_content 里的纯文本。"""
    m = re.search(r'<div[^>]+id="js_content"[^>]*>(.*?)</div>\s*(?:</div>|<script)', h, re.S)
    if not m:
        return ""
    txt = re.sub(r"<[^>]+>", " ", m.group(1))
    return re.sub(r"\s+", " ", html.unescape(txt)).strip()


def _source(url):
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    if "xiaohongshu" in host or "xhslink" in host:
        return "小红书"
    if "weixin" in host or "wechat" in host:
        return "公众号"
    if "zhihu" in host:
        return "知乎"
    if "github" in host:
        return "GitHub"
    return host


def fetch(url, force=False):
    """抓一个链接 → {url, final, title, text, source, ok, note, at}。永远不抛异常。"""
    cache = _load_cache()
    hit = cache.get(url)
    if hit and not force and time.time() - hit.get("at", 0) < TTL:
        return hit

    rec = {"url": url, "final": url, "title": "", "text": "", "source": _source(url),
           "ok": False, "note": "", "at": int(time.time())}
    try:
        final, h = _get(url)
        rec["final"] = final
        rec["source"] = _source(final)
        m = _metas(h)
        title = m.get("og:title") or m.get("twitter:title") or _title_tag(h)
        title = re.sub(r"\s*[-_|]\s*小红书\s*$", "", html.unescape(title or "")).strip()
        desc = m.get("og:description") or m.get("description") or m.get("keywords") or ""
        if "mp.weixin.qq.com" in final:
            body = _wechat_body(h)
            if body:
                desc = body
        rec["title"] = title
        rec["text"] = re.sub(r"\s+", " ", html.unescape(desc)).strip()[:MAX_LEN]
        rec["ok"] = bool(rec["title"] or rec["text"])
        if not rec["ok"]:
            low = h.lower()
            if "安全验证" in h or "verify" in low:
                rec["note"] = "页面要求验证（风控）"
            else:
                rec["note"] = "页面里没有可读的标题/正文"
    except Exception as e:
        rec["note"] = f"{type(e).__name__}: {e}"

    cache[url] = rec
    try:
        _save_cache(cache)
    except Exception:
        pass
    return rec


def brief(rec, n=120):
    """一行摘要：标题 + 正文前 n 字。"""
    t = (rec.get("title") or "").strip()
    d = (rec.get("text") or "").strip()
    if t and d and d.startswith(t):
        d = d[len(t):].strip()
    out = t
    if d:
        out = (out + "｜" + d) if out else d
    out = re.sub(r"[—\-_=‧·]{3,}", " ", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:n] + ("…" if len(out) > n else "")


def main():
    import sys
    for u in sys.argv[1:]:
        r = fetch(u, force=True)
        print(f"=== {u}")
        print(f"  source: {r['source']}  ok={r['ok']}  {r.get('note','')}")
        if r["title"]:
            print(f"  title: {r['title']}")
        if r["text"]:
            print(f"  text : {r['text'][:600]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
