@echo off
title Sin'X Manual Poster
echo ============================================================
echo   Starting Sin'X Manual Poster (Web Dashboard)
echo ============================================================

cd /d "%~dp0"
python manage.py run-web
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Gagal menjalankan aplikasi. Pastikan Python sudah terinstall.
    pause
)
