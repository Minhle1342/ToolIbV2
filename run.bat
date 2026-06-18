@echo off
:: Đặt tiêu đề cho cửa sổ CMD
title Khởi động Team YOLO Labeling Hub 🏷️

:: Di chuyển tới thư mục chứa file batch này
cd /d "%~dp0"

:: Khởi chạy PowerShell script bypass Execution Policy để chạy không bị chặn
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
