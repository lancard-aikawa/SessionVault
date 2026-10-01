@echo off
REM Build dist\sessionvault\sessionvault.exe (PyInstaller onedir). See docs/design.md section 2.1.
REM The exe uses its own folder for sessionvault.json and vault\ by default. PyInstaller deletes
REM dist\sessionvault\ on every build, so both are moved to build\keep\ and moved back afterwards.
REM Keep this file ASCII only: cmd.exe reads .cmd files as cp932 and breaks on UTF-8 Japanese.
setlocal
cd /d "%~dp0.."
set "OUT=dist\sessionvault"
set "KEEP=build\keep"

if exist "%KEEP%\sessionvault.json" goto :leftover
if exist "%KEEP%\vault" goto :leftover
if not exist "%KEEP%" mkdir "%KEEP%"
if exist "%OUT%\sessionvault.json" move "%OUT%\sessionvault.json" "%KEEP%\" >nul
if exist "%OUT%\vault" move "%OUT%\vault" "%KEEP%\" >nul

uv run --group build pyinstaller --noconfirm --clean --onedir --console ^
  --name sessionvault --distpath dist --workpath build\pyinstaller --specpath build ^
  "%CD%\scripts\exe_entry.py"
set "RC=%errorlevel%"

if not exist "%OUT%" mkdir "%OUT%"
if exist "%KEEP%\sessionvault.json" move "%KEEP%\sessionvault.json" "%OUT%\" >nul
if exist "%KEEP%\vault" move "%KEEP%\vault" "%OUT%\" >nul

if not "%RC%"=="0" (
  echo.
  echo build failed.
  exit /b 1
)
echo.
echo built: %OUT%\sessionvault.exe
exit /b 0

:leftover
echo %KEEP% still holds files from an earlier build. Check them, move them back to %OUT%, then retry.
exit /b 1
