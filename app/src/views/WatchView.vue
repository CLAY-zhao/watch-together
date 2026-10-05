<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
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

/* ============================================================
 *  常量
 * ============================================================ */
const CLIENT_ID = Math.random().toString(36).slice(2, 10)
const WS_BASE = getWsBase()
const PING_INTERVAL = 25000
const RECONNECT_BASE = 1500
const RECONNECT_MAX = 10000

/* 情绪弹幕 */
const EMOTIONS = [
    { emoji: '😂', label: '笑死', color: '#fbbf24' },
    { emoji: '😭', label: '哭了', color: '#60a5fa' },
    { emoji: '😱', label: '卧槽', color: '#f472b6' },
    { emoji: '😍', label: '好美', color: '#fb7185' },
    { emoji: '🥱', label: '无聊', color: '#94a3b8' },
    { emoji: '💩', label: '烂片', color: '#a16207' },
    { emoji: '👏', label: '好棒', color: '#22c55e' },
    { emoji: '❤️', label: '爱了', color: '#ef4444' },
]

/* ============================================================
 *  状态
 * ============================================================ */
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

/* ★ 语音音量（独立于影片音量） */
const voiceVolume = ref(1)
const hasVoiceAudio = ref(false)
let voiceAudioEl = null
let remoteMicStreamId = null

const micEnabled = ref(false)
const micConnecting = ref(false)
const micLevel = ref(0)
const broadcasterVoiceActive = ref(false)

/* 聊天 */
const showChat = ref(false)
const chatInput = ref('')
const chatMessages = ref([])
const chatUnread = ref(0)

/* ★ 新消息提示音 */
const chatSoundEnabled = ref(true)
let chatNotifAudioCtx = null

let lastEmotion = { emoji: '', ts: 0, combo: 0 }

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

/* 语音 */
let audioPc = null
let audioPendingIce = []
let localMicStream = null
let micAnalyser = null
let micAudioCtx = null
let micRaf = 0

/* 手势 */
let touchStartX = 0
let touchStartY = 0
let touchStartTime = 0
let touchStartVolume = 0
let gesture = ''

/* ============================================================
 *  计算
 * ============================================================ */
const statusLabel = computed(() => {
    const map = {
        idle: '未连接',
        connecting: '连接中',
        waiting: '等待主播',
        connected: '已连接',
        failed: '连接失败',
        disconnected: '已断开',
    }
    return map[status.value] || ''
})

const statusKind = computed(() => {
    if (status.value === 'connected') return 'ok'
    if (status.value === 'connecting' || status.value === 'waiting') return 'warn'
    if (status.value === 'failed' || status.value === 'disconnected') return 'err'
    return 'idle'
})

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

function fmtChatTime(ts) {
    const d = new Date(ts)
    const h = String(d.getHours()).padStart(2, '0')
    const m = String(d.getMinutes()).padStart(2, '0')
    return `${h}:${m}`
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

/* ============================================================
 *  影片音量
 * ============================================================ */
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
 *  ★ 语音音量（独立）
 * ============================================================ */
function ensureVoiceAudioEl() {
    if (voiceAudioEl) return voiceAudioEl
    voiceAudioEl = new Audio()
    voiceAudioEl.autoplay = true
    voiceAudioEl.volume = voiceVolume.value
    voiceAudioEl.setAttribute('playsinline', '')
    voiceAudioEl.style.position = 'fixed'
    voiceAudioEl.style.left = '-9999px'
    voiceAudioEl.style.width = '1px'
    voiceAudioEl.style.height = '1px'
    voiceAudioEl.style.opacity = '0'
    document.body.appendChild(voiceAudioEl)
    console.log('[voice-audio] created')
    return voiceAudioEl
}

function destroyVoiceAudioEl() {
    if (voiceAudioEl) {
        try { voiceAudioEl.pause() } catch (e) { }
        voiceAudioEl.srcObject = null
        try { voiceAudioEl.remove() } catch (e) { }
        voiceAudioEl = null
    }
    hasVoiceAudio.value = false
}

function setVoiceVolume(v) {
    v = Math.max(0, Math.min(1, v))
    voiceVolume.value = v
    if (voiceAudioEl) voiceAudioEl.volume = v
    localStorage.setItem('wt:voiceVolume', String(v))
}

/* ============================================================
 *  ★ 新消息提示音
 * ============================================================ */
function playChatNotifSound() {
    if (!chatSoundEnabled.value) return
    try {
        if (!chatNotifAudioCtx) {
            const AC = window.AudioContext || window.webkitAudioContext
            if (!AC) return
            chatNotifAudioCtx = new AC()
        }
        if (chatNotifAudioCtx.state === 'suspended') {
            chatNotifAudioCtx.resume()
        }

        const ctx = chatNotifAudioCtx
        const now = ctx.currentTime

        // C6 → G6 短促上升音，跟电脑端的"叮"区分
        const osc = ctx.createOscillator()
        const gain = ctx.createGain()

        osc.type = 'sine'
        osc.frequency.setValueAtTime(1046.5, now)          // C6
        osc.frequency.exponentialRampToValueAtTime(1568, now + 0.08)  // G6

        gain.gain.setValueAtTime(0, now)
        gain.gain.linearRampToValueAtTime(0.15, now + 0.01)
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.22)

        osc.connect(gain)
        gain.connect(ctx.destination)
        osc.start(now)
        osc.stop(now + 0.28)
    } catch (e) {
        console.warn('[chat-notif] 音效播放失败:', e)
    }
}

/* ============================================================
 *  聊天
 * ============================================================ */
function addChatMessage(msg) {
    chatMessages.value.push(msg)
    while (chatMessages.value.length > 100) {
        chatMessages.value.shift()
    }

    /* ★ 收到对方消息时播放提示音（自己发的不响） */
    if (msg.from !== 'me') {
        playChatNotifSound()
    }

    nextTick(() => {
        const el = document.querySelector('.chat-list')
        if (el) el.scrollTop = el.scrollHeight
    })
}

function sendChat() {
    const text = chatInput.value.trim()
    if (!text) return
    if (!ws || ws.readyState !== WebSocket.OPEN) return

    addChatMessage({
        id: Date.now() + Math.random(),
        from: 'me',
        text,
        time: Date.now(),
    })

    send({
        type: 'chat',
        channel: 'chat',
        text,
    })

    chatInput.value = ''
}

function toggleChat() {
    showChat.value = !showChat.value
    if (showChat.value) {
        chatUnread.value = 0
        nextTick(() => {
            const el = document.querySelector('.chat-list')
            if (el) el.scrollTop = el.scrollHeight
        })
    }
}

/* ============================================================
 *  情绪弹幕
 * ============================================================ */
function sendEmotion(e) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return

    const now = Date.now()
    let combo = 1

    if (lastEmotion.emoji === e.emoji && now - lastEmotion.ts < 1500) {
        combo = lastEmotion.combo + 1
    }

    lastEmotion = { emoji: e.emoji, ts: now, combo }

    send({
        type: 'emotion',
        channel: 'emotion',
        emoji: e.emoji,
        label: e.label,
        color: e.color,
        combo,
    })

    if (navigator.vibrate) {
        try { navigator.vibrate(combo > 1 ? 30 : 15) } catch (err) { }
    }
}

/* ============================================================
 *  语音通话
 * ============================================================ */
