<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useIceConfig } from '@/composables/useIceConfig'
import { getWsBase } from '@/config/backend'
import { Capacitor } from '@capacitor/core'
import { StatusBar } from '@capacitor/status-bar'
import { App as CapApp } from '@capacitor/app'

const route = useRoute()
const router = useRouter()
const { iceServers, ensureIceReady } = useIceConfig()

const isNative = Capacitor.isNativePlatform()

/* 常量 */
const CLIENT_ID = Math.random().toString(36).slice(2, 10)
const WS_BASE = getWsBase()
const PING_INTERVAL = 25000
const RECONNECT_BASE = 1500
const RECONNECT_MAX = 10000

/* 状态 */
const roomId = ref('')
const inputRoom = ref('')
const joined = ref(false)

const status = ref('idle')
const hasMedia = ref(false)
const playing = ref(false)
const muted = ref(true)
const volume = ref(1)
const showControls = ref(true)
const isFullscreen = ref(false)
const needsTapToPlay = ref(false)
const showVolumeBubble = ref(false)

/* ★ 语音通话状态 */
const micEnabled = ref(false)          // 麦克风是否开启
const micConnecting = ref(false)       // 正在连接
const micLevel = ref(0)                // 本地麦克风电平 0-100
const broadcasterVoiceActive = ref(false) // 对方是否在说话
const showVoicePanel = ref(false)      // 语音通话浮层

const videoEl = ref(null)
const stageEl = ref(null)

/* 占位图 */
const placeholderImage = ref('')
const PLACEHOLDER_SEEDS = [
    'cinema', 'neon', 'stars', 'clouds',
    'movie-night', 'theater', 'violet', 'purple-dream',
    'galaxy', 'sunset', 'lights', 'aurora',
]
function pickPlaceholder() {
    const seed = PLACEHOLDER_SEEDS[Math.floor(Math.random() * PLACEHOLDER_SEEDS.length)]
        + '-' + Math.random().toString(36).slice(2, 8)
    return `https://picsum.photos/seed/${seed}/1280/720`
}

/* 非响应式 */
let ws = null
let pc = null
let pendingIce = []
let pingTimer = null
let reconnectTimer = null
let reconnectAttempts = 0
let currentRoom = ''
let intentionalClose = false
let hideTimer = null
let volumeBubbleTimer = null
let wakeLock = null
let backListener = null

/* ★ 语音 */
let audioPc = null
let audioPendingIce = []
let localMicStream = null
let micAnalyser = null
let micAudioCtx = null
let micRaf = 0
let broadcasterAnalyser = null
let broadcasterAudioCtx = null
let broadcasterRaf = 0

/* 手势 */
let touchStartX = 0
let touchStartY = 0
let touchStartTime = 0
let touchStartVolume = 0
let gesture = ''

/* 计算 */
const statusLabel = computed(() => {
    const map = {
        idle: '未连接',
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

const volumeIcon = computed(() => {
    if (muted.value || volume.value === 0) return 'muted'
    if (volume.value < 0.5) return 'low'
    return 'high'
})

/* ============================================================
 *  工具
 * ============================================================ */
function getVideo() {
    return videoEl.value || document.getElementById('remoteVideo')
}

async function unlockAudio() {
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
        setTimeout(() => { try { ctx.close() } catch (e) { } }, 300)
    } catch (e) { }
}

async function tryAutoPlay() {
    const v = getVideo()
    if (!v) return
    try {
        v.muted = false
        v.volume = volume.value
        await v.play()
        playing.value = true
        muted.value = false
        needsTapToPlay.value = false
    } catch (e) {
        try {
            v.muted = true
            await v.play()
            playing.value = true
            muted.value = true
            needsTapToPlay.value = false
        } catch (e2) {
            playing.value = false
            needsTapToPlay.value = true
        }
    }
}

async function userPlay() {
    unlockAudio()
    const v = getVideo()
    if (!v) return
    v.muted = false
    v.volume = volume.value
    try {
        await v.play()
        playing.value = true
        muted.value = false
        needsTapToPlay.value = false
    } catch (e) {
        playing.value = false
    }
}

/* 音量 */
function setVolume(v) {
    v = Math.max(0, Math.min(1, v))
    volume.value = v
    const video = getVideo()
    if (video) {
        video.volume = v
        video.muted = v === 0
    }
    muted.value = v === 0
    localStorage.setItem('wt:volume', String(v))
}

function toggleMute() {
    const video = getVideo()
    if (!video) return
    if (muted.value || volume.value === 0) {
        if (volume.value === 0) setVolume(1)
        else { video.muted = false; muted.value = false }
    } else {
        video.muted = true
        muted.value = true
    }
    scheduleHideControls()
}

/* ============================================================
 *  ★★★ 语音通话 ★★★
 * ============================================================ */
async function toggleMic() {
    if (micEnabled.value) {
        await stopMic()
    } else {
        await startMic()
    }
}

async function startMic() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        alert('尚未连接到房间，请稍后重试')
        return
    }
    micConnecting.value = true
    console.log('[voice] 开始请求麦克风…')

    try {
        /* 1. 请求麦克风 */
        localMicStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
            },
        })
        console.log('[voice] ✅ 麦克风已获取，tracks=', localMicStream.getAudioTracks().length)

        /* 2. 本地电平 */
        startMicMeter(localMicStream)

        /* 3. 创建语音 PC */
        closeAudioPeer()
        audioPc = new RTCPeerConnection({ iceServers: iceServers.value })

        /* 4. 加入麦克风 */
        localMicStream.getTracks().forEach(t => {
            console.log('[voice] 添加 track:', t.kind, t.label)
            audioPc.addTrack(t, localMicStream)
        })

        /* 5. ICE */
        audioPc.onicecandidate = e => {
            if (e.candidate) {
                send({ type: 'ice', channel: 'audio', candidate: e.candidate })
            }
        }

        /* 6. 状态 */
        audioPc.onconnectionstatechange = () => {
            console.log('[voice] state:', audioPc?.connectionState)
            if (audioPc &&
                (audioPc.connectionState === 'failed' ||
                    audioPc.connectionState === 'closed')) {
                stopMic()
            }
        }

        /* 7. 生成 offer */
        const offer = await audioPc.createOffer()
        await audioPc.setLocalDescription(offer)

        const sdpText = audioPc.localDescription.sdp
        console.log('[voice] offer SDP 长度:', sdpText.length)
        console.log('[voice] SDP 里有 audio?', sdpText.includes('m=audio'))
        console.log('[voice] SDP 里有 sendrecv/sendonly?',
            sdpText.match(/a=(sendrecv|sendonly|recvonly)/g))

        send({
            type: 'offer',
            channel: 'audio',
            sdp: {
                type: audioPc.localDescription.type,
                sdp: sdpText,
            },
        })
        console.log('[voice] ✅ offer 已通过 WebSocket 发送')

        micEnabled.value = true
    } catch (e) {
        console.warn('[voice] 开启失败:', e)
        if (e.name === 'NotAllowedError') {
            alert('麦克风权限被拒绝，请在系统设置里允许')
        } else {
            alert('开启语音失败：' + (e.message || e))
        }
        await stopMic()
    } finally {
        micConnecting.value = false
    }
}

