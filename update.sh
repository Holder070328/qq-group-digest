#!/usr/bin/env bash
# USTC飞跃群2027 · 摘要与提醒 —— 拉取最新档案
cd "$(dirname "$0")" || exit 1
echo "正在从 GitHub 同步最新档案..."
if git pull --ff-only; then
  echo "[√] 已是最新。"
else
  echo "[x] 同步失败：检查是否安装 git、本地是否有未提交改动、网络能否访问 github.com"
fi
