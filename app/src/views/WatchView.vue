<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useIceConfig } from '@/composables/useIceConfig'

const route = useRoute()
const router = useRouter()
const { iceServers, ensureIceReady } = useIceConfig()

/* ============================================================
 *  常量
 * ============================================================ */
const CLIENT_ID = Math.random().toString(36).slice(2, 10)
const WS_BASE = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host
const PING_INTERVAL = 25000       // 25 秒心跳
const RECONNECT_BASE = 1500       // 重连基础延迟
const RECONNECT_MAX = 10000       // 重连最大延迟

/* ============================================================
 *  响应式状态
 * ============================================================ */
const roomId = ref('')
const inputRoom = ref('')
const joined = ref(false)

const status = ref('idle')        // idle | connecting | waiting | connected | failed | disconnected
const hasMedia = ref(false)
const playing = ref(false)
const muted = ref(true)
const showControls = ref(true)

const videoEl = ref(null)

/* ============================================================
 *  非响应式变量
 * ============================================================ */
let ws = null
let pc = null
let pendingIce = []                // ICE 候选缓存（远程描述还没设置时）
let pingTimer = null
let reconnectTimer = null
let reconnectAttempts = 0
let currentRoom = ''
let intentionalClose = false
let hideControlsTimer = null
let wakeLock = null

/* ============================================================
 *  计算属性
 * ============================================================ */
const statusLabel = computed(() => {
    const map = {
        idle: '',
        connecting: '连接中…',
        waiting: '等待主播…',
        connected: '已连接',
        failed: '连接失败',
        disconnected: '已断开',
    }
    return map[status.value] || ''
})

const dotClass = computed(() => ({
    ok: status.value === 'connected',
    warn: status.value === 'connecting' || status.value === 'waiting',
    err: status.value === 'failed' || status.value === 'disconnected',
}))

const canRetry = computed(() =>
    status.value === 'failed' || status.value === 'disconnected'
)

/* ============================================================
 *  工具函数
 * ============================================================ */
function getVideo() {
    return videoEl.value || document.getElementById('remoteVideo')
}

async function unlockAudio() {
    /* 在用户手势里创建一个空的 AudioContext 并播放，解锁音频输出 */
    try {
        const AC = window.AudioContext || window.webkitAudioContext
        if (!AC) return
        const ctx = new AC()
        if (ctx.state === 'suspended') ctx.resume()
        const buf = ctx.createBuffer(1, 1, 22050)
        const src = ctx.createBufferSource()
        src.buffer = buf
        src.connect(ctx.destination)
        src.start(0)
        setTimeout(() => {
            try { ctx.close() } catch (e) { /* ignore */ }
        }, 300)
    } catch (e) {
        /* ignore */
    }
}

async function tryAutoPlay() {
    const v = getVideo()
    if (!v) return
    try {
        v.muted = false
        v.volume = 1
        await v.play()
        playing.value = true
        muted.value = false
    } catch (e) {
        /* 带声音自动播放被拦截 → 先静音播，让用户点按钮取消静音 */
        try {
            v.muted = true
            await v.play()
            playing.value = true
            muted.value = true
        } catch (e2) {
            playing.value = false
        }
    }
}

async function userPlay() {
    unlockAudio()
    const v = getVideo()
    if (!v) return
    v.muted = false
    v.volume = 1
    try {
        await v.play()
        playing.value = true
        muted.value = false
    } catch (e) {
        playing.value = false
    }
}

async function toggleMute() {
    const v = getVideo()
    if (!v) return
    v.muted = !v.muted
    muted.value = v.muted
    if (!v.muted) {
        try { await v.play() } catch (e) { /* ignore */ }
    }
}

/* ============================================================
 *  控制条自动隐藏
 * ============================================================ */
function scheduleHideControls() {
    clearTimeout(hideControlsTimer)
    if (!playing.value) return
    hideControlsTimer = setTimeout(() => {
        showControls.value = false
    }, 3500)
}

