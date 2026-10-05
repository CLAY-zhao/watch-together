<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useIceConfig } from '@/composables/useIceConfig'
import { getWsBase } from '@/config/backend'

const { iceServers, ensureIceReady } = useIceConfig()

const CLIENT_ID = Math.random().toString(36).slice(2, 10)
const WS_BASE = getWsBase()

/* ============================================================
 *  ★ 画质档位
 * ============================================================ */
const QUALITY_PRESETS = {
    high: { w: 3840, h: 2160, fps: 24, bitrate: 20_000_000, label: '高清 4K' },
    medium: { w: 2560, h: 1440, fps: 30, bitrate: 10_000_000, label: '清晰 2K' },
    low: { w: 1920, h: 1080, fps: 30, bitrate: 5_000_000, label: '流畅 1080p' },
}

/* ============================================================
 *  状态
 * ============================================================ */
const roomId = ref(localStorage.getItem('wt:room') || 'home')
const live = ref(false)
const viewerCount = ref(0)
const useMic = ref(true)
const shareUrl = ref('')
const errorMsg = ref('')
const copied = ref(false)
const hasAudio = ref(false)
const audioLevel = ref(0)
const starting = ref(false)
const voiceChatEnabled = ref(true)
const remoteVoiceActive = ref(false)
const soundEnabled = ref(true)
const qualityPreset = ref('medium')

/* 情绪弹幕 */
const emotions = ref([])

/* ★ 聊天 */
const chatMessages = ref([])
const chatInput = ref('')
const chatUnread = ref(0)
let chatListEl = null

function addChatMessage(msg) {
    chatMessages.value.push(msg)
    while (chatMessages.value.length > 200) {
        chatMessages.value.shift()
    }
    nextTick(() => {
        if (chatListEl) chatListEl.scrollTop = chatListEl.scrollHeight
    })
}

function sendChat() {
    const text = chatInput.value.trim()
    if (!text) return
    if (!bWs || bWs.readyState !== WebSocket.OPEN) return

    // 广播给所有 viewer
    for (const vid of bPeers.keys()) {
        sendB({
            type: 'chat',
            channel: 'chat',
            viewerId: vid,
            text,
        })
    }

    // 本地也显示
    addChatMessage({
        id: Date.now() + Math.random(),
        from: 'me',
        text,
        time: Date.now(),
    })

    chatInput.value = ''
}

function fmtChatTime(ts) {
    const d = new Date(ts)
    const h = String(d.getHours()).padStart(2, '0')
    const m = String(d.getMinutes()).padStart(2, '0')
    return `${h}:${m}`
}

/* 非响应式 */
let bWs = null
let bDisplay = null
let bMic = null
const bPeers = new Map()
const bAudioPeers = new Map()
const bRemoteAudioEls = new Map()
const audioPendingIce = new Map()

let audioCtx = null
let analyser = null
let rafId = 0

let emotionCleaner = null

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

function barHeight(n) {
    if (!hasAudio.value) return '4%'
    const base = audioLevel.value
    const wave = 0.5 + Math.sin(n / 1.8) * 0.5
    return Math.max(8, Math.min(100, base * (0.6 + wave * 0.6))) + '%'
}

/* ============================================================
 *  音波表
 * ============================================================ */
function stopAudioMeter() {
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0 }
    analyser = null
    if (audioCtx) { try { audioCtx.close() } catch (e) { } audioCtx = null }
    audioLevel.value = 0
}

function startAudioMeter(stream) {
    stopAudioMeter()
    const tracks = stream.getAudioTracks()
    if (!tracks.length) { hasAudio.value = false; return }
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
    } catch (e) { console.warn('[meter]', e) }
}

/* ============================================================
 *  提示音
 * ============================================================ */
let notifAudioCtx = null

