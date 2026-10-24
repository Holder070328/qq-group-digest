#!/usr/bin/env python
"""qq_archive.py — 查阅每日摘要档案。

用法:
    python qq_archive.py --list               # 列出所有摘要文件（新→旧）
    python qq_archive.py --grep 博士          # 全文搜索
    python qq_archive.py --grep DDL --files   # 只列命中文件
    python qq_archive.py --today              # 打开今天那份
"""
import argparse
import os
import re
import sys
from datetime import date

from paths import DIGESTS as ROOT


def files():
    out = []
    for dp, _, fn in os.walk(ROOT):
        for f in fn:
            if re.match(r"^\d{4}-\d{2}-\d{2}.*\.md$", f):
                out.append(os.path.join(dp, f))
    return sorted(out, reverse=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--grep")
    ap.add_argument("--files", action="store_true")
    ap.add_argument("--today", action="store_true")
    a = ap.parse_args()

    fs = files()

    if a.today:
        target = os.path.join(ROOT, str(date.today().year), f"{date.today():%m}", f"{date.today()}.md")
        if os.path.exists(target):
            print(open(target, encoding="utf-8").read())
        else:
            print(f"(今天还没有摘要: {target})")
        return

    if a.grep:
        pat = re.compile(a.grep, re.I)
        hits = 0
        for f in fs:
            txt = open(f, encoding="utf-8", errors="ignore").read()
            for line in txt.splitlines():
                if pat.search(line):
                    hits += 1
                    if a.files:
                        print(os.path.basename(f))
                        break
                    print(f"{os.path.basename(f)[:-3]} │ {line.strip()[:110]}")
        if not hits:
            print(f"(没有命中「{a.grep}」，共搜了 {len(fs)} 个文件)")
        return

    print(f"档案目录: {ROOT}\n共 {len(fs)} 天\n")
    for f in fs:
        size = os.path.getsize(f)
        print(f"  {os.path.basename(f)[:-3]}   {size:>5} B")
    idx = os.path.join(ROOT, "INDEX.md")
    if os.path.exists(idx):
        print("\n--- INDEX.md ---")
        print(open(idx, encoding="utf-8").read().strip())


if __name__ == "__main__":
    main()
