#!/usr/bin/env python
"""qq_watchdog.py — 看门狗：每 5 分钟检查采集链路，断了就自动拉起来。

分级处理（2026-11 起）：
  ① 只有采集器（5700）掉线、NapCat（3000）还活着
     → 只重启采集器（计划任务 HermesQQCollector），**不碰 QQ**
       因为杀 QQ 会触发重新登录、历史消息重放，代价大得多
  ② NapCat 也掉线 → 走整链重启（计划任务 HermesQQBoot）

健康时**不输出任何内容**（cron 侧静默）。
修复成功 → 输出一句「已自动恢复」；修复失败/连续失败 → 输出告警并停止重试。

状态: qq/watchdog_state.json
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

WS = r"D:\Hermes\profiles\muelsyse-us\workspace"
PY = sys.executable
BOOT = os.path.join(WS, "tools", "qq_boot.py")
CRED = os.path.join(WS, "qq", "napcat_credentials.json")
STATE = os.path.join(WS, "qq", "watchdog_state.json")

MAX_ATTEMPTS_PER_HOUR = 3
TASK_ALL = "HermesQQBoot"        # NapCat + 采集器
TASK_COL = "HermesQQCollector"   # 只启采集器


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


def run_task(name):
    try:
        r = subprocess.run(["schtasks", "/run", "/tn", name],
                           capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def wait_port(port, tries=12, gap=2):
    for _ in range(tries):
        time.sleep(gap)
        if port_open(port):
            return True
    return False


def main():
    p3000 = port_open(3000)
    api = api_ok() if p3000 else False
    p5700 = port_open(5700)
    if p3000 and api and p5700:
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

    # ---------- ① 只掉采集器：温和处理，不动 QQ ----------
    if p3000 and api and not p5700:
        st["attempts"].append(now)
        save_state(st)
        if run_task(TASK_COL) and wait_port(5700):
            print("🔧 采集器掉线，已单独重启（QQ 没动，不用重新登录）。")
            return 0
        print("⚠️ 采集器单独重启没成功，改走整链重启…")

    # ---------- ② 整链重启 ----------
    if now not in st["attempts"]:
        st["attempts"].append(now)
        save_state(st)

    started = run_task(TASK_ALL)
    if not started:
        try:
            subprocess.run([PY, BOOT], capture_output=True, text=True, timeout=300)
        except Exception:
            pass

    if wait_port(3000, tries=20, gap=3) and wait_port(5700, tries=1, gap=0):
        print("🔧 采集链路断过，看门狗已自动重启恢复（NapCat + 采集器）。")
        return 0

    print("⚠️ 采集链路断了，看门狗重启失败。可能需要扫码登录，或 QQ 被限制了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
