@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================
echo  USTC飞跃群2027 · 摘要与提醒
echo  正在从 GitHub 同步最新档案...
echo ================================
git pull --ff-only
if errorlevel 1 (
  echo.
  echo [x] 同步失败。常见原因：
  echo     1. 本机没装 git —— 去 https://git-scm.com/downloads 装一个
  echo     2. 本地改过文件导致冲突 —— 先 git status 看看
  echo     3. 网络不通 —— 需要能访问 github.com
) else (
  echo.
  echo [√] 已是最新。
)
echo.
pause
