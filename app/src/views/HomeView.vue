<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()
const roomId = ref(
  (route.query.room || '').toString() ||
  localStorage.getItem('wt:last-room') ||
  ''
)

function enter() {
  const r = roomId.value.trim()
  if (!r) return
  localStorage.setItem('wt:last-room', r)
  router.push({ name: 'watch', query: { room: r } })
}
</script>

<template>
  <div class="home">
    <div class="bg-glow glow-1"></div>
    <div class="bg-glow glow-2"></div>

    <div class="home-wrap">
      <div class="brand">
        <div class="brand-logo">
          <svg viewBox="0 0 48 48" width="36" height="36">
            <path d="M16 12 L36 24 L16 36 Z" fill="#fff" />
          </svg>
        </div>
        <h1>一起看</h1>
        <p>与朋友同步观影 · 无需付费</p>
      </div>

      <div class="card">
        <label class="label">房间号</label>
        <div class="input-wrap">
          <input v-model="roomId" type="text" placeholder="例如 home" autocomplete="off" autocapitalize="off"
            autocorrect="off" spellcheck="false" @keyup.enter="enter" />
        </div>
        <button class="btn-primary" :disabled="!roomId.trim()" @click="enter">
          <span>进入房间</span>
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4"
            stroke-linecap="round" stroke-linejoin="round">
            <path d="M5 12h14M13 5l7 7-7 7" />
          </svg>
        </button>
      </div>

      <div class="footer-hint">
        <div class="dot-mini"></div>
        <span>电脑端打开投屏页面开始共享</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.home {
  position: relative;
  height: 100%;
  overflow: hidden;
  background:
    radial-gradient(1000px 500px at 80% -10%, rgba(124, 107, 255, .25), transparent 60%),
    radial-gradient(800px 600px at -20% 100%, rgba(79, 140, 255, .18), transparent 60%),
    var(--bg);
}

.bg-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: .55;
  pointer-events: none;
}

.glow-1 {
  width: 320px;
  height: 320px;
  top: -80px;
  right: -80px;
  background: radial-gradient(circle, #7c6bff, transparent 70%);
}

.glow-2 {
  width: 300px;
  height: 300px;
  bottom: -100px;
  left: -80px;
  background: radial-gradient(circle, #4f8cff, transparent 70%);
}

.home-wrap {
  position: relative;
  z-index: 1;
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: calc(env(safe-area-inset-top, 0px) + 60px) 24px calc(env(safe-area-inset-bottom, 0px) + 24px);
  max-width: 480px;
  margin: 0 auto;
  gap: 32px;
}

.brand {
  text-align: center;
  margin-bottom: 8px;
}

.brand-logo {
  width: 72px;
  height: 72px;
  margin: 0 auto 18px;
  border-radius: 22px;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 20px 50px -10px rgba(124, 107, 255, .6), inset 0 1px 0 rgba(255, 255, 255, .2);
}

.brand h1 {
  margin: 0;
  font-size: 30px;
  font-weight: 700;
  letter-spacing: -0.02em;
  background: linear-gradient(180deg, #fff, #b9b4ff);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.brand p {
  margin: 6px 0 0;
  color: var(--fg-2);
  font-size: 14px;
}

.card {
  background: var(--panel);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 20px 50px -20px rgba(0, 0, 0, .7), inset 0 1px 0 rgba(255, 255, 255, .05);
}

.label {
  font-size: 12px;
  color: var(--fg-2);
  font-weight: 500;
  letter-spacing: .03em;
  text-transform: uppercase;
}

.input-wrap {
  display: flex;
  align-items: center;
  background: rgba(0, 0, 0, .3);
  border: 1px solid var(--line);
  border-radius: 12px;
  transition: border-color .2s, background .2s;
}

.input-wrap:focus-within {
  border-color: var(--accent);
  background: rgba(124, 107, 255, .08);
}

.input-wrap input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  color: var(--fg);
  font-size: 17px;
  font-weight: 500;
  padding: 14px 16px;
  letter-spacing: .02em;
}

.input-wrap input::placeholder {
  color: var(--fg-3);
}

.footer-hint {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--fg-3);
  font-size: 12px;
}

.dot-mini {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 8px var(--ok);
  animation: pulse 2s infinite;
}

@keyframes pulse {

  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: .4;
  }
}
</style>