function playNotifSound(combo = 1) {
    if (!soundEnabled.value) return
    try {
        if (!notifAudioCtx) {
            const AC = window.AudioContext || window.webkitAudioContext
            if (!AC) return
            notifAudioCtx = new AC()
        }
        if (notifAudioCtx.state === 'suspended') {
            notifAudioCtx.resume()
        }

        const ctx = notifAudioCtx
        const now = ctx.currentTime

        const freqs = [880, 1318.5]
        const peak = Math.min(0.18 / Math.sqrt(combo), 0.18)

        freqs.forEach((freq, i) => {
            const osc = ctx.createOscillator()
            const gain = ctx.createGain()

            osc.type = 'sine'
            osc.frequency.value = freq

            const start = now + i * 0.06

            gain.gain.setValueAtTime(0, start)
            gain.gain.linearRampToValueAtTime(peak, start + 0.01)
            gain.gain.exponentialRampToValueAtTime(0.001, start + 0.4)

            osc.connect(gain)
            gain.connect(ctx.destination)

            osc.start(start)
            osc.stop(start + 0.5)
        })
    } catch (e) {
        console.warn('[notif] 音效播放失败:', e)
    }
}

/* ============================================================
 *  分享链接
 * ============================================================ */
async function buildShareUrl() {
    let host = location.host
    if (location.hostname === '127.0.0.1' || location.hostname === 'localhost') {
        try {
            const r = await fetch('/api/lanip')
            const { ip } = await r.json()
            if (ip && ip !== '127.0.0.1') host = `${ip}:${location.port || 80}`
        } catch (e) { }
    }
    shareUrl.value = `${location.protocol}//${host}/#/watch?room=${encodeURIComponent(roomId.value)}`
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
    } catch (e) { }
}

/* ============================================================
 *  情绪弹幕
 * ============================================================ */
function addEmotion(payload) {
    playNotifSound(payload.combo || 1)

    const now = Date.now()
    const expireAt = now + 3000

    if (payload.combo > 1) {
        for (let i = emotions.value.length - 1; i >= 0; i--) {
            const item = emotions.value[i]
            if (item.emoji === payload.emoji && item.expireAt > now) {
                item.combo = payload.combo
                item.expireAt = expireAt
                item.bounce = false
                requestAnimationFrame(() => { item.bounce = true })
                return
            }
        }
    }

    emotions.value.push({
        id: Date.now() + Math.random(),
        emoji: payload.emoji || '🎬',
        label: payload.label || '',
        color: payload.color || '#7c6bff',
        combo: payload.combo || 1,
        expireAt,
        bounce: true,
    })

    while (emotions.value.length > 5) {
        emotions.value.shift()
    }
}

function startEmotionCleaner() {
    if (emotionCleaner) return
    emotionCleaner = setInterval(() => {
        const now = Date.now()
        emotions.value = emotions.value.filter(e => e.expireAt > now)
    }, 400)
}

function stopEmotionCleaner() {
    if (emotionCleaner) {
        clearInterval(emotionCleaner)
        emotionCleaner = null
    }
}

/* ============================================================
 *  WebSocket
 * ============================================================ */
function sendB(obj) {
    if (bWs && bWs.readyState === WebSocket.OPEN) {
        bWs.send(JSON.stringify(obj))
    }
}

/* ============================================================
 *  视频 PC
 * ============================================================ */
function closePeer(vid) {
    const pc = bPeers.get(vid)
    if (pc) {
        if (pc._statTimer) clearInterval(pc._statTimer)
        try { pc.close() } catch (e) { }
        bPeers.delete(vid)
    }
    viewerCount.value = bPeers.size
}

function closeAllPeers() {
    for (const vid of [...bPeers.keys()]) closePeer(vid)
}

