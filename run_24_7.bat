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
ping 127.0.0.1 -n 4 >nul
goto loop
