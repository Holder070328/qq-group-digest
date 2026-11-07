#!/usr/bin/env python
"""qq_alert_backfill.py — 把历史「高价值即时提醒」的 cron 输出补成 md 归档。

cron 每次运行的输出存在 profiles/<profile>/cron/output/<job_id>/<日期>_<时间>.md，
其中「silent (empty output)」那类跳过，有内容的按 qq_alert 的格式重建：

    qq/alerts/<年>/<月>/<YYYY-MM-DD HHMM> · 高价值提醒.md

幂等：目标文件已存在就覆盖重写（内容只来自 cron 输出，不会叠加）。

用法:
    python qq_alert_backfill.py --last 2      # 只补最近 2 次有内容的提醒
    python qq_alert_backfill.py               # 全部补（已有 md 也重写）
    python qq_alert_backfill.py --dry
"""
import argparse
import glob
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qq_alert

OUTPUT_DIR = r"D:\Hermes\profiles\muelsyse-us\cron\output\5120c8055656"

LINE_RE = re.compile(
    r"^·\s*【(?P<label>[^】]+)】\s*(?P<text>.*?)\s+—\s*(?P<who>.+?)\s+"
    r"(?P<mmdd>\d{2}-\d{2})\s+(?P<hhmm>\d{2}:\d{2})\s*$")
RUN_RE = re.compile(r"\*\*Run Time:\*\*\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def parse(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    if "silent (empty output)" in raw:
        return None
    m = RUN_RE.search(raw)
    when = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else \
        datetime.fromtimestamp(os.path.getmtime(path))
    items = []
    for line in raw.split("\n"):
        g = LINE_RE.match(line.strip())
        if not g:
            continue
        try:
            ts = datetime.strptime(f"{when.year}-{g['mmdd']} {g['hhmm']}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        items.append((g["label"], int(ts.timestamp()), g["who"], g["text"]))
    if not items:
        return None
    return when, items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=OUTPUT_DIR)
    ap.add_argument("--last", type=int, default=0, help="只处理最近 N 次有内容的提醒")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.dir, "*.md")))
    parsed = []
    for f in reversed(files):            # 从新到旧
        got = parse(f)
        if got:
            parsed.append((f, got))
    if a.last:
        parsed = parsed[:a.last]
    parsed.reverse()                     # 处理时按时间正序

    n = 0
    for f, (when, items) in parsed:
        if a.dry:
            print(f"[dry] {when:%Y-%m-%d %H:%M}  {len(items)} 条  ← {os.path.basename(f)}")
            continue
        path, _body = qq_alert.write_alert_md(when, items)
        n += 1
        print(f"{len(items):2d} 条 → {path}")
    print(f"共 {n if not a.dry else len(parsed)} 份")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
