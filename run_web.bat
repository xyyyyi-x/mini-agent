@echo off
REM 网页版（Gradio）—— 双击即可运行
chcp 65001 >nul
set PYTHONUTF8=1
python -m mini_agent.app
pause