async function stopMic() {
    micEnabled.value = false
    micLevel.value = 0
    broadcasterVoiceActive.value = false
    stopMicMeter()
    closeAudioPeer()
    if (localMicStream) {
        localMicStream.getTracks().forEach(t => t.stop())
        localMicStream = null
    }
    console.log('[voice] 麦克风已关闭')
}

function closeAudioPeer() {
    if (audioPc) {
        try { audioPc.close() } catch (e) { }
        audioPc = null
    }
    audioPendingIce = []
}

/* ---------- 本地麦克风电平检测 ---------- */
function startMicMeter(stream) {
    stopMicMeter()
    const tracks = stream.getAudioTracks()
    if (!tracks.length) return
    try {
        const AC = window.AudioContext || window.webkitAudioContext
        micAudioCtx = new AC()
        if (micAudioCtx.state === 'suspended') micAudioCtx.resume()
        const src = micAudioCtx.createMediaStreamSource(new MediaStream(tracks))
        micAnalyser = micAudioCtx.createAnalyser()
        micAnalyser.fftSize = 256
        src.connect(micAnalyser)

        const buf = new Uint8Array(micAnalyser.frequencyBinCount)
        const tick = () => {
            if (!micAnalyser) return
            micAnalyser.getByteFrequencyData(buf)
            let sum = 0
            for (let i = 0; i < buf.length; i++) sum += buf[i]
            micLevel.value = Math.min(100, Math.round((sum / buf.length) * 2.4))
            micRaf = requestAnimationFrame(tick)
        }
        tick()
    } catch (e) {
        console.warn('[mic meter]', e)
    }
}

function stopMicMeter() {
    if (micRaf) { cancelAnimationFrame(micRaf); micRaf = 0 }
    micAnalyser = null
    if (micAudioCtx) {
        try { micAudioCtx.close() } catch (e) { }
        micAudioCtx = null
    }
    micLevel.value = 0
}

/* ---------- 对方语音接收处理 ---------- */
async function handleVoiceAnswer(sdp) {
    if (!audioPc) return
    try {
        await audioPc.setRemoteDescription(new RTCSessionDescription(sdp))
        for (const c of audioPendingIce) {
            try { await audioPc.addIceCandidate(new RTCIceCandidate(c)) } catch (e) { }
        }
        audioPendingIce = []
    } catch (e) {
        console.warn('[voice] 处理 answer 失败:', e)
    }
}

async function handleVoiceIce(candidate) {
    if (!audioPc || !audioPc.remoteDescription) {
        audioPendingIce.push(candidate)
        return
    }
    try { await audioPc.addIceCandidate(new RTCIceCandidate(candidate)) } catch (e) { }
}

/* ============================================================
 *  手势
 * ============================================================ */
function onTouchStart(e) {
    const t = e.touches[0]
    touchStartX = t.clientX
    touchStartY = t.clientY
    touchStartTime = Date.now()
    touchStartVolume = volume.value
    gesture = ''
    clearTimeout(hideTimer)
}

function onTouchMove(e) {
    const t = e.touches[0]
    const dx = t.clientX - touchStartX
    const dy = t.clientY - touchStartY

    if (!gesture) {
        if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return
        if (Math.abs(dy) > Math.abs(dx)) {
            gesture = 'volume'
            showVolumeBubble.value = true
            clearTimeout(volumeBubbleTimer)
        } else {
            gesture = 'ignore'
        }
    }

    if (gesture !== 'volume') return
    if (e.cancelable) e.preventDefault()

    const h = stageEl.value?.clientHeight || window.innerHeight
    const delta = -dy / (h * 0.6)
    setVolume(touchStartVolume + delta)
}

function onTouchEnd(e) {
    if (gesture === 'volume') {
        gesture = ''
        volumeBubbleTimer = setTimeout(() => { showVolumeBubble.value = false }, 500)
        if (isFullscreen.value && showControls.value) scheduleHideControls()
        return
    }
    if (gesture === 'ignore') { gesture = ''; return }

    const dt = Date.now() - touchStartTime
    const t = e.changedTouches[0]
    const moved = Math.hypot(t.clientX - touchStartX, t.clientY - touchStartY)
    if (dt > 300 || moved > 12) return

    if (isFullscreen.value) {
        showControls.value = !showControls.value
        if (showControls.value) scheduleHideControls()
    }
}

function scheduleHideControls() {
    clearTimeout(hideTimer)
    if (!playing.value) return
    hideTimer = setTimeout(() => { showControls.value = false }, 3000)
}

/* ============================================================
 *  WakeLock / 全屏
 * ============================================================ */
async function requestWakeLock() {
    try {
        if ('wakeLock' in navigator) {
            wakeLock = await navigator.wakeLock.request('screen')
            wakeLock.addEventListener('release', () => { wakeLock = null })
        }
    } catch (e) { }
}

function releaseWakeLock() {
    if (wakeLock) { try { wakeLock.release() } catch (e) { } wakeLock = null }
}