async function toggleMic() {
    if (micEnabled.value) await stopMic()
    else await startMic()
}

async function startMic() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        alert('尚未连接到房间，请稍后重试')
        return
    }
    micConnecting.value = true

    try {
        localMicStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
            },
        })

        startMicMeter(localMicStream)
        closeAudioPeer()
        audioPc = new RTCPeerConnection({ iceServers: iceServers.value })

        localMicStream.getTracks().forEach(t => {
            audioPc.addTrack(t, localMicStream)
        })

        audioPc.onicecandidate = e => {
            if (e.candidate) {
                send({ type: 'ice', channel: 'audio', candidate: e.candidate })
            }
        }

        audioPc.onconnectionstatechange = () => {
            if (audioPc &&
                (audioPc.connectionState === 'failed' ||
                    audioPc.connectionState === 'closed')) {
                stopMic()
            }
        }

        const offer = await audioPc.createOffer()
        await audioPc.setLocalDescription(offer)

        send({
            type: 'offer',
            channel: 'audio',
            sdp: {
                type: audioPc.localDescription.type,
                sdp: audioPc.localDescription.sdp,
            },
        })

        micEnabled.value = true
    } catch (e) {
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
}

function closeAudioPeer() {
    if (audioPc) { try { audioPc.close() } catch (e) { } audioPc = null }
    audioPendingIce = []
}

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
    } catch (e) { }
}

function stopMicMeter() {
    if (micRaf) { cancelAnimationFrame(micRaf); micRaf = 0 }
    micAnalyser = null
    if (micAudioCtx) { try { micAudioCtx.close() } catch (e) { } micAudioCtx = null }
    micLevel.value = 0
}

