@echo off
cd /d "%~dp0"
echo.
echo ==============================================
echo   DengeERP Pilot - http://0.0.0.0:5050
echo ==============================================
echo.
echo Bu pencere acik kaldigi surece pilot sunucu calisir.
echo Durdurmak icin CTRL+C kullanin.
echo.
dotnet run --urls "http://0.0.0.0:5050"
pause
