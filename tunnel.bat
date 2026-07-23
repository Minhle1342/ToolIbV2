@echo off
title Cloudflare Quick Tunnel (Port 5000)
cd /d "%~dp0"
echo ==========================================================
echo    Dang khoi dong Cloudflare Tunnel (https://localhost:5000)
echo ==========================================================
echo.
cloudflared tunnel --url https://localhost:5000 --no-tls-verify
pause