async function enterFullscreen() {
    if (isFullscreen.value) return
    isFullscreen.value = true

    if (isNative) {
        try {
            await StatusBar.setOverlaysWebView({ overlay: true })
            await StatusBar.hide()
        } catch (e) { }
        try {
            const { ScreenOrientation } = await import('@capacitor/screen-orientation')
            await ScreenOrientation.lock({ orientation: 'landscape' })
        } catch (e) { }
    } else {
        try {
            const el = document.documentElement
            if (el.requestFullscreen) await el.requestFullscreen()
            if (screen.orientation && screen.orientation.lock) {
                await screen.orientation.lock('landscape')
            }
        } catch (e) { }
    }

    showControls.value = true
    scheduleHideControls()
}

async function exitFullscreen() {
    if (!isFullscreen.value) return
    isFullscreen.value = false
    showControls.value = true

    if (isNative) {
        try {
            await StatusBar.show()
            await StatusBar.setOverlaysWebView({ overlay: false })
        } catch (e) { }
        try {
            const { ScreenOrientation } = await import('@capacitor/screen-orientation')
            await ScreenOrientation.unlock()
        } catch (e) { }
    } else {
        try {
            if (document.fullscreenElement && document.exitFullscreen) {
                await document.exitFullscreen()
            }
            if (screen.orientation && screen.orientation.unlock) {
                screen.orientation.unlock()
            }
        } catch (e) { }
    }
}

function toggleFullscreen() {
    if (isFullscreen.value) exitFullscreen()
    else enterFullscreen()
}

/* ============================================================
 *  WebSocket / WebRTC
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

function createPeerConnection() {
    const p = new RTCPeerConnection({ iceServers: iceServers.value })

    p.ontrack = event => {
        const v = getVideo()
        if (!v) return
        const stream = (event.streams && event.streams[0]) || null
        if (stream) {
            if (v.srcObject !== stream) v.srcObject = stream
        } else {
            let s = v.srcObject
            if (!(s instanceof MediaStream)) { s = new MediaStream(); v.srcObject = s }
            s.addTrack(event.track)
        }
        hasMedia.value = true
        tryAutoPlay()
    }

    p.onicecandidate = event => {
        if (event.candidate) {
            send({ type: 'ice', channel: 'video', candidate: event.candidate })
        }
    }

    p.onconnectionstatechange = () => {
        if (!pc) return
        const s = pc.connectionState
        if (s === 'connected') status.value = 'connected'
        else if (s === 'failed') status.value = 'failed'
        else if (s === 'disconnected') status.value = 'disconnected'
    }

    return p
}

async function handleOffer(sdp) {
    if (!pc) pc = createPeerConnection()
    await pc.setRemoteDescription(new RTCSessionDescription(sdp))
    for (const c of pendingIce) {
        try { await pc.addIceCandidate(new RTCIceCandidate(c)) } catch (e) { }
    }
    pendingIce = []
    const answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    send({
        type: 'answer', channel: 'video',
        sdp: { type: pc.localDescription.type, sdp: pc.localDescription.sdp },
    })
}

async function handleRemoteIce(candidate) {
    if (!pc || !pc.remoteDescription) {
        pendingIce.push(candidate)
        return
    }
    try { await pc.addIceCandidate(new RTCIceCandidate(candidate)) } catch (e) { }
}

function closePeer() {
    if (pc) { try { pc.close() } catch (e) { } pc = null }
    pendingIce = []
    hasMedia.value = false
    playing.value = false
    muted.value = true
    needsTapToPlay.value = false
    const v = getVideo()
    if (v) v.srcObject = null
}

function closeWs() {
    stopPing()
    if (ws) { try { ws.close() } catch (e) { } ws = null }
}

function cleanup() {
    stopPing()
    clearTimeout(reconnectTimer)
    reconnectTimer = null
    clearTimeout(hideTimer)
    hideTimer = null
    clearTimeout(volumeBubbleTimer)
    volumeBubbleTimer = null
    closeWs()
    closePeer()
    stopMic()
    releaseWakeLock()
}

function scheduleReconnect() {
    clearTimeout(reconnectTimer)
    if (!currentRoom || intentionalClose) return
    const delay = Math.min(RECONNECT_BASE * Math.pow(2, reconnectAttempts), RECONNECT_MAX)
    reconnectAttempts++
    reconnectTimer = setTimeout(() => {
        if (currentRoom && !intentionalClose) joinInternal(currentRoom)
    }, delay)
}

function joinInternal(room) {
    closeWs()
    closePeer()
    status.value = 'connecting'

    const v = getVideo()
    if (v) { v.muted = true; v.volume = volume.value; v.play().catch(() => { }) }

    const url = `${WS_BASE}/ws/${encodeURIComponent(room)}/viewer/${CLIENT_ID}`
    ws = new WebSocket(url)

    ws.onopen = () => {
        reconnectAttempts = 0
        status.value = 'waiting'
        startPing()
    }
    ws.onerror = () => console.warn('[ws] error')
    ws.onclose = () => {
        stopPing()
        if (intentionalClose) return
        status.value = 'disconnected'
        closePeer()
        stopMic()
        scheduleReconnect()
    }

    ws.onmessage = async event => {
        let msg
        try { msg = JSON.parse(event.data) } catch (e) { return }
        const channel = msg.channel || 'video'

        if (msg.type === 'offer' && channel === 'video') {
            try { await handleOffer(msg.sdp) } catch (e) { status.value = 'failed' }
        } else if (msg.type === 'ice' && channel === 'video') {
            await handleRemoteIce(msg.candidate)
        } else if (msg.type === 'broadcaster-left') {
            status.value = 'waiting'
            closePeer()
            stopMic()
        } else if (msg.type === 'answer' && channel === 'audio') {
            await handleVoiceAnswer(msg.sdp)
        } else if (msg.type === 'ice' && channel === 'audio') {
            await handleVoiceIce(msg.candidate)
        } else if (msg.type === 'voice-rejected') {
            alert('对方没有开启语音聊天功能')
            stopMic()
        }
    }
}

async function join(room) {
    if (!room) return
    currentRoom = room
    intentionalClose = false
    reconnectAttempts = 0
    unlockAudio()
    try {
        await Promise.race([
            ensureIceReady(),
            new Promise(resolve => setTimeout(resolve, 3000)),
        ])
    } catch (e) { }
    joinInternal(room)
}

function leave() {
    intentionalClose = true
    currentRoom = ''
    cleanup()
    status.value = 'idle'
    joined.value = false
    if (isFullscreen.value) exitFullscreen()
}

/* 用户操作 */
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
    if (isFullscreen.value) { exitFullscreen(); return }
    leave()
    if (window.history.length > 1) router.back()
    else router.push('/')
}

