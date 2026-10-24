#!/usr/bin/env python
r"""qq_prune.py — 把 90 天以上的原始消息压成 gzip 归档，然后从库里删掉。

归档位置: workspace\qq\archive\YYYY-MM.jsonl.gz（按月一个文件）
没有需要归档的数据时**不输出任何内容**（cron 侧保持静默）。

用法:
    python qq_prune.py                # 默认 90 天
    python qq_prune.py --days 60 --dry-run
"""
import argparse
import gzip
import json
import os
import sqlite3
import time
from datetime import datetime

from paths import QQDIR
DB = os.path.join(QQDIR, "messages.db")
ARCHIVE = os.path.join(QQDIR, "archive")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(DB):
        return
    cutoff = int(time.time()) - a.days * 86400

    con = sqlite3.connect(DB)
    cols = [r[1] for r in con.execute("PRAGMA table_info(messages)")]
    rows = con.execute(
        f"SELECT {','.join(cols)} FROM messages WHERE ts < ? ORDER BY ts", (cutoff,)
    ).fetchall()
    if not rows:
        con.close()
        return

    by_month = {}
    for r in rows:
        m = datetime.fromtimestamp(r[cols.index("ts")]).strftime("%Y-%m")
        by_month.setdefault(m, []).append(dict(zip(cols, r)))

    os.makedirs(ARCHIVE, exist_ok=True)
    written = []
    for m, items in sorted(by_month.items()):
        path = os.path.join(ARCHIVE, f"{m}.jsonl.gz")
        with gzip.open(path, "at", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        written.append((m, len(items), os.path.getsize(path)))

    if not a.dry_run:
        con.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
        con.commit()
        con.execute("VACUUM")
    con.close()

    total = sum(w[1] for w in written)
    size = sum(w[2] for w in written)
    action = "将归档" if a.dry_run else "已归档"
    print(f"🧹 {action} {total} 条（{a.days} 天以前）→ archive\\，"
          f"当前占用 {size/1024:.0f} KB")
    for m, n, s in written:
        print(f"  {m}.jsonl.gz  {n} 条  {s/1024:.0f} KB")


if __name__ == "__main__":
    main()