async function makeOffer(vid) {
    closePeer(vid)

    const pc = new RTCPeerConnection({
        iceServers: iceServers.value,
        bundlePolicy: 'max-bundle',
        rtcpMuxPolicy: 'require',
    })
    bPeers.set(vid, pc)
    viewerCount.value = bPeers.size

    /* ★ 关键改动：用独立的 MediaStream 分离音频 */
    // stream A：屏幕视频 + 系统音频（电影声音）
    const displayStream = new MediaStream([...bDisplay.getTracks()])
    displayStream.getTracks().forEach(t => pc.addTrack(t, displayStream))

    // stream B：麦克风（语音），独立
    let micStreamId = null
    if (bMic) {
        const micStream = new MediaStream([...bMic.getTracks()])
        micStream.getTracks().forEach(t => pc.addTrack(t, micStream))
        micStreamId = micStream.id
        console.log('[stream] mic stream id:', micStreamId)
    }

    // ★ 提前通过 WebSocket 告知观看端 mic stream 的 id
    sendB({
        type: 'stream-info',
        channel: 'video',
        viewerId: vid,
        micStreamId,
    })

    const preset = QUALITY_PRESETS[qualityPreset.value] || QUALITY_PRESETS.medium

    /* 编码参数 */
    await new Promise(r => setTimeout(r, 0))
    for (const sender of pc.getSenders()) {
        if (!sender.track) continue
        try {
            const params = sender.getParameters()
            if (!params.encodings || params.encodings.length === 0) {
                params.encodings = [{}]
            }
            if (sender.track.kind === 'video') {
                params.encodings[0].maxBitrate = preset.bitrate
                params.encodings[0].maxFramerate = preset.fps
                params.degradationPreference = 'maintain-resolution'
            } else if (sender.track.kind === 'audio') {
                params.encodings[0].maxBitrate = 128_000
            }
            await sender.setParameters(params)
        } catch (e) {
            console.warn('[encoding]', e)
        }
    }

    /* 优先 H.264 */
    try {
        const caps = RTCRtpSender.getCapabilities('video')
        if (caps && caps.codecs) {
            const order = { 'video/H264': 0, 'video/VP9': 1, 'video/VP8': 2 }
            const sorted = [...caps.codecs].sort((a, b) => {
                const ka = order[`${a.kind}/${a.mimeType.split('/')[1]}`] ?? 99
                const kb = order[`${b.kind}/${b.mimeType.split('/')[1]}`] ?? 99
                return ka - kb
            })
            for (const t of pc.getTransceivers()) {
                if (t.sender && t.sender.track?.kind === 'video') {
                    t.setCodecPreferences(sorted)
                }
            }
        }
    } catch (e) {
        console.warn('[codec]', e)
    }

    pc.onicecandidate = e => {
        if (e.candidate) {
            sendB({ type: 'ice', channel: 'video', viewerId: vid, candidate: e.candidate })
        }
    }
    pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
            closePeer(vid)
        }
    }

    /* 状态打印 */
    let prevBytes = 0
    const statTimer = setInterval(async () => {
        if (!pc || pc.connectionState !== 'connected') return
        try {
            const stats = await pc.getStats()
            let outbound = null
            for (const r of stats.values()) {
                if (r.type === 'outbound-rtp' && r.kind === 'video') outbound = r
            }
            if (outbound) {
                const deltaBytes = (outbound.bytesSent || 0) - prevBytes
                prevBytes = outbound.bytesSent || 0
                const kbps = Math.round((deltaBytes * 8) / 1000 / 3)
                console.log(
                    `[stats] ${outbound.frameWidth}×${outbound.frameHeight}`,
                    `@${outbound.framesPerSecond}fps`,
                    `${kbps}kbps`,
                    `quality: ${outbound.qualityLimitationReason || 'none'}`
                )
            }
        } catch (e) { }
    }, 3000)
    pc._statTimer = statTimer

    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    sendB({
        type: 'offer', channel: 'video', viewerId: vid,
        sdp: { type: pc.localDescription.type, sdp: pc.localDescription.sdp },
    })
}

/* ============================================================
 *  语音 PC
 * ============================================================ */
function closeAudioPeer(vid) {
    const pc = bAudioPeers.get(vid)
    if (pc) { try { pc.close() } catch (e) { } bAudioPeers.delete(vid) }

    const el = bRemoteAudioEls.get(vid)
    if (el) {
        el.srcObject = null
        try { el.remove() } catch (e) { }
        bRemoteAudioEls.delete(vid)
    }

    audioPendingIce.delete(vid)
    if (bAudioPeers.size === 0) remoteVoiceActive.value = false
}

function closeAllAudioPeers() {
    for (const vid of [...bAudioPeers.keys()]) closeAudioPeer(vid)
}

