@echo off
REM 终端版（最稳，不依赖浏览器/端口/防火墙）—— 双击即可运行
chcp 65001 >nul
set PYTHONUTF8=1
python -m mini_agent.cli
pause
