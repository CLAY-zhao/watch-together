import { ref, onUnmounted } from 'vue'

const ICE_SERVERS = [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
    { urls: 'stun:stun.miwifi.com:3478' },
]

function getWsUrl(room, clientId) {
    const proto = location.protocol === 'https:' ? 'wss://' : 'ws://'
    return `${proto}${location.host}/ws/${encodeURIComponent(room)}/viewer/${clientId}`
}

function genClientId() {
    return Math.random().toString(36).slice(2, 10)
}

export function useViewer() {
    const status = ref('idle')       // idle | connecting | waiting | connected | failed | disconnected
    const hasMedia = ref(false)
    const playing = ref(false)
    const muted = ref(true)
    const videoEl = ref(null)

    let ws = null
    let pc = null
    let pendingIce = []
    let reconnectTimer = null
    let reconnectAttempts = 0
    let currentRoom = ''
    let intentionalClose = false

    const clientId = genClientId()

    function setStatus(v) { status.value = v }
    function getVideo() { return videoEl.value }

    // —— 解锁音频播放（必须在用户手势里调用）——
    function unlockAudio() {
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
        } catch (e) { /* ignore */ }
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
            // 带声音的自动播放被拦截 → 先静音播
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

    // 用户手势调用
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
            try { await v.play() } catch (e) { }
        }
    }

    function handleTrack(event) {
        const v = getVideo()
        if (!v) return
        const stream = (event.streams && event.streams[0]) || null
        if (stream) {
            if (v.srcObject !== stream) v.srcObject = stream
        } else {
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

    function send(msg) {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg))
    }

    async function handleOffer(sdp) {
        if (!pc) {
            pc = new RTCPeerConnection({ iceServers: ICE_SERVERS })
            pc.ontrack = handleTrack
            pc.onicecandidate = e => {
                if (e.candidate) send({ type: 'ice', candidate: e.candidate })
            }
            pc.onconnectionstatechange = () => {
                if (!pc) return
                const s = pc.connectionState
                if (s === 'connected') setStatus('connected')
                else if (s === 'failed') setStatus('failed')
                else if (s === 'disconnected') setStatus('disconnected')
            }
        }
        await pc.setRemoteDescription(new RTCSessionDescription(sdp))
        for (const c of pendingIce) {
            try { await pc.addIceCandidate(new RTCIceCandidate(c)) } catch (e) { }
        }
        pendingIce = []
        const answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        send({
            type: 'answer',
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
        const v = getVideo()
        if (v) v.srcObject = null
    }

    function closeWs() {
        if (ws) {
            try { ws.close() } catch (e) { }
            ws = null
        }
    }

    function scheduleReconnect() {
        clearTimeout(reconnectTimer)
        if (!currentRoom || intentionalClose) return
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 8000)
        reconnectAttempts++
        reconnectTimer = setTimeout(() => {
            if (currentRoom && !intentionalClose) joinInternal(currentRoom)
        }, delay)
    }

    function joinInternal(room) {
        closeWs()
        closePeer()
        setStatus('connecting')

        const v = getVideo()
        if (v) { v.muted = true; v.play().catch(() => { }) }

        ws = new WebSocket(getWsUrl(room, clientId))

        ws.onopen = () => {
            reconnectAttempts = 0
            setStatus('waiting')
        }
        ws.onerror = () => setStatus('failed')
        ws.onclose = () => {
            if (intentionalClose) return
            setStatus('disconnected')
            closePeer()
            scheduleReconnect()
        }
        ws.onmessage = async ev => {
            let msg; try { msg = JSON.parse(ev.data) } catch (e) { return }
            if (msg.type === 'offer') {
                await handleOffer(msg.sdp)
            } else if (msg.type === 'ice') {
                await handleRemoteIce(msg.candidate)
            } else if (msg.type === 'broadcaster-left') {
                setStatus('waiting')
                closePeer()
            }
        }
    }

    function join(room) {
        if (!room) return
        currentRoom = room
        intentionalClose = false
        reconnectAttempts = 0
        unlockAudio()
        joinInternal(room)
    }

    function leave() {
        intentionalClose = true
        clearTimeout(reconnectTimer)
        reconnectTimer = null
        currentRoom = ''
        reconnectAttempts = 0
        closeWs()
        closePeer()
        setStatus('idle')
    }

    onUnmounted(() => leave())

    return {
        status, hasMedia, playing, muted, videoEl,
        join, leave, userPlay, toggleMute,
    }
}