async function handleVoiceAnswer(sdp) {
    if (!audioPc) return
    try {
        await audioPc.setRemoteDescription(new RTCSessionDescription(sdp))
        for (const c of audioPendingIce) {
            try { await audioPc.addIceCandidate(new RTCIceCandidate(c)) } catch (e) { }
        }
        audioPendingIce = []
    } catch (e) { }
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
 *  WakeLock
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

/* ============================================================
 *  全屏
 * ============================================================ */
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
 *  WebSocket
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
 *  WebRTC —— ★ 关键：区分语音和电影音频
 * ============================================================ */
function createPeerConnection() {
    const p = new RTCPeerConnection({
        iceServers: iceServers.value,
        bundlePolicy: 'max-bundle',
        rtcpMuxPolicy: 'require',
    })

    p.ontrack = event => {
        const stream = (event.streams && event.streams[0]) || null

        /* ---- 视频轨道 ---- */
        if (event.track.kind === 'video') {
            const v = getVideo()
            if (!v) return

            try {
                const receiver = p.getReceivers().find(r => r.track === event.track)
                if (receiver && 'playoutDelayHint' in receiver) {
                    receiver.playoutDelayHint = 0
                }
            } catch (e) { }

            if (stream) {
                if (v.srcObject !== stream) v.srcObject = stream
            } else {
                let s = v.srcObject
                if (!(s instanceof MediaStream)) { s = new MediaStream(); v.srcObject = s }
                s.addTrack(event.track)
            }
            hasMedia.value = true
            tryAutoPlay()
            return
        }

        /* ---- 音频轨道：区分电影音频 / 语音 ---- */
        if (event.track.kind === 'audio') {
            const isVoice = stream && remoteMicStreamId && stream.id === remoteMicStreamId

            if (isVoice) {
                /* 语音 → 独立 audio 元素 */
                console.log('[voice-audio] 收到语音轨，路由到独立播放器')
                const el = ensureVoiceAudioEl()
                el.srcObject = new MediaStream([event.track])
                el.volume = voiceVolume.value
                el.play()
                    .then(() => {
                        hasVoiceAudio.value = true
                        console.log('[voice-audio] 语音开始播放')
                    })
                    .catch(e => {
                        console.warn('[voice-audio] play failed:', e)
                        hasVoiceAudio.value = true
                    })
            } else {
                /* 电影音频 → 合并到视频元素 */
                console.log('[video-audio] 电影音频轨道 → video 元素')
                const v = getVideo()
                if (!v) return
                if (stream) {
                    if (v.srcObject !== stream) v.srcObject = stream
                } else {
                    let s = v.srcObject
                    if (!(s instanceof MediaStream)) { s = new MediaStream(); v.srcObject = s }
                    s.addTrack(event.track)
                }
            }
        }
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
    destroyVoiceAudioEl()
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
    ws.onerror = () => { }
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

        /* ★ 麦克风流 ID */
        if (msg.type === 'stream-info') {
            remoteMicStreamId = msg.micStreamId
            console.log('[voice-audio] mic stream id =', remoteMicStreamId)
            return
        }

        /* 聊天 */
        if (msg.type === 'chat' && channel === 'chat') {
            addChatMessage({
                id: Date.now() + Math.random(),
                from: 'broadcaster',
                text: msg.text || '',
                time: Date.now(),
            })
            if (!showChat.value) chatUnread.value++
            return
        }

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

onMounted(async () => {
    placeholderImage.value = pickPlaceholder()

    /* 恢复音量偏好 */
    const savedVol = localStorage.getItem('wt:volume')
    if (savedVol !== null) {
        const v = parseFloat(savedVol)
        if (!isNaN(v)) volume.value = Math.max(0, Math.min(1, v))
    }

    const savedVoiceVol = localStorage.getItem('wt:voiceVolume')
    if (savedVoiceVol !== null) {
        const v = parseFloat(savedVoiceVol)
        if (!isNaN(v)) voiceVolume.value = Math.max(0, Math.min(1, v))
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
                if (showChat.value) { showChat.value = false; return }
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

        <!-- ============ 视频舞台 ============ -->
        <div ref="stageEl" class="stage" @touchstart.passive="onTouchStart" @touchmove="onTouchMove"
            @touchend.passive="onTouchEnd" @touchcancel.passive="onTouchEnd">
            <video id="remoteVideo" ref="videoEl" class="stage__video" playsinline webkit-playsinline autoplay></video>

            <transition name="fade">
                <div v-if="!hasMedia && placeholderImage" class="stage__bg"
                    :style="{ backgroundImage: `url('${placeholderImage}')` }">
                    <div class="stage__bg-overlay"></div>
                    <div class="stage__bg-grid"></div>
                    <div class="stage__bg-noise"></div>
                </div>
            </transition>

            <transition name="fade">
                <div v-if="!hasMedia && joined" class="stage__boot">
                    <div class="boot__spinner" :class="{ 'boot__spinner--err': canRetry }">
                        <div class="boot__ring"></div>
                        <div class="boot__ring boot__ring--2"></div>
                        <div class="boot__core"></div>
                    </div>
                    <p class="boot__text">{{ statusLabel }}</p>
                    <p class="boot__sub">正在与主播建立连接</p>
                    <button v-if="canRetry" class="boot__retry" @click.stop="retry">
                        重新连接
                    </button>
                </div>
            </transition>

            <transition name="pop">
                <button v-if="hasMedia && (!playing || needsTapToPlay)" class="bigplay" @click.stop="userPlay">
                    <div class="bigplay__ring"></div>
                    <div class="bigplay__ring bigplay__ring--2"></div>
                    <svg viewBox="0 0 24 24" width="34" height="34" fill="currentColor">
                        <path d="M8 5.5v13l11-6.5-11-6.5Z" />
                    </svg>
                </button>
            </transition>

            <transition name="pop">
                <div v-if="showVolumeBubble" class="volume-bubble">
                    <div class="volume-bubble__icon">
                        <svg v-if="volumeIcon === 'muted'" viewBox="0 0 24 24" width="24" height="24" fill="none"
                            stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M4 9v6h4l5 4V5L8 9H4Z" />
                            <path d="m17 9 5 6M22 9l-5 6" />
                        </svg>
                        <svg v-else-if="volumeIcon === 'low'" viewBox="0 0 24 24" width="24" height="24" fill="none"
                            stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M4 9v6h4l5 4V5L8 9H4Z" />
                            <path d="M16.5 8.5a5 5 0 0 1 0 7" />
                        </svg>
                        <svg v-else viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor"
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

            <!-- 全屏顶栏 -->
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
                            <span class="dot" :class="statusKind"></span>
                            <span class="topbar__room">{{ roomId || '未加入' }}</span>
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

            <!-- 全屏底栏 -->
            <transition name="slide-up">
                <div v-show="isFullscreen && showControls" class="bottombar">
                    <div class="bottombar__hint">
                        <span class="hint-icon">↕</span>
                        滑动调音量
                    </div>

                    <div class="spacer"></div>

                    <button class="mic-fab" :class="{ 'mic-fab--on': micEnabled, 'mic-fab--connecting': micConnecting }"
                        @click.stop="toggleMic">
                        <div v-if="micEnabled" class="mic-fab__pulse" :style="{ opacity: micLevel / 150 + 0.4 }"></div>
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
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

        <!-- ============ 工具栏 ============ -->
        <div v-if="!isFullscreen" class="toolbar">
            <div class="toolbar__bg"></div>

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

            <button class="tool tool--mic" :class="{ 'tool--active': micEnabled, 'tool--connecting': micConnecting }"
                @click="toggleMic">
                <div class="tool__icon">
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

            <button class="tool tool--chat" :class="{ 'tool--active': showChat }" @click="toggleChat">
                <div class="tool__icon">
                    <div v-if="chatUnread > 0 && !showChat" class="chat-badge">{{ chatUnread > 99 ? '99+' : chatUnread
                        }}</div>
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                    </svg>
                </div>
                <span class="tool__label">聊天</span>
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

        <!-- ============ 聊天抽屉 ============ -->
        <transition name="chat-drawer">
            <div v-if="showChat && !isFullscreen" class="chat-drawer">
                <div class="chat-drawer__header">
                    <div class="chat-drawer__title">
                        <span class="chat-drawer__dot"></span>
                        聊天
                    </div>

                    <!-- ★ 提示音开关 -->
                    <button class="chat-drawer__sound" :class="{ 'is-on': chatSoundEnabled }"
                        @click="chatSoundEnabled = !chatSoundEnabled"
                        :aria-label="chatSoundEnabled ? '关闭提示音' : '开启提示音'">
                        <svg v-if="chatSoundEnabled" viewBox="0 0 24 24" width="16" height="16" fill="none"
                            stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M11 5L6 9H2v6h4l5 4V5z" />
                            <path d="M15.5 8.5a5 5 0 0 1 0 7" />
                            <path d="M19 5a9 9 0 0 1 0 14" />
                        </svg>
                        <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M11 5L6 9H2v6h4l5 4V5z" />
                            <path d="m23 9-6 6M17 9l6 6" />
                        </svg>
                        <span class="chat-drawer__sound-text">{{ chatSoundEnabled ? '提示音' : '静音' }}</span>
                    </button>

                    <button class="chat-drawer__close" @click="showChat = false">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                            stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M18 6L6 18M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                <div class="chat-list">
                    <div v-if="chatMessages.length === 0" class="chat-empty">
                        <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor"
                            stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                        </svg>
                        <p>还没有消息</p>
                        <p class="chat-empty__sub">说点什么吧～</p>
                    </div>

                    <div v-for="m in chatMessages" :key="m.id" class="chat-msg"
                        :class="{ 'chat-msg--me': m.from === 'me' }">
                        <div class="chat-msg__bubble">
                            <div class="chat-msg__text">{{ m.text }}</div>
                            <div class="chat-msg__time">{{ fmtChatTime(m.time) }}</div>
                        </div>
                    </div>
                </div>

                <div class="chat-input-wrap">
                    <input v-model="chatInput" type="text" placeholder="说点什么…" class="chat-input" maxlength="200"
                        @keyup.enter="sendChat" />
                    <button class="chat-send" :disabled="!chatInput.trim()" @click="sendChat">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                            stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
                        </svg>
                    </button>
                </div>
            </div>
        </transition>

        <!-- ============ 情绪弹幕条 ============ -->
        <transition name="slide-up">
            <div v-if="!isFullscreen && joined && hasMedia && !showChat" class="emotion-bar">
                <div class="emotion-bar__glow"></div>

                <div class="emotion-bar__header">
                    <span class="emotion-bar__dot"></span>
                    <span class="emotion-bar__label">快捷弹幕</span>
                    <span class="emotion-bar__hint">点一下发给对方</span>
                </div>

                <div class="emotion-bar__list">
                    <button v-for="(e, i) in EMOTIONS" :key="i" class="emotion-btn" :style="{ '--e-color': e.color }"
                        @click="sendEmotion(e)" :aria-label="e.label">
                        <span class="emotion-btn__emoji">{{ e.emoji }}</span>
                        <span class="emotion-btn__label">{{ e.label }}</span>
                    </button>
                </div>
            </div>
        </transition>

        <!-- ============ 语音浮层 ============ -->
        <transition name="slide-up">
            <div v-if="micEnabled && !isFullscreen && !showChat" class="voice-panel">
                <div class="voice-panel__glow"></div>

                <div class="voice-panel__row">
                    <div class="voice-panel__avatar voice-panel__avatar--me">
                        <div class="voice-panel__ring"
                            :style="{ transform: `scale(${1 + micLevel / 150})`, opacity: micLevel / 120 + 0.3 }"></div>
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="9" y="3" width="6" height="12" rx="3" />
                            <path d="M5 11a7 7 0 0 0 14 0" />
                            <line x1="12" y1="18" x2="12" y2="22" />
                            <line x1="8" y1="22" x2="16" y2="22" />
                        </svg>
                    </div>
                    <div class="voice-panel__info">
                        <div class="voice-panel__name">我</div>
                        <div class="voice-panel__status">{{ micLevel > 8 ? '正在说话' : '安静中' }}</div>
                    </div>
                    <div class="voice-panel__bars">
                        <span v-for="n in 14" :key="n" class="voice-panel__bar" :style="{
                            height: Math.max(4, micLevel * (0.4 + Math.sin(n / 1.5) * 0.4)) + '%',
                        }"></span>
                    </div>
                </div>

                <div class="voice-panel__divider"></div>

                <div class="voice-panel__row">
                    <div class="voice-panel__avatar voice-panel__avatar--other">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M11 5 6 9H2v6h4l5 4V5z" />
                            <path d="M15.5 8.5a5 5 0 0 1 0 7" />
                            <path d="M19 5a9 9 0 0 1 0 14" />
                        </svg>
                    </div>
                    <div class="voice-panel__info">
                        <div class="voice-panel__name">投屏端</div>
                        <div class="voice-panel__status">
                            {{ broadcasterVoiceActive ? '正在说话' : '在线' }}
                        </div>
                    </div>
                    <div class="voice-panel__hint">
                        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M3 18v-6a9 9 0 0 1 18 0v6" />
                            <path
                                d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z" />
                        </svg>
                        戴耳机
                    </div>
                </div>
            </div>
        </transition>

        <!-- ============ 信息面板 ============ -->
        <section v-show="!isFullscreen" class="panel">

            <div v-if="!joined" class="join-card">
                <div class="join-card__icon">
                    <div class="join-card__halo"></div>
                    <div class="join-card__core">
                        <svg viewBox="0 0 48 48" width="26" height="26">
                            <path d="M16 12 L36 24 L16 36 Z" fill="#fff" />
                        </svg>
                    </div>
                </div>
                <h2 class="join-card__title">加入房间</h2>
                <p class="join-card__desc">输入电脑端显示的房间号</p>
                <div class="join-card__input">
                    <span class="join-card__prefix">#</span>
                    <input v-model="inputRoom" type="text" placeholder="房间号" autocomplete="off" autocapitalize="off"
                        spellcheck="false" @keyup.enter="enter" />
                </div>
                <button class="join-card__btn" :disabled="!inputRoom.trim()" @click="enter">
                    <span>进入房间</span>
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4"
                        stroke-linecap="round" stroke-linejoin="round">
                        <path d="M5 12h14M13 5l7 7-7 7" />
                    </svg>
                </button>
            </div>

            <template v-else>
                <div class="status-card">
                    <div class="status-card__shine"></div>

                    <div class="status-card__header">
                        <span class="status-card__step">LIVE</span>
                        <span class="status-card__label">房间状态</span>
                    </div>

                    <div class="status-card__row">
                        <div class="status-card__key">
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <rect x="3" y="6" width="18" height="12" rx="2" />
                                <path d="M3 10h18" />
                            </svg>
                            房间号
                        </div>
                        <div class="status-card__value">{{ roomId }}</div>
                    </div>

                    <div class="status-card__divider"></div>

                    <div class="status-card__row">
                        <div class="status-card__key">
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <circle cx="12" cy="12" r="10" />
                                <path d="M12 6v6l4 2" />
                            </svg>
                            连接
                        </div>
                        <div class="status-card__value">
                            <span class="dot" :class="statusKind"></span>
                            {{ statusLabel }}
                        </div>
                    </div>

                    <div class="status-card__divider"></div>

                    <div class="status-card__row">
                        <div class="status-card__key">
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <rect x="9" y="3" width="6" height="12" rx="3" />
                                <path d="M5 11a7 7 0 0 0 14 0" />
                                <line x1="12" y1="18" x2="12" y2="22" />
                                <line x1="8" y1="22" x2="16" y2="22" />
                            </svg>
                            语音
                        </div>
                        <div class="status-card__value">
                            <span class="dot" :class="micEnabled ? 'ok' : 'idle'"></span>
                            {{ micConnecting ? '连接中' : (micEnabled ? '已开启' : '未开启') }}
                        </div>
                    </div>

                    <div class="status-card__divider"></div>

                    <div class="status-card__row">
                        <div class="status-card__key">
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                            </svg>
                            聊天
                        </div>
                        <div class="status-card__value">
                            {{ chatMessages.length }} 条消息
                        </div>
                    </div>
                </div>

                <!-- ★ 语音音量卡片 -->
                <transition name="slide-up">
                    <div v-if="hasVoiceAudio" class="voice-volume-card">
                        <div class="voice-volume-card__header">
                            <div class="voice-volume-card__icon">
                                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
                                    stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="9" y="3" width="6" height="12" rx="3" />
                                    <path d="M5 11a7 7 0 0 0 14 0" />
                                    <line x1="12" y1="18" x2="12" y2="22" />
                                    <line x1="8" y1="22" x2="16" y2="22" />
                                </svg>
                            </div>
                            <div class="voice-volume-card__info">
                                <div class="voice-volume-card__title">对方语音</div>
                                <div class="voice-volume-card__sub">仅调节通话声音，不影响影片</div>
                            </div>
                            <div class="voice-volume-card__value">{{ Math.round(voiceVolume * 100) }}</div>
                        </div>

                        <div class="voice-volume-card__slider-wrap">
                            <svg class="voice-volume-card__slider-icon" viewBox="0 0 24 24" width="14" height="14"
                                fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
                                stroke-linejoin="round">
                                <path d="M11 5 6 9H2v6h4l5 4V5z" />
                            </svg>
                            <input type="range" class="voice-volume-card__slider" min="0" max="1" step="0.01"
                                :value="voiceVolume" @input="e => setVoiceVolume(parseFloat(e.target.value))" />
                            <svg class="voice-volume-card__slider-icon" viewBox="0 0 24 24" width="14" height="14"
                                fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
                                stroke-linejoin="round">
                                <path d="M11 5 6 9H2v6h4l5 4V5z" />
                                <path d="M15.5 8.5a5 5 0 0 1 0 7" />
                                <path d="M18.5 5.5a9 9 0 0 1 0 13" />
                            </svg>
                        </div>
                    </div>
                </transition>

                <div v-if="canRetry" class="warn-card">
                    <div class="warn-card__icon">
                        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path
                                d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                            <line x1="12" y1="9" x2="12" y2="13" />
                            <line x1="12" y1="17" x2="12.01" y2="17" />
                        </svg>
                    </div>
                    <div class="warn-card__body">
                        <div class="warn-card__title">连接已断开</div>
                        <div class="warn-card__text">请检查网络后重试</div>
                    </div>
                    <button class="warn-card__btn" @click="retry">重试</button>
                </div>

                <div class="tips-card">
                    <div class="tips-card__title">
                        <span class="tips-card__dot"></span>
                        使用提示
                    </div>
                    <ul class="tips-card__list">
                        <li>
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M7 16V4M7 4L3 8M7 4l4 4" />
                                <path d="M17 8v12M17 20l4-4M17 20l-4-4" />
                            </svg>
                            在画面上<b>上下滑动</b>调节影片音量
                        </li>
                        <li>
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <rect x="9" y="3" width="6" height="12" rx="3" />
                                <path d="M5 11a7 7 0 0 0 14 0" />
                            </svg>
                            上方滑块<b>单独调语音</b>大小
                        </li>
                        <li>
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                            </svg>
                            点<b>聊天</b>可以文字吐槽剧情
                        </li>
                        <li>
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path
                                    d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4" />
                            </svg>
                            点<b>全屏</b>进入沉浸观影
                        </li>
                        <li>
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M3 18v-6a9 9 0 0 1 18 0v6" />
                                <path
                                    d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z" />
                            </svg>
                            <b>戴耳机</b>可以避免回声
                        </li>
                    </ul>
                </div>
            </template>
        </section>
    </div>
</template>

<style scoped>
.watch {
    position: relative;
    width: 100%;
    height: 100vh;
    height: 100dvh;
    background: #05060a;
    display: flex;
    flex-direction: column;
    color: #f1f5f9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Microsoft YaHei", sans-serif;
    overflow-y: auto;
    overflow-x: hidden;
    -webkit-overflow-scrolling: touch;
    overscroll-behavior-y: contain;
    -webkit-font-smoothing: antialiased;
    -webkit-tap-highlight-color: transparent;
}

.watch::-webkit-scrollbar {
    width: 0;
    display: none;
}

.watch {
    scrollbar-width: none;
}

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
    flex: none;
}

.stage__video {
    position: relative;
    z-index: 2;
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
    animation: bgZoom 24s ease-in-out infinite alternate;
}

@keyframes bgZoom {
    0% {
        transform: scale(1);
    }

    100% {
        transform: scale(1.08);
    }
}

.stage__bg-overlay {
    position: absolute;
    inset: 0;
    background:
        radial-gradient(ellipse at center, rgba(124, 107, 255, 0.28), transparent 65%),
        linear-gradient(180deg, rgba(5, 6, 10, 0.35) 0%, rgba(5, 6, 10, 0.75) 100%);
}

.stage__bg-grid {
    position: absolute;
    inset: 0;
    background-image:
        linear-gradient(rgba(124, 107, 255, 0.06) 1px, transparent 1px),
        linear-gradient(90deg, rgba(124, 107, 255, 0.06) 1px, transparent 1px);
    background-size: 40px 40px;
    mask-image: radial-gradient(ellipse at center, #000 20%, transparent 70%);
    -webkit-mask-image: radial-gradient(ellipse at center, #000 20%, transparent 70%);
}

.stage__bg-noise {
    position: absolute;
    inset: 0;
    opacity: 0.04;
    mix-blend-mode: overlay;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='3'/></filter><rect width='200' height='200' filter='url(%23n)'/></svg>");
}

.stage__boot {
    position: absolute;
    inset: 0;
    z-index: 3;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    background: rgba(5, 6, 10, 0.55);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
}

.boot__spinner {
    position: relative;
    width: 64px;
    height: 64px;
    margin-bottom: 12px;
    display: grid;
    place-items: center;
}

.boot__ring {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    border: 2px solid transparent;
    border-top-color: #7c6bff;
    animation: spin 1.2s linear infinite;
}

.boot__ring--2 {
    inset: 8px;
    border-top-color: #4f8cff;
    animation-duration: 1.8s;
    animation-direction: reverse;
}

.boot__core {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    box-shadow: 0 0 20px rgba(124, 107, 255, 0.9);
    animation: corePulse 1.4s ease-in-out infinite;
}

@keyframes spin {
    to {
        transform: rotate(360deg);
    }
}

@keyframes corePulse {

    0%,
    100% {
        transform: scale(1);
        opacity: 1;
    }

    50% {
        transform: scale(1.3);
        opacity: 0.7;
    }
}

.boot__spinner--err .boot__ring {
    border-top-color: #ff4d6d;
    animation-play-state: paused;
}

.boot__spinner--err .boot__ring--2 {
    border-top-color: #ff4d6d;
}

.boot__spinner--err .boot__core {
    background: #ff4d6d;
    box-shadow: 0 0 20px rgba(255, 77, 109, 0.9);
}

.boot__text {
    font-size: 14px;
    font-weight: 600;
    color: #fff;
    margin: 0;
}

.boot__sub {
    font-size: 11.5px;
    color: #94a3b8;
    margin: 0;
}

.boot__retry {
    margin-top: 14px;
    padding: 10px 24px;
    border-radius: 12px;
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    color: #fff;
    border: none;
    font-family: inherit;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 12px 30px -8px rgba(124, 107, 255, 0.7);
}

.bigplay {
    position: absolute;
    inset: 0;
    margin: auto;
    width: 84px;
    height: 84px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: #0b0b0f;
    background: rgba(255, 255, 255, 0.96);
    padding-left: 5px;
    z-index: 4;
    border: none;
    cursor: pointer;
    transition: transform 0.2s;
    box-shadow:
        0 20px 50px -10px rgba(0, 0, 0, 0.9),
        0 0 0 8px rgba(124, 107, 255, 0.14);
}

.bigplay:active {
    transform: scale(0.94);
}

.bigplay__ring {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    border: 2px solid rgba(124, 107, 255, 0.6);
    animation: bigplayRing 2s ease-out infinite;
}

.bigplay__ring--2 {
    animation-delay: 1s;
}

@keyframes bigplayRing {
    0% {
        transform: scale(1);
        opacity: 0.8;
    }

    100% {
        transform: scale(1.6);
        opacity: 0;
    }
}

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
    padding: 20px 24px;
    border-radius: 22px;
    background: rgba(5, 6, 10, 0.82);
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow:
        0 30px 70px -20px rgba(0, 0, 0, 0.95),
        0 0 0 1px rgba(124, 107, 255, 0.2) inset;
    pointer-events: none;
}

.volume-bubble__icon {
    color: #a89bff;
    filter: drop-shadow(0 0 10px rgba(124, 107, 255, 0.6));
}

.volume-bubble__track {
    position: relative;
    width: 8px;
    height: 120px;
    background: rgba(255, 255, 255, 0.14);
    border-radius: 4px;
    display: flex;
    flex-direction: column-reverse;
    overflow: hidden;
}

.volume-bubble__fill {
    width: 100%;
    background: linear-gradient(0deg, #7c6bff, #4f8cff);
    border-radius: 4px;
    transition: height 0.08s linear;
    box-shadow: 0 0 20px rgba(124, 107, 255, 0.7);
}

.volume-bubble__value {
    font-size: 14px;
    font-weight: 800;
    color: #fff;
    font-variant-numeric: tabular-nums;
    line-height: 1;
}

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
    background: linear-gradient(180deg, rgba(5, 6, 10, 0.85), transparent);
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
}

.topbar__room {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #64748b;
    flex: none;
    display: inline-block;
    position: relative;
}

.dot.idle {
    background: #64748b;
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
    background: linear-gradient(0deg, rgba(5, 6, 10, 0.85), transparent);
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
    background: rgba(5, 6, 10, 0.6);
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

.iconbtn {
    width: 42px;
    height: 42px;
    flex: none;
    display: grid;
    place-items: center;
    border-radius: 50%;
    background: rgba(5, 6, 10, 0.55);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: #fff;
    cursor: pointer;
    transition: transform 0.15s, background 0.15s;
}

.iconbtn:active {
    transform: scale(0.9);
    background: rgba(124, 107, 255, 0.25);
    border-color: rgba(124, 107, 255, 0.5);
}

.iconbtn.is-on {
    color: #a89bff;
    background: rgba(124, 107, 255, 0.2);
    border-color: rgba(124, 107, 255, 0.45);
}

.mic-fab {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 18px;
    border-radius: 999px;
    background: rgba(5, 6, 10, 0.6);
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
    box-shadow: 0 0 24px rgba(124, 107, 255, 0.65);
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
}

.mic-fab__text {
    position: relative;
    z-index: 1;
}

.toolbar {
    position: relative;
    flex: none;
    display: flex;
    align-items: stretch;
    gap: 4px;
    padding: 14px 10px;
    background: rgba(10, 13, 18, 0.85);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-bottom: 1px solid rgba(124, 107, 255, 0.1);
    overflow: hidden;
}

.toolbar__bg {
    position: absolute;
    inset: 0;
    background:
        radial-gradient(300px 80px at 50% 0%, rgba(124, 107, 255, 0.15), transparent 70%);
    pointer-events: none;
}

.tool {
    position: relative;
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 10px 2px;
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
    background: rgba(255, 255, 255, 0.05);
}

.tool--active {
    color: #a89bff;
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
    border-radius: 13px;
    background: rgba(255, 255, 255, 0.045);
    border: 1px solid rgba(255, 255, 255, 0.08);
    transition: background 0.15s, border-color 0.2s, color 0.2s, box-shadow 0.2s;
}

.tool--active .tool__icon {
    background: rgba(124, 107, 255, 0.18);
    border-color: rgba(124, 107, 255, 0.55);
    box-shadow: 0 0 16px rgba(124, 107, 255, 0.45);
}

.tool--connecting .tool__icon {
    background: rgba(245, 158, 11, 0.15);
    border-color: rgba(245, 158, 11, 0.5);
    animation: connectingPulse 1s infinite;
}

.chat-badge {
    position: absolute;
    top: -4px;
    right: -4px;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    border-radius: 9px;
    background: #ff4d6d;
    color: #fff;
    font-size: 10px;
    font-weight: 800;
    display: grid;
    place-items: center;
    box-shadow: 0 0 10px rgba(255, 77, 109, 0.8);
    animation: badgePop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
    z-index: 2;
}

@keyframes badgePop {
    0% {
        transform: scale(0);
    }

    100% {
        transform: scale(1);
    }
}

.mic-halo {
    position: absolute;
    inset: 0;
    border-radius: 13px;
    background: radial-gradient(circle, rgba(124, 107, 255, 0.7) 0%, transparent 70%);
    pointer-events: none;
    transition: transform 0.06s linear, opacity 0.06s linear;
}

.tool__label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.02em;
}

/* 聊天抽屉 */
.chat-drawer {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 100;
    max-height: 70vh;
    height: 70vh;
    display: flex;
    flex-direction: column;
    background: rgba(12, 15, 22, 0.98);
    backdrop-filter: blur(28px);
    -webkit-backdrop-filter: blur(28px);
    border-top-left-radius: 24px;
    border-top-right-radius: 24px;
    border-top: 1px solid rgba(124, 107, 255, 0.3);
    box-shadow:
        0 -20px 60px -10px rgba(0, 0, 0, 0.9),
        0 -1px 0 rgba(255, 255, 255, 0.06) inset;
    padding-bottom: env(safe-area-inset-bottom, 0px);
    overflow: hidden;
}

.chat-drawer::before {
    content: '';
    position: absolute;
    top: 8px;
    left: 50%;
    transform: translateX(-50%);
    width: 40px;
    height: 4px;
    border-radius: 2px;
    background: rgba(255, 255, 255, 0.15);
}

.chat-drawer__header {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 20px 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.chat-drawer__title {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 15px;
    font-weight: 700;
    color: #f1f5f9;
}

.chat-drawer__dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #7c6bff;
    box-shadow: 0 0 8px #7c6bff;
    animation: dotPulse 2s ease-in-out infinite;
}

@keyframes dotPulse {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: 0.4;
    }
}

/* ★ 提示音开关 */
.chat-drawer__sound {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 6px 12px;
    margin-right: 8px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: #64748b;
    font-family: inherit;
    font-size: 11.5px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.18s;
}

.chat-drawer__sound:active {
    transform: scale(0.94);
}

.chat-drawer__sound.is-on {
    background: rgba(34, 197, 94, 0.15);
    border-color: rgba(34, 197, 94, 0.4);
    color: #86efac;
    box-shadow: 0 0 12px rgba(34, 197, 94, 0.25);
}

.chat-drawer__sound-text {
    letter-spacing: 0.02em;
}

.chat-drawer__close {
    width: 34px;
    height: 34px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: #94a3b8;
    cursor: pointer;
    transition: all 0.15s;
}

.chat-drawer__close:active {
    transform: scale(0.92);
    background: rgba(255, 77, 109, 0.2);
    color: #ff4d6d;
}

.chat-list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.chat-list::-webkit-scrollbar {
    width: 4px;
}

.chat-list::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 2px;
}

.chat-empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: #475569;
}

.chat-empty p {
    margin: 0;
    font-size: 13px;
}

.chat-empty__sub {
    font-size: 11px !important;
    color: #334155;
}

.chat-msg {
    display: flex;
    justify-content: flex-start;
}

.chat-msg--me {
    justify-content: flex-end;
}

.chat-msg__bubble {
    max-width: 78%;
    padding: 10px 14px;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-bottom-left-radius: 4px;
}

.chat-msg--me .chat-msg__bubble {
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    border: none;
    border-bottom-left-radius: 16px;
    border-bottom-right-radius: 4px;
    box-shadow: 0 6px 18px -6px rgba(124, 107, 255, 0.7);
}

.chat-msg__text {
    font-size: 14px;
    line-height: 1.45;
    color: #f1f5f9;
    word-break: break-word;
    white-space: pre-wrap;
}

.chat-msg__time {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.4);
    margin-top: 4px;
    text-align: right;
}

.chat-msg--me .chat-msg__time {
    color: rgba(255, 255, 255, 0.75);
}

.chat-input-wrap {
    flex: none;
    display: flex;
    gap: 10px;
    padding: 12px 16px;
    background: rgba(0, 0, 0, 0.35);
    border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.chat-input {
    flex: 1;
    min-width: 0;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 22px;
    padding: 12px 18px;
    color: #f1f5f9;
    font-size: 14px;
    font-family: inherit;
    outline: none;
    transition: border-color 0.2s, background 0.2s;
}

.chat-input:focus {
    border-color: rgba(124, 107, 255, 0.6);
    background: rgba(124, 107, 255, 0.08);
}

.chat-input::placeholder {
    color: #475569;
}

.chat-send {
    flex: none;
    width: 46px;
    height: 46px;
    border-radius: 50%;
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    color: #fff;
    border: none;
    display: grid;
    place-items: center;
    cursor: pointer;
    box-shadow: 0 8px 20px -6px rgba(124, 107, 255, 0.8);
    transition: transform 0.15s, opacity 0.2s;
}

.chat-send:active:not(:disabled) {
    transform: scale(0.92);
}

.chat-send:disabled {
    opacity: 0.35;
    box-shadow: none;
    cursor: not-allowed;
}

/* 情绪弹幕条 */
.emotion-bar {
    position: relative;
    flex: none;
    margin: 0 14px 12px;
    padding: 14px 16px 16px;
    border-radius: 20px;
    background: rgba(255, 255, 255, 0.03);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    overflow: hidden;
    box-shadow:
        0 12px 30px -12px rgba(0, 0, 0, 0.7),
        0 1px 0 rgba(255, 255, 255, 0.04) inset;
    animation: emotionBarIn 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes emotionBarIn {
    0% {
        opacity: 0;
        transform: translateY(12px);
    }

    100% {
        opacity: 1;
        transform: translateY(0);
    }
}

.emotion-bar__glow {
    position: absolute;
    top: -60%;
    left: 50%;
    width: 200px;
    height: 200px;
    transform: translateX(-50%);
    background: radial-gradient(circle, rgba(124, 107, 255, 0.25) 0%, transparent 65%);
    filter: blur(30px);
    pointer-events: none;
    animation: emotionGlow 6s ease-in-out infinite alternate;
}

@keyframes emotionGlow {
    0% {
        transform: translateX(-50%) scale(1);
        opacity: 0.6;
    }

    100% {
        transform: translateX(-50%) scale(1.3);
        opacity: 0.9;
    }
}

.emotion-bar__header {
    position: relative;
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
}

.emotion-bar__dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #7c6bff;
    box-shadow: 0 0 8px #7c6bff;
    animation: dotPulse 2s ease-in-out infinite;
}

.emotion-bar__label {
    font-size: 11.5px;
    font-weight: 700;
    color: #94a3b8;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.emotion-bar__hint {
    margin-left: auto;
    font-size: 10.5px;
    color: #475569;
}

.emotion-bar__list {
    position: relative;
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
}

.emotion-btn {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 10px 4px 8px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 14px;
    color: #f1f5f9;
    font-family: inherit;
    cursor: pointer;
    transition: transform 0.12s, background 0.2s, border-color 0.2s, box-shadow 0.2s;
    overflow: hidden;
}

.emotion-btn:active {
    transform: scale(0.92);
    background: rgba(124, 107, 255, 0.12);
    border-color: rgba(124, 107, 255, 0.45);
    box-shadow: 0 0 20px rgba(124, 107, 255, 0.35);
}

.emotion-btn__emoji {
    font-size: 24px;
    line-height: 1;
    filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.3));
    transition: transform 0.15s;
}