async function handleAudioOffer(vid, sdp) {
    console.log('[voice] 收到语音 offer from', vid)

    if (!voiceChatEnabled.value) {
        sendB({ type: 'voice-rejected', viewerId: vid })
        return
    }

    closeAudioPeer(vid)

    const pc = new RTCPeerConnection({ iceServers: iceServers.value })
    bAudioPeers.set(vid, pc)
    audioPendingIce.set(vid, [])

    pc.addTransceiver('audio', { direction: 'recvonly' })

    pc.ontrack = event => {
        console.log('[voice] ontrack, kind=', event.track.kind)
        const stream = (event.streams && event.streams[0]) || null

        let el = bRemoteAudioEls.get(vid)
        if (!el) {
            el = new Audio()
            el.autoplay = true
            el.volume = 1
            el.setAttribute('playsinline', '')
            el.style.position = 'fixed'
            el.style.left = '-9999px'
            el.style.width = '1px'
            el.style.height = '1px'
            el.style.opacity = '0'
            document.body.appendChild(el)
            bRemoteAudioEls.set(vid, el)
        }

        if (stream) {
            el.srcObject = stream
            el.play()
                .then(() => {
                    console.log('[voice] 语音开始播放')
                    remoteVoiceActive.value = true
                })
                .catch(e => console.warn('[voice] play failed:', e))
        } else {
            let s = el.srcObject
            if (!(s instanceof MediaStream)) { s = new MediaStream(); el.srcObject = s }
            s.addTrack(event.track)
            el.play()
                .then(() => { remoteVoiceActive.value = true })
                .catch(e => console.warn('[voice] play failed:', e))
        }
    }

    pc.onicecandidate = e => {
        if (e.candidate) {
            sendB({ type: 'ice', channel: 'audio', viewerId: vid, candidate: e.candidate })
        }
    }

    pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
            closeAudioPeer(vid)
        }
    }

    await pc.setRemoteDescription(new RTCSessionDescription(sdp))

    const pending = audioPendingIce.get(vid) || []
    for (const c of pending) {
        try { await pc.addIceCandidate(new RTCIceCandidate(c)) } catch (e) { }
    }
    audioPendingIce.set(vid, [])

    const answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    sendB({
        type: 'answer', channel: 'audio', viewerId: vid,
        sdp: { type: pc.localDescription.type, sdp: pc.localDescription.sdp },
    })
}

async function handleAudioIce(vid, candidate) {
    const pc = bAudioPeers.get(vid)
    if (!pc) return
    if (!pc.remoteDescription) {
        const arr = audioPendingIce.get(vid) || []
        arr.push(candidate)
        audioPendingIce.set(vid, arr)
        return
    }
    try { await pc.addIceCandidate(new RTCIceCandidate(candidate)) } catch (e) { }
}

/* ============================================================
 *  WebSocket 消息
 * ============================================================ */
function connectWs() {
    const url = `${WS_BASE}/ws/${encodeURIComponent(roomId.value)}/broadcaster/${CLIENT_ID}`
    bWs = new WebSocket(url)

    bWs.onmessage = async ev => {
        let msg
        try { msg = JSON.parse(ev.data) } catch (e) { return }

        if (msg.type === 'emotion') {
            addEmotion(msg)
            return
        }

        /* ★ 聊天消息 */
        if (msg.type === 'chat' && (msg.channel === 'chat' || !msg.channel)) {
            addChatMessage({
                id: Date.now() + Math.random(),
                from: 'viewer',
                text: msg.text || '',
                time: Date.now(),
            })
            return
        }

        const channel = msg.channel || 'video'

        if (msg.type === 'viewer-joined') {
            try { await makeOffer(msg.viewerId) } catch (e) { }
        } else if (msg.type === 'viewer-left') {
            closePeer(msg.viewerId)
            closeAudioPeer(msg.viewerId)
        } else if (msg.type === 'offer' && channel === 'audio') {
            try { await handleAudioOffer(msg.viewerId, msg.sdp) } catch (e) { }
        } else if (msg.type === 'ice' && channel === 'audio') {
            await handleAudioIce(msg.viewerId, msg.candidate)
        } else if (msg.type === 'answer' && channel === 'video') {
            const pc = bPeers.get(msg.viewerId)
            if (pc) {
                try {
                    await pc.setRemoteDescription(new RTCSessionDescription(msg.sdp))
                    const pending = pc._pendingIce || []
                    pc._pendingIce = []
                    for (const c of pending) {
                        try { await pc.addIceCandidate(new RTCIceCandidate(c)) } catch (e) { }
                    }
                } catch (e) { }
            }
        } else if (msg.type === 'ice' && channel === 'video') {
            const pc = bPeers.get(msg.viewerId)
            if (pc) {
                if (!pc.remoteDescription) {
                    pc._pendingIce = pc._pendingIce || []
                    pc._pendingIce.push(msg.candidate)
                } else {
                    try { await pc.addIceCandidate(new RTCIceCandidate(msg.candidate)) } catch (e) { }
                }
            }
        }
    }

    bWs.onerror = () => { }
    bWs.onclose = () => {
        closeAllPeers()
        closeAllAudioPeers()
        if (live.value) setTimeout(() => { if (live.value) connectWs() }, 1500)
    }
}