function toggleControls() {
    if (!playing.value) return
    showControls.value = !showControls.value
    if (showControls.value) scheduleHideControls()
}

/* ============================================================
 *  屏幕常亮
 * ============================================================ */
async function requestWakeLock() {
    try {
        if ('wakeLock' in navigator) {
            wakeLock = await navigator.wakeLock.request('screen')
            wakeLock.addEventListener('release', () => { wakeLock = null })
        }
    } catch (e) { /* ignore */ }
}

function releaseWakeLock() {
    if (wakeLock) {
        try { wakeLock.release() } catch (e) { /* ignore */ }
        wakeLock = null
    }
}

/* ============================================================
 *  全屏
 * ============================================================ */
async function toggleFullscreen() {
    try {
        const el = document.documentElement
        const v = getVideo()

        if (!document.fullscreenElement) {
            if (el.requestFullscreen) {
                await el.requestFullscreen()
            } else if (el.webkitRequestFullscreen) {
                el.webkitRequestFullscreen()
            } else if (v && v.webkitEnterFullscreen) {
                v.webkitEnterFullscreen()
            }
            /* 安卓横屏 */
            try {
                if (screen.orientation && screen.orientation.lock) {
                    await screen.orientation.lock('landscape')
                }
            } catch (e) { /* ignore */ }
        } else {
            if (document.exitFullscreen) await document.exitFullscreen()
        }
    } catch (e) { /* ignore */ }
}

/* ============================================================
 *  WebSocket 信令
 * ============================================================ */
function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg))
    }
}

function startPing() {
    clearInterval(pingTimer)
    pingTimer = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }))
        }
    }, PING_INTERVAL)
}

function stopPing() {
    clearInterval(pingTimer)
    pingTimer = null
}

/* ============================================================
 *  WebRTC PeerConnection
 * ============================================================ */
function createPeerConnection() {
    const p = new RTCPeerConnection({ iceServers: iceServers.value })

    p.ontrack = event => {
        const v = getVideo()
        if (!v) return

        /* 优先用 e.streams[0]，音视频在同一个 stream 里浏览器才会正确输出声音 */
        const stream = (event.streams && event.streams[0]) || null

        if (stream) {
            if (v.srcObject !== stream) {
                v.srcObject = stream
            }
        } else {
            /* 兜底：手动拼一个 MediaStream */
            let s = v.srcObject
            if (!(s instanceof MediaStream)) {
                s = new MediaStream()
                v.srcObject = s
            }
            s.addTrack(event.track)
        }

        hasMedia.value = true
        tryAutoPlay()
    }

    p.onicecandidate = event => {
        if (event.candidate) {
            send({ type: 'ice', candidate: event.candidate })
        }
    }

    p.onconnectionstatechange = () => {
        if (!pc) return
        const s = pc.connectionState
        if (s === 'connected') {
            status.value = 'connected'
        } else if (s === 'failed') {
            status.value = 'failed'
        } else if (s === 'disconnected') {
            status.value = 'disconnected'
        }
    }

    return p
}

async function handleOffer(sdp) {
    if (!pc) {
        pc = createPeerConnection()
    }

    /* 1. 设置远程 SDP */
    await pc.setRemoteDescription(new RTCSessionDescription(sdp))

    /* 2. 把缓存的 ICE 候选补上 */
    for (const c of pendingIce) {
        try {
            await pc.addIceCandidate(new RTCIceCandidate(c))
        } catch (e) {
            console.warn('[ice] add failed', e)
        }
    }
    pendingIce = []

    /* 3. 生成 answer */
    const answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    send({
        type: 'answer',
        sdp: {
            type: pc.localDescription.type,
            sdp: pc.localDescription.sdp,
        },
    })
}

