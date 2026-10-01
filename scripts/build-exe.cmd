@echo off
REM sessionvault.exe を dist\sessionvault\ に作る（PyInstaller の onedir）。
REM exe では保管庫と設定ファイルの既定の場所が exe のあるフォルダになる（docs/design.md §2.1）。
setlocal
cd /d "%~dp0.."

uv run --group build pyinstaller --noconfirm --clean --onedir --console ^
  --name sessionvault --distpath dist --workpath build\pyinstaller --specpath build ^
  "%CD%\scripts\exe_entry.py"
if errorlevel 1 (
  echo.
  echo build failed.
  exit /b 1
)
echo.
echo built: dist\sessionvault\sessionvault.exe
endlocal
