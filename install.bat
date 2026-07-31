@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ========================================
echo  学习检查自动化 - 环境安装
echo ========================================
echo.

pip install -r requirements.txt

echo.
echo 安装完成！
pause