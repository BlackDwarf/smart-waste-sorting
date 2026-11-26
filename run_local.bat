@echo off
chcp 65001 >nul
title 智能垃圾分拣 · 本机原生窗口
cd /d "%~dp0"

echo ============================================
echo   智能垃圾分拣控制台（本机原生窗口）
echo   不需要 Docker、不需要浏览器
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 没有找到 Python，请先安装并勾选 "Add Python to PATH"。
    pause
    exit /b 1
)

python -m tools.run_native %*

if errorlevel 1 (
    echo.
    echo [提示] 如果提示缺少模块，请先执行：
    echo        python -m pip install -r requirements-local.txt
    pause
)
