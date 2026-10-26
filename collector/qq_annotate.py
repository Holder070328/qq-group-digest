#!/usr/bin/env python
"""qq_annotate.py — 给摘要里的行话加「课本式」脚注。

正文里在术语后面标上标数字（¹²³…），正文下方按号码列出解释：

    - 【招生】10-20 NUS CDE¹/ISEM² 李在乐组招³ 2027 Fall⁴ 全奖⁵博士，DDL⁶ 1.15

    ---
    📖 注释
    ¹ NUS CDE：新加坡国立大学 设计与工程学院
    ² ISEM：NUS 工业系统工程与管理系
    ...

规则：
  · 每个术语在每份文件里只标第一次出现
  · 幂等：重复运行不会叠加（会先清掉旧的上标与旧的注释段再重建）
  · 跳过 H1 标题行；跳过已有的「📖 名词小抄」段落

用法:
    python qq_annotate.py <file.md|目录>
    python qq_annotate.py <file.md> --style comment    # 旧的 HTML 注释风格
    python qq_annotate.py <file.md> --dry
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
SUP = "⁰¹²³⁴⁵⁶⁷⁸⁹"
NOTE_HEAD = "📖 注释"
NOTE_SPLIT = "\n---\n\n"


def sup(n: int) -> str:
    return "".join(SUP[int(d)] for d in str(n))


def load_terms():
    try:
        return json.load(open(GLOSSARY, encoding="utf-8")).get("terms", [])
    except Exception:
        return []


def _canon(name):
    return re.split(r"[（(/]", name)[0].strip()


def strip_notes(text):
    """去掉上一次生成的注释段和正文里的上标数字（幂等的前置清理）。"""
    # 1) 去掉尾部注释段
    marker = NOTE_SPLIT + NOTE_HEAD
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    # 2) 去掉上标字符
    text = re.sub(f"[{SUP}]+", "", text)
    return text


def annotate_footnote(text, terms):
    """按「正文出现顺序」编号的课本式脚注。"""
    text = strip_notes(text)
    body = text.rstrip("\n")
    lines = body.split("\n")
    head_idx = next((i for i, l in enumerate(lines) if l.startswith("# ")), None)

    # 1) 收集每个术语在正文里第一次有效出现的位置
    cands = {}
    for t in terms:
        name, pat, say = t.get("name"), t.get("pat"), t.get("say")
        if not name or not pat or not say:
            continue
        try:
            rx = re.compile(pat, re.I)
        except re.error:
            continue
        for m in rx.finditer(body):
            start, end = m.span()
            canon = _canon(name)
            matched = body[start:end]
            if canon.startswith(matched) and len(canon) > len(matched):
                rest = canon[len(matched):]
                if body[end:end + len(rest)] == rest:
                    end += len(rest)
            line_start = body.rfind("\n", 0, start) + 1
            if body[line_start:].startswith("# "):
                continue
            if SKIP_HEADING in body[:start][-400:]:
                continue
            if canon not in cands or start < cands[canon][0]:
                cands[canon] = (start, end, say)
            break

    if not cands:
        return body + "\n", 0

    # 2) 按出现位置排序 → 顺序编号
    ordered = sorted(cands.items(), key=lambda kv: kv[1][0])

    # 3) 从后往前插入上标，避免位置错乱
    for idx, (canon, (start, end, say)) in reversed(list(enumerate(ordered, 1))):
        body = body[:end] + sup(idx) + body[end:]

    notes = "\n".join(f"{sup(i)} {canon}：{say}" for i, (canon, (_, _, say)) in enumerate(ordered, 1))
    body = body + NOTE_SPLIT + NOTE_HEAD + "\n" + notes
    return body + "\n", len(ordered)


def annotate_comment(text, terms):
    """旧风格：HTML 注释（渲染时不显示）。"""
    lines = text.split("\n")
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
            canon = _canon(name)
            matched = text[start:end]
            if canon.startswith(matched) and len(canon) > len(matched):
                rest = canon[len(matched):]
                if text[end:end + len(rest)] == rest:
                    end += len(rest)
            if text[end:end + 40].startswith("<!--"):
                break
            before = text[:start]
            if before.rfind("<!--") > before.rfind("-->"):
                continue
            line_start = text.rfind("\n", 0, start) + 1
            if text[line_start:].startswith("# "):
                continue
            if SKIP_HEADING in before[-400:]:
                continue
            text = text[:end] + f"<!--{name}：{say}-->" + text[end:]
            n += 1
            break
    return text, n


def process(path, style="footnote", dry=False):
    text = open(path, encoding="utf-8").read()
    if style == "comment":
        new, n = annotate_comment(text, load_terms())
    else:
        new, n = annotate_footnote(text, load_terms())
    if not dry:
        open(path, "w", encoding="utf-8", newline="\n").write(new)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--style", choices=["footnote", "comment"], default="footnote")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    tgt = os.path.abspath(a.target)
    files = ([os.path.join(tgt, f) for f in sorted(os.listdir(tgt)) if f.endswith(".md")]
             if os.path.isdir(tgt) else [tgt])

    total = 0
    for f in files:
        n = process(f, a.style, a.dry)
        total += n
        if n:
            print(f"{'[dry] ' if a.dry else ''}{n:2d} 条脚注  {os.path.basename(f)}")
    print(f"共 {total} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