async function handleRemoteIce(candidate) {
    /* pc 或 remoteDescription 还没准备好 → 缓存起来 */
    if (!pc || !pc.remoteDescription) {
        pendingIce.push(candidate)
        return
    }
    try {
        await pc.addIceCandidate(new RTCIceCandidate(candidate))
    } catch (e) {
        console.warn('[ice] add failed', e)
    }
}

/* ============================================================
 *  关闭资源
 * ============================================================ */
function closePeer() {
    if (pc) {
        try { pc.close() } catch (e) { /* ignore */ }
        pc = null
    }
    pendingIce = []
    hasMedia.value = false
    playing.value = false
    muted.value = true

    const v = getVideo()
    if (v) v.srcObject = null
}

function closeWs() {
    stopPing()
    if (ws) {
        try { ws.close() } catch (e) { /* ignore */ }
        ws = null
    }
}

function cleanup() {
    stopPing()
    clearTimeout(reconnectTimer)
    reconnectTimer = null
    closeWs()
    closePeer()
    releaseWakeLock()
    clearTimeout(hideControlsTimer)
}

/* ============================================================
 *  自动重连
 * ============================================================ */
function scheduleReconnect() {
    clearTimeout(reconnectTimer)
    if (!currentRoom || intentionalClose) return

    const delay = Math.min(
        RECONNECT_BASE * Math.pow(2, reconnectAttempts),
        RECONNECT_MAX
    )
    reconnectAttempts++

    console.log(`[ws] 将在 ${delay}ms 后重连（第 ${reconnectAttempts} 次）`)

    reconnectTimer = setTimeout(() => {
        if (currentRoom && !intentionalClose) {
            joinInternal(currentRoom)
        }
    }, delay)
}

/* ============================================================
 *  加入房间
 * ============================================================ */
function joinInternal(room) {
    closeWs()
    closePeer()
    status.value = 'connecting'

    /* 预热视频元素（iOS 需要用户手势后才能真正播放） */
    const v = getVideo()
    if (v) {
        v.muted = true
        v.play().catch(() => { })
    }

    const url = `${WS_BASE}/ws/${encodeURIComponent(room)}/viewer/${CLIENT_ID}`
    ws = new WebSocket(url)

    ws.onopen = () => {
        reconnectAttempts = 0
        status.value = 'waiting'
        startPing()
    }

    ws.onerror = () => {
        console.warn('[ws] error')
    }

    ws.onclose = () => {
        stopPing()
        if (intentionalClose) return
        status.value = 'disconnected'
        closePeer()
        scheduleReconnect()
    }

    ws.onmessage = async event => {
        let msg
        try {
            msg = JSON.parse(event.data)
        } catch (e) {
            return
        }

        if (msg.type === 'offer') {
            try {
                await handleOffer(msg.sdp)
            } catch (e) {
                console.warn('[webrtc] handleOffer failed', e)
                status.value = 'failed'
            }
        } else if (msg.type === 'ice') {
            await handleRemoteIce(msg.candidate)
        } else if (msg.type === 'broadcaster-left') {
            status.value = 'waiting'
            closePeer()
        } else if (msg.type === 'ping') {
            /* 服务端可能回 ping，忽略 */
        }
    }
}

async function join(room) {
    if (!room) return

    console.log('[watch] join 开始，房间:', room)

    currentRoom = room
    intentionalClose = false
    reconnectAttempts = 0

    unlockAudio()

    // ★ 关键：ICE 拉取加超时，失败也继续（最多等 3 秒）
    try {
        await Promise.race([
            ensureIceReady(),
            new Promise(resolve => setTimeout(resolve, 3000)),
        ])
    } catch (e) {
        console.warn('[watch] ICE 就绪检查失败（继续用默认）:', e)
    }

    console.log('[watch] ICE 就绪，实际配置:', iceServers.value)

    joinInternal(room)
}

function leave() {
    intentionalClose = true
    currentRoom = ''
    cleanup()
    status.value = 'idle'
    joined.value = false
}

/* ============================================================
 *  用户操作
 * ============================================================ */
