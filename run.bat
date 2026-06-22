@echo off
:: Đặt tiêu đề cho cửa sổ CMD
title Khởi động Team YOLO Labeling Hub 🏷️

:: Di chuyển tới thư mục chứa file batch này
cd /d "%~dp0"

:: Khởi chạy Cloudflare Tunnel trong cửa sổ CMD mới (sử dụng /k để cửa sổ không tự đóng giúp người dùng lấy URL)
echo [SYSTEM] Đang khởi động Cloudflare Tunnel...
start "Cloudflare Tunnel" cmd /k "title Cloudflare Tunnel && cloudflared tunnel --url http://localhost:5000"

:: Khởi chạy PowerShell script bypass Execution Policy để chạy không bị chặn
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
