@echo off
chcp 65001 >nul
echo Bot jarayoni qidirilmoqda va to'xtatilmoqda...
for /f "tokens=2" %%i in ('tasklist /nh /fi "imagename eq python.exe" /fi "windowtitle eq Instagram AI Bot*"') do (
    taskkill /pid %%i /f >nul 2>&1
)
taskkill /fi "windowtitle eq Instagram AI Bot*" /f >nul 2>&1
echo [TAYYOR] Bot to'xtatildi.
pause
