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
    <!-- ============ 背景装饰 ============ -->
    <div class="bg">
      <div class="bg__grid"></div>
      <div class="bg__glow bg__glow--1"></div>
      <div class="bg__glow bg__glow--2"></div>
      <div class="bg__glow bg__glow--3"></div>
    </div>

    <!-- ============ 内容 ============ -->
    <div class="content">

      <!-- 品牌 -->
      <header class="brand">
        <div class="brand__logo-wrap">
          <div class="brand__halo"></div>
          <div class="brand__logo">
            <svg viewBox="0 0 48 48" width="40" height="40">
              <path d="M18 13 L36 24 L18 35 Z" fill="#fff" />
            </svg>
          </div>
        </div>

        <h1 class="brand__name">一起看</h1>
        <p class="brand__slogan">与朋友同步观影，无需付费</p>
      </header>

      <!-- 房间卡片 -->
      <div class="card">
        <div class="card__row">
          <span class="card__index">01</span>
          <span class="card__label">房间号</span>
        </div>

        <div class="input-wrap">
          <span class="input-wrap__prefix">#</span>
          <input v-model="roomId" type="text" placeholder="例如 home" autocomplete="off" autocapitalize="off"
            autocorrect="off" spellcheck="false" @keyup.enter="enter" />
          <div class="input-wrap__glow"></div>
        </div>

        <button class="btn-primary" :disabled="!roomId.trim()" @click="enter">
          <span>进入房间</span>
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4"
            stroke-linecap="round" stroke-linejoin="round">
            <path d="M5 12h14M13 5l7 7-7 7" />
          </svg>
        </button>
      </div>

      <!-- 底部提示 -->
      <footer class="footer">
        <div class="footer__pulse"></div>
        <span>电脑端打开投屏页面开始共享</span>
      </footer>
    </div>
  </div>
</template>

<style scoped>
/* ============================================================
 *  基础
 * ============================================================ */
.home {
  position: relative;
  height: 100%;
  min-height: 100vh;
  min-height: 100dvh;
  overflow: hidden;
  background: #05070b;
  color: #f1f5f9;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
  -webkit-tap-highlight-color: transparent;
}

/* ============================================================
 *  背景层
 * ============================================================ */
.bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

/* 网格纹理 */
.bg__grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(124, 107, 255, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(124, 107, 255, 0.035) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse at 50% 40%, #000 30%, transparent 75%);
  -webkit-mask-image: radial-gradient(ellipse at 50% 40%, #000 30%, transparent 75%);
}

/* 光晕 */
.bg__glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.55;
}

