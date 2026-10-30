@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows_2.ps1"
if errorlevel 1 (
  echo Build failed. Keep this window open and send the error message.
) else (
  echo Build finished. The EXE path is printed above.
)
pause
