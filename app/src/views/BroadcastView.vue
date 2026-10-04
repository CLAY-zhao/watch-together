<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useIceConfig } from '@/composables/useIceConfig'

const { iceServers, ensureIceReady } = useIceConfig()

/* ============================================================
 *  常量
 * ============================================================ */
const ICE_SERVERS = [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
    { urls: 'stun:stun.miwifi.com:3478' },
]

const CLIENT_ID = Math.random().toString(36).slice(2, 10)

/* 同源 WS：dev 走 Vite proxy，生产走 127.0.0.1:8765 */
const WS_BASE = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host

/* ============================================================
 *  响应式状态
 * ============================================================ */
const roomId = ref(localStorage.getItem('wt:room') || 'home')
const live = ref(false)
const viewerCount = ref(0)
const useMic = ref(false)
const shareUrl = ref('')
const errorMsg = ref('')
const copied = ref(false)
const hasAudio = ref(false)
const audioLevel = ref(0)
const starting = ref(false)

/* ============================================================
 *  非响应式局部变量
 * ============================================================ */
let bWs = null
let bDisplay = null
let bMic = null
const bPeers = new Map()      // viewerId -> RTCPeerConnection

let audioCtx = null
let analyser = null
let rafId = 0

/* ============================================================
 *  计算属性
 * ============================================================ */
const statusDot = computed(() => {
    if (!live.value) return ''
    if (!hasAudio.value) return 'warn'
    return 'ok'
})

const statusText = computed(() => {
    if (!live.value) return '未开始'
    if (viewerCount.value === 0) return '等待观众'
    return `正在投屏 · ${viewerCount.value} 位观众`
})

/* 音波条高度 */
function barHeight(n) {
    if (!hasAudio.value) return '4%'
    const base = audioLevel.value
    const wave = 0.5 + Math.sin(n / 1.8) * 0.5
    return Math.max(8, Math.min(100, base * (0.6 + wave * 0.6))) + '%'
}

/* ============================================================
 *  音频电平表
 * ============================================================ */
function stopAudioMeter() {
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0 }
    analyser = null
    if (audioCtx) {
        try { audioCtx.close() } catch (e) { /* ignore */ }
        audioCtx = null
    }
    audioLevel.value = 0
}

function startAudioMeter(stream) {
    stopAudioMeter()
    const tracks = stream.getAudioTracks()
    if (!tracks.length) {
        hasAudio.value = false
        return
    }
    hasAudio.value = true
    try {
        const AC = window.AudioContext || window.webkitAudioContext
        audioCtx = new AC()
        if (audioCtx.state === 'suspended') audioCtx.resume()

        const src = audioCtx.createMediaStreamSource(new MediaStream(tracks))
        analyser = audioCtx.createAnalyser()
        analyser.fftSize = 256
        src.connect(analyser)

        const buf = new Uint8Array(analyser.frequencyBinCount)
        const tick = () => {
            if (!analyser) return
            analyser.getByteFrequencyData(buf)
            let sum = 0
            for (let i = 0; i < buf.length; i++) sum += buf[i]
            audioLevel.value = Math.min(100, Math.round((sum / buf.length) * 2.4))
            rafId = requestAnimationFrame(tick)
        }
        tick()
    } catch (e) {
        console.warn('[audio meter]', e)
    }
}

/* ============================================================
 *  分享链接
 * ============================================================ */
async function buildShareUrl() {
    // 公网部署：直接用当前域名
    // 本地开发：如果 /api/lanip 返回了真实 IP，用它（局域网共享给手机）
    let base = location.origin

    // 只在本地 loopback 时才尝试替换为 LAN IP
    if (location.hostname === '127.0.0.1' || location.hostname === 'localhost') {
        try {
            const r = await fetch('/api/lanip')
            const { ip } = await r.json()
            if (ip && ip !== '127.0.0.1') {
                base = `${location.protocol}//${ip}:${location.port || 80}`
            }
        } catch (e) { /* ignore */ }
    }

    shareUrl.value = `${base}/#/watch?room=${encodeURIComponent(roomId.value)}`
}

function onRoomChange() {
    localStorage.setItem('wt:room', roomId.value)
    buildShareUrl()
}

async function copyShare() {
    if (!shareUrl.value) return
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(shareUrl.value)
        } else {
            /* 兜底：老浏览器 / 非安全上下文 */
            const ta = document.createElement('textarea')
            ta.value = shareUrl.value
            ta.style.position = 'fixed'
            ta.style.opacity = '0'
            document.body.appendChild(ta)
            ta.select()
            document.execCommand('copy')
            document.body.removeChild(ta)
        }
        copied.value = true
        setTimeout(() => (copied.value = false), 1500)
    } catch (e) {
        console.warn('copy failed', e)
    }
}

