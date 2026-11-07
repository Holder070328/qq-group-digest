#!/usr/bin/env python
"""qq_alert.py — 高价值消息即时提醒（无消息时完全静默）。

由 cron 每 20 分钟跑一次。命中「招生 / 截止 / 结果 / 机会 / 签证」这类关键词才输出，
否则不打印任何东西（= 不打扰）。

两条消息来源都算数：
  ① 文字本身命中关键词
  ② 消息里带的链接（小红书 / 公众号 / 网页）——先抓正文，再按正文判断值不值得提醒

命中时做三件事：
  · 打印 Telegram 提醒（含「🔗 链接里有内容」，末尾附与 md 相同的「📖 注释」）
  · 写一份 md 归档到 qq/alerts/<年>/<月>/<覆盖起点 YYYY-MM-DD HHMM> · 高价值提醒.md
    文件名用**这批消息里最早那条的时间**，方便回群里对照
  · 没命中任何术语时，注释段写一句说明，保持格式统一

状态存在 qq/alert_state.json：记住已提醒到的消息时间，避免重复。
"""
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime

QQBASE = r"D:\Hermes\profiles\muelsyse-us\workspace"
QQDIR = os.path.join(QQBASE, "qq")
DB = os.path.join(QQDIR, "messages.db")
STATE = os.path.join(QQDIR, "alert_state.json")
HB = os.path.join(QQDIR, "heartbeat.json")
GLOSSARY = os.path.join(QQDIR, "glossary.json")
ALERTDIR = os.path.join(QQDIR, "alerts")
MAX_LINKS = 5          # 一批最多抓 5 个链接

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PATTERNS = [
    ("招生", r"招生|招聘|招人|PhD|phd|博士|博后|postdoc|position|opening|vacanc|RA|全奖|助理教授|课题组"),
    ("截止", r"截止|ddl|DDL|deadline|due|报名截止|申请截止"),
    ("结果", r"offer|Offer|录取|admission|面试|interview|waitlist|拒信|放榜"),
    ("机会", r"暑研|暑校|summer school|VISP|visiting|fellowship|实习"),
    ("签证", r"签证|面签|拒签|10043|212f|212g|美签|I-?20|DS-?2019"),
]

MAX_LINES = 4
OFFLINE_HOURS = 14          # 心跳超过这么久没动静，提醒一次
QUIET_START, QUIET_END = 0, 8   # 这个时段不报掉线（夜里没人发消息很正常）
NO_TERM_NOTE = "（本批没有需要解释的术语）"

TAG_NAME = {"招生": "招生", "截止": "DDL", "结果": "offer", "机会": "暑研实习", "签证": "签证"}
TITLE_KEYWORDS = ["10043", "212f", "212g", "美签", "面签", "F1", "I-20", "DS-160", "暑研",
                  "西湖", "NUS", "港理工", "Madison", "田纳西", "全奖", "PhD", "交换"]


def title_hint(items):
    """抓一个「重点」短语，让标题像周报那样一眼能看出这条在说什么。"""
    labels = []
    for it in items:
        if it[0] not in labels:
            labels.append(it[0])
    blob = " ".join((i[3] or "") for i in items)
    heads = [TAG_NAME.get(l, l) for l in labels[:2]]
    kws = [k for k in TITLE_KEYWORDS if k.lower() in blob.lower()]
    # 已经在类别名里的词不再重复（否则会出现「暑研实习：暑研」这种）
    kws = [k for k in dict.fromkeys(kws) if not any(k in h for h in heads)][:2]
    head = "、".join(heads) or "群内动态"
    tail = "、".join(kws)[:12]
    return (head + "：" + tail) if tail else head


def load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def klass(text):
    """返回命中的标签，没命中返回 None。"""
    text = text or ""
    for label, pat in PATTERNS:
        if re.search(pat, text):
            return label
    return None


def collect_links(rows):
    """抓这批消息里的链接正文 → [(ts, who, rec)]，只看前 MAX_LINKS 个不同 URL。"""
    try:
        import qq_links
    except Exception:
        return []
    seen, out = set(), []
    for ts, who, text, _mid in rows:
        for u in qq_links.find_urls(text):
            if u in seen or len(seen) >= MAX_LINKS:
                continue
            seen.add(u)
            rec = qq_links.fetch(u)
            if rec.get("ok"):
                out.append((ts, who, rec))
    return out


def build_body(when, items):
    """生成 md 正文（含 📖 注释）。返回 (body, 注释条数)。"""
    first, last = min(i[1] for i in items), max(i[1] for i in items)
    first_dt, last_dt = datetime.fromtimestamp(first), datetime.fromtimestamp(last)
    who = {i[2] for i in items}
    span = f"{first_dt:%m-%d %H:%M} ~ {last_dt:%m-%d %H:%M}"

    lines = [f"# {first_dt:%Y-%m-%d %H:%M} ~ {last_dt:%H:%M} · {title_hint(items)}", "",
             f"- {len(items)} 条 / {len(who)} 人 · 覆盖 {span}",
             f"- 由 {when:%m-%d %H:%M} 这轮即时提醒整理（文件名取覆盖起点，方便回群里对照）"]
    for label, ts, poster, text in items[:10]:
        text = re.sub(r"\s+", " ", text or "").strip()
        lines.append(f"- 【{label}】{datetime.fromtimestamp(ts):%m-%d} {text[:70]} —{poster}")
    if len(items) > 10:
        lines.append(f"- 另有 {len(items) - 10} 条同类，见当日周报")
    lines += ["", "> 标准：招生/DDL > 流程通知 > 经验帖 > 求问 > 闲聊"]
    body = "\n".join(lines) + "\n"

    n = 0
    try:
        import qq_annotate
        body, n = qq_annotate.annotate_footnote(body, qq_annotate.load_terms())
    except Exception:
        pass
    if "📖 注释" not in body:                       # 没词命中也要有这一段，格式才统一
        body = body.rstrip("\n") + f"\n---\n\n📖 注释\n{NO_TERM_NOTE}\n"
    return body, n