.emotion-btn:active .emotion-btn__emoji {
    transform: scale(1.3);
}

.emotion-btn__label {
    font-size: 10.5px;
    color: #94a3b8;
    font-weight: 600;
    transition: color 0.2s;
}

.emotion-btn:active .emotion-btn__label {
    color: #c7bfff;
}

/* 语音浮层 */
.voice-panel {
    position: relative;
    flex: none;
    margin: 0 14px 12px;
    padding: 16px 18px;
    border-radius: 20px;
    background: linear-gradient(135deg,
            rgba(124, 107, 255, 0.14) 0%,
            rgba(79, 140, 255, 0.08) 100%);
    border: 1px solid rgba(124, 107, 255, 0.3);
    display: flex;
    flex-direction: column;
    gap: 12px;
    overflow: hidden;
    box-shadow:
        0 12px 30px -10px rgba(124, 107, 255, 0.5),
        0 0 0 1px rgba(255, 255, 255, 0.03) inset;
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

.voice-panel__glow {
    position: absolute;
    top: -50%;
    left: -20%;
    width: 60%;
    height: 200%;
    background: radial-gradient(circle, rgba(124, 107, 255, 0.4) 0%, transparent 60%);
    filter: blur(40px);
    pointer-events: none;
    animation: voiceGlow 8s ease-in-out infinite alternate;
}

@keyframes voiceGlow {
    0% {
        transform: translate(0, 0);
    }

    100% {
        transform: translate(80px, 20px);
    }
}

.voice-panel__row {
    position: relative;
    display: flex;
    align-items: center;
    gap: 12px;
}

.voice-panel__avatar {
    position: relative;
    width: 44px;
    height: 44px;
    flex: none;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: #fff;
}

.voice-panel__avatar--me {
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    box-shadow:
        0 6px 18px -4px rgba(124, 107, 255, 0.8),
        0 0 0 1px rgba(255, 255, 255, 0.1) inset;
}

.voice-panel__avatar--other {
    background: rgba(34, 197, 94, 0.15);
    border: 1px solid rgba(34, 197, 94, 0.4);
    color: #86efac;
}

.voice-panel__ring {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(124, 107, 255, 0.6) 0%, transparent 70%);
    pointer-events: none;
    transition: transform 0.06s linear, opacity 0.06s linear;
}