/* ============================================================
 *  WebSocket 信令
 * ============================================================ */
function sendB(obj) {
    if (bWs && bWs.readyState === WebSocket.OPEN) {
        bWs.send(JSON.stringify(obj))
    }
}

function closePeer(vid) {
    const pc = bPeers.get(vid)
    if (pc) {
        try { pc.close() } catch (e) { /* ignore */ }
        bPeers.delete(vid)
    }
    viewerCount.value = bPeers.size
}

function closeAllPeers() {
    for (const vid of [...bPeers.keys()]) closePeer(vid)
}

async function makeOffer(vid) {
    closePeer(vid)

    console.log('[webrtc] 为新观众创建 PC, ICE:', iceServers.value)
    const pc = new RTCPeerConnection({ iceServers: iceServers.value })
    bPeers.set(vid, pc)
    viewerCount.value = bPeers.size

    const stream = new MediaStream([
        ...bDisplay.getTracks(),
        ...(bMic ? bMic.getTracks() : []),
    ])
    stream.getTracks().forEach(t => pc.addTrack(t, stream))

    pc.onicecandidate = e => {
        if (e.candidate) {
            sendB({ type: 'ice', viewerId: vid, candidate: e.candidate })
        }
    }
    pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
            closePeer(vid)
        }
    }

    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    sendB({
        type: 'offer',
        viewerId: vid,
        sdp: { type: pc.localDescription.type, sdp: pc.localDescription.sdp },
    })
}

function connectWs() {
    const url = `${WS_BASE}/ws/${encodeURIComponent(roomId.value)}/broadcaster/${CLIENT_ID}`
    bWs = new WebSocket(url)

    bWs.onmessage = async ev => {
        let msg
        try { msg = JSON.parse(ev.data) } catch (e) { return }

        if (msg.type === 'viewer-joined') {
            try { await makeOffer(msg.viewerId) }
            catch (e) { console.warn('makeOffer failed', e) }
        } else if (msg.type === 'answer') {
            const pc = bPeers.get(msg.viewerId)
            if (pc) {
                try {
                    await pc.setRemoteDescription(new RTCSessionDescription(msg.sdp))
                    const pending = pc._pendingIce || []
                    pc._pendingIce = []
                    for (const c of pending) {
                        try { await pc.addIceCandidate(new RTCIceCandidate(c)) } catch (e) { }
                    }
                } catch (e) { console.warn('setRemote answer failed', e) }
            }
        } else if (msg.type === 'ice') {
            const pc = bPeers.get(msg.viewerId)
            if (pc) {
                if (!pc.remoteDescription) {
                    pc._pendingIce = pc._pendingIce || []
                    pc._pendingIce.push(msg.candidate)
                } else {
                    try { await pc.addIceCandidate(new RTCIceCandidate(msg.candidate)) }
                    catch (e) { console.warn('addIce failed', e) }
                }
            }
        } else if (msg.type === 'viewer-left') {
            closePeer(msg.viewerId)
        }
    }

    bWs.onerror = () => {
        console.warn('[ws] error')
    }

    bWs.onclose = () => {
        closeAllPeers()
        /* 还在投屏中 → 自动重连 */
        if (live.value) {
            setTimeout(() => { if (live.value) connectWs() }, 1500)
        }
    }
}

function disconnectWs() {
    if (bWs) {
        try { bWs.close() } catch (e) { /* ignore */ }
        bWs = null
    }
}

/* ============================================================
 *  开始 / 停止 投屏
 * ============================================================ */
