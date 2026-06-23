@echo off
setlocal EnableDelayedExpansion

:: Đặt tiêu đề cho cửa sổ CMD
title Khởi động lại Team YOLO Labeling Hub

:: Di chuyển tới thư mục chứa file batch này
cd /d "%~dp0"

echo ==========================================================
echo          Khởi động lại Team YOLO Labeling Hub
echo ==========================================================
echo.

:: Bước 1: Tắt server cũ và tunnel (nếu đang chạy)
echo [BƯỚC 1] Đang tắt server cũ và Cloudflare Tunnel...
taskkill /IM cloudflared.exe /F >nul 2>&1
net stop "cloudflared" >nul 2>&1
net stop "CloudflareTunnel" >nul 2>&1

set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000" ^| findstr "LISTENING"') do (
    set "FOUND=1"
    echo [INFO] Tìm thấy tiến trình PID: %%a. Đang tắt...
    taskkill /PID %%a /F >nul 2>&1
)

if "!FOUND!"=="0" (
    echo [INFO] Không có server nào đang chạy.
) else (
    echo [OK] Đã tắt server cũ.
    :: Chờ 1 giây để cổng được giải phóng hoàn toàn
    timeout /t 1 /nobreak >nul
)

echo.

:: Bước 2: Khởi chạy lại server
echo [BƯỚC 2] Đang khởi chạy lại server...
echo ----------------------------------------------------------

endlocal

:: Gọi run.bat để khởi động lại
call "%~dp0run.bat"