function pickRoom() {
    if (route.query.room) return String(route.query.room)
    const sp = new URLSearchParams(location.search)
    if (sp.get('room')) return sp.get('room')
    return localStorage.getItem('wt:last-room') || ''
}

/* watch */
watch(playing, (isPlaying) => {
    if (isPlaying) {
        requestWakeLock()
        if (isFullscreen.value) scheduleHideControls()
    } else {
        releaseWakeLock()
        showControls.value = true
        clearTimeout(hideTimer)
    }
})

/* 生命周期 */
onMounted(async () => {
    placeholderImage.value = pickPlaceholder()

    const savedVol = localStorage.getItem('wt:volume')
    if (savedVol !== null) {
        const v = parseFloat(savedVol)
        if (!isNaN(v)) volume.value = Math.max(0, Math.min(1, v))
    }

    const r = pickRoom().trim()
    if (r) {
        roomId.value = r
        inputRoom.value = r
        joined.value = true
        setTimeout(() => join(r), 100)
    }

    if (isNative) {
        try {
            backListener = await CapApp.addListener('backButton', ({ canGoBack }) => {
                if (isFullscreen.value) exitFullscreen()
                else if (canGoBack) router.back()
                else CapApp.exitApp()
            })
        } catch (e) { }
    }
})

onUnmounted(async () => {
    intentionalClose = true
    cleanup()
    if (backListener) { backListener.remove(); backListener = null }
    if (isNative) {
        try {
            await StatusBar.show()
            await StatusBar.setOverlaysWebView({ overlay: false })
        } catch (e) { }
        try {
            const { ScreenOrientation } = await import('@capacitor/screen-orientation')
            await ScreenOrientation.unlock()
        } catch (e) { }
    }
})
</script>

