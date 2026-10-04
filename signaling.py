"""
一起看 · 信令服务器
"""
import os
import socket
import sys
from pathlib import Path
from typing import Dict

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


# ============================================================
# 资源路径（兼容 PyInstaller）
# ============================================================
def resource_path(rel):
    # type: (str) -> Path
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / rel
    return Path(__file__).parent / rel


def find_dist_dir():
    # type: () -> Path
    candidates = [
        resource_path("app/dist"),
        resource_path("web/dist"),
        resource_path("frontend/dist"),
        resource_path("dist"),
    ]
    for p in candidates:
        if (p / "index.html").exists():
            return p
    return candidates[0]


DIST_DIR = find_dist_dir()
ASSETS_DIR = DIST_DIR / "assets"


# ============================================================
# FastAPI
# ============================================================
app = FastAPI(title="一起看 · 信令服务器")

# ★★★ 删掉 CORSMiddleware！它会拦截 WebSocket 导致 403 ★★★
# app.add_middleware(CORSMiddleware, ...)   ← 这行不要了

rooms = {}  # type: Dict[str, dict]


# ============================================================
# HTTP 路由
# ============================================================
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


@app.get("/")
async def index():
    index_file = DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse(
        status_code=503,
        content={"error": "前端未构建", "hint": "cd app && npm run build"},
    )


@app.get("/favicon.ico")
async def favicon():
    f = DIST_DIR / "favicon.ico"
    if f.exists():
        return FileResponse(f)
    return JSONResponse({}, status_code=404)


@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "rooms": len(rooms),
        "dist_ready": DIST_DIR.exists(),
    }


@app.get("/api/lanip")
async def lan_ip():
    ip = "127.0.0.1"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        pass
    finally:
        s.close()
    return JSONResponse({"ip": ip})


# ============================================================
# WebSocket 信令
# ============================================================
async def _safe_send(ws, payload):
    # type: (WebSocket, dict) -> None
    try:
        await ws.send_json(payload)
    except Exception:
        pass


async def _cleanup(room_id, role, client_id, ws):
    # type: (str, str, str, WebSocket) -> None
    room = rooms.get(room_id)
    if not room:
        return

    if role == "broadcaster":
        if room.get("broadcaster") is ws:
            room["broadcaster"] = None
        for v in list(room["viewers"].values()):
            await _safe_send(v, {"type": "broadcaster-left"})
    else:
        room["viewers"].pop(client_id, None)
        if room.get("broadcaster"):
            await _safe_send(
                room["broadcaster"],
                {"type": "viewer-left", "viewerId": client_id},
            )

    if room.get("broadcaster") is None and not room["viewers"]:
        rooms.pop(room_id, None)


@app.websocket("/ws/{room_id}/{role}/{client_id}")
async def signaling(ws: WebSocket, room_id: str, role: str, client_id: str):
    # ★ 加了类型注解（WebSocket, str, str, str），更规范
    print("[ws] 新连接 room={} role={} client={}".format(room_id, role, client_id))

    await ws.accept()
    print("[ws] ✅ 连接已 accept")

    room = rooms.setdefault(room_id, {"broadcaster": None, "viewers": {}})

    if role == "broadcaster":
        old = room.get("broadcaster")
        if old is not None and old is not ws:
            try:
                await old.close()
            except Exception:
                pass
        room["broadcaster"] = ws
        for vid in list(room["viewers"].keys()):
            await _safe_send(ws, {"type": "viewer-joined", "viewerId": vid})
        print("[ws] broadcaster 就位，当前观众数={}".format(len(room["viewers"])))
    else:
        room["viewers"][client_id] = ws
        if room.get("broadcaster"):
            await _safe_send(
                room["broadcaster"],
                {"type": "viewer-joined", "viewerId": client_id},
            )
        print("[ws] viewer 就位，观众总数={}".format(len(room["viewers"])))

    try:
        while True:
            msg = await ws.receive_json()

            if msg.get("type") == "ping":
                continue

            if role == "broadcaster":
                target = room["viewers"].get(msg.get("viewerId"))
                if target:
                    await _safe_send(target, msg)
            else:
                bc = room.get("broadcaster")
                if bc:
                    await _safe_send(bc, {**msg, "viewerId": client_id})
    except WebSocketDisconnect:
        print("[ws] 客户端断开 room={} role={}".format(room_id, role))
    except Exception as e:
        print("[ws] error: {!r}".format(e))
    finally:
        await _cleanup(room_id, role, client_id, ws)


# ============================================================
# 直接运行
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    uvicorn.run(app, host="0.0.0.0", port=port)