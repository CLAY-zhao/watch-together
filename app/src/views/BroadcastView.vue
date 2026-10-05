<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useIceConfig } from '@/composables/useIceConfig'
import { getWsBase } from '@/config/backend'

const { iceServers, ensureIceReady } = useIceConfig()

const CLIENT_ID = Math.random().toString(36).slice(2, 10)
const WS_BASE = getWsBase()

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
    if (pc) { try { pc.close() } catch (e) { } bPeers.delete(vid) }
    viewerCount.value = bPeers.size
}

function closeAllPeers() {
    for (const vid of [...bPeers.keys()]) closePeer(vid)
}

async function makeOffer(vid) {
    closePeer(vid)
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
            sendB({ type: 'ice', channel: 'video', viewerId: vid, candidate: e.candidate })
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
        type: 'offer', channel: 'video', viewerId: vid,
        sdp: { type: pc.localDescription.type, sdp: pc.localDescription.sdp },
    })
}

/* ============================================================
 *  ★★★ 语音 PC（关键修复）★★★
 * ============================================================ */
function closeAudioPeer(vid) {
    const pc = bAudioPeers.get(vid)
    if (pc) { try { pc.close() } catch (e) { } bAudioPeers.delete(vid) }

    // ★ 从 DOM 移除
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
    console.log('[voice] 📨 收到语音 offer from', vid)

    if (!voiceChatEnabled.value) {
        sendB({ type: 'voice-rejected', viewerId: vid })
        return
    }

    closeAudioPeer(vid)

    const pc = new RTCPeerConnection({ iceServers: iceServers.value })
    bAudioPeers.set(vid, pc)
    audioPendingIce.set(vid, [])

    // ★★★ 关键修复：显式声明"只接收音频" ★★★
    pc.addTransceiver('audio', { direction: 'recvonly' })
    console.log('[voice] ✅ 已添加 recvonly audio transceiver')

    pc.ontrack = event => {
        console.log('[voice] 📥 ontrack 触发, kind=', event.track.kind)

        const stream = (event.streams && event.streams[0]) || null

        let el = bRemoteAudioEls.get(vid)
        if (!el) {
            el = new Audio()
            el.autoplay = true
            el.volume = 1
            el.setAttribute('playsinline', '')
            // ★★★ 关键：挂到 DOM，隐藏起来 ★★★
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
                    console.log('[voice] ✅ 语音开始播放')
                    remoteVoiceActive.value = true
                })
                .catch(e => console.warn('[voice] 播放失败:', e))
        } else {
            let s = el.srcObject
            if (!(s instanceof MediaStream)) { s = new MediaStream(); el.srcObject = s }
            s.addTrack(event.track)
            el.play()
                .then(() => {
                    console.log('[voice] ✅ 语音开始播放（手动加 track）')
                    remoteVoiceActive.value = true
                })
                .catch(e => console.warn('[voice] 播放失败:', e))
        }
    }

    pc.onicecandidate = e => {
        if (e.candidate) {
            sendB({ type: 'ice', channel: 'audio', viewerId: vid, candidate: e.candidate })
        }
    }

    pc.onconnectionstatechange = () => {
        console.log('[voice] PC state:', pc.connectionState)
        if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
            closeAudioPeer(vid)
        }
    }

    await pc.setRemoteDescription(new RTCSessionDescription(sdp))
    console.log('[voice] ✅ remote description 已设置')

    const pending = audioPendingIce.get(vid) || []
    for (const c of pending) {
        try { await pc.addIceCandidate(new RTCIceCandidate(c)) } catch (e) { }
    }
    audioPendingIce.set(vid, [])

    const answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    console.log('[voice] ✅ answer 已创建并发送')

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
 *  WebSocket 消息处理
 * ============================================================ */
function connectWs() {
    const url = `${WS_BASE}/ws/${encodeURIComponent(roomId.value)}/broadcaster/${CLIENT_ID}`
    bWs = new WebSocket(url)

    bWs.onmessage = async ev => {
        let msg
        try { msg = JSON.parse(ev.data) } catch (e) { return }

        const channel = msg.channel || 'video'

        if (msg.type === 'viewer-joined') {
            try { await makeOffer(msg.viewerId) } catch (e) { console.warn(e) }
        } else if (msg.type === 'viewer-left') {
            closePeer(msg.viewerId)
            closeAudioPeer(msg.viewerId)
        } else if (msg.type === 'offer' && channel === 'audio') {
            try { await handleAudioOffer(msg.viewerId, msg.sdp) } catch (e) { console.warn(e) }
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

    bWs.onerror = () => console.warn('[ws] error')
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

    try {
        bDisplay = await navigator.mediaDevices.getDisplayMedia({
            video: { frameRate: { ideal: 30, max: 60 }, width: { ideal: 1920 }, height: { ideal: 1080 } },
            audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        })
    } catch (e) {
        errorMsg.value = '已取消屏幕共享'
        starting.value = false
        return
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

onMounted(async () => {
    try { await ensureIceReady() } catch (e) { }
    buildShareUrl()
})

onUnmounted(() => {
    stopBroadcast()
    stopAudioMeter()
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
                    <strong>一起看</strong>
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
                    · <b>强烈建议戴耳机</b>
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