<template>
    <div class="watch" :class="{ 'is-fullscreen': isFullscreen }">

        <!-- ==================== 视频舞台 ==================== -->
        <div ref="stageEl" class="stage" @touchstart.passive="onTouchStart" @touchmove="onTouchMove"
            @touchend.passive="onTouchEnd" @touchcancel.passive="onTouchEnd">
            <video id="remoteVideo" ref="videoEl" class="stage__video" playsinline webkit-playsinline autoplay></video>

            <transition name="fade">
                <div v-if="!hasMedia && placeholderImage" class="stage__bg"
                    :style="{ backgroundImage: `url('${placeholderImage}')` }">
                    <div class="stage__bg-overlay"></div>
                </div>
            </transition>

            <transition name="fade">
                <div v-if="!hasMedia && joined" class="stage__boot">
                    <div class="spinner" :class="{ err: canRetry }"></div>
                    <p class="stage__boot-text">{{ statusLabel }}</p>
                    <button v-if="canRetry" class="btn-retry" @click.stop="retry">重试连接</button>
                </div>
            </transition>

            <transition name="pop">
                <button v-if="hasMedia && (!playing || needsTapToPlay)" class="bigplay" @click.stop="userPlay">
                    <svg viewBox="0 0 24 24" width="32" height="32" fill="currentColor">
                        <path d="M8 5.5v13l11-6.5-11-6.5Z" />
                    </svg>
                </button>
            </transition>

            <!-- 音量气泡 -->
            <transition name="pop">
                <div v-if="showVolumeBubble" class="volume-bubble">
                    <div class="volume-bubble__icon">
                        <svg v-if="volumeIcon === 'muted'" viewBox="0 0 24 24" width="22" height="22" fill="none"
                            stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M4 9v6h4l5 4V5L8 9H4Z" />
                            <path d="m17 9 5 6M22 9l-5 6" />
                        </svg>
                        <svg v-else-if="volumeIcon === 'low'" viewBox="0 0 24 24" width="22" height="22" fill="none"
                            stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M4 9v6h4l5 4V5L8 9H4Z" />
                            <path d="M16.5 8.5a5 5 0 0 1 0 7" />
                        </svg>
                        <svg v-else viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M4 9v6h4l5 4V5L8 9H4Z" />
                            <path d="M16.5 8.5a5 5 0 0 1 0 7" />
                            <path d="M19 6a8 8 0 0 1 0 12" />
                        </svg>
                    </div>
                    <div class="volume-bubble__track">
                        <div class="volume-bubble__fill" :style="{ height: (volume * 100) + '%' }"></div>
                    </div>
                    <div class="volume-bubble__value">{{ Math.round(volume * 100) }}</div>
                </div>
            </transition>

            <!-- ============ 全屏顶栏 ============ -->
            <transition name="slide-down">
                <div v-show="isFullscreen && showControls" class="topbar">
                    <button class="iconbtn" @click.stop="goBack">
                        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
                            stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M15 18l-6-6 6-6" />
                        </svg>
                    </button>

                    <div class="topbar__info">
                        <div class="topbar__title">
                            <span class="dot" :class="dotClass"></span>
                            <span class="topbar__room">{{ roomId || '未加入' }}</span>
                            <span v-if="micEnabled" class="mic-badge">🎙 语音中</span>
                            <span v-else-if="broadcasterVoiceActive" class="mic-badge mic-badge--listen">🔊 对方在说</span>
                        </div>
                    </div>

                    <button class="iconbtn" :class="{ 'is-on': !muted }" @click.stop="toggleMute">
                        <svg v-if="volumeIcon === 'muted'" viewBox="0 0 24 24" width="18" height="18" fill="none"
                            stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M4 9v6h4l5 4V5L8 9H4Z" />
                            <path d="m17 9 5 6M22 9l-5 6" />
                        </svg>
                        <svg v-else-if="volumeIcon === 'low'" viewBox="0 0 24 24" width="18" height="18" fill="none"
                            stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M4 9v6h4l5 4V5L8 9H4Z" />
                            <path d="M16.5 8.5a5 5 0 0 1 0 7" />
                        </svg>
                        <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M4 9v6h4l5 4V5L8 9H4Z" />
                            <path d="M16.5 8.5a5 5 0 0 1 0 7" />
                            <path d="M19 6a8 8 0 0 1 0 12" />
                        </svg>
                    </button>
                </div>
            </transition>

            <!-- ============ 全屏底栏 ============ -->
            <transition name="slide-up">
                <div v-show="isFullscreen && showControls" class="bottombar">
                    <div class="bottombar__hint">
                        <span class="hint-icon">↕</span>
                        上下滑动调节音量
                    </div>

                    <div class="spacer"></div>

                    <!-- ★ 全屏时的语音按钮 -->
                    <button class="mic-fab" :class="{ 'mic-fab--on': micEnabled, 'mic-fab--connecting': micConnecting }"
                        @click.stop="toggleMic">
                        <div v-if="micEnabled" class="mic-fab__pulse" :style="{ opacity: micLevel / 150 + 0.4 }"></div>
                        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="9" y="3" width="6" height="12" rx="3" />
                            <path d="M5 11a7 7 0 0 0 14 0" />
                            <line x1="12" y1="18" x2="12" y2="22" />
                            <line x1="8" y1="22" x2="16" y2="22" />
                        </svg>
                        <span class="mic-fab__text">
                            {{ micConnecting ? '连接中' : (micEnabled ? '语音中' : '说话') }}
                        </span>
                    </button>

                    <button class="iconbtn" @click.stop="toggleFullscreen">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />
                        </svg>
                    </button>
                </div>
            </transition>
        </div>

        <!-- ==================== 独立工具栏（竖屏） ==================== -->
        <div v-if="!isFullscreen" class="toolbar">

            <button class="tool" :class="{ 'tool--active': !muted }" @click="toggleMute">
                <div class="tool__icon">
                    <svg v-if="volumeIcon === 'muted'" viewBox="0 0 24 24" width="22" height="22" fill="none"
                        stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M4 9v6h4l5 4V5L8 9H4Z" />
                        <path d="m17 9 5 6M22 9l-5 6" />
                    </svg>
                    <svg v-else-if="volumeIcon === 'low'" viewBox="0 0 24 24" width="22" height="22" fill="none"
                        stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M4 9v6h4l5 4V5L8 9H4Z" />
                        <path d="M16.5 8.5a5 5 0 0 1 0 7" />
                    </svg>
                    <svg v-else viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor"
                        stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M4 9v6h4l5 4V5L8 9H4Z" />
                        <path d="M16.5 8.5a5 5 0 0 1 0 7" />
                        <path d="M19 6a8 8 0 0 1 0 12" />
                    </svg>
                </div>
                <span class="tool__label">{{ muted ? '静音' : '音效' }}</span>
            </button>

            <!-- ★★★ 语音通话按钮 ★★★ -->
            <button class="tool tool--mic" :class="{
                'tool--active': micEnabled,
                'tool--connecting': micConnecting,
            }" @click="toggleMic">
                <div class="tool__icon">
                    <!-- 说话时脉冲光晕 -->
                    <div v-if="micEnabled" class="mic-halo"
                        :style="{ transform: `scale(${1 + micLevel / 200})`, opacity: micLevel / 130 + 0.3 }"></div>
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                        <rect x="9" y="3" width="6" height="12" rx="3" />
                        <path d="M5 11a7 7 0 0 0 14 0" />
                        <line x1="12" y1="18" x2="12" y2="22" />
                        <line x1="8" y1="22" x2="16" y2="22" />
                    </svg>
                </div>
                <span class="tool__label">
                    {{ micConnecting ? '连接中' : (micEnabled ? '语音中' : '语音') }}
                </span>
            </button>

            <button class="tool" @click="toggleFullscreen">
                <div class="tool__icon">
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                        <path
                            d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4" />
                    </svg>
                </div>
                <span class="tool__label">全屏</span>
            </button>

            <button class="tool" @click="goBack">
                <div class="tool__icon">
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                        <path d="M15 18l-6-6 6-6" />
                    </svg>
                </div>
                <span class="tool__label">退出</span>
            </button>
        </div>

        <!-- ★★★ 语音通话浮层（竖屏时显示） ★★★ -->
        <transition name="slide-up">
            <div v-if="micEnabled && !isFullscreen" class="voice-panel">
                <div class="voice-panel__row">
                    <div class="voice-panel__avatar voice-panel__avatar--me">
                        <div class="voice-panel__ring"
                            :style="{ transform: `scale(${1 + micLevel / 150})`, opacity: micLevel / 120 + 0.3 }"></div>
                        <span class="voice-panel__emoji">🎤</span>
                    </div>
                    <div class="voice-panel__info">
                        <div class="voice-panel__name">我</div>
                        <div class="voice-panel__status">{{ micLevel > 8 ? '正在说话…' : '安静' }}</div>
                    </div>
                    <div class="voice-panel__bars">
                        <span v-for="n in 12" :key="n" class="voice-panel__bar" :style="{
                            height: Math.max(4, micLevel * (0.4 + Math.sin(n / 1.5) * 0.4)) + '%',
                        }"></span>
                    </div>
                </div>

                <div class="voice-panel__divider"></div>

                <div class="voice-panel__row">
                    <div class="voice-panel__avatar voice-panel__avatar--other">
                        <span class="voice-panel__emoji">🔊</span>
                    </div>
                    <div class="voice-panel__info">
                        <div class="voice-panel__name">投屏端</div>
                        <div class="voice-panel__status">
                            {{ broadcasterVoiceActive ? '对方正在说话…' : '在线' }}
                        </div>
                    </div>
                    <div class="voice-panel__hint">🎧 建议戴耳机</div>
                </div>
            </div>
        </transition>

        <!-- ==================== 信息面板 ==================== -->
        <section v-show="!isFullscreen" class="panel">
            <div v-if="!joined" class="card">
                <div class="card__icon">
                    <svg viewBox="0 0 48 48" width="26" height="26">
                        <path d="M16 12 L36 24 L16 36 Z" fill="currentColor" />
                    </svg>
                </div>
                <h2 class="card__title">加入房间</h2>
                <p class="card__desc">输入电脑端显示的房间号</p>
                <input v-model="inputRoom" type="text" placeholder="房间号" class="card__input" autocomplete="off"
                    autocapitalize="off" spellcheck="false" @keyup.enter="enter" />
                <button class="btn-primary" :disabled="!inputRoom.trim()" @click="enter">进入房间</button>
            </div>

            <template v-else>
                <div class="card">
                    <div class="card__row">
                        <span class="card__label">房间号</span>
                        <span class="card__value">{{ roomId }}</span>
                    </div>
                    <div class="card__divider"></div>
                    <div class="card__row">
                        <span class="card__label">连接状态</span>
                        <span class="card__value card__value--status">
                            <span class="dot" :class="dotClass"></span>
                            {{ statusLabel }}
                        </span>
                    </div>
                    <div class="card__divider"></div>
                    <div class="card__row">
                        <span class="card__label">语音通话</span>
                        <span class="card__value card__value--status">
                            <span class="dot" :class="micEnabled ? 'ok' : ''"></span>
                            {{ micConnecting ? '连接中…' : (micEnabled ? '已开启' : '未开启') }}
                        </span>
                    </div>
                </div>

                <div v-if="canRetry" class="card card--warn">
                    <div class="card__warn-icon">⚠️</div>
                    <div class="card__warn-body">
                        <div class="card__warn-title">连接已断开</div>
                        <div class="card__warn-text">请检查网络后重试</div>
                    </div>
                    <button class="btn-retry-inline" @click="retry">重试</button>
                </div>

                <div class="tips">
                    <div class="tips__title">使用提示</div>
                    <ul class="tips__list">
                        <li>点底部「<b>语音</b>」按钮，可与对方实时对话</li>
                        <li>说话时按钮会有<b>光晕动效</b>，表示麦克风在工作</li>
                        <li>在画面上<b>上下滑动</b>可调节音量</li>
                        <li>点「全屏」进入沉浸观看，全屏也有语音按钮</li>
                        <li><b>戴耳机</b>可以避免回声</li>
                    </ul>
                </div>
            </template>
        </section>
    </div>