async function startBroadcast() {
    if (starting.value || live.value) return
    errorMsg.value = ''
    starting.value = true

    /* 1. 检查 API 支持 */
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
        errorMsg.value = '当前环境不支持屏幕共享，请使用 Chrome/Edge 打开'
        starting.value = false
        return
    }

    /* 2. 请求屏幕共享（含系统音频） */
    try {
        bDisplay = await navigator.mediaDevices.getDisplayMedia({
            video: {
                frameRate: { ideal: 30, max: 60 },
                width: { ideal: 1920 },
                height: { ideal: 1080 },
            },
            audio: {
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false,
            },
        })
    } catch (e) {
        console.warn('getDisplayMedia cancelled', e)
        errorMsg.value = '已取消屏幕共享'
        starting.value = false
        return
    }

    /* 3. 检查是否捕获到系统声音 */
    const audioTracks = bDisplay.getAudioTracks()
    hasAudio.value = audioTracks.length > 0

    /* 4. 可选麦克风 */
    if (useMic.value) {
        try {
            bMic = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                },
            })
        } catch (e) {
            console.warn('麦克风获取失败', e)
            bMic = null
        }
    }

    /* 5. 本地预览 */
    const pv = document.getElementById('previewVideo')
    if (pv) {
        pv.srcObject = new MediaStream([
            ...bDisplay.getTracks(),
            ...(bMic ? bMic.getTracks() : []),
        ])
        pv.play().catch(() => { })
    }

    /* 6. 启动音波表 */
    startAudioMeter(bDisplay)

    /* 7. 用户点浏览器自带的"停止共享"按钮 */
    const videoTrack = bDisplay.getVideoTracks()[0]
    if (videoTrack) {
        videoTrack.addEventListener('ended', () => stopBroadcast())
    }

    /* 8. 开启投屏状态 */
    live.value = true
    starting.value = false
    connectWs()
}

function stopBroadcast() {
    if (!live.value) return

    live.value = false
    hasAudio.value = false

    closeAllPeers()
    disconnectWs()

    if (bDisplay) {
        bDisplay.getTracks().forEach(t => t.stop())
        bDisplay = null
    }
    if (bMic) {
        bMic.getTracks().forEach(t => t.stop())
        bMic = null
    }

    stopAudioMeter()

    const pv = document.getElementById('previewVideo')
    if (pv) pv.srcObject = null

    viewerCount.value = 0
}

/* ============================================================
 *  生命周期
 * ============================================================ */
onMounted(async () => {
    // ICE 拉取失败不阻塞启动
    try {
        await Promise.race([
            ensureIceReady(),
            new Promise(resolve => setTimeout(resolve, 3000)),
        ])
    } catch (e) { /* ignore */ }

    buildShareUrl()
})

onUnmounted(() => {
    stopBroadcast()
    stopAudioMeter()
})
</script>

<template>
    <div class="app">

        <!-- ============ 顶栏 ============ -->
        <header class="topbar">
            <div class="brand">
                <div class="logo">
                    <svg viewBox="0 0 48 48" width="18" height="18">
                        <path d="M16 12 L36 24 L16 36 Z" fill="currentColor" />
                    </svg>
                </div>
                <div class="brand-text">
                    <strong>一起看</strong>
                    <span>投屏端</span>
                </div>
            </div>

            <div class="status">
                <span class="dot" :class="statusDot"></span>
                <span>{{ statusText }}</span>
            </div>

            <div class="spacer"></div>

            <div class="viewer-badge" v-if="live">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                    <circle cx="9" cy="7" r="4" />
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
                <span>{{ viewerCount }} 位观众</span>
            </div>
        </header>

        <!-- ============ 主体 ============ -->
        <main class="main">

            <!-- 预览区 -->
            <section class="preview">
                <video id="previewVideo" autoplay muted playsinline></video>

                <div class="preview-empty" v-if="!live">
                    <div class="ico">📺</div>
                    <p>点击右侧「开始共享屏幕」，选择要投屏的内容</p>
                </div>

                <div class="preview-hud" v-if="live">
                    <div class="meter" :class="{ idle: !hasAudio || audioLevel < 3 }">
                        <i v-for="n in 20" :key="n" :style="{ height: barHeight(n) }"></i>
                    </div>
                    <div class="hud-label">
                        <span class="dot" :class="hasAudio ? 'ok' : 'err'"></span>
                        {{ hasAudio ? '音频正常' : '无音频' }}
                    </div>
                </div>
            </section>

            <!-- 面板 -->
            <aside class="panel">

                <div class="card">
                    <label>房间号</label>
                    <input v-model="roomId" :disabled="live" @change="onRoomChange" spellcheck="false"
                        autocomplete="off" autocapitalize="off" />
                </div>

                <div class="card" v-if="shareUrl">
                    <label>分享链接</label>
                    <div class="share-row">
                        <input :value="shareUrl" readonly />
                        <button class="btn-copy" @click="copyShare">
                            {{ copied ? '✓ 已复制' : '复制' }}
                        </button>
                    </div>
                    <p class="hint">发给她，手机浏览器打开即可观看</p>
                </div>

                <div class="card" v-if="live">
                    <label>系统声音</label>
                    <div class="audio-status">
                        <span class="dot" :class="hasAudio ? 'ok' : 'err'"></span>
                        <span>{{ hasAudio ? '已捕获' : '未捕获，请查看下方提示' }}</span>
                    </div>
                </div>

                <label class="check-row">
                    <input type="checkbox" v-model="useMic" :disabled="live" />
                    <span>同时传输我的麦克风</span>
                </label>

                <button class="btn-main" v-if="!live" :disabled="starting" @click="startBroadcast">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4"
                        stroke-linecap="round" stroke-linejoin="round">
                        <rect x="2" y="3" width="20" height="14" rx="2" />
                        <line x1="8" y1="21" x2="16" y2="21" />
                        <line x1="12" y1="17" x2="12" y2="21" />
                    </svg>
                    {{ starting ? '正在启动…' : '开始共享屏幕' }}
                </button>

                <button class="btn-stop" v-else @click="stopBroadcast">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                        <rect x="6" y="6" width="12" height="12" rx="2" />
                    </svg>
                    停止共享
                </button>

                <div class="tips" v-if="!live">
                    <b>💡 共享技巧</b><br>
                    · 弹窗中选「<b>整个屏幕</b>」<br>
                    · 勾选左下角「<b>分享系统音频</b>」<br>
                    · macOS 需安装 BlackHole 才能捕获系统声
                </div>

                <div class="err" v-if="live && !hasAudio">
                    <b>⚠️ 未捕获到系统声音</b><br>
                    请点击「停止共享」，重新共享时：
                    选「整个屏幕」并勾选「分享系统音频」
                </div>

                <div class="err" v-if="errorMsg && !live">
                    {{ errorMsg }}
                </div>

            </aside>
        </main>
    </div>
