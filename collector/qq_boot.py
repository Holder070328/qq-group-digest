#!/usr/bin/env python
"""qq_boot.py — 一次性把 QQ 采集链路拉起来（可放进开机/登录启动）。

顺序：NapCat（含 QQ）→ 等接口就绪 → 采集器。
已在运行的部分会跳过。

用法: python qq_boot.py
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

PY = sys.executable
from paths import WORKSPACE as WS
CTL = os.path.join(WS, "tools", "napcat_ctl.py")
COL = os.path.join(WS, "tools", "qq_collector.py")
COLLOG = os.path.join(WS, "qq", "collector.log")
BOOTLOG = os.path.join(WS, "qq", "boot.log")


def log(msg):
    os.makedirs(os.path.dirname(BOOTLOG), exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(BOOTLOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def port_open(port):
    with socket.socket() as s:
        s.settimeout(1.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def api_ok():
    try:
        cred = json.load(open(os.path.join(WS, "qq", "napcat_credentials.json"), encoding="utf-8"))
        req = urllib.request.Request(cred["api"] + "/get_login_info",
                                     headers={"Authorization": "Bearer " + cred["api_token"]})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r).get("retcode") == 0
    except Exception:
        return False


def main():
    log("boot start")

    # 1) NapCat —— 端口不通就强制重启（可能残留一个"没有钩子的 QQ"）
    if not port_open(3000):
        log("napcat not listening -> restart (kill stale QQ, relaunch with hook)")
        subprocess.run([PY, CTL, "restart"], capture_output=True, text=True)
    else:
        log("napcat already up")

    # 2) 等登录就绪（最多 90 秒）
    for i in range(30):
        if api_ok():
            log(f"napcat api ready after {i * 3}s")
            break
        time.sleep(3)
    else:
        log("WARN napcat api not ready in 90s (可能需要扫码登录)")

    # 3) 采集器
    if not port_open(5700):
        log("collector not listening -> start")
        os.makedirs(os.path.dirname(COLLOG), exist_ok=True)
        f = open(COLLOG, "ab")
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        subprocess.Popen([PY, COL], stdout=f, stderr=subprocess.STDOUT,
                         cwd=WS, creationflags=flags)
        time.sleep(3)
        log("collector started" if port_open(5700) else "ERROR collector failed to bind 5700")
    else:
        log("collector already up")

    log("boot done")


if __name__ == "__main__":
    main()
