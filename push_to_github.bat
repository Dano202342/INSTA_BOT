@echo off
chcp 65001 >nul
echo ========================================================
echo   GitHub'ga kodni yuklash (https://github.com/Dano202342/INSTA_BOT)
echo ========================================================
echo.
git add .
git commit -m "Yangilanish: Universal media yuklash, MP3 ajratish va xatoliklar tuzatildi"
git push origin main
echo.
echo [TAYYOR] Kod muvaffaqiyatli GitHub'ga yuklandi!
pause