</template>

<style scoped>
/* ============================================================
 *  基础
 * ============================================================ */
.watch {
    position: relative;
    width: 100%;
    min-height: 100vh;
    min-height: 100dvh;
    background: #000;
    display: flex;
    flex-direction: column;
    color: #f1f5f9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Microsoft YaHei", sans-serif;
    overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
    -webkit-tap-highlight-color: transparent;
}

/* ============ 视频舞台 ============ */
.stage {
    position: relative;
    width: 100%;
    aspect-ratio: 16 / 9;
    max-height: 60vh;
    min-height: 200px;
    background: #000;
    overflow: hidden;
    user-select: none;
    touch-action: none;
}

.stage__video {
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #000;
    display: block;
    pointer-events: none;
}

.stage__bg {
    position: absolute;
    inset: 0;
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    background-color: #0a0d12;
    z-index: 1;
    animation: bgZoom 20s ease-in-out infinite alternate;
}

@keyframes bgZoom {
    0% {
        transform: scale(1);
    }

    100% {
        transform: scale(1.06);
    }
}

.stage__bg-overlay {
    position: absolute;
    inset: 0;
    background:
        radial-gradient(ellipse at center, rgba(124, 107, 255, 0.18), transparent 70%),
        linear-gradient(180deg, rgba(0, 0, 0, 0.2) 0%, rgba(0, 0, 0, 0.55) 100%);
}

.stage__boot {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 14px;
    background: rgba(0, 0, 0, 0.45);
    backdrop-filter: blur(3px);
    -webkit-backdrop-filter: blur(3px);
    z-index: 3;
}

.stage__boot-text {
    font-size: 13px;
    color: #94a3b8;
    margin: 0;
}

.spinner {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    border: 3px solid rgba(124, 107, 255, 0.18);
    border-top-color: #7c6bff;
    animation: spin 0.9s linear infinite;
}

.spinner.err {
    border-color: rgba(255, 77, 109, 0.2);
    border-top-color: #ff4d6d;
    animation: none;
}

@keyframes spin {
    to {
        transform: rotate(360deg);
    }
}

.bigplay {
    position: absolute;
    inset: 0;
    margin: auto;
    width: 76px;
    height: 76px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: #0b0b0f;
    background: rgba(255, 255, 255, 0.95);
    box-shadow: 0 12px 40px -10px rgba(0, 0, 0, 0.9),
        0 0 0 8px rgba(124, 107, 255, 0.16);
    padding-left: 4px;
    z-index: 4;
    border: none;
    cursor: pointer;
}

.bigplay:active {
    transform: scale(0.94);
}

/* 音量气泡 */
.volume-bubble {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    z-index: 6;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    padding: 18px 22px;
    border-radius: 20px;
    background: rgba(0, 0, 0, 0.72);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    box-shadow: 0 20px 60px -20px rgba(0, 0, 0, 0.9);
    pointer-events: none;
}

.volume-bubble__icon {
    color: #fff;
}

.volume-bubble__track {
    position: relative;
    width: 6px;
    height: 100px;
    background: rgba(255, 255, 255, 0.2);
    border-radius: 3px;
    display: flex;
    flex-direction: column-reverse;
    overflow: hidden;
}

.volume-bubble__fill {
    width: 100%;
    background: linear-gradient(0deg, #7c6bff, #4f8cff);
    border-radius: 3px;
    transition: height 0.08s linear;
}

.volume-bubble__value {
    font-size: 13px;
    font-weight: 700;
    color: #fff;
    font-variant-numeric: tabular-nums;
    line-height: 1;
}

/* ============ 顶栏 ============ */
.topbar {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    z-index: 10;
    padding: calc(env(safe-area-inset-top, 0px) + 10px) 12px 10px;
    display: flex;
    align-items: center;
    gap: 10px;
    background: linear-gradient(180deg, rgba(0, 0, 0, 0.72), transparent);
    pointer-events: none;
}

.topbar>* {
    pointer-events: auto;
}

.topbar__info {
    flex: 1;
    min-width: 0;
    text-align: center;
}

.topbar__title {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13.5px;
    font-weight: 700;
    color: #fff;
    max-width: 100%;
    overflow: hidden;
}

.topbar__room {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.mic-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 999px;
    background: rgba(34, 197, 94, 0.2);
    color: #86efac;
    font-size: 10.5px;
    font-weight: 700;
    flex: none;
    animation: micBadgePulse 2s ease-in-out infinite;
}

.mic-badge--listen {
    background: rgba(245, 158, 11, 0.2);
    color: #fcd34d;
}

@keyframes micBadgePulse {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: 0.7;
    }
}

