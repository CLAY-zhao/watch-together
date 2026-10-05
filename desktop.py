"""
CoWatch · 桌面投屏端
启动流程：
    - 开发模式（未打包）：
        · 启动本地 FastAPI 信令
        · 检查 Vite 是否在跑，没有就尝试拉起
        · 加载本地页面
    - 生产模式（PyInstaller 打包后）：
        · 不启动任何本地服务
        · 直接加载 Render 线上页面

开发运行:  python desktop.py
打包:      见 build.bat
"""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

import webview


# ============================================================
# 配置
# ============================================================
HOST = "127.0.0.1"
BACKEND_PORT = 8765
VITE_PORT = 5173

# ★★★ 线上地址 —— 打包后 exe 加载这里 ★★★
# 把下面域名改成你自己的 Render 域名
ONLINE_ORIGIN = "https://watch-together-t10x.onrender.com"
ONLINE_URL = ONLINE_ORIGIN + "/#/broadcast"

APP_TITLE = "CoWatch · 一起看"


# ============================================================
# 基础工具
# ============================================================
def app_root():
    # type: () -> Path
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def wait_server(host, port, timeout=15.0):
    # type: (str, int, float) -> bool
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def is_dev_mode():
    # type: () -> bool
    """打包后返回 False；未打包返回 True"""
    if hasattr(sys, "_MEIPASS"):
        return False
    if os.environ.get("WT_MODE", "").lower() == "prod":
        return False
    return True


# ============================================================
# Vite 探测 & 启动（仅开发模式用）
# ============================================================
def find_web_dir():
    # type: () -> Optional[Path]
    root = app_root()
    candidates = [
        root / "app",
        root / "web",
        root / "frontend",
    ]
    for p in candidates:
        if (p / "package.json").exists():
            return p
    return None


def find_npm():
    # type: () -> Optional[str]
    for name in ("npm.cmd", "npm"):
        path = shutil.which(name)
        if path:
            return path
    return None


def kill_proc(proc):
    # type: (Optional[subprocess.Popen]) -> None
    if not proc:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception as e:
        print("[warn] close process failed: {}".format(e))


def start_vite(npm_path, cwd, port):
    # type: (str, Path, int) -> subprocess.Popen
    log_path = cwd / "vite.dev.log"
    log_file = open(str(log_path), "w", encoding="utf-8", errors="ignore")

    cmd = [npm_path, "run", "dev", "--", "--port", str(port), "--strictPort"]

    kwargs = dict(
        cwd=str(cwd),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    print("[start] vite: {}".format(" ".join(cmd)))
    print("        cwd: {}".format(cwd))

    return subprocess.Popen(cmd, **kwargs)


# ============================================================
# 决定加载哪个 URL
# ============================================================
def resolve_web_url(backend_port):
    # type: (int) -> Tuple[str, Optional[subprocess.Popen]]
    """
    返回 (要加载的 URL, Vite 进程或 None)
    """
    dev_mode = is_dev_mode()
    backend_url = "http://{}:{}/#/broadcast".format(HOST, backend_port)

    # ---------- 生产模式：直接加载线上地址 ----------
    if not dev_mode:
        print("[mode] production - loading online url")
        print("       {}".format(ONLINE_URL))
        return ONLINE_URL, None

    # ---------- 开发模式 ----------
    web_dir = find_web_dir()
    if web_dir is None:
        print("[warn] no frontend project found")
        print("       falling back to online url")
        return ONLINE_URL, None

    print("[mode] development - web dir: {}".format(web_dir))
    dist_ready = (web_dir / "dist" / "index.html").exists()
    force_vite = os.environ.get("WT_FORCE_VITE", "") == "1"

    # 1) 已经在跑 Vite → 直接用
    if wait_server(HOST, VITE_PORT, 0.5):
        print("[vite] detected running vite at :{}".format(VITE_PORT))
        return "http://{}:{}/#/broadcast".format(HOST, VITE_PORT), None

    # 2) dist 存在且不强制 Vite → 用后端托管 dist
    if dist_ready and not force_vite:
        print("[vite] using dist via local backend")
        return backend_url, None

    # 3) 拉起 Vite
    print("[vite] no dist, trying to start vite...")
    npm = find_npm()
    if not npm:
        print("[warn] npm not found")
        print("       run manually: cd {} && npm run dev".format(web_dir))
        return backend_url, None

    vite_proc = start_vite(npm, web_dir, VITE_PORT)

    if not wait_server(HOST, VITE_PORT, 40.0):
        print("[warn] vite start timeout, see: {}".format(web_dir / "vite.dev.log"))
        kill_proc(vite_proc)
        return backend_url, None

    vite_url = "http://{}:{}/#/broadcast".format(HOST, VITE_PORT)
    print("[vite] ready at {}".format(vite_url))
    return vite_url, vite_proc


# ============================================================
# 本地后端（仅开发模式启动）
# ============================================================
def start_local_backend():
    # type: () -> bool
    """启动本地 FastAPI 信令服务，返回是否成功"""
    try:
        import uvicorn
        from signaling import app as fastapi_app
    except Exception as e:
        print("[error] cannot import signaling/uvicorn: {}".format(e))
        return False

    def run_server():
        uvicorn.run(
            fastapi_app,
            host="0.0.0.0",
            port=BACKEND_PORT,
            log_level="warning",
            access_log=False,
        )

    threading.Thread(target=run_server, daemon=True).start()

    if not wait_server(HOST, BACKEND_PORT, 15.0):
        print("[error] backend start failed (port {})".format(BACKEND_PORT))
        print("        1. port {} might be occupied".format(BACKEND_PORT))
        print("        2. firewall may be blocking")
        return False

    print("[ok] local backend running at http://{}:{}".format(HOST, BACKEND_PORT))
    return True


# ============================================================
# 主入口
# ============================================================
def main():
    dev_mode = is_dev_mode()

    # ---------- 开发模式：启动本地后端 ----------
    if dev_mode:
        if not start_local_backend():
            print("[warn] local backend failed, still trying frontend...")

    # ---------- 决定加载 URL ----------
    url, vite_proc = resolve_web_url(BACKEND_PORT)
    print("[ok] loading page: {}".format(url))
    print()

    # ---------- 打开窗口 ----------
    webview.create_window(
        title=APP_TITLE,
        url=url,
        width=1280,
        height=820,
        min_size=(1024, 680),
        background_color="#0a0b0f",
        text_select=False,
        confirm_close=False,
    )

    try:
        webview.start(debug=dev_mode, http_server=False)
    finally:
        if vite_proc:
            print("[stop] closing vite...")
            kill_proc(vite_proc)


if __name__ == "__main__":
    main()