#!/usr/bin/env python
"""qq_alert.py — 高价值消息即时提醒（无消息时完全静默）。

由 cron 每 20 分钟跑一次。命中「招生 / 截止 / 结果 / 机会 / 签证」这类关键词才输出，
否则不打印任何东西（= 不打扰）。

两条消息来源都算数：
  ① 文字本身命中关键词
  ② 消息里带的链接（小红书 / 公众号 / 网页）——先抓正文，再按正文判断值不值得提醒

命中时做两件事：
  · 打印 Telegram 提醒（原有格式，末尾加「🔗 链接内容」）
  · 写一份 md 归档到 qq/alerts/<年>/<月>/<YYYY-MM-DD HHMM> · 高价值提醒.md

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
MAX_GLOSS = 3          # 一次最多附 3 条名词解释
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


def load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def explain_terms(texts, limit=MAX_GLOSS):
    """从文本里找术语，返回 [(名词, 解释)]，最多 limit 条。"""
    try:
        terms = json.load(open(GLOSSARY, encoding="utf-8")).get("terms", [])
    except Exception:
        return []
    blob = "\n".join(t or "" for t in texts)
    out, seen = [], set()
    for t in terms:
        name = t.get("name")
        if not name or name in seen:
            continue
        try:
            if re.search(t.get("pat", ""), blob, re.I):
                out.append((name, t.get("say", "")))
                seen.add(name)
        except re.error:
            continue
        if len(out) >= limit:
            break
    return out


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


def write_alert_md(when, items):
    """把这次提醒整理成 md（格式与摘要一致：要点带 MM-DD，文末 📖 注释）。"""
    if not items:
        return None
    folder = os.path.join(ALERTDIR, f"{when:%Y}", f"{when:%m}")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{when:%Y-%m-%d %H%M} · 高价值提醒.md")

    first, last = min(i[1] for i in items), max(i[1] for i in items)
    span = f"{datetime.fromtimestamp(first):%m-%d %H:%M} ~ {datetime.fromtimestamp(last):%m-%d %H:%M}"
    who = {i[2] for i in items}
    lines = [f"# {when:%Y-%m-%d %H:%M} · 高价值提醒", "",
             f"- {len(items)} 条命中 / {len(who)} 人 · 覆盖 {span}"]
    for label, ts, poster, text in items[:10]:
        text = re.sub(r"\s+", " ", text or "").strip()
        lines.append(f"- 【{label}】{datetime.fromtimestamp(ts):%m-%d} {text[:70]} —{poster}")
    if len(items) > 10:
        lines.append(f"- 另有 {len(items) - 10} 条同类，见当日周报")
    lines += ["", "> 标准：招生/DDL > 流程通知 > 经验帖 > 求问 > 闲聊"]
    body = "\n".join(lines) + "\n"
    try:
        import qq_annotate
        body, _ = qq_annotate.annotate_footnote(body, qq_annotate.load_terms())
    except Exception:
        pass
    open(path, "w", encoding="utf-8", newline="\n").write(body)
    return path


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
        merged = sorted({(h[0], h[1], h[2][:80], h[3]) for h in hits})
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

        # 附上专业名词解释（只解释真正出现的词）
        tips = explain_terms([h[2] for h in hits[-MAX_LINES:]] +
                             [r.get("title", "") + r.get("text", "") for (_t, _w, r, _l) in link_hits[:MAX_LINES]])
        if tips:
            print("\n📖 名词小抄")
            for name, say in tips:
                print(f"· {name}：{say}")

        # ---------- 归档成 md ----------
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
            path = write_alert_md(datetime.now(), items)
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
