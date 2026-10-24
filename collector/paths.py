#!/usr/bin/env python
"""paths.py — 统一的路径与配置入口。

本仓库是可移植版本：所有路径都从环境变量或用户主目录推导，
不再写死某台机器的绝对路径。

环境变量：
  QQ_WORKSPACE   工作区根目录（默认 ~/qq-workspace）
  NAPCAT_HOME    NapCat 安装目录（默认 ~/napcat/shell）
  QQ_GROUP_ID    采集的目标群号（必填，或写在 napcat_credentials.json 的 group_id）
  QQ_GROUP_NAME  群名，仅用于摘要标题（默认「某高校飞跃群」）
"""
import os

HOME = os.path.expanduser("~")

WORKSPACE = os.environ.get("QQ_WORKSPACE") or os.path.join(HOME, "qq-workspace")

QQDIR = os.path.join(WORKSPACE, "qq")
DB = os.path.join(QQDIR, "messages.db")
CRED = os.path.join(QQDIR, "napcat_credentials.json")
HEARTBEAT = os.path.join(QQDIR, "heartbeat.json")
DIGESTS = os.path.join(QQDIR, "digests")
ARCHIVE = os.path.join(QQDIR, "archive")

NAPCAT_HOME = os.environ.get("NAPCAT_HOME") or os.path.join(HOME, "napcat", "shell")

GROUP_ID = int(os.environ.get("QQ_GROUP_ID") or 1035480173)
GROUP_NAME = os.environ.get("QQ_GROUP_NAME") or "USTC飞跃群2027"

REPO = os.path.join(WORKSPACE, "qq-digest")
