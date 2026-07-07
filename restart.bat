@echo off
setlocal

title Khoi dong lai Team YOLO Labeling Hub
cd /d "%~dp0"

echo ==========================================================
echo          Khoi dong lai Team YOLO Labeling Hub
echo ==========================================================
echo.

echo [BUOC 1] Dang dung server, Tailwind CSS va Cloudflare Tunnel...
call "%~dp0stop.bat" --no-pause

echo.
echo [BUOC 2] Dang khoi dong lai he thong...
call "%~dp0run.bat"
