#!/usr/bin/env python
"""qq_digest.py — 把最近 N 小时的群消息整理成一份「喂给模型」的原始材料。

用法:
    python qq_digest.py                 # 默认最近 24 小时
    python qq_digest.py --hours 48
    python qq_digest.py --hours 24 --max-samples 60
"""
import argparse
import os
import re
import sqlite3
import time
from datetime import datetime

from paths import DB
from paths import GROUP_NAME

KEY_PATTERNS = {
    "招生/职位": r"招|PhD|phd|博士|博后|postdoc|position|position|全奖|RA|TA|导师|实验室|opening|vacanc",
    "截止/DDL": r"ddl|DDL|截止|deadline|due|报名|申请截止|材料|提交",
    "暑研/交流": r"暑研|交换|交流|visiting|VISP|summer|summer school|暑校",
    "offer/结果": r"offer|录取|admission|面试|interview|拒信|waitlist|结果",
    "经验/求问": r"请问|求问|请教|有人|有没有|怎么|如何|经验|建议",
    "链接/文件": r"http|www\.|\.com|\.edu|\.cn|文件|pdf",
}


def fetch(hours):
    since = int(time.time()) - hours * 3600
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT ts, COALESCE(NULLIF(card,''),nickname), text FROM messages "
        "WHERE ts >= ? ORDER BY ts", (since,)).fetchall()
    con.close()
    return rows


def norm(s):
    """归一化：去掉表情、标点、空白、链接，用于判断两条是不是同一条消息被转发。"""
    s = re.sub(r"\[[^\]]{0,12}\]", "", s or "")
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"[\s，。、；：！？,.;:!?~～…—\-（）()「」【】\"]+", "", s)
    return s


def dedup(rows):
    """把内容高度相似的消息归成一簇，返回 [(代表行, 重复数)] 与被折叠的行集合。"""
    from difflib import SequenceMatcher
    clusters = []          # [representative_row, count, [norm...]]
    folded = set()
    for row in rows:
        ts, who, text = row[0], row[1], row[2] or ""
        key = norm(text)
        if len(key) < 24:
            clusters.append([row, 1, key])
            continue
        placed = False
        for cl in clusters:
            other = cl[2]
            if not other or len(other) < 24:
                continue
            if SequenceMatcher(None, key, other).quick_ratio() > 0.9:
                cl[1] += 1
                folded.add(ts)
                placed = True
                break
        if not placed:
            clusters.append([row, 1, key])
    return [(c[0], c[1]) for c in clusters], folded


def links_and_files(rows):
    urls, files = {}, {}
    for ts, who, text in rows:
        for u in re.findall(r"https?://[^\s，。、；）)】\"]+", text or ""):
            urls.setdefault(u, (ts, who))
        for f in re.findall(r"\[文件:([^\]]+)\]", text or ""):
            files.setdefault(f, (ts, who))
    return urls, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--max-samples", type=int, default=50)
    ap.add_argument("--sample-chars", type=int, default=90)
    a = ap.parse_args()

    rows = fetch(a.hours)
    if not rows:
        print(f"【{GROUP_NAME}】最近 {a.hours} 小时：0 条消息。")
        return

    t0 = datetime.fromtimestamp(rows[0][0])
    t1 = datetime.fromtimestamp(rows[-1][0])
    senders = {}
    hours_bucket = {}
    cat = {k: 0 for k in KEY_PATTERNS}
    for ts, who, text in rows:
        senders[who] = senders.get(who, 0) + 1
        h = datetime.fromtimestamp(ts).hour
        hours_bucket[h] = hours_bucket.get(h, 0) + 1
        for k, pat in KEY_PATTERNS.items():
            if text and re.search(pat, text):
                cat[k] += 1

    print(f"【{GROUP_NAME}】最近 {a.hours} 小时采集概况")
    print(f"窗口: {t0:%m-%d %H:%M} → {t1:%m-%d %H:%M}")
    print(f"消息数: {len(rows)} | 发言人数: {len(senders)}")
    hb = os.path.join(os.path.dirname(DB), "heartbeat.json")
    if os.path.exists(hb):
        try:
            import json as _json
            h = _json.load(open(hb, encoding="utf-8"))
            last = datetime.fromtimestamp(h.get("last_event", 0)) if h.get("last_event") else None
            print(f"管道心跳: 累计收 {h.get('events_total',0)} 个事件 / 命中本群 {h.get('saved_total',0)} 条"
                  f" | 最近事件 {last:%m-%d %H:%M}" if last else "管道心跳: 无")
        except Exception:
            pass
    peak = sorted(hours_bucket.items(), key=lambda x: -x[1])[:4]
    print("高峰时段: " + ", ".join(f"{h:02d}点×{c}" for h, c in peak))
    print("\n发言人 Top10:")
    for who, c in sorted(senders.items(), key=lambda x: -x[1])[:10]:
        print(f"  {c:>3}  {who[:28]}")
    print("\n关键词粗筛（单条可能命中多类）:")
    for k, c in cat.items():
        if c:
            print(f"  {k}: {c} 条")

    urls, files = links_and_files(rows)
    if urls or files:
        print(f"\n链接与群文件（去重后）：")
        for u, (ts, who) in list(urls.items())[:12]:
            print(f"  🔗 {u[:110]}  —{who[:12]} {datetime.fromtimestamp(ts):%m-%d %H:%M}")
        for f, (ts, who) in list(files.items())[:12]:
            print(f"  📎 {f[:80]}  —{who[:12]} {datetime.fromtimestamp(ts):%m-%d %H:%M}")

    clusters, folded = dedup(rows)
    if folded:
        print(f"\n重复转发：{len(folded)} 条内容雷同，已折叠（保留最早那条并标注转发次数）")

    print(f"\n消息样本（原始 {len(rows)} 条，去重后 {len(clusters)} 组，按下述规则抽样）:")
    scored = []
    for (ts, who, text), dup in clusters:
        score = sum(1 for pat in KEY_PATTERNS.values() if text and re.search(pat, text))
        score += min(len(text or "") // 40, 2)
        scored.append((score, ts, who, text, dup))
    picked = sorted(sorted(scored, key=lambda x: -x[0])[: a.max_samples], key=lambda x: x[1])
    for score, ts, who, text, dup in picked:
        t = (text or "").replace("\n", " ")[: a.sample_chars]
        extra = f"（另有 {dup - 1} 人转发）" if dup > 1 else ""
        print(f"[{datetime.fromtimestamp(ts):%m-%d %H:%M}] {who[:18]}: {t}{extra}")

    print(f"\n(样本 {len(picked)}/{len(clusters)} 组；库 {os.path.getsize(DB)//1024} KB)")


if __name__ == "__main__":
    main()