.voice-panel__info {
    flex: 1;
    min-width: 0;
}

.voice-panel__name {
    font-size: 14px;
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
    width: 70px;
}

.voice-panel__bar {
    flex: 1;
    min-height: 3px;
    border-radius: 1.5px;
    background: linear-gradient(180deg, #a89bff, #4f8cff);
    transition: height 0.06s linear;
    box-shadow: 0 0 4px rgba(124, 107, 255, 0.5);
}

.voice-panel__hint {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    color: #94a3b8;
    padding: 4px 10px;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 999px;
    flex: none;
}

.voice-panel__divider {
    position: relative;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(124, 107, 255, 0.3), transparent);
}

/* 面板 */
.panel {
    flex: 0 0 auto;
    padding: 20px 16px 40px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    background: #05060a;
    position: relative;
}

.panel::before {
    content: '';
    position: absolute;
    inset: 0;
    background:
        radial-gradient(400px 200px at 90% 0%, rgba(124, 107, 255, 0.1), transparent 70%),
        radial-gradient(300px 200px at 10% 100%, rgba(79, 140, 255, 0.08), transparent 70%);
    pointer-events: none;
}

.join-card {
    position: relative;
    background: rgba(255, 255, 255, 0.035);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 22px;
    padding: 24px 22px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    box-shadow:
        0 30px 60px -20px rgba(0, 0, 0, 0.9),
        0 1px 0 rgba(255, 255, 255, 0.06) inset;
    animation: cardIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes cardIn {
    0% {
        opacity: 0;
        transform: translateY(12px);
    }

    100% {
        opacity: 1;
        transform: translateY(0);
    }
}

.join-card__icon {
    position: relative;
    width: 68px;
    height: 68px;
    margin: 0 auto 4px;
    display: grid;
    place-items: center;
}

.join-card__halo {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(124, 107, 255, 0.6) 0%, transparent 65%);
    animation: haloPulse 3s ease-in-out infinite;
}

