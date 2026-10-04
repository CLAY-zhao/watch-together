"""
一起看 · 桌面投屏端
启动流程：
    1. 后台启动 FastAPI 信令服务（8765+）
    2. 判断运行模式：
       - 开发模式（python desktop.py）：
           · dist 存在 → 后端托管（加载 8765）
           · dist 不存在 → 自动拉起 Vite dev server，加载 5173
       - 生产模式（PyInstaller 打包后）：只用后端托管
    3. PyWebView 打开投屏页面

开发运行:  python desktop.py
强制走 Vite:  set WT_FORCE_VITE=1  (Windows) / export WT_FORCE_VITE=1 (macOS/Linux)
强制走 dist:  set WT_MODE=prod     (Windows) / export WT_MODE=prod    (macOS/Linux)
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

import uvicorn
import webview


HOST = "127.0.0.1"
BACKEND_PORT = 8765       # 固定端口，需与 vite.config.js 的 proxy 一致
VITE_PORT = 5173


# ============================================================
# 基础工具
# ============================================================
def wait_server(host, port, timeout=15.0):
    # type: (str, int, float) -> bool
    """轮询直到端口可连接或超时"""
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
    """是否处于开发模式（非 PyInstaller 打包）"""
    if hasattr(sys, "_MEIPASS"):
        return False
    if os.environ.get("WT_MODE", "").lower() == "prod":
        return False
    return True


# ============================================================
# Vite 项目探测 & 启动
# ============================================================
def find_web_dir():
    # type: () -> Optional[Path]
    """在若干候选目录里找第一个含 package.json 的前端项目"""
    if hasattr(sys, "_MEIPASS"):
        root = Path(sys._MEIPASS)
    else:
        root = Path(__file__).parent

    candidates = [
        root / "app",         # 你的项目名
        root / "web",
        root / "frontend",
        root,                 # 万一根目录就是前端
    ]
    for p in candidates:
        if (p / "package.json").exists():
            return p
    return None


def find_npm():
    # type: () -> Optional[str]
    """跨平台找 npm 可执行文件"""
    for name in ("npm.cmd", "npm"):     # Windows 优先 npm.cmd
        path = shutil.which(name)
        if path:
            return path
    return None


def kill_proc(proc):
    # type: (Optional[subprocess.Popen]) -> None
    """强制结束进程（Windows 会连子进程一起杀）"""
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
        print("⚠️ 关闭进程失败: {}".format(e))


def start_vite(npm_path, cwd, port):
    # type: (str, Path, int) -> subprocess.Popen
    """启动 Vite dev server，日志写到 cwd/vite.dev.log"""
    log_path = cwd / "vite.dev.log"
    log_file = open(str(log_path), "w", encoding="utf-8", errors="ignore")

    cmd = [
        npm_path, "run", "dev", "--",
        "--port", str(port),
        "--strictPort",       # 端口被占用就报错，不自动换
    ]

    kwargs = dict(
        cwd=str(cwd),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    print("🚀 启动 Vite: {}".format(" ".join(cmd)))
    print("   工作目录: {}".format(cwd))
    print("   日志文件: {}".format(log_path))

    return subprocess.Popen(cmd, **kwargs)


# ============================================================
# 决定加载哪个 URL
# ============================================================
def resolve_web_url(backend_port):
    # type: (int) -> Tuple[str, Optional[subprocess.Popen]]
    """
    返回 (要加载的 URL, 需要随窗口关闭一起杀掉的 Vite 进程或 None)
    """
    dev_mode = is_dev_mode()
    backend_url = "http://{}:{}/#/broadcast".format(HOST, backend_port)

    # ---------- 生产模式：直接用后端托管 ----------
    if not dev_mode:
        print("🏭 生产模式：使用后端托管 dist")
        return backend_url, None

    # ---------- 开发模式 ----------
    web_dir = find_web_dir()
    if web_dir is None:
        print("⚠️ 未找到前端项目（找过 app/ web/ frontend/）")
        print("   → 使用后端托管（可能显示 503）")
        return backend_url, None

    print("🔍 前端项目: {}".format(web_dir))
    dist_ready = (web_dir / "dist" / "index.html").exists()
    force_vite = os.environ.get("WT_FORCE_VITE", "") == "1"

    # 1) 已经有 Vite 在跑？直接用
    if wait_server(HOST, VITE_PORT, 0.5):
        print("✅ 检测到 Vite 已在运行 → http://{}:{}".format(HOST, VITE_PORT))
        return "http://{}:{}/#/broadcast".format(HOST, VITE_PORT), None

    # 2) dist 存在且不强制 Vite → 用后端托管
    if dist_ready and not force_vite:
        print("✅ 检测到 dist → {}".format(backend_url))
        return backend_url, None

    # 3) 拉起 Vite
    print("📦 未找到可用 dist，尝试自动启动 Vite…")
    npm = find_npm()
    if not npm:
        print("⚠️ 未找到 npm，请手动启动：")
        print("   cd {} && npm run dev".format(web_dir))
        return backend_url, None

    vite_proc = start_vite(npm, web_dir, VITE_PORT)

    # 等待端口就绪（首次冷启动可能慢一点，给 40 秒）
    if not wait_server(HOST, VITE_PORT, 40.0):
        print("⚠️ Vite 启动超时，检查日志: {}".format(web_dir / "vite.dev.log"))
        kill_proc(vite_proc)
        return backend_url, None

    vite_url = "http://{}:{}/#/broadcast".format(HOST, VITE_PORT)
    print("✅ Vite 已就绪 → {}".format(vite_url))
    return vite_url, vite_proc


# ============================================================
# 主入口
# ============================================================
def main():
    # 延迟导入，确保 PyInstaller 收集依赖
    from signaling import app as fastapi_app

    # ---- 1. 启动后端 ----
    backend_port = BACKEND_PORT

    def run_server():
        uvicorn.run(
            fastapi_app,
            host="0.0.0.0",
            port=backend_port,
            log_level="warning",
            access_log=False,
        )

    threading.Thread(target=run_server, daemon=True).start()

    if not wait_server(HOST, backend_port, 15.0):
        print("❌ 后端启动失败（端口 {} 未监听）".format(backend_port))
        print("   可能原因：")
        print("   1. 端口 {} 已被占用 → 用 netstat -ano | findstr 8765 查".format(backend_port))
        print("   2. 防火墙拦截")
        sys.exit(1)

    print("✅ 后端已启动 → http://{}:{}".format(HOST, backend_port))

    # ---- 2. 决定加载哪个 URL ----
    url, vite_proc = resolve_web_url(backend_port)
    print("🌐 加载页面 → {}".format(url))
    print()

    # ---- 3. 打开 PyWebView 窗口 ----
    webview.create_window(
        title="一起看 · 投屏",
        url=url,
        width=1280,
        height=820,
        min_size=(1024, 680),
        background_color="#0a0b0f",
        text_select=False,
        confirm_close=False,
    )

    try:
        webview.start(debug=is_dev_mode(), http_server=False)
    finally:
        # 窗口关闭 → 顺手杀掉 Vite
        if vite_proc:
            print("🛑 关闭 Vite dev server…")
            kill_proc(vite_proc)


if __name__ == "__main__":
    main()