</template>

<style scoped>
.app {
    --bg: #0a0b0f;
    --bg-2: #12141a;
    --panel: rgba(255, 255, 255, 0.035);
    --panel-2: rgba(255, 255, 255, 0.06);
    --line: rgba(255, 255, 255, 0.08);
    --fg: #f1f5f9;
    --fg-2: #94a3b8;
    --fg-3: #64748b;
    --accent: #7c6bff;
    --accent-2: #4f8cff;
    --ok: #22c55e;
    --danger: #ff4d6d;
    --warn: #f59e0b;

    height: 100%;
    display: flex;
    flex-direction: column;
    background:
        radial-gradient(900px 500px at 85% -20%, rgba(124, 107, 255, 0.18), transparent 60%),
        radial-gradient(700px 500px at -10% 110%, rgba(79, 140, 255, 0.14), transparent 60%),
        var(--bg);
    color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Microsoft YaHei", sans-serif;
    font-size: 14px;
    overflow: hidden;
    user-select: none;
    -webkit-font-smoothing: antialiased;
}

button {
    font-family: inherit;
    cursor: pointer;
    border: none;
    background: none;
    color: inherit;
}

input {
    font-family: inherit;
}

/* ============ 顶栏 ============ */
.topbar {
    flex: none;
    height: 56px;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 0 18px;
    background: rgba(10, 11, 15, 0.6);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-bottom: 1px solid var(--line);
}

.brand {
    display: flex;
    align-items: center;
    gap: 10px;
}

.logo {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    box-shadow: 0 8px 20px -6px rgba(124, 107, 255, 0.7);
}

.brand-text {
    display: flex;
    flex-direction: column;
    line-height: 1.15;
}

.brand-text strong {
    font-size: 14px;
    font-weight: 700;
    letter-spacing: -0.01em;
}

.brand-text span {
    font-size: 11px;
    color: var(--fg-3);
}

.status {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    border-radius: 999px;
    background: var(--panel);
    border: 1px solid var(--line);
    font-size: 12px;
    color: var(--fg-2);
}

.dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #475569;
    flex: none;
}

.dot.ok {
    background: var(--ok);
    box-shadow: 0 0 8px var(--ok);
    animation: pulse 2s infinite;
}

.dot.warn {
    background: var(--warn);
    box-shadow: 0 0 8px var(--warn);
}

.dot.err {
    background: var(--danger);
    box-shadow: 0 0 8px var(--danger);
}

@keyframes pulse {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: 0.5;
    }
}

.spacer {
    flex: 1;
}

.viewer-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 999px;
    background: var(--panel);
    border: 1px solid var(--line);
    font-size: 12px;
    color: var(--fg-2);
}

.viewer-badge svg {
    color: var(--accent);
}

/* ============ 主体 ============ */
.main {
    flex: 1;
    display: flex;
    min-height: 0;
}

