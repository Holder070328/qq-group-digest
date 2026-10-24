#!/usr/bin/env python
"""napcat_ctl.py — 管理这台机器上的 NapCat（脱离 Hermes 会话独立运行）。

用法:
    python napcat_ctl.py start      # 启动（后台脱离，日志写 logs/napcat_console.log）
    python napcat_ctl.py stop       # 停止
    python napcat_ctl.py restart    # 重启
    python napcat_ctl.py status     # 状态（进程 / 端口 / 登录信息）
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

from paths import NAPCAT_HOME, CRED
BASE = NAPCAT_HOME
QQ = r"C:\Program Files\Tencent\QQNT\QQ.exe"


def _uin() -> str:
    """QQ 号从凭据文件读，换号只改 napcat_credentials.json 的 uin 字段。"""
    try:
        import json as _json
        return str(_json.load(open(CRED, encoding="utf-8")).get("uin") or "")
    except Exception:
        return ""


def _qq_exe() -> str:
    """用哪个客户端跑采集：默认系统安装，可指向 QQ 副本（给小号用）。"""
    try:
        import json as _json
        p = _json.load(open(CRED, encoding="utf-8")).get("qq_exe") or ""
        return p if p and os.path.isfile(p) else QQ
    except Exception:
        return QQ


UIN = _uin()
QQ = _qq_exe()
LOG = os.path.join(BASE, "logs")
CONSOLE = os.path.join(LOG, "napcat_console.log")


def env():
    e = dict(os.environ)
    e.update({
        "NAPCAT_PATCH_PACKAGE": os.path.join(BASE, "qqnt.json"),
        "NAPCAT_LOAD_PATH": os.path.join(BASE, "loadNapCat.js"),
        "NAPCAT_INJECT_PATH": os.path.join(BASE, "NapCatWinBootHook.dll"),
        "NAPCAT_LAUNCHER_PATH": os.path.join(BASE, "NapCatWinBootMain.exe"),
        "NAPCAT_MAIN_PATH": os.path.join(BASE, "napcat.mjs"),
    })
    return e


def procs():
    """只认「采集用的那个客户端」的进程，绝不碰用户自己那份 QQ。"""
    import psutil
    out = []
    qq_path = os.path.normcase(os.path.abspath(QQ))
    for p in psutil.process_iter(["pid", "name", "exe"]):
        n = (p.info["name"] or "").lower()
        if n == "napcatwinbootmain.exe":
            out.append((p.info["pid"], p.info["name"]))
            continue
        if n != "qq.exe":
            continue
        try:
            if os.path.normcase(os.path.abspath(p.info["exe"] or "")) == qq_path:
                out.append((p.info["pid"], p.info["name"]))
        except Exception:
            continue
    return out


def _is_system_qq() -> bool:
    """采集用的客户端是否指向「系统安装的原版 QQ」（用户的日常客户端）。"""
    try:
        p = os.path.normcase(os.path.abspath(QQ))
        return p.startswith(os.path.normcase(r"c:\program files"))
    except Exception:
        return False


def stop(force=False):
    import psutil
    if _is_system_qq() and not force:
        print("REFUSED: 采集客户端指向系统安装的原版 QQ，为保护你的日常客户端，已拒绝操作。\n"
              "         如确需操作，请先把 napcat_credentials.json 的 qq_exe 改成副本，或加 --force。")
        return
    qq_path = os.path.normcase(os.path.abspath(QQ))
    n = 0
    for p in psutil.process_iter(["pid", "name", "exe"]):
        name = (p.info["name"] or "").lower()
        kill = False
        if name == "napcatwinbootmain.exe":
            kill = True
        elif name == "qq.exe":
            try:
                kill = os.path.normcase(os.path.abspath(p.info["exe"] or "")) == qq_path
            except Exception:
                kill = False
        if kill:
            try:
                p.terminate()
                n += 1
            except Exception:
                pass
    time.sleep(3)
    print(f"stopped {n} process(es) of {QQ}")


def start(force=False):
    if _is_system_qq() and not force:
        print("REFUSED: 采集客户端指向系统安装的原版 QQ，已拒绝启动（会把它变成无头）。\n"
              "         请把 napcat_credentials.json 的 qq_exe 改成副本路径。")
        return
    if procs():
        print("already running:", procs())
        return
    os.makedirs(LOG, exist_ok=True)
    # 必须给独立控制台：DETACHED_PROCESS 会让 NapCat 的 Worker 进程 -616 崩溃
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    p = subprocess.Popen(
        [os.path.join(BASE, "NapCatWinBootMain.exe"), QQ,
         os.path.join(BASE, "NapCatWinBootHook.dll"), UIN],
        cwd=BASE, env=env(),
        creationflags=flags,
    )
    print(f"started pid={p.pid} (client={QQ}, uin={UIN})")
    _hide_console_window()


def _hide_console_window(timeout=15):
    """把 NapCat 的控制台窗口藏起来——但它必须存在，关掉会导致进程退出。"""
    if os.name != "nt":
        return
    import ctypes, ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    target = os.path.basename(QQ).lower()
    want = os.path.normcase(os.path.abspath(QQ))
    for _ in range(timeout):
        time.sleep(1)
        hits = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        def cb(h, _l):
            if user32.IsWindowVisible(h):
                n = user32.GetWindowTextLengthW(h)
                if n:
                    b = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(h, b, n + 1)
                    if b.value and (target in b.value.lower()):
                        hits.append(int(h))
            return True

        user32.EnumWindows(cb, 0)
        if hits:
            for h in hits:
                user32.ShowWindow(h, 0)   # SW_HIDE
            return


def api(path):
    cred = json.load(open(CRED, encoding="utf-8"))
    req = urllib.request.Request(
        cred["api"] + path,
        headers={"Authorization": f"Bearer {cred['api_token']}"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def status():
    print("processes:", procs())
    try:
        info = api("/get_login_info")
        print("login:", info)
    except Exception as e:
        print("api:", type(e).__name__, str(e)[:120])
    if os.path.exists(CONSOLE):
        print("console log tail:")
        with open(CONSOLE, "rb") as f:
            data = f.read()[-1200:]
        print(data.decode("utf-8", "ignore"))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    cmd = args[0] if args else "status"
    if cmd == "start":
        start(force=force)
    elif cmd == "stop":
        stop(force=force)
    elif cmd == "restart":
        stop(force=force)
        start(force=force)
    else:
        status()