/* ============ 底栏 ============ */
.bottombar {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 10;
    padding: 10px 12px calc(env(safe-area-inset-bottom, 0px) + 12px);
    display: flex;
    align-items: center;
    gap: 10px;
    background: linear-gradient(0deg, rgba(0, 0, 0, 0.72), transparent);
    pointer-events: none;
}

.bottombar>* {
    pointer-events: auto;
}

.spacer {
    flex: 1;
}

.bottombar__hint {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    border-radius: 999px;
    background: rgba(0, 0, 0, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.1);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    font-size: 12px;
    color: rgba(255, 255, 255, 0.7);
    pointer-events: none;
}

.hint-icon {
    color: #7c6bff;
    font-weight: 700;
    font-size: 14px;
}

/* ★ 全屏语音按钮 */
.mic-fab {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 18px;
    border-radius: 999px;
    background: rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.15);
    color: #fff;
    font-family: inherit;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
}

.mic-fab:active {
    transform: scale(0.94);
}

.mic-fab--on {
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    border-color: rgba(124, 107, 255, 0.6);
    box-shadow: 0 0 20px rgba(124, 107, 255, 0.6);
}

.mic-fab--connecting {
    background: rgba(245, 158, 11, 0.25);
    border-color: rgba(245, 158, 11, 0.5);
    color: #fcd34d;
    animation: connectingPulse 1s infinite;
}

@keyframes connectingPulse {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: 0.6;
    }
}

.mic-fab__pulse {
    position: absolute;
    inset: -4px;
    border-radius: 999px;
    border: 2px solid rgba(124, 107, 255, 0.7);
    pointer-events: none;
    transition: opacity 0.06s linear;
}

.mic-fab__text {
    position: relative;
    z-index: 1;
}

/* ============ 状态点 ============ */
.dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #64748b;
    flex: none;
    display: inline-block;
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
        opacity: 0.35;
    }
}

/* ============ 图标按钮 ============ */
.iconbtn {
    width: 42px;
    height: 42px;
    flex: none;
    display: grid;
    place-items: center;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.42);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: #fff;
    cursor: pointer;
}

.iconbtn:active {
    transform: scale(0.9);
    background: rgba(255, 255, 255, 0.18);
}

.iconbtn.is-on {
    color: #7c6bff;
    background: rgba(124, 107, 255, 0.18);
    border-color: rgba(124, 107, 255, 0.4);
}

/* ============================================================
 *  工具栏
 * ============================================================ */
.toolbar {
    flex: none;
    display: flex;
    align-items: stretch;
    gap: 6px;
    padding: 12px 14px;
    background: #0a0d12;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.tool {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 12px 4px;
    background: transparent;
    border: none;
    border-radius: 14px;
    color: #94a3b8;
    font-family: inherit;
    cursor: pointer;
    transition: background 0.15s, color 0.2s, transform 0.1s;
}

.tool:active {
    transform: scale(0.96);
    background: rgba(255, 255, 255, 0.06);
}

.tool--active {
    color: #7c6bff;
}

.tool--connecting {
    color: #f59e0b;
}

.tool__icon {
    position: relative;
    width: 40px;
    height: 40px;
    display: grid;
    place-items: center;
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
    transition: background 0.15s, border-color 0.2s, color 0.2s;
}

.tool--active .tool__icon {
    background: rgba(124, 107, 255, 0.15);
    border-color: rgba(124, 107, 255, 0.5);
    box-shadow: 0 0 12px rgba(124, 107, 255, 0.35);
}

.tool--connecting .tool__icon {
    background: rgba(245, 158, 11, 0.15);
    border-color: rgba(245, 158, 11, 0.5);
    animation: connectingPulse 1s infinite;
}

/* 说话时的光晕 */
.mic-halo {
    position: absolute;
    inset: 0;
    border-radius: 12px;
    background: radial-gradient(circle, rgba(124, 107, 255, 0.7) 0%, transparent 70%);
    pointer-events: none;
    transition: transform 0.06s linear, opacity 0.06s linear;
}

.tool__label {
    font-size: 11.5px;
    font-weight: 600;
    letter-spacing: 0.02em;
}

.tool--mic.tool--active .tool__label {
    color: #a99dff;
}

/* ============================================================
 *  ★ 语音通话浮层
 * ============================================================ */
.voice-panel {
    flex: none;
    margin: 0 14px 12px;
    padding: 16px 18px;
    border-radius: 16px;
    background: linear-gradient(135deg,
            rgba(124, 107, 255, 0.12) 0%,
            rgba(79, 140, 255, 0.08) 100%);
    border: 1px solid rgba(124, 107, 255, 0.25);
    display: flex;
    flex-direction: column;
    gap: 12px;
    box-shadow: 0 8px 24px -8px rgba(124, 107, 255, 0.35);
    animation: voiceIn 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes voiceIn {
    0% {
        opacity: 0;
        transform: translateY(8px) scale(0.96);
    }

    100% {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
}

.voice-panel__row {
    display: flex;
    align-items: center;
    gap: 12px;
}

.voice-panel__avatar {
    position: relative;
    width: 42px;
    height: 42px;
    flex: none;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 18px;
}

.voice-panel__avatar--me {
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    box-shadow: 0 4px 14px -4px rgba(124, 107, 255, 0.7);
}

.voice-panel__avatar--other {
    background: rgba(34, 197, 94, 0.15);
    border: 1px solid rgba(34, 197, 94, 0.3);
}

.voice-panel__ring {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(124, 107, 255, 0.6) 0%, transparent 70%);
    pointer-events: none;
    transition: transform 0.06s linear, opacity 0.06s linear;
}

.voice-panel__emoji {
    position: relative;
    z-index: 1;
    filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.3));
}

.voice-panel__info {
    flex: 1;
    min-width: 0;
}

