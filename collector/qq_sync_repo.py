#!/usr/bin/env python
"""qq_sync_repo.py — 把摘要同步进 git 仓库，并提交/推送。

只同步 `digests/`（内容）；`collector/` 里是「可移植版」代码，
**不会被正在运行的版本覆盖**，以免把本机路径、真实群号等带回仓库。

用法:
    python qq_sync_repo.py                 # 同步 + 提交 + 推送
    python qq_sync_repo.py --dry-run       # 只同步和看状态，不提交
    python qq_sync_repo.py --no-push       # 提交但不推送
"""
import argparse
import os
import shutil
import subprocess
import sys

from paths import WORKSPACE as WS

REPO = os.path.join(WS, "qq-digest")
DIGESTS = os.path.join(WS, "qq", "digests")


def run(args, **kw):
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="ignore", **kw)


def sync():
    """只同步摘要；返回已复制的文件数。"""
    n = 0
    for dp, _, fn in os.walk(DIGESTS):
        for f in fn:
            if not f.endswith(".md"):
                continue
            src = os.path.join(dp, f)
            dst = os.path.join(REPO, "digests", os.path.relpath(src, DIGESTS))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            # 统一写成 LF，避免 Windows 的 CRLF 让 git 每天报"有改动"
            with open(src, "rb") as fh:
                data = fh.read().replace(b"\r\n", b"\n")
            with open(dst, "wb") as fh:
                fh.write(data)
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()

    n = sync()
    st = run(["git", "status", "--porcelain"])
    if st.returncode != 0:
        print("git 状态读取失败:", st.stderr[:200])
        return 1
    if not st.stdout.strip():
        return 0          # 没有变化，完全静默

    print(f"同步: {n} 个摘要")
    if a.dry_run:
        return 0

    run(["git", "add", "-A"])
    r = run(["git", "commit", "-m", "chore: 同步摘要"])
    print((r.stdout or r.stderr).strip()[:400])
    if r.returncode != 0:
        return 1

    if not a.no_push:
        p = run(["git", "push"])
        out = (p.stdout or p.stderr).strip()
        print(out[:400])
        if p.returncode != 0:
            print("推送失败——检查 remote、代理与凭据")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