function enter() {
    const r = inputRoom.value.trim()
    if (!r) return
    roomId.value = r
    joined.value = true
    localStorage.setItem('wt:last-room', r)
    join(r)
}

function retry() {
    if (!roomId.value) return
    reconnectAttempts = 0
    join(roomId.value)
}

function goBack() {
    leave()
    if (window.history.length > 1) {
        router.back()
    } else {
        router.push('/')
    }
}

/* ============================================================
 *  从 URL / localStorage 解析房间号
 * ============================================================ */
function pickRoom() {
    /* 优先 route.query（hash 路由时 ?room=xxx 会在这里） */
    if (route.query.room) return String(route.query.room)
    /* 再试 location.search（兼容非 hash 路由） */
    const sp = new URLSearchParams(location.search)
    if (sp.get('room')) return sp.get('room')
    /* 最后从 localStorage 拿 */
    return localStorage.getItem('wt:last-room') || ''
}

/* ============================================================
 *  生命周期
 * ============================================================ */
onMounted(() => {
    const r = pickRoom().trim()
    if (r) {
        roomId.value = r
        inputRoom.value = r
        joined.value = true
        /* 稍等一拍，等 video 元素挂载 */
        setTimeout(() => join(r), 100)
    }
})

onUnmounted(() => {
    intentionalClose = true
    cleanup()
})
</script>

<template>
    <div class="watch">
        <video id="remoteVideo" ref="videoEl" class="video" playsinline webkit-playsinline autoplay
            @click="toggleControls"></video>

        <!-- 顶栏 -->
        <transition name="fade">
            <div v-show="showControls || !playing" class="topbar">
                <button class="icon-btn" @click="goBack" aria-label="返回">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.4"
                        stroke-linecap="round" stroke-linejoin="round">
                        <path d="M15 18l-6-6 6-6" />
                    </svg>
                </button>

                <div class="room-chip">
                    <span class="dot" :class="dotClass"></span>
                    <span class="chip-text">{{ roomId || '未加入' }}</span>
                    <span v-if="statusLabel" class="chip-status">· {{ statusLabel }}</span>
                </div>

                <div style="width:42px"></div>
            </div>
        </transition>

        <!-- 底栏 -->
        <transition name="fade">
            <div v-show="showControls && playing" class="bottombar">
                <button class="icon-btn" @click="toggleMute" aria-label="静音切换">
                    <svg v-if="muted" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
                        stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M11 5L6 9H2v6h4l5 4V5z" />
                        <line x1="23" y1="9" x2="17" y2="15" />
                        <line x1="17" y1="9" x2="23" y2="15" />
                    </svg>
                    <svg v-else viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
                        stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M11 5L6 9H2v6h4l5 4V5z" />
                        <path d="M15.5 8.5a5 5 0 0 1 0 7" />
                        <path d="M19 5a9 9 0 0 1 0 14" />
                    </svg>
                </button>

                <div class="spacer"></div>

                <button class="icon-btn" @click="toggleFullscreen" aria-label="全屏">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.2"
                        stroke-linecap="round" stroke-linejoin="round">
                        <path d="M8 3H5a2 2 0 0 0-2 2v3" />
                        <path d="M21 8V5a2 2 0 0 0-2-2h-3" />
                        <path d="M3 16v3a2 2 0 0 0 2 2h3" />
                        <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
                    </svg>
                </button>
            </div>
        </transition>

        <!-- 取消静音悬浮按钮 -->
        <button v-if="hasMedia && muted && playing" class="unmute-fab" @click="toggleMute">
            🔇 点击开启声音
        </button>

        <!-- 覆盖层 -->
        <transition name="fade">
            <div v-if="!playing" class="overlay">

                <!-- 未加入 -->
                <div v-if="!joined" class="panel">
                    <div class="panel-icon">
                        <svg viewBox="0 0 48 48" width="30" height="30">
                            <path d="M16 12 L36 24 L16 36 Z" fill="currentColor" />
                        </svg>
                    </div>
                    <h2>加入房间</h2>
                    <p class="muted small">输入电脑端显示的房间号</p>
                    <input v-model="inputRoom" type="text" placeholder="房间号" class="panel-input" autocomplete="off"
                        autocapitalize="off" spellcheck="false" @keyup.enter="enter" />
                    <button class="btn-primary" :disabled="!inputRoom.trim()" @click="enter">
                        进入房间
                    </button>
                </div>

                <!-- 已加入但无画面 -->
                <div v-else-if="!hasMedia" class="panel">
                    <div class="spinner" :class="{ err: canRetry }"></div>
                    <p class="panel-text">{{ statusLabel || '等待主播投屏…' }}</p>
                    <button v-if="canRetry" class="btn-primary" @click="retry">
                        重试连接
                    </button>
                    <p v-else class="muted small">请保持此页面打开</p>
                </div>

                <!-- 有画面，需手势播放 -->
                <div v-else class="play-overlay" @click="userPlay">
                    <div class="play-button">
                        <svg viewBox="0 0 48 48" width="40" height="40">
                            <path d="M16 12 L36 24 L16 36 Z" fill="currentColor" />
                        </svg>
                    </div>
                    <p>点击开始播放</p>
                </div>

            </div>
        </transition>
    </div>
