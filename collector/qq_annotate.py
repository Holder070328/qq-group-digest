#!/usr/bin/env python
"""qq_annotate.py — 给摘要 Markdown 里的行话就地加注释。

把术语表（glossary.json）里的解释，以 **HTML 注释** 的形式插到术语后面：

    NUS CDE<!--NUS 设计与工程学院--> 李在乐组招 2027 Fall<!--2027 年秋季入学-->

规则：
  · 每个术语在**每份文件里只标注第一次出现**，不重复刷屏
  · 已经是注释里的内容不再标注
  · 跳过「📖 名词小抄」段落（那段本身就是解释）

用法:
    python qq_annotate.py <file.md>          # 就地标注
    python qq_annotate.py <file.md> --dry    # 只看会改什么
    python qq_annotate.py <dir>              # 目录下所有 .md
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    from paths import QQDIR
except Exception:
    QQDIR = os.path.join(os.path.dirname(HERE), "qq")

GLOSSARY = os.path.join(QQDIR, "glossary.json")
SKIP_HEADING = "名词小抄"


def load_terms():
    try:
        return json.load(open(GLOSSARY, encoding="utf-8")).get("terms", [])
    except Exception:
        return []


def _canon(name):
    """把「答辩（项目）」「Fall / 入学季」这类名字取成最短可匹配形式。"""
    n = re.split(r"[（(/]", name)[0].strip()
    return n


def annotate(text, terms):
    """返回 (新文本, 标注数)。每个术语只标第一次出现，且幂等。"""
    lines = text.split("\n")
    head_idx = next((i for i, l in enumerate(lines) if l.startswith("# ")), None)

    n = 0
    for t in terms:
        name, pat, say = t.get("name"), t.get("pat"), t.get("say")
        if not name or not pat or not say:
            continue
        try:
            rx = re.compile(pat, re.I)
        except re.error:
            continue

        for m in rx.finditer(text):
            start, end = m.span()

            # 1) 先把被截断的词补完整（结题 → 结题报告），再判断注释
            canon = _canon(name)
            matched = text[start:end]
            if canon.startswith(matched) and len(canon) > len(matched):
                rest = canon[len(matched):]
                if text[end:end + len(rest)] == rest:
                    end += len(rest)

            # 2) 后面已经跟着注释 → 视为已标注过，整个术语收工
            if text[end:end + 40].startswith("<!--"):
                break
            # 3) 落在已有注释内部 → 跳过
            before = text[:start]
            if before.rfind("<!--") > before.rfind("-->"):
                continue
            # 4) 标题行不标
            line_start = text.rfind("\n", 0, start) + 1
            if text[line_start:].startswith("# "):
                continue
            # 5) 「名词小抄」段落不标
            if SKIP_HEADING in before[-400:]:
                continue

            text = text[:end] + f"<!--{name}：{say}-->" + text[end:]
            n += 1
            break
    return text, n


def process(path, dry=False):
    text = open(path, encoding="utf-8").read()
    if "名词小抄" in text and "<!--" not in text:
        pass
    new, n = annotate(text, load_terms())
    if n and not dry:
        open(path, "w", encoding="utf-8", newline="\n").write(new)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    tgt = os.path.abspath(a.target)
    files = [os.path.join(tgt, f) for f in os.listdir(tgt) if f.endswith(".md")] \
        if os.path.isdir(tgt) else [tgt]

    total = 0
    for f in files:
        n = process(f, a.dry)
        total += n
        if n:
            print(f"{'[dry] ' if a.dry else ''}{n:2d} 处注释  {os.path.basename(f)}")
    print(f"共标注 {total} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