@keyframes haloPulse {

    0%,
    100% {
        transform: scale(1);
        opacity: 0.7;
    }

    50% {
        transform: scale(1.15);
        opacity: 1;
    }
}

.join-card__core {
    position: relative;
    width: 56px;
    height: 56px;
    border-radius: 18px;
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    display: grid;
    place-items: center;
    padding-left: 3px;
    box-shadow:
        0 12px 30px -8px rgba(124, 107, 255, 0.8),
        0 0 0 1px rgba(255, 255, 255, 0.1) inset;
}

.join-card__title {
    margin: 0;
    font-size: 19px;
    font-weight: 700;
    text-align: center;
    color: #f1f5f9;
    letter-spacing: -0.01em;
}

.join-card__desc {
    margin: 0 0 4px;
    font-size: 12.5px;
    color: #94a3b8;
    text-align: center;
}

.join-card__input {
    position: relative;
    display: flex;
    align-items: center;
    background: rgba(0, 0, 0, 0.4);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    overflow: hidden;
    transition: border-color 0.25s, background 0.25s;
}

.join-card__input:focus-within {
    border-color: rgba(124, 107, 255, 0.6);
    background: rgba(124, 107, 255, 0.06);
}

.join-card__prefix {
    padding: 0 4px 0 16px;
    font-size: 17px;
    font-weight: 700;
    color: #7c6bff;
}

