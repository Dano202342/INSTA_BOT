@echo off
chcp 65001 >nul
echo ========================================================
echo   Bot jarayonlari to'xtatilmoqda...
echo ========================================================

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -and $_.CommandLine -like '*main.py*') -or ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*run_24_7*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('[TOXSTATILDI] PID: ' + $_.ProcessId) }"

echo.
echo [TAYYOR] Barcha bot jarayonlari to'xtatildi.
echo.
pause
