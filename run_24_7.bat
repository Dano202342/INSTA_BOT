@echo off
title Instagram AI Bot (24/7 Auto-Restart)
chcp 65001 >nul
echo ========================================================
echo   Instagram Downloader & AI Bot (24/7 Ishga Tushirildi)
echo ========================================================
echo.

:loop
echo [%date% %time%] Bot ishga tushirilmoqda...
python -u main.py
echo.
echo [%date% %time%] OGOHLANTIRISH: Bot to'xtadi yoki xatolik yuz berdi.
echo 3 soniyadan so'ng avtomatik qayta yurgiziladi...
timeout /t 3 /nobreak >nul
goto loop
