@echo off
setlocal EnableDelayedExpansion

set "NO_PAUSE=0"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

title Dung Team YOLO Labeling Hub

echo ==========================================================
echo               Dung Team YOLO Labeling Hub
echo ==========================================================
echo.

echo [INFO] Dang dung Tailwind CSS va Cloudflare Tunnel...
taskkill /fi "windowtitle eq YOLO_Tailwind_Tunnel" /t /f >nul 2>&1
taskkill /f /im cloudflared.exe >nul 2>&1
echo [OK] Da dung Tailwind CSS va Cloudflare Tunnel.

echo [INFO] Dang tim tien trinh dang lang nghe tren cong 5000...
set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000" ^| findstr "LISTENING"') do (
    set "FOUND=1"
    echo [INFO] Tim thay tien trinh PID %%a. Dang tat...
    taskkill /PID %%a /F >nul 2>&1
    if !errorlevel! == 0 (
        echo [OK] Da tat tien trinh PID %%a.
    ) else (
        echo [CANH BAO] Khong the tat tien trinh PID %%a.
    )
)

if "!FOUND!"=="0" (
    echo [INFO] Khong tim thay tien trinh nao dang chay tren cong 5000.
)

if "%NO_PAUSE%"=="1" (
    endlocal & exit /b 0
)

endlocal

echo.
echo ----------------------------------------------------------
echo Nhan phim bat ky de dong cua so nay...
pause >nul
