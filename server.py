"""
一起看 · 极简投屏信令服务器
本地运行:  python server.py
然后浏览器打开:  http://localhost:8000
"""
import socket
from pathlib import Path
from typing import Dict

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="一起看 · 投屏信令服务器")

# room_id -> {"broadcaster": WebSocket | None, "viewers": {client_id: WebSocket}}
rooms: Dict[str, dict] = {}


# ---------- HTTP ----------
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "rooms": len(rooms)}


@app.get("/api/lanip")
async def lan_ip():
    """获取本机局域网 IP，用于生成手机可访问的分享链接"""
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


# ---------- WebSocket 信令 ----------
async def _safe_send(ws: WebSocket, payload: dict):
    try:
        await ws.send_json(payload)
    except Exception:
        pass


async def _cleanup(room_id: str, role: str, client_id: str, ws: WebSocket):
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
            await _safe_send(room["broadcaster"],
                             {"type": "viewer-left", "viewerId": client_id})
    # 房间空了就回收
    if room.get("broadcaster") is None and not room["viewers"]:
        rooms.pop(room_id, None)


@app.websocket("/ws/{room_id}/{role}/{client_id}")
async def signaling(ws: WebSocket, room_id: str, role: str, client_id: str):
    await ws.accept()

    room = rooms.setdefault(room_id, {"broadcaster": None, "viewers": {}})

    if role == "broadcaster":
        # 踢掉旧的 broadcaster
        old = room.get("broadcaster")
        if old is not None and old is not ws:
            try:
                await old.close()
            except Exception:
                pass
        room["broadcaster"] = ws
        # 告诉新来的 broadcaster 房间里已经有哪些观众
        for vid in list(room["viewers"].keys()):
            await _safe_send(ws, {"type": "viewer-joined", "viewerId": vid})
    else:
        room["viewers"][client_id] = ws
        if room.get("broadcaster"):
            await _safe_send(room["broadcaster"],
                             {"type": "viewer-joined", "viewerId": client_id})

    try:
        while True:
            msg = await ws.receive_json()
            if role == "broadcaster":
                # 广播端指定发给哪个观众
                target = room["viewers"].get(msg.get("viewerId"))
                if target:
                    await _safe_send(target, msg)
            else:
                # 观众发来的消息，附带 viewerId 后转给广播端
                bc = room.get("broadcaster")
                if bc:
                    await _safe_send(bc, {**msg, "viewerId": client_id})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[ws] error: {e!r}")
    finally:
        await _cleanup(room_id, role, client_id, ws)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