.bg__glow--1 {
  width: 340px;
  height: 340px;
  top: -110px;
  right: -100px;
  background: radial-gradient(circle, #7c6bff 0%, transparent 70%);
  animation: drift1 18s ease-in-out infinite alternate;
}

.bg__glow--2 {
  width: 320px;
  height: 320px;
  bottom: -110px;
  left: -100px;
  background: radial-gradient(circle, #4f8cff 0%, transparent 70%);
  animation: drift2 22s ease-in-out infinite alternate;
}

.bg__glow--3 {
  width: 200px;
  height: 200px;
  top: 45%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: radial-gradient(circle, rgba(167, 139, 250, 0.6) 0%, transparent 70%);
  opacity: 0.3;
  animation: drift3 25s ease-in-out infinite alternate;
}

@keyframes drift1 {
  0% {
    transform: translate(0, 0) scale(1);
  }

  100% {
    transform: translate(-30px, 30px) scale(1.15);
  }
}

@keyframes drift2 {
  0% {
    transform: translate(0, 0) scale(1);
  }

  100% {
    transform: translate(30px, -30px) scale(1.15);
  }
}

@keyframes drift3 {
  0% {
    transform: translate(-50%, -50%) scale(1);
  }

  100% {
    transform: translate(-50%, -50%) scale(1.3);
  }
}

/* ============================================================
 *  内容布局
 * ============================================================ */
.content {
  position: relative;
  z-index: 1;
  height: 100%;
  min-height: 100vh;
  min-height: 100dvh;
  max-width: 480px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  padding: calc(env(safe-area-inset-top, 0px) + 40px) 24px calc(env(safe-area-inset-bottom, 0px) + 24px);
  gap: 32px;
}

/* ============================================================
 *  品牌
 * ============================================================ */
.brand {
  text-align: center;
  margin-top: 20px;
  animation: brandIn 0.8s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

@keyframes brandIn {
  0% {
    opacity: 0;
    transform: translateY(12px);
  }

  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

.brand__logo-wrap {
  position: relative;
  width: 96px;
  height: 96px;
  margin: 0 auto 22px;
  display: grid;
  place-items: center;
}

.brand__halo {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(124, 107, 255, 0.6) 0%, transparent 65%);
  animation: haloPulse 2.8s ease-in-out infinite;
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

.brand__logo {
  position: relative;
  width: 76px;
  height: 76px;
  border-radius: 24px;
  background: linear-gradient(135deg, #7c6bff 0%, #4f8cff 100%);
  display: grid;
  place-items: center;
  box-shadow:
    0 20px 50px -10px rgba(124, 107, 255, 0.7),
    0 0 0 1px rgba(255, 255, 255, 0.1) inset,
    0 1px 0 rgba(255, 255, 255, 0.25) inset;
  padding-left: 4px;
}

.brand__name {
  margin: 0;
  font-size: 34px;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.1;
  background: linear-gradient(180deg, #ffffff 0%, #b8b1ff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.brand__slogan {
  margin: 10px 0 0;
  font-size: 13.5px;
  color: #94a3b8;
  letter-spacing: 0.02em;
}

/* ============================================================
 *  房间卡片
 * ============================================================ */
.card {
  position: relative;
  background: rgba(255, 255, 255, 0.035);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 22px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow:
    0 30px 60px -20px rgba(0, 0, 0, 0.8),
    0 0 0 1px rgba(255, 255, 255, 0.04) inset,
    0 1px 0 rgba(255, 255, 255, 0.06) inset;
  animation: cardIn 0.8s cubic-bezier(0.34, 1.56, 0.64, 1) 0.1s both;
}

@keyframes cardIn {
  0% {
    opacity: 0;
    transform: translateY(16px);
  }

  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

.card__row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 4px;
}

.card__index {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: #7c6bff;
  font-variant-numeric: tabular-nums;
}

.card__label {
  font-size: 12px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

/* ============================================================
 *  输入框
 * ============================================================ */
.input-wrap {
  position: relative;
  display: flex;
  align-items: center;
  background: rgba(0, 0, 0, 0.42);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  overflow: hidden;
  transition: border-color 0.25s, background 0.25s;
}

.input-wrap:focus-within {
  border-color: rgba(124, 107, 255, 0.6);
  background: rgba(124, 107, 255, 0.06);
}

.input-wrap__prefix {
  padding: 0 4px 0 18px;
  font-size: 16px;
  font-weight: 700;
  color: #7c6bff;
  user-select: none;
}

.input-wrap input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  color: #f1f5f9;
  font-size: 17px;
  font-weight: 600;
  font-family: inherit;
  padding: 15px 18px 15px 8px;
  letter-spacing: 0.02em;
}

.input-wrap input::placeholder {
  color: #475569;
  font-weight: 500;
}

.input-wrap__glow {
  position: absolute;
  inset: 0;
  border-radius: 14px;
  pointer-events: none;
  opacity: 0;
  box-shadow: 0 0 0 4px rgba(124, 107, 255, 0.15),
    0 0 20px rgba(124, 107, 255, 0.3);
  transition: opacity 0.25s;
}

.input-wrap:focus-within .input-wrap__glow {
  opacity: 1;
}

/* ============================================================
 *  主按钮
 * ============================================================ */
.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  background: linear-gradient(135deg, #7c6bff 0%, #4f8cff 100%);
  color: #fff;
  border: none;
  border-radius: 14px;
  padding: 16px 20px;
  font-size: 15px;
  font-weight: 700;
  font-family: inherit;
  letter-spacing: 0.02em;
  cursor: pointer;
  box-shadow:
    0 14px 34px -8px rgba(124, 107, 255, 0.75),
    0 1px 0 rgba(255, 255, 255, 0.2) inset;
  transition: transform 0.15s, box-shadow 0.2s, opacity 0.2s;
}

.btn-primary:active:not(:disabled) {
  transform: scale(0.98);
  box-shadow:
    0 6px 18px -6px rgba(124, 107, 255, 0.7),
    0 1px 0 rgba(255, 255, 255, 0.2) inset;
}

.btn-primary:disabled {
  opacity: 0.45;
  box-shadow: none;
  cursor: not-allowed;
}

/* ============================================================
 *  底部
 * ============================================================ */
.footer {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #64748b;
  font-size: 12px;
  animation: cardIn 0.8s cubic-bezier(0.34, 1.56, 0.64, 1) 0.25s both;
}

.footer__pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 8px #22c55e;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {

  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }

  50% {
    opacity: 0.4;
    transform: scale(0.85);
  }
}
</style>