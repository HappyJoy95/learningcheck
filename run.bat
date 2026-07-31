@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ========================================
echo  学习检查自动化
echo ========================================
echo.

python main.py %*

pause