function disconnectWs() {
    if (bWs) { try { bWs.close() } catch (e) { } bWs = null }
}

/* ============================================================
 *  开始/停止投屏
 * ============================================================ */
async function startBroadcast() {
    if (starting.value || live.value) return
    errorMsg.value = ''
    starting.value = true

    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
        errorMsg.value = '当前环境不支持屏幕共享'
        starting.value = false
        return
    }

    const preset = QUALITY_PRESETS[qualityPreset.value] || QUALITY_PRESETS.medium

    try {
        bDisplay = await navigator.mediaDevices.getDisplayMedia({
            video: {
                width: { ideal: preset.w, max: preset.w },
                height: { ideal: preset.h, max: preset.h },
                frameRate: { ideal: preset.fps, max: preset.fps },
            },
            audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        })
    } catch (e) {
        errorMsg.value = '已取消屏幕共享'
        starting.value = false
        return
    }

    /* ★ contentHint：告诉编码器"细节优先" */
    const videoTrack = bDisplay.getVideoTracks()[0]
    if (videoTrack && 'contentHint' in videoTrack) {
        videoTrack.contentHint = 'detail'
    }

    hasAudio.value = bDisplay.getAudioTracks().length > 0

    if (useMic.value) {
        try {
            bMic = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
            })
        } catch (e) { bMic = null }
    }

    const pv = document.getElementById('previewVideo')
    if (pv) {
        pv.srcObject = new MediaStream([
            ...bDisplay.getTracks(),
            ...(bMic ? bMic.getTracks() : []),
        ])
        pv.play().catch(() => { })
    }

    startAudioMeter(bDisplay)
    const vt = bDisplay.getVideoTracks()[0]
    if (vt) vt.addEventListener('ended', () => stopBroadcast())

    live.value = true
    starting.value = false
    connectWs()
}

function stopBroadcast() {
    if (!live.value) return
    live.value = false
    hasAudio.value = false
    remoteVoiceActive.value = false
    emotions.value = []

    closeAllPeers()
    closeAllAudioPeers()
    disconnectWs()

    if (bDisplay) { bDisplay.getTracks().forEach(t => t.stop()); bDisplay = null }
    if (bMic) { bMic.getTracks().forEach(t => t.stop()); bMic = null }

    stopAudioMeter()
    const pv = document.getElementById('previewVideo')
    if (pv) pv.srcObject = null
    viewerCount.value = 0
}

/* ============================================================
 *  生命周期
 * ============================================================ */
onMounted(async () => {
    try { await ensureIceReady() } catch (e) { }
    buildShareUrl()
    startEmotionCleaner()
})

onUnmounted(() => {
    stopBroadcast()
    stopAudioMeter()
    stopEmotionCleaner()
})
</script>

