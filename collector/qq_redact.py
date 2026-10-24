#!/usr/bin/env python
"""qq_redact.py — 生成用于公开分享的摘要副本。

默认策略（本项目采用）：
  · **保留消息来源**（群名片/昵称、QQ 号），方便回溯原消息
  · 只对手机号、邮箱这类与「来源」无关的隐私项打码

如果确实需要连来源一起隐去（例如要发给群里以外的人），加 `--redact-names`：
  群名片 → 群友01/群友02…，QQ 号 → [QQ]

用法:
    python qq_redact.py                    # 保留来源，只打码手机/邮箱
    python qq_redact.py --redact-names     # 连来源一起隐去
    python qq_redact.py --out /tmp/out     # 指定输出目录
"""
import argparse
import os
import re
import sqlite3

from paths import DB, DIGESTS as SRC

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "digests-public")

PHONE = re.compile(r"1[3-9]\d{9}")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
QQNO = re.compile(r"(?<!\d)[1-9]\d{4,10}(?!\d)")


def name_map():
    """从数据库里取出出现过的群名片/昵称，按出现次数排序，映射成代号。"""
    mapping = {}
    if not os.path.exists(DB):
        return mapping
    con = sqlite3.connect(DB)
    try:
        rows = con.execute("""
            SELECT COALESCE(NULLIF(card,''),nickname) n, COUNT(*) c
            FROM messages GROUP BY n ORDER BY c DESC
        """).fetchall()
    finally:
        con.close()
    idx = 0
    for n, _ in rows:
        n = (n or "").strip()
        if len(n) >= 2 and n not in mapping:
            idx += 1
            mapping[n] = f"群友{idx:02d}"
    return mapping


def redact_text(text, mapping=None, redact_names=False):
    """打码手机号与邮箱；redact_names=True 时连群名片和 QQ 号一起隐去。"""
    if redact_names and mapping:
        for real, fake in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(real, fake)
    text = PHONE.sub("[手机]", text)
    text = EMAIL.sub("[邮箱]", text)
    if redact_names:
        text = QQNO.sub("[QQ]", text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--redact-names", action="store_true",
                    help="连消息来源（群名片/QQ号）一起隐去")
    a = ap.parse_args()

    out = os.path.abspath(a.out)
    mapping = name_map() if a.redact_names else {}
    if a.redact_names:
        print(f"代号表: {len(mapping)} 个群名片 → 群友NN")
    else:
        print("策略: 保留消息来源（群名片/QQ号），仅打码手机与邮箱")

    n = 0
    for dp, _, fn in os.walk(SRC):
        for f in fn:
            if not f.endswith(".md"):
                continue
            src = os.path.join(dp, f)
            rel = os.path.relpath(src, SRC)
            dst = os.path.join(out, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(src, encoding="utf-8") as fh:
                text = fh.read()
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(redact_text(text, mapping, a.redact_names))
            n += 1

    print(f"脱敏完成: {n} 个文件 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
