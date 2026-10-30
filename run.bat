@echo off
setlocal enabledelayedexpansion
title Sin'X Manual Poster
echo ============================================================
echo   Sin'X Manual Poster (Web Dashboard)
echo ============================================================

cd /d "%~dp0"

:: 1. Cari path Python yang valid
set "PY_CMD="

:: Cek python di PATH
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PY_CMD=python"
)

:: Jika tidak ketemu atau mengarah ke Windows Store stub, cek lokasi instalasi standar Python
if not defined PY_CMD (
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
        set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    ) else if exist "C:\Python313\python.exe" (
        set "PY_CMD=C:\Python313\python.exe"
    ) else if exist "C:\Python312\python.exe" (
        set "PY_CMD=C:\Python312\python.exe"
    )
)

if not defined PY_CMD (
    echo.
    echo [ERROR] Python tidak ditemukan di komputer ini!
    echo Silakan install Python dari https://www.python.org/downloads/
    echo dan pastikan centang opsi "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

:: 2. Cek apakah dependensi (rich, fastapi, uvicorn, playwright) sudah terpasang
"%PY_CMD%" -c "import rich, fastapi, uvicorn, playwright" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [*] Paket library belum terpasang di Python Anda.
    echo [*] Sedang menginstall dependensi otomatis (harap tunggu beberapa menit)...
    echo.
    "%PY_CMD%" -m pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo [ERROR] Gagal menginstall dependensi via pip.
        pause
        exit /b 1
    )
    echo.
    echo [*] Mengunduh browser automation Playwright...
    "%PY_CMD%" -m playwright install chromium firefox
)

:: 3. Jalankan web dashboard
echo.
echo [*] Memulai server di http://localhost:8090...
echo.
"%PY_CMD%" manage.py run-web
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Server berhenti dengan kode error.
    pause
)
