@echo off
title NGMC Video Generator - PW
cd /d "%~dp0"
echo Starting NGMC Video Generator on http://localhost:7864 ...
start "" http://localhost:7864
python -m uvicorn main:app --host 127.0.0.1 --port 7864
pause