/* 预览区 */
.preview {
    flex: 1;
    position: relative;
    background: #000;
    min-width: 0;
    display: flex;
    align-items: center;
    justify-content: center;
}

.preview video {
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #000;
    display: block;
}

.preview-empty {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    color: var(--fg-3);
    pointer-events: none;
}

.preview-empty .ico {
    font-size: 56px;
    opacity: 0.6;
    animation: float 3s ease-in-out infinite;
}

.preview-empty p {
    font-size: 14px;
}

@keyframes float {

    0%,
    100% {
        transform: translateY(0);
    }

    50% {
        transform: translateY(-6px);
    }
}

.preview-hud {
    position: absolute;
    left: 16px;
    bottom: 16px;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    border-radius: 12px;
    background: rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.08);
}

.meter {
    display: flex;
    align-items: flex-end;
    gap: 2px;
    height: 22px;
    width: 110px;
}

.meter i {
    flex: 1;
    background: var(--ok);
    border-radius: 1px;
    transition: height 0.06s linear;
    min-height: 2px;
}

.meter.idle i {
    background: #475569;
}

.hud-label {
    font-size: 11px;
    color: var(--fg-2);
    display: flex;
    align-items: center;
    gap: 6px;
}

/* 右侧面板 */
.panel {
    width: 340px;
    flex: none;
    border-left: 1px solid var(--line);
    background: rgba(18, 20, 26, 0.6);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    padding: 18px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    overflow-y: auto;
}

.panel::-webkit-scrollbar {
    width: 6px;
}

.panel::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 3px;
}

.card {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.card label {
    font-size: 11px;
    color: var(--fg-3);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 600;
}

.card input {
    background: rgba(0, 0, 0, 0.35);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 11px 13px;
    color: var(--fg);
    font-size: 14px;
    outline: none;
    width: 100%;
    transition: border-color 0.2s, background 0.2s;
}

.card input:focus {
    border-color: var(--accent);
    background: rgba(124, 107, 255, 0.08);
}

.card input:disabled {
    opacity: 0.55;
    cursor: not-allowed;
}

.card .hint {
    font-size: 11px;
    color: var(--fg-3);
    margin-top: -2px;
}

.share-row {
    display: flex;
    gap: 8px;
}

.share-row input {
    flex: 1;
    min-width: 0;
    font-size: 12px;
    color: var(--fg-2);
}

.btn-copy {
    flex: none;
    padding: 0 14px;
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 10px;
    font-size: 12px;
    color: var(--fg);
    transition: all 0.15s;
    white-space: nowrap;
}

.btn-copy:hover {
    background: rgba(124, 107, 255, 0.15);
    border-color: var(--accent);
}

.audio-status {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
}

.check-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 14px;
    cursor: pointer;
    transition: border-color 0.15s;
}

.check-row:hover {
    border-color: rgba(255, 255, 255, 0.16);
}

.check-row input {
    width: 16px;
    height: 16px;
    accent-color: var(--accent);
    cursor: pointer;
}

.check-row span {
    font-size: 13px;
    color: var(--fg);
}

.btn-main,
.btn-stop {
    padding: 15px 20px;
    border-radius: 14px;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.01em;
    transition: all 0.15s;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
}

.btn-main {
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    color: #fff;
    box-shadow: 0 12px 30px -8px rgba(124, 107, 255, 0.7);
}

.btn-main:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 16px 36px -8px rgba(124, 107, 255, 0.8);
}

.btn-main:active:not(:disabled) {
    transform: translateY(0);
}

.btn-main:disabled {
    opacity: 0.6;
    cursor: not-allowed;
    box-shadow: none;
}

.btn-stop {
    background: rgba(255, 77, 109, 0.12);
    border: 1px solid rgba(255, 77, 109, 0.35);
    color: #ff8ba0;
}

.btn-stop:hover {
    background: rgba(255, 77, 109, 0.2);
}

.tips {
    padding: 12px 14px;
    border-radius: 14px;
    background: rgba(245, 158, 11, 0.07);
    border: 1px solid rgba(245, 158, 11, 0.2);
    font-size: 12px;
    line-height: 1.65;
    color: #fcd088;
}

.tips b {
    color: #fbbf24;
}

.err {
    padding: 12px 14px;
    border-radius: 14px;
    background: rgba(255, 77, 109, 0.08);
    border: 1px solid rgba(255, 77, 109, 0.25);
    font-size: 12px;
    line-height: 1.55;
    color: #ffb3c1;
}
</style>