</template>

<style scoped>
.watch {
    position: relative;
    width: 100%;
    height: 100%;
    background: #000;
    overflow: hidden;
}

.video {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #000;
}

/* ============ 顶栏 ============ */
.topbar {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    padding: calc(env(safe-area-inset-top, 0px) + 12px) 14px 12px;
    display: flex;
    align-items: center;
    gap: 12px;
    background: linear-gradient(180deg, rgba(0, 0, 0, .7), transparent);
    z-index: 5;
}

.room-chip {
    flex: 1;
    min-width: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    background: rgba(0, 0, 0, .4);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, .1);
    border-radius: 999px;
    padding: 8px 14px;
    font-size: 13px;
}

.chip-text {
    font-weight: 600;
    letter-spacing: .02em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: #fff;
}

.chip-status {
    color: var(--fg-2, #94a3b8);
    font-size: 12px;
    white-space: nowrap;
}

.dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #64748b;
    flex: none;
}

.dot.ok {
    background: #22c55e;
    box-shadow: 0 0 8px #22c55e;
}

.dot.warn {
    background: #f59e0b;
    box-shadow: 0 0 8px #f59e0b;
    animation: blink 1.4s infinite;
}

.dot.err {
    background: #ff4d6d;
    box-shadow: 0 0 8px #ff4d6d;
}

@keyframes blink {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: .35;
    }
}

/* ============ 底栏 ============ */
.bottombar {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 12px 16px calc(env(safe-area-inset-bottom, 0px) + 14px);
    display: flex;
    align-items: center;
    gap: 12px;
    background: linear-gradient(0deg, rgba(0, 0, 0, .75), transparent);
    z-index: 5;
}

.spacer {
    flex: 1;
}

/* ============ 通用按钮 ============ */
.icon-btn {
    width: 42px;
    height: 42px;
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background: rgba(0, 0, 0, .45);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, .1);
    color: #fff;
    font-size: 18px;
    transition: transform .15s, background .15s;
}

.icon-btn:active {
    transform: scale(.92);
    background: rgba(255, 255, 255, .14);
}

.btn-primary {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    color: #fff;
    border: none;
    border-radius: 14px;
    padding: 15px 20px;
    font-size: 15px;
    font-weight: 600;
    font-family: inherit;
    cursor: pointer;
    box-shadow: 0 12px 30px -8px rgba(124, 107, 255, .7);
    transition: transform .15s;
}

.btn-primary:active {
    transform: scale(.98);
}

.btn-primary:disabled {
    opacity: .5;
    box-shadow: none;
    cursor: not-allowed;
}

