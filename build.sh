#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

pyinstaller --noconfirm --clean \
  --name "watch-together" \
  --windowed \
  --add-data "ui:ui" \
  --add-data "signaling.py:." \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on \
  desktop.py

echo "✅ 打包完成，见 dist/watch-together/"