<template>
    <div class="app">
        <header class="topbar">
            <div class="brand">
                <div class="logo">
                    <svg viewBox="0 0 48 48" width="18" height="18">
                        <path d="M16 12 L36 24 L16 36 Z" fill="currentColor" />
                    </svg>
                </div>
                <div class="brand-text">
                    <strong>CoWatch</strong>
                    <span>投屏端</span>
                </div>
            </div>

            <div class="status">
                <span class="dot" :class="statusDot"></span>
                <span>{{ statusText }}</span>
            </div>

            <div v-if="live" class="voice-status" :class="{ active: remoteVoiceActive }">
                <span class="voice-dot"></span>
                <span>{{ remoteVoiceActive ? '对方正在说话' : (voiceChatEnabled ? '语音已开启' : '语音关闭') }}</span>
            </div>

            <div class="spacer"></div>

            <div class="viewer-badge" v-if="live">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                    <circle cx="9" cy="7" r="4" />
                </svg>
                <span>{{ viewerCount }} 位观众</span>
            </div>
        </header>

        <main class="main">
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

                <!-- 情绪弹幕层 -->
                <transition-group name="emotion" tag="div" class="emotion-layer">
                    <div v-for="e in emotions" :key="e.id" class="emotion-item" :class="{ 'is-bounce': e.bounce }"
                        :style="{ '--em-color': e.color }">
                        <div class="emotion-item__bar"></div>
                        <span class="emotion-item__emoji">{{ e.emoji }}</span>
                        <span class="emotion-item__label" v-if="e.label">{{ e.label }}</span>
                        <span class="emotion-item__combo" v-if="e.combo > 1">
                            ×{{ e.combo }}
                        </span>
                    </div>
                </transition-group>
            </section>

            <aside class="panel">
                <div class="card">
                    <label>房间号</label>
                    <input v-model="roomId" :disabled="live" @change="onRoomChange" spellcheck="false" />
                </div>

                <div class="card" v-if="shareUrl">
                    <label>分享链接</label>
                    <div class="share-row">
                        <input :value="shareUrl" readonly />
                        <button class="btn-copy" @click="copyShare">{{ copied ? '✓' : '复制' }}</button>
                    </div>
                </div>

                <!-- ★ 画质档位 -->
                <div class="card">
                    <label>画质档位</label>
                    <div class="quality-options">
                        <button v-for="(v, k) in QUALITY_PRESETS" :key="k" class="quality-option"
                            :class="{ 'is-active': qualityPreset === k }" :disabled="live" @click="qualityPreset = k">
                            {{ v.label }}
                        </button>
                    </div>
                </div>

                <label class="check-row">
                    <input type="checkbox" v-model="useMic" :disabled="live" />
                    <span>传输我的麦克风</span>
                </label>

                <label class="check-row">
                    <input type="checkbox" v-model="voiceChatEnabled" :disabled="live" />
                    <div class="check-text">
                        <span>接收对方的语音（双向对话）</span>
                        <span class="check-hint">打开后对方可点手机上的「语音」按钮</span>
                    </div>
                </label>

                <label class="check-row">
                    <input type="checkbox" v-model="soundEnabled" />
                    <div class="check-text">
                        <span>收到弹幕时播放提示音</span>
                        <span class="check-hint">对方发送情绪弹幕时，本机 "叮" 一声提醒</span>
                    </div>
                </label>

                <!-- ★ 聊天面板 -->
                <div class="chat-card">
                    <div class="chat-card__header">
                        <span class="chat-card__dot"></span>
                        <span class="chat-card__title">聊天</span>
                        <span class="chat-card__count">{{ chatMessages.length }}</span>
                    </div>

                    <div class="chat-card__list" ref="el => chatListEl = el">
                        <div v-if="chatMessages.length === 0" class="chat-card__empty">
                            对方的消息会显示在这里
                        </div>
                        <div v-for="m in chatMessages" :key="m.id" class="chat-bubble"
                            :class="{ 'chat-bubble--me': m.from === 'me' }">
                            <div class="chat-bubble__text">{{ m.text }}</div>
                            <div class="chat-bubble__time">{{ fmtChatTime(m.time) }}</div>
                        </div>
                    </div>

                    <div class="chat-card__input-wrap">
                        <input v-model="chatInput" type="text" placeholder="回复…" class="chat-card__input"
                            maxlength="200" @keyup.enter="sendChat" />
                        <button class="chat-card__send" :disabled="!chatInput.trim()" @click="sendChat">
                            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
                                stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
                            </svg>
                        </button>
                    </div>
                </div>

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
                    · 想双向语音，请勾上两个开关<br>
                    · <strong>强烈建议戴耳机</strong><br>
                    · 对方网络差时降到 2K 或 1080p
                </div>

                <div class="err" v-if="live && !hasAudio">
                    <b>⚠️ 未捕获到系统声音</b><br>
                    停止后重新共享，选「整个屏幕」+「分享系统音频」
                </div>

                <div class="err" v-if="errorMsg && !live">{{ errorMsg }}</div>
            </aside>
        </main>
    </div>
</template>

<style scoped>
.app {
    --bg: #0a0b0f;
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

/* ★ 聊天卡片 */
.chat-card {
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 14px;
    overflow: hidden;
    flex: 1;
    min-height: 240px;
    max-height: 400px;
}

.chat-card__header {
    flex: none;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 14px;
    border-bottom: 1px solid var(--line);
    font-size: 12px;
    font-weight: 700;
    color: var(--fg-2);
    letter-spacing: 0.06em;
    text-transform: uppercase;
}

.chat-card__dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #7c6bff;
    box-shadow: 0 0 8px #7c6bff;
    animation: dotPulse 2s ease-in-out infinite;
}