def notes_block(body):
    """从 md 正文里取出注释段，供聊天消息复用。"""
    if "📖 注释" not in body:
        return NO_TERM_NOTE
    return body.split("📖 注释", 1)[1].strip()


def write_alert_md(when, items):
    """写 md；文件名与目录都用「覆盖起点」。返回 (path, body)。"""
    if not items:
        return None, ""
    body, _ = build_body(when, items)
    first = datetime.fromtimestamp(min(i[1] for i in items))
    folder = os.path.join(ALERTDIR, f"{first:%Y}", f"{first:%m}")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{first:%Y-%m-%d %H%M} · 高价值提醒.md")
    open(path, "w", encoding="utf-8", newline="\n").write(body)
    return path, body


def main():
    state = load(STATE, {"last_ts": 0, "offline_notified": ""})
    now = int(time.time())

    # ---------- 一、关键词命中 ----------
    rows = []
    if os.path.exists(DB):
        con = sqlite3.connect(DB)
        try:
            rows = con.execute(
                "SELECT ts, COALESCE(NULLIF(card,''),nickname), text, msg_id FROM messages "
                "WHERE ts > ? ORDER BY ts", (state.get("last_ts", 0),)).fetchall()
        finally:
            con.close()

    hits = []          # (ts, who, text, label)
    for ts, who, text, mid in rows:
        label = klass(text)
        if label:
            hits.append((ts, who, text, label))

    # ---------- 一之二、链接正文也当消息来源 ----------
    link_hits = []     # (ts, who, rec, label)
    for ts, who, rec in collect_links(rows):
        label = klass(rec.get("title", "") + " " + rec.get("text", ""))
        if label:
            link_hits.append((ts, who, rec, label))

    if hits or link_hits:
        if hits:
            print("博士，群里刚冒出来这几条——")
            for ts, who, text, label in hits[-MAX_LINES:]:
                t = text.replace("\n", " ")[:80]
                print(f"· 【{label}】{t}  —{who[:14]} {datetime.fromtimestamp(ts):%m-%d %H:%M}")
            if len(hits) > MAX_LINES:
                print(f"（另有 {len(hits) - MAX_LINES} 条同类，周一汇总里一起说）")

        if link_hits:
            print("\n🔗 链接里有内容——")
            for ts, who, rec, label in link_hits[:MAX_LINES]:
                try:
                    import qq_links
                    brief = qq_links.brief(rec, 110)
                except Exception:
                    brief = rec.get("title", "")
                print(f"· 【{label}·{rec.get('source','链接')}】{brief}"
                      f"  —{who[:14]} {datetime.fromtimestamp(ts):%m-%d %H:%M}")

        # ---------- 归档成 md（文件名取覆盖起点）----------
        items = []
        for ts, who, text, label in hits:
            items.append((label, ts, who, text))
        for ts, who, rec, label in link_hits:
            try:
                import qq_links
                snippet = qq_links.brief(rec, 60)
            except Exception:
                snippet = rec.get("title", "")
            items.append((f"链接·{rec.get('source','网页')}", ts, who, snippet))
        items.sort(key=lambda x: x[1])

        try:
            path, body = write_alert_md(datetime.now(), items)
            # 聊天里附上与 md 完全一致的注释
            if body:
                print("\n📖 注释")
                for ln in notes_block(body).split("\n"):
                    ln = ln.strip()
                    if ln:
                        print(f"· {ln}" if not ln.startswith(("¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹", "⁰", "（")) else f"· {ln}")
            if path:
                try:
                    shown = os.path.relpath(path, QQBASE)
                except Exception:
                    shown = path
                print(f"\n📄 已归档：{shown}")
        except Exception as e:
            print(f"\n[归档失败] {type(e).__name__}: {e}")

    # ---------- 二、掉线告警 ----------
    hb = load(HB, {})
    last_event = hb.get("last_event") or 0
    today = datetime.now().strftime("%Y-%m-%d")
    hour = datetime.now().hour
    if (last_event and now - last_event > OFFLINE_HOURS * 3600
            and not (QUIET_START <= hour < QUIET_END)
            and state.get("offline_notified") != today):
        gap = (now - last_event) / 3600
        print(f"⚠️ 采集管道已经 {gap:.0f} 小时没收到任何事件了，可能 QQ 掉线或被限制登录。"
              f"需要我去查一下吗？")
        state["offline_notified"] = today

    # ---------- 三、推进游标 ----------
    if rows:
        state["last_ts"] = max(r[0] for r in rows)
    elif hits or link_hits:
        state["last_ts"] = now
    os.makedirs(QQDIR, exist_ok=True)
    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
