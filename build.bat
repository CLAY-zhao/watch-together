@echo off
chcp 65001 >nul
cd /d %~dp0

echo ========================================
echo   Build Frontend
echo ========================================
cd app
call npm install
call npm run build
cd ..

echo.
echo ========================================
echo   Build Python (onefile, no console)
echo ========================================
pyinstaller --noconfirm --clean ^
  --name "CoWatch" ^
  --onefile ^
  --windowed ^
  --noconsole ^
  --uac-admin ^
  --icon=app\public\icon.ico ^
  --add-data "app\dist;app\dist" ^
  --add-data "signaling.py;." ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.loops.asyncio ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.http.h11_impl ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.protocols.websockets.wsproto_impl ^
  --hidden-import uvicorn.protocols.websockets.websockets_impl ^
  --hidden-import uvicorn.lifespan.on ^
  --hidden-import fastapi ^
  --hidden-import starlette ^
  --hidden-import anyio ^
  --hidden-import anyio._backends._asyncio ^
  --hidden-import webview ^
  --hidden-import webview.platforms.edgechromium ^
  --hidden-import webview.platforms.winforms ^
  --hidden-import clr_loader ^
  --hidden-import pythonnet ^
  --collect-all webview ^
  --collect-all clr_loader ^
  --collect-all pythonnet ^
  desktop.py

echo.
echo ========================================
echo   Done
echo   Output: dist\CoWatch.exe
echo ========================================
pause