.chat-card__title {
    flex: 1;
}

.chat-card__count {
    padding: 2px 8px;
    border-radius: 999px;
    background: rgba(124, 107, 255, 0.15);
    color: #a89bff;
    font-size: 11px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
}

.chat-card__list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.chat-card__list::-webkit-scrollbar {
    width: 4px;
}

.chat-card__list::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 2px;
}

.chat-card__empty {
    padding: 20px 0;
    text-align: center;
    font-size: 12px;
    color: var(--fg-3);
}

.chat-bubble {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 3px;
    max-width: 88%;
    align-self: flex-start;
    padding: 8px 12px;
    border-radius: 12px;
    border-bottom-left-radius: 3px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    animation: bubbleIn 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.chat-bubble--me {
    align-self: flex-end;
    align-items: flex-end;
    border-bottom-left-radius: 12px;
    border-bottom-right-radius: 3px;
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    border: none;
    box-shadow: 0 6px 18px -6px rgba(124, 107, 255, 0.7);
}

.chat-bubble__text {
    font-size: 13px;
    line-height: 1.45;
    color: var(--fg);
    word-break: break-word;
    white-space: pre-wrap;
}

.chat-bubble--me .chat-bubble__text {
    color: #fff;
}

.chat-bubble__time {
    font-size: 10px;
    color: var(--fg-3);
    font-variant-numeric: tabular-nums;
}

.chat-bubble--me .chat-bubble__time {
    color: rgba(255, 255, 255, 0.75);
}

@keyframes bubbleIn {
    0% {
        opacity: 0;
        transform: translateY(6px) scale(0.96);
    }

    100% {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
}

.chat-card__input-wrap {
    flex: none;
    display: flex;
    gap: 8px;
    padding: 10px 12px;
    border-top: 1px solid var(--line);
    background: rgba(0, 0, 0, 0.2);
}

.chat-card__input {
    flex: 1;
    min-width: 0;
    background: rgba(0, 0, 0, 0.35);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 9px 13px;
    color: var(--fg);
    font-size: 13px;
    font-family: inherit;
    outline: none;
    transition: border-color 0.2s, background 0.2s;
}

.chat-card__input:focus {
    border-color: var(--accent);
    background: rgba(124, 107, 255, 0.08);
}

.chat-card__input::placeholder {
    color: var(--fg-3);
}

.chat-card__send {
    flex: none;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    color: #fff;
    border: none;
    display: grid;
    place-items: center;
    cursor: pointer;
    box-shadow: 0 6px 16px -6px rgba(124, 107, 255, 0.8);
    transition: transform 0.15s, opacity 0.2s;
}

.chat-card__send:active:not(:disabled) {
    transform: scale(0.92);
}

.chat-card__send:disabled {
    opacity: 0.35;
    box-shadow: none;
    cursor: not-allowed;
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

.topbar {
    flex: none;
    height: 56px;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 0 18px;
    background: rgba(10, 11, 15, 0.6);
    backdrop-filter: blur(20px);
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
    display: inline-block;
}

.dot.ok {
    background: var(--ok);
    box-shadow: 0 0 8px var(--ok);
}

.dot.warn {
    background: var(--warn);
    box-shadow: 0 0 8px var(--warn);
}

.dot.err {
    background: var(--danger);
    box-shadow: 0 0 8px var(--danger);
}

.voice-status {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    border-radius: 999px;
    background: var(--panel);
    border: 1px solid var(--line);
    font-size: 12px;
    color: var(--fg-2);
    transition: all 0.3s;
}

.voice-status.active {
    background: rgba(34, 197, 94, 0.12);
    border-color: rgba(34, 197, 94, 0.3);
    color: #86efac;
}

.voice-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #475569;
}

.voice-status.active .voice-dot {
    background: var(--ok);
    box-shadow: 0 0 8px var(--ok);
    animation: voicePulse 0.8s ease-in-out infinite;
}

@keyframes voicePulse {

    0%,
    100% {
        transform: scale(1);
        opacity: 1;
    }

    50% {
        transform: scale(1.4);
        opacity: 0.6;
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

.main {
    flex: 1;
    display: flex;
    min-height: 0;
}

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
}

.preview-empty p {
    font-size: 14px;
}

.preview-hud {
    position: absolute;
    left: 16px;
    bottom: 16px;
    z-index: 21;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    border-radius: 12px;
    background: rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(12px);
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

/* 情绪弹幕层 */
.emotion-layer {
    position: absolute;
    top: 20px;
    right: 20px;
    z-index: 20;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 8px;
    pointer-events: none;
    max-width: 280px;
}

.emotion-item {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px 10px 14px;
    background: rgba(5, 6, 10, 0.88);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 14px;
    box-shadow:
        0 12px 30px -10px rgba(0, 0, 0, 0.9),
        0 0 20px -8px var(--em-color),
        0 1px 0 rgba(255, 255, 255, 0.06) inset;
    overflow: hidden;
    transform-origin: right center;
}

.emotion-item__bar {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 3px;
    background: var(--em-color);
    box-shadow: 0 0 12px var(--em-color);
}

.emotion-item__emoji {
    font-size: 24px;
    line-height: 1;
    filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.4));
}

.emotion-item__label {
    font-size: 14px;
    font-weight: 700;
    color: #f1f5f9;
    letter-spacing: 0.02em;
}

.emotion-item__combo {
    display: inline-flex;
    align-items: center;
    padding: 3px 9px;
    border-radius: 999px;
    background: linear-gradient(135deg, var(--em-color), #4f8cff);
    color: #fff;
    font-size: 11.5px;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    box-shadow: 0 4px 12px -4px var(--em-color);
}

.emotion-enter-active {
    transition:
        opacity 0.35s cubic-bezier(0.34, 1.56, 0.64, 1),
        transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.emotion-enter-from {
    opacity: 0;
    transform: translateX(80px) scale(0.7);
}

.emotion-leave-active {
    transition: opacity 0.3s ease, transform 0.3s ease;
    position: absolute;
}

.emotion-leave-to {
    opacity: 0;
    transform: translateX(40px) scale(0.9);
}

.emotion-move {
    transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.emotion-item.is-bounce .emotion-item__emoji {
    animation: emojiBounce 0.4s ease-out;
}

@keyframes emojiBounce {
    0% {
        transform: scale(1);
    }

    40% {
        transform: scale(1.35);
    }

    70% {
        transform: scale(0.95);
    }

    100% {
        transform: scale(1);
    }
}

.emotion-item.is-bounce .emotion-item__combo {
    animation: comboPop 0.4s ease-out;
}

@keyframes comboPop {
    0% {
        transform: scale(0.6);
    }

    50% {
        transform: scale(1.25);
    }

    100% {
        transform: scale(1);
    }
}

/* 侧栏 */
.panel {
    width: 340px;
    flex: none;
    border-left: 1px solid var(--line);
    background: rgba(18, 20, 26, 0.6);
    backdrop-filter: blur(20px);
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
}

.card input:focus {
    border-color: var(--accent);
}

.card input:disabled {
    opacity: 0.55;
    cursor: not-allowed;
}

/* ★ 画质档位 */
.quality-options {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
}

.quality-option {
    padding: 10px 6px;
    border-radius: 10px;
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid var(--line);
    color: var(--fg-2);
    font-family: inherit;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
}

.quality-option:hover:not(:disabled) {
    border-color: var(--accent);
}

.quality-option.is-active {
    background: rgba(124, 107, 255, 0.2);
    border-color: var(--accent);
    color: #c7bfff;
    box-shadow: 0 0 12px rgba(124, 107, 255, 0.3);
}

.quality-option:disabled {
    opacity: 0.4;
    cursor: not-allowed;
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
    white-space: nowrap;
}

.btn-copy:hover {
    background: rgba(124, 107, 255, 0.15);
    border-color: var(--accent);
}

.check-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 14px;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 14px;
    cursor: pointer;
}

.check-row input {
    width: 16px;
    height: 16px;
    accent-color: var(--accent);
    cursor: pointer;
    flex: none;
}

.check-text {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 3px;
}

.check-text>span:first-child {
    font-size: 13px;
    color: var(--fg);
}

.check-hint {
    font-size: 11.5px;
    color: var(--fg-3);
    line-height: 1.4;
}

.btn-main,
.btn-stop {
    padding: 15px 20px;
    border-radius: 14px;
    font-size: 14px;
    font-weight: 600;
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

.tips strong {
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