/* ============ 覆盖层 ============ */
.overlay {
    position: absolute;
    inset: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    background:
        radial-gradient(800px 400px at 50% 0%, rgba(124, 107, 255, .18), transparent 60%),
        rgba(0, 0, 0, .75);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
}

.panel {
    width: 100%;
    max-width: 340px;
    background: rgba(255, 255, 255, .04);
    border: 1px solid rgba(255, 255, 255, .08);
    border-radius: 22px;
    padding: 26px 22px;
    text-align: center;
    display: flex;
    flex-direction: column;
    gap: 14px;
    box-shadow: 0 30px 60px -20px rgba(0, 0, 0, .7), inset 0 1px 0 rgba(255, 255, 255, .05);
}

.panel h2 {
    margin: 4px 0 0;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -.01em;
    color: #f1f5f9;
}

.panel p {
    margin: 0;
    color: #f1f5f9;
}

.panel .muted {
    color: #94a3b8;
}

.panel .small {
    font-size: 12px;
}

.panel-icon {
    width: 60px;
    height: 60px;
    margin: 0 auto;
    border-radius: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    color: #fff;
    box-shadow: 0 12px 30px -8px rgba(124, 107, 255, .7);
}

.panel-input {
    width: 100%;
    background: rgba(0, 0, 0, .35);
    border: 1px solid rgba(255, 255, 255, .08);
    color: #f1f5f9;
    border-radius: 12px;
    padding: 14px 16px;
    font-size: 16px;
    font-family: inherit;
    outline: none;
    text-align: center;
    letter-spacing: .04em;
    transition: border-color .2s, background .2s;
}

.panel-input:focus {
    border-color: #7c6bff;
    background: rgba(124, 107, 255, .08);
}

.panel-text {
    color: #f1f5f9;
    font-size: 15px;
    font-weight: 500;
}

.spinner {
    width: 42px;
    height: 42px;
    margin: 8px auto;
    border-radius: 50%;
    border: 3px solid rgba(124, 107, 255, .18);
    border-top-color: #7c6bff;
    animation: spin .9s linear infinite;
}

.spinner.err {
    border-color: rgba(255, 77, 109, .2);
    border-top-color: #ff4d6d;
    animation: none;
}

@keyframes spin {
    to {
        transform: rotate(360deg);
    }
}

/* ============ 播放按钮 ============ */
.play-overlay {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 14px;
    cursor: pointer;
    padding: 20px;
}

.play-button {
    width: 84px;
    height: 84px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    color: #fff;
    animation: ripple 2s infinite;
}

.play-overlay p {
    margin: 0;
    color: #fff;
    font-size: 15px;
    font-weight: 600;
}

@keyframes ripple {
    0% {
        box-shadow: 0 20px 50px -10px rgba(124, 107, 255, .8),
            0 0 0 0 rgba(124, 107, 255, .55);
    }

    100% {
        box-shadow: 0 20px 50px -10px rgba(124, 107, 255, .8),
            0 0 0 30px rgba(124, 107, 255, 0);
    }
}

/* ============ 取消静音悬浮按钮 ============ */
.unmute-fab {
    position: absolute;
    right: 16px;
    bottom: calc(env(safe-area-inset-bottom, 0px) + 20px);
    z-index: 20;
    padding: 12px 20px;
    border-radius: 30px;
    background: #ff4d6d;
    color: #fff;
    border: none;
    font-family: inherit;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 8px 24px -6px rgba(255, 77, 109, .6);
    animation: pulse 1.6s infinite;
}

@keyframes pulse {

    0%,
    100% {
        transform: scale(1);
    }

    50% {
        transform: scale(1.04);
    }
}

/* ============ 过渡 ============ */
.fade-enter-active,
.fade-leave-active {
    transition: opacity .22s ease;
}

.fade-enter-from,
.fade-leave-to {
    opacity: 0;
}
</style>