.join-card__input input {
    flex: 1;
    min-width: 0;
    background: transparent;
    border: none;
    outline: none;
    color: #f1f5f9;
    font-size: 16px;
    font-weight: 600;
    font-family: inherit;
    padding: 15px 16px 15px 8px;
    text-align: center;
    letter-spacing: 0.04em;
}

.join-card__input input::placeholder {
    color: #3f4a5c;
    font-weight: 500;
}

.join-card__btn {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    background: linear-gradient(135deg, #7c6bff 0%, #4f8cff 100%);
    color: #fff;
    border: none;
    border-radius: 13px;
    padding: 16px 20px;
    font-size: 15px;
    font-weight: 700;
    font-family: inherit;
    letter-spacing: 0.02em;
    cursor: pointer;
    box-shadow:
        0 14px 34px -8px rgba(124, 107, 255, 0.75),
        0 1px 0 rgba(255, 255, 255, 0.2) inset;
    transition: transform 0.15s, opacity 0.2s;
}

.join-card__btn:active:not(:disabled) {
    transform: scale(0.98);
}

.join-card__btn:disabled {
    opacity: 0.45;
    box-shadow: none;
    cursor: not-allowed;
}

.status-card {
    position: relative;
    background: rgba(255, 255, 255, 0.035);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 20px;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    overflow: hidden;
    box-shadow:
        0 20px 50px -20px rgba(0, 0, 0, 0.85),
        0 1px 0 rgba(255, 255, 255, 0.05) inset;
    animation: cardIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.status-card__shine {
    position: absolute;
    top: 0;
    left: -40%;
    width: 40%;
    height: 2px;
    background: linear-gradient(90deg, transparent, rgba(124, 107, 255, 0.8), transparent);
    animation: shineMove 4s ease-in-out infinite;
}

@keyframes shineMove {
    0% {
        left: -40%;
    }

    50% {
        left: 100%;
    }

    100% {
        left: 100%;
    }
}

.status-card__header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding-bottom: 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.status-card__step {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.12em;
    color: #22c55e;
    padding: 3px 8px;
    background: rgba(34, 197, 94, 0.12);
    border: 1px solid rgba(34, 197, 94, 0.3);
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
}

.status-card__step::before {
    content: '';
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #22c55e;
    box-shadow: 0 0 6px #22c55e;
    animation: dotPulse 1.5s ease-in-out infinite;
}

.status-card__label {
    font-size: 11px;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-weight: 600;
}

.status-card__row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.status-card__key {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 12.5px;
    color: #94a3b8;
    flex: none;
}

.status-card__key svg {
    color: #7c6bff;
    opacity: 0.8;
}

.status-card__value {
    font-size: 14px;
    font-weight: 600;
    color: #f1f5f9;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: right;
    display: inline-flex;
    align-items: center;
    gap: 7px;
}

.status-card__divider {
    height: 1px;
    background: rgba(255, 255, 255, 0.05);
    margin: -4px 0;
}

/* ★ 语音音量卡片 */
.voice-volume-card {
    padding: 16px 18px;
    border-radius: 18px;
    background: linear-gradient(135deg,
            rgba(34, 197, 94, 0.08) 0%,
            rgba(79, 140, 255, 0.05) 100%);
    border: 1px solid rgba(34, 197, 94, 0.25);
    display: flex;
    flex-direction: column;
    gap: 14px;
    box-shadow:
        0 12px 30px -14px rgba(34, 197, 94, 0.4),
        0 1px 0 rgba(255, 255, 255, 0.04) inset;
    animation: cardIn 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.voice-volume-card__header {
    display: flex;
    align-items: center;
    gap: 12px;
}

.voice-volume-card__icon {
    width: 34px;
    height: 34px;
    flex: none;
    border-radius: 11px;
    display: grid;
    place-items: center;
    background: rgba(34, 197, 94, 0.15);
    border: 1px solid rgba(34, 197, 94, 0.35);
    color: #86efac;
}

.voice-volume-card__info {
    flex: 1;
    min-width: 0;
}

.voice-volume-card__title {
    font-size: 13.5px;
    font-weight: 700;
    color: #f1f5f9;
}

.voice-volume-card__sub {
    font-size: 11px;
    color: #64748b;
    margin-top: 2px;
}

.voice-volume-card__value {
    flex: none;
    padding: 4px 10px;
    border-radius: 999px;
    background: rgba(34, 197, 94, 0.15);
    color: #86efac;
    font-size: 12px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
}

.voice-volume-card__slider-wrap {
    display: flex;
    align-items: center;
    gap: 12px;
}

.voice-volume-card__slider-icon {
    color: #64748b;
    flex: none;
}

.voice-volume-card__slider {
    flex: 1;
    -webkit-appearance: none;
    appearance: none;
    height: 6px;
    border-radius: 3px;
    background: rgba(255, 255, 255, 0.1);
    outline: none;
    cursor: pointer;
}

.voice-volume-card__slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: linear-gradient(135deg, #22c55e, #4ade80);
    box-shadow:
        0 0 0 3px rgba(34, 197, 94, 0.2),
        0 4px 12px -2px rgba(34, 197, 94, 0.6);
    cursor: pointer;
    transition: transform 0.15s;
}

.voice-volume-card__slider::-webkit-slider-thumb:active {
    transform: scale(1.15);
}

.voice-volume-card__slider::-moz-range-thumb {
    width: 20px;
    height: 20px;
    border: none;
    border-radius: 50%;
    background: linear-gradient(135deg, #22c55e, #4ade80);
    box-shadow:
        0 0 0 3px rgba(34, 197, 94, 0.2),
        0 4px 12px -2px rgba(34, 197, 94, 0.6);
    cursor: pointer;
}

.warn-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 16px;
    background: rgba(255, 77, 109, 0.1);
    border: 1px solid rgba(255, 77, 109, 0.28);
    border-radius: 16px;
    backdrop-filter: blur(10px);
    animation: cardIn 0.4s ease-out;
}

.warn-card__icon {
    width: 36px;
    height: 36px;
    flex: none;
    display: grid;
    place-items: center;
    border-radius: 11px;
    background: rgba(255, 77, 109, 0.15);
    color: #ff4d6d;
}

.warn-card__body {
    flex: 1;
    min-width: 0;
}

.warn-card__title {
    font-size: 13.5px;
    font-weight: 700;
    color: #ffb3c1;
}

.warn-card__text {
    font-size: 11.5px;
    color: rgba(255, 179, 193, 0.75);
    margin-top: 2px;
}

.warn-card__btn {
    padding: 8px 16px;
    border-radius: 10px;
    background: linear-gradient(135deg, #ff4d6d, #ff6b8a);
    color: #fff;
    border: none;
    font-family: inherit;
    font-size: 12.5px;
    font-weight: 700;
    cursor: pointer;
    flex: none;
    box-shadow: 0 8px 20px -6px rgba(255, 77, 109, 0.6);
}

.warn-card__btn:active {
    transform: scale(0.96);
}

.tips-card {
    padding: 18px;
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.06);
    backdrop-filter: blur(10px);
    animation: cardIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) 0.1s both;
}

.tips-card__title {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 11.5px;
    font-weight: 700;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 12px;
}

.tips-card__dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #7c6bff;
    box-shadow: 0 0 8px #7c6bff;
    animation: dotPulse 2s ease-in-out infinite;
}

.tips-card__list {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.tips-card__list li {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 12.5px;
    line-height: 1.5;
    color: #94a3b8;
}

.tips-card__list li svg {
    flex: none;
    color: #7c6bff;
    opacity: 0.8;
}

.tips-card__list li b {
    color: #c7bfff;
    font-weight: 600;
}

/* 全屏 */
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
.watch.is-fullscreen .voice-panel,
.watch.is-fullscreen .emotion-bar,
.watch.is-fullscreen .chat-drawer {
    display: none;
}

/* 过渡 */
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

.chat-drawer-enter-active,
.chat-drawer-leave-active {
    transition: transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.22s ease;
}

.chat-drawer-enter-from,
.chat-drawer-leave-to {
    transform: translateY(100%);
    opacity: 0;
}
</style>