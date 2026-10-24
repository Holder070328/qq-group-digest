#!/usr/bin/env python
"""qq_collector.py — 接收 NapCat 的 OneBot 事件上报，只采集指定群的群消息，落 SQLite。

用法:
    python qq_collector.py                # 启动采集服务（127.0.0.1:5700）
    python qq_collector.py --backfill 24  # 从历史接口回填最近 N 小时
    python qq_collector.py --stats        # 打印数据库概况
"""
import argparse
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from paths import CRED, DB, GROUP_ID as _ENV_GROUP_ID


def _group_id():
    """白名单群号：优先读凭据文件，兜底写死的默认值。"""
    try:
        return int(json.load(open(CRED, encoding="utf-8")).get("group_id") or _ENV_GROUP_ID)
    except Exception:
        return _ENV_GROUP_ID


GROUP_ID = _group_id()          # 白名单群，硬编码兜底
PORT = 5700
_lock = threading.Lock()

SEG_LABEL = {
    "image": lambda d: "[图片]",
    "face": lambda d: "[表情]",
    "mface": lambda d: "[表情]",
    "record": lambda d: "[语音]",
    "video": lambda d: "[视频]",
    "file": lambda d: "[文件:%s]" % (d.get("name") or d.get("file") or ""),
    "reply": lambda d: "[回复]",
    "forward": lambda d: "[转发]",
    "json": lambda d: "[卡片]",
    "xml": lambda d: "[卡片]",
    "markdown": lambda d: "[md]",
    "at": lambda d: "@%s " % (d.get("name") or d.get("qq") or ""),
}


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB, timeout=30)
    con.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            msg_id      INTEGER PRIMARY KEY,
            group_id    INTEGER NOT NULL,
            user_id     INTEGER,
            nickname    TEXT,
            card        TEXT,
            ts          INTEGER,          -- 服务器秒级时间戳
            text        TEXT,             -- 拍平后的可读文本
            segs        TEXT,             -- 原始消息段 JSON
            collected_at INTEGER
        )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ts ON messages(ts)")
    con.commit()
    return con


def flatten(message):
    parts = []
    if isinstance(message, str):
        return message
    for seg in message or []:
        t = seg.get("type")
        d = seg.get("data") or {}
        if t == "text":
            parts.append(d.get("text", ""))
        elif t in SEG_LABEL:
            parts.append(SEG_LABEL[t](d))
        else:
            parts.append("[%s]" % t)
    return "".join(parts).strip()


def save(ev):
    mid = ev.get("message_id")
    if mid is None:
        return False
    text = flatten(ev.get("message"))
    segs = json.dumps(ev.get("message"), ensure_ascii=False)
    sender = ev.get("sender") or {}
    with _lock:
        con = db()
        try:
            cur = con.execute(
                "INSERT OR IGNORE INTO messages(msg_id,group_id,user_id,nickname,card,ts,text,segs,collected_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (mid, GROUP_ID, ev.get("user_id"),
                 sender.get("nickname") or "", sender.get("card") or "",
                 ev.get("time") or int(time.time()),
                 text, segs, int(time.time())))
            con.commit()
            return cur.rowcount > 0
        finally:
            con.close()


HB = os.path.join(os.path.dirname(DB), "heartbeat.json")
_hb = {"events_total": 0, "saved_total": 0, "last_event": 0, "last_saved": 0, "started": int(time.time())}


def heartbeat(ev=None, saved=False):
    """记录管道心跳：收到的全部事件数 vs 白名单命中的消息数。"""
    if ev is not None:
        _hb["events_total"] += 1
        _hb["last_event"] = int(time.time())
        if saved:
            _hb["saved_total"] += 1
            _hb["last_saved"] = int(time.time())
    try:
        os.makedirs(os.path.dirname(HB), exist_ok=True)
        tmp = HB + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_hb, f, ensure_ascii=False)
        os.replace(tmp, HB)
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):   # 静默，避免刷屏
        pass

    def _ok(self, body=b'{"ok":true}'):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n)
            ev = json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            self._ok(b'{"ok":false}')
            return

        try:
            if ev.get("post_type") == "message" and ev.get("message_type") == "group" \
                    and int(ev.get("group_id") or 0) == GROUP_ID:
                added = save(ev)
                heartbeat(ev, added)
                ts = datetime.fromtimestamp(ev.get("time") or time.time()).strftime("%H:%M:%S")
                who = (ev.get("sender") or {}).get("card") or (ev.get("sender") or {}).get("nickname") or ev.get("user_id")
                if added:
                    print(f"[{ts}] {who}: {flatten(ev.get('message'))[:60]}", flush=True)
            else:
                heartbeat(ev, False)
        except Exception as e:
            print("save error:", e, flush=True)

        self._ok()          # 立刻回 200，避免 NapCat 等待超时


def serve():
    print(f"collector listening on 127.0.0.1:{PORT}, group whitelist = {GROUP_ID}", flush=True)
    heartbeat()          # 启动即写一次心跳，便于判断采集器是否刚重启过
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


def api(path):
    cred = json.load(open(CRED, encoding="utf-8"))
    req = urllib.request.Request(cred["api"] + path,
                                 headers={"Authorization": "Bearer " + cred["api_token"]})
    return json.load(urllib.request.urlopen(req, timeout=120))


def backfill(hours):
    """向更早的方向翻页回填。NapCat 的 message_seq 游标取【本页最早那条】。"""
    since = int(time.time()) - hours * 3600
    seq = None
    total = 0
    pages = 0
    while pages < 40:
        pages += 1
        path = f"/get_group_msg_history?group_id={GROUP_ID}&count=5000"
        if seq:
            path += f"&message_seq={seq}"
        try:
            data = api(path)
        except Exception as e:
            print("api error:", e)
            break
        msgs = (data.get("data") or {}).get("messages") or []
        if not msgs:
            break
        msgs.sort(key=lambda m: m.get("message_seq") or 0)
        for m in msgs:
            if (m.get("time") or 0) < since:      # 超出时间窗口的一律不要
                continue
            if save(m):
                total += 1
        oldest_ts = min(m.get("time") or 0 for m in msgs)
        new_seq = msgs[0].get("message_seq")
        if oldest_ts < since or not new_seq or new_seq == seq:
            break
        seq = new_seq
        time.sleep(0.4)
    print(f"backfilled {total} new message(s) from last {hours}h ({pages} page(s))")


def stats():
    con = db()
    rows = con.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM messages").fetchone()
    print("total:", rows[0])
    if rows[1]:
        print("range:", datetime.fromtimestamp(rows[1]), "→", datetime.fromtimestamp(rows[2]))
    print("\nTop senders:")
    for r in con.execute("""SELECT COALESCE(NULLIF(card,''),nickname) n, COUNT(*) c
                            FROM messages GROUP BY n ORDER BY c DESC LIMIT 10"""):
        print(f"  {r[0] or '?':<20} {r[1]}")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    if a.stats:
        stats()
    elif a.backfill:
        backfill(a.backfill)
    else:
        serve()
