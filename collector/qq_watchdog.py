#!/usr/bin/env python
"""qq_watchdog.py — 看门狗：每 5 分钟检查采集链路，断了就自动拉起来。

健康时**不输出任何内容**（cron 侧静默）。
修复成功 → 输出一句「已自动恢复」；修复失败/连续失败 → 输出告警并停止重试，避免反复杀掉用户的 QQ。

状态: qq/watchdog_state.json
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

from paths import WORKSPACE as WS
PY = sys.executable
BOOT = os.path.join(WS, "tools", "qq_boot.py")
CRED = os.path.join(WS, "qq", "napcat_credentials.json")
STATE = os.path.join(WS, "qq", "watchdog_state.json")
HB = os.path.join(WS, "qq", "heartbeat.json")

MAX_ATTEMPTS_PER_HOUR = 3


def port_open(p):
    with socket.socket() as s:
        s.settimeout(1.5)
        return s.connect_ex(("127.0.0.1", p)) == 0


def api_ok():
    try:
        cred = json.load(open(CRED, encoding="utf-8"))
        req = urllib.request.Request(cred["api"] + "/get_login_info",
                                     headers={"Authorization": "Bearer " + cred["api_token"]})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r).get("retcode") == 0
    except Exception:
        return False


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"attempts": [], "alerted": ""}


def save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)


def main():
    if port_open(3000) and api_ok() and port_open(5700):
        return 0                                  # 健康，静默

    now = int(time.time())
    st = load_state()
    st["attempts"] = [t for t in st.get("attempts", []) if now - t < 3600]

    if len(st["attempts"]) >= MAX_ATTEMPTS_PER_HOUR:
        if st.get("alerted") != time.strftime("%Y-%m-%d %H"):
            print("⚠️ 采集链路一小时里已经试着重启 3 次仍不通。"
                  "可能是 QQ 登录态失效或需扫码，需要你来看一眼。")
            st["alerted"] = time.strftime("%Y-%m-%d %H")
            save_state(st)
        return 0

    st["attempts"].append(now)
    save_state(st)

    # 优先用「任务计划」拉起：进程树归 Task Scheduler 管，不会随本进程退出而被回收
    started = False
    try:
        r = subprocess.run(["schtasks", "/run", "/tn", "HermesQQBoot"],
                           capture_output=True, text=True, timeout=60)
        started = r.returncode == 0
    except Exception:
        started = False
    if not started:
        subprocess.run([PY, BOOT], capture_output=True, text=True, timeout=300)

    # 给 NapCat 一点时间起来
    for _ in range(20):
        time.sleep(3)
        if port_open(3000) and api_ok() and port_open(5700):
            print("🔧 采集链路断过，看门狗已自动重启恢复（NapCat + 采集器）。")
            return 0

    print("⚠️ 采集链路断了，看门狗重启失败。可能需要扫码登录，或 QQ 被限制了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
