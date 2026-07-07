@echo off
setlocal

title Khoi dong Team YOLO Labeling Hub
cd /d "%~dp0"
set "CF_CONFIG=%~dp0config.yml"

echo ==========================================================
echo              Khoi dong Team YOLO Labeling Hub
echo ==========================================================
echo.

echo [INFO] Kiem tra Cloudflare Tunnel config...
if exist "%CF_CONFIG%" (
    echo [INFO] Cloudflare Tunnel dang dung config: "%CF_CONFIG%"
) else (
    echo [CANH BAO] Khong tim thay file config Cloudflare Tunnel: "%CF_CONFIG%"
)

echo [INFO] Dang khoi dong Tailwind CSS va Cloudflare Tunnel...
start "YOLO_Tailwind_Tunnel" cmd /c "title YOLO_Tailwind_Tunnel && npm run dev -- --tunnel"

echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