.voice-panel__name {
    font-size: 13.5px;
    font-weight: 700;
    color: #f1f5f9;
}

.voice-panel__status {
    font-size: 11.5px;
    color: #94a3b8;
    margin-top: 2px;
}

.voice-panel__bars {
    display: flex;
    align-items: center;
    gap: 2px;
    height: 26px;
    width: 60px;
}

.voice-panel__bar {
    flex: 1;
    min-height: 3px;
    border-radius: 1.5px;
    background: linear-gradient(180deg, #7c6bff, #4f8cff);
    transition: height 0.06s linear;
}

.voice-panel__hint {
    font-size: 11px;
    color: #94a3b8;
    padding: 4px 10px;
    background: rgba(255, 255, 255, 0.04);
    border-radius: 999px;
    flex: none;
}

.voice-panel__divider {
    height: 1px;
    background: rgba(255, 255, 255, 0.06);
}

/* ============================================================
 *  主面板
 * ============================================================ */
.panel {
    flex: 1;
    padding: 20px 16px 32px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    background: #000;
}

.card {
    background: rgba(255, 255, 255, 0.035);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 18px;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.card__icon {
    width: 56px;
    height: 56px;
    margin: 0 auto 4px;
    border-radius: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    color: #fff;
    box-shadow: 0 12px 30px -8px rgba(124, 107, 255, 0.65);
}

.card__title {
    margin: 0;
    font-size: 19px;
    font-weight: 700;
    text-align: center;
    color: #f1f5f9;
}

.card__desc {
    margin: 0 0 4px;
    font-size: 12.5px;
    color: #94a3b8;
    text-align: center;
}

.card__input {
    width: 100%;
    background: rgba(0, 0, 0, 0.4);
    border: 1px solid rgba(255, 255, 255, 0.09);
    color: #f1f5f9;
    border-radius: 12px;
    padding: 14px 16px;
    font-size: 16px;
    font-family: inherit;
    outline: none;
    text-align: center;
    letter-spacing: 0.04em;
}

.card__input:focus {
    border-color: #7c6bff;
    background: rgba(124, 107, 255, 0.08);
}

.card__row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.card__label {
    font-size: 13px;
    color: #94a3b8;
    flex: none;
}

.card__value {
    font-size: 14px;
    font-weight: 600;
    color: #f1f5f9;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: right;
}

.card__value--status {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

.card__divider {
    height: 1px;
    background: rgba(255, 255, 255, 0.06);
    margin: -4px 0;
}

.card--warn {
    flex-direction: row;
    align-items: center;
    gap: 12px;
    padding: 14px 16px;
    background: rgba(255, 77, 109, 0.08);
    border-color: rgba(255, 77, 109, 0.25);
}

.card__warn-icon {
    font-size: 22px;
}

.card__warn-body {
    flex: 1;
    min-width: 0;
}

.card__warn-title {
    font-size: 13.5px;
    font-weight: 700;
    color: #ffb3c1;
}

.card__warn-text {
    font-size: 11.5px;
    color: rgba(255, 179, 193, 0.75);
    margin-top: 2px;
}

.btn-primary {
    display: inline-flex;
    align-items: center;
    justify-content: center;
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
    box-shadow: 0 12px 30px -8px rgba(124, 107, 255, 0.7);
}

.btn-primary:active {
    transform: scale(0.98);
}

.btn-primary:disabled {
    opacity: 0.5;
    box-shadow: none;
    cursor: not-allowed;
}

.btn-retry {
    padding: 10px 22px;
    border-radius: 12px;
    background: rgba(124, 107, 255, 0.9);
    color: #fff;
    border: none;
    font-size: 14px;
    font-weight: 600;
    font-family: inherit;
    cursor: pointer;
}

.btn-retry-inline {
    padding: 8px 16px;
    border-radius: 10px;
    background: rgba(255, 77, 109, 0.9);
    color: #fff;
    border: none;
    font-size: 12.5px;
    font-weight: 600;
    font-family: inherit;
    cursor: pointer;
    flex: none;
}

.tips {
    padding: 16px 18px;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.06);
}

.tips__title {
    font-size: 12px;
    font-weight: 700;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 10px;
}

.tips__list {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.tips__list li {
    position: relative;
    padding-left: 18px;
    font-size: 12.5px;
    line-height: 1.55;
    color: #94a3b8;
}

.tips__list li b {
    color: #7c6bff;
    font-weight: 600;
}

.tips__list li::before {
    content: '';
    position: absolute;
    left: 6px;
    top: 8px;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #7c6bff;
    opacity: 0.7;
}

/* ============================================================
 *  全屏
 * ============================================================ */
.watch.is-fullscreen {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    width: 100vw;
    height: 100vh;
    height: 100dvh;
    min-height: unset;
    z-index: 9999;
    background: #000;
    padding: 0;
    margin: 0;
    overflow: hidden;
}

.watch.is-fullscreen .stage {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    min-height: 0;
    max-height: none;
    aspect-ratio: auto;
    flex: none;
}

.watch.is-fullscreen .stage__video {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
}

.watch.is-fullscreen .toolbar,
.watch.is-fullscreen .panel,
.watch.is-fullscreen .voice-panel {
    display: none;
}

/* ============================================================
 *  过渡
 * ============================================================ */
.fade-enter-active,
.fade-leave-active {
    transition: opacity 0.22s ease;
}

.fade-enter-from,
.fade-leave-to {
    opacity: 0;
}

.pop-enter-active,
.pop-leave-active {
    transition: opacity 0.22s ease, transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.pop-enter-from,
.pop-leave-to {
    opacity: 0;
    transform: translate(-50%, -50%) scale(0.82);
}

.slide-down-enter-active,
.slide-down-leave-active {
    transition: opacity 0.22s ease, transform 0.22s ease;
}

.slide-down-enter-from,
.slide-down-leave-to {
    opacity: 0;
    transform: translateY(-12px);
}

.slide-up-enter-active,
.slide-up-leave-active {
    transition: opacity 0.22s ease, transform 0.22s ease;
}

.slide-up-enter-from,
.slide-up-leave-to {
    opacity: 0;
    transform: translateY(12px);
}
</style>