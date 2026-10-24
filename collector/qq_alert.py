#!/usr/bin/env python
"""qq_alert.py — 高价值消息即时提醒（无消息时完全静默）。

由 cron 每 20 分钟跑一次。命中「招生 / 截止 / 全奖 / offer」这类关键词才输出，
否则不打印任何东西（= 不打扰）。

状态存在 qq/alert_state.json：记住已提醒到的消息时间，避免重复。
"""
import json
import os
import re
import sqlite3
import time
from datetime import datetime

from paths import QQDIR
DB = os.path.join(QQDIR, "messages.db")
STATE = os.path.join(QQDIR, "alert_state.json")
HB = os.path.join(QQDIR, "heartbeat.json")

PATTERNS = [
    ("招生", r"招生|招聘|招人|PhD|phd|博士|博后|postdoc|postdoc|position|opening|vacanc|RA|全奖|助理教授|课题组"),
    ("截止", r"截止|ddl|DDL|deadline|deadline|due|报名截止|申请截止"),
    ("结果", r"offer|Offer|录取|admission|面试|interview|waitlist|拒信|放榜"),
    ("机会", r"暑研|暑校|summer school|VISP|visiting|fellowship|实习"),
]

MAX_LINES = 4
OFFLINE_HOURS = 14          # 心跳超过这么久没动静，提醒一次
QUIET_START, QUIET_END = 0, 8   # 这个时段不报掉线（夜里没人发消息很正常）


def load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


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

    hits = []
    for ts, who, text, mid in rows:
        text = text or ""
        for label, pat in PATTERNS:
            if re.search(pat, text):
                hits.append((ts, who, text, label))
                break

    if hits:
        print("博士，群里刚冒出来这几条——")
        for ts, who, text, label in hits[-MAX_LINES:]:
            t = text.replace("\n", " ")[:80]
            print(f"· 【{label}】{t}  —{who[:14]} {datetime.fromtimestamp(ts):%m-%d %H:%M}")
        if len(hits) > MAX_LINES:
            print(f"（另有 {len(hits) - MAX_LINES} 条同类，周一汇总里一起说）")

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
    elif hits:
        state["last_ts"] = now
    os.makedirs(QQDIR, exist_ok=True)
    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
