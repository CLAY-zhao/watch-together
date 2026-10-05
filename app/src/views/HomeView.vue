<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()

const roomId = ref(
  (route.query.room || '').toString() ||
  localStorage.getItem('wt:last-room') ||
  ''
)

const focused = ref(false)
const submitting = ref(false)
const canvasRef = ref(null)

let starsAnimId = null
let stars = []

/* ============================================================
 *  星空粒子背景（canvas 动画）
 * ============================================================ */
function initStars() {
  const canvas = canvasRef.value
  if (!canvas) return

  const ctx = canvas.getContext('2d')
  let w = 0
  let h = 0

  function resize() {
    w = canvas.width = canvas.offsetWidth * window.devicePixelRatio
    h = canvas.height = canvas.offsetHeight * window.devicePixelRatio
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio)
    w /= window.devicePixelRatio
    h /= window.devicePixelRatio
  }
  resize()
  window.addEventListener('resize', resize)

  const STAR_COUNT = 80
  const COLOR_POOL = [
    'rgba(124, 107, 255, ',   // 紫
    'rgba(79, 140, 255, ',    // 蓝
    'rgba(167, 139, 250, ',   // 浅紫
    'rgba(255, 255, 255, ',   // 白
  ]

  stars = Array.from({ length: STAR_COUNT }, () => ({
    x: Math.random() * w,
    y: Math.random() * h,
    r: Math.random() * 1.6 + 0.4,
    a: Math.random() * 0.6 + 0.2,
    vx: (Math.random() - 0.5) * 0.15,
    vy: (Math.random() - 0.5) * 0.15,
    twinkle: Math.random() * Math.PI * 2,
    color: COLOR_POOL[Math.floor(Math.random() * COLOR_POOL.length)],
  }))

  function tick() {
    ctx.clearRect(0, 0, w, h)

    for (const s of stars) {
      s.x += s.vx
      s.y += s.vy
      s.twinkle += 0.02

      if (s.x < 0) s.x = w
      if (s.x > w) s.x = 0
      if (s.y < 0) s.y = h
      if (s.y > h) s.y = 0

      const twinkleAlpha = s.a * (0.6 + Math.sin(s.twinkle) * 0.4)

      ctx.beginPath()
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
      ctx.fillStyle = s.color + twinkleAlpha + ')'
      ctx.fill()

      // 大星星加光晕
      if (s.r > 1.2) {
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.r * 3, 0, Math.PI * 2)
        ctx.fillStyle = s.color + (twinkleAlpha * 0.15) + ')'
        ctx.fill()
      }
    }

    starsAnimId = requestAnimationFrame(tick)
  }
  tick()
}

/* ============================================================
 *  进入房间
 * ============================================================ */
async function enter() {
  const r = roomId.value.trim()
  if (!r || submitting.value) return

  submitting.value = true
  localStorage.setItem('wt:last-room', r)

  // 300ms 延迟让按钮动画播完
  setTimeout(() => {
    router.push({ name: 'watch', query: { room: r } })
  }, 300)
}

/* ============================================================
 *  生命周期
 * ============================================================ */
onMounted(() => {
  initStars()
})

onUnmounted(() => {
  if (starsAnimId) cancelAnimationFrame(starsAnimId)
})
</script>

<template>
  <div class="home">
    <!-- ============ 背景层 ============ -->
    <div class="bg">
      <canvas ref="canvasRef" class="bg__stars"></canvas>

      <!-- 大光晕 -->
      <div class="bg__glow bg__glow--1"></div>
      <div class="bg__glow bg__glow--2"></div>
      <div class="bg__glow bg__glow--3"></div>

      <!-- 网格 -->
      <div class="bg__grid"></div>

      <!-- 胶片噪点 -->
      <div class="bg__noise"></div>
    </div>

    <!-- ============ 内容 ============ -->
    <div class="content">

      <!-- ===== 品牌区 ===== -->
      <header class="brand">
        <div class="brand__mark">
          <div class="brand__halo"></div>
          <div class="brand__halo brand__halo--2"></div>
          <div class="brand__logo">
            <!-- 播放三角 + 波纹 -->
            <svg viewBox="0 0 64 64" width="44" height="44">
              <defs>
                <linearGradient id="logoGrad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stop-color="#fff" />
                  <stop offset="100%" stop-color="#e0d9ff" />
                </linearGradient>
              </defs>
              <path d="M22 16 L48 32 L22 48 Z" fill="url(#logoGrad)" />
            </svg>
          </div>
        </div>

        <h1 class="brand__name">
          <span class="brand__name-c">Co</span><span class="brand__name-w">Watch</span>
        </h1>

        <p class="brand__slogan">
          <span class="brand__dot"></span>
          与朋友同步观影
        </p>
      </header>

      <!-- ===== 房间卡片 ===== -->
      <div class="card" :class="{ 'card--focused': focused }">
        <div class="card__shine"></div>

        <div class="card__header">
          <div class="card__step">
            <span class="card__step-num">01</span>
            <span class="card__step-line"></span>
          </div>
          <span class="card__label">Enter Room</span>
        </div>

        <div class="input-wrap" :class="{ 'is-focused': focused }">
          <span class="input-wrap__prefix">#</span>
          <input v-model="roomId" type="text" placeholder="房间号" autocomplete="off" autocapitalize="off"
            autocorrect="off" spellcheck="false" @focus="focused = true" @blur="focused = false" @keyup.enter="enter" />
          <div class="input-wrap__underline"></div>
        </div>

        <button class="btn-enter" :class="{ 'is-loading': submitting }" :disabled="!roomId.trim() || submitting"
          @click="enter">
          <span class="btn-enter__text">
            {{ submitting ? '进入中…' : '进入房间' }}
          </span>
          <svg v-if="!submitting" class="btn-enter__icon" viewBox="0 0 24 24" width="18" height="18" fill="none"
            stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M5 12h14M13 5l7 7-7 7" />
          </svg>
          <span v-else class="btn-enter__spinner"></span>
          <span class="btn-enter__shine"></span>
        </button>

        <div class="card__footer">
          <div class="card__hint">
            <span class="card__hint-dot"></span>
            从电脑端获取房间号
          </div>
        </div>
      </div>

      <!-- ===== 特性 ===== -->
      <div class="features">
        <div class="feature">
          <div class="feature__icon">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round">
              <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />
            </svg>
          </div>
          <span>低延迟</span>
        </div>
        <div class="feature__divider"></div>
        <div class="feature">
          <div class="feature__icon">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          </div>
          <span>点对点加密</span>
        </div>
        <div class="feature__divider"></div>
        <div class="feature">
          <div class="feature__icon">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2v20M2 12h20" />
              <circle cx="12" cy="12" r="9" />
            </svg>
          </div>
          <span>实时语音</span>
        </div>
      </div>

      <!-- ===== 底部 ===== -->
      <footer class="footer">
        <div class="footer__line"></div>
        <span class="footer__text">v1.0 · CoWatch</span>
        <div class="footer__line"></div>
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
  width: 100%;
  min-height: 100vh;
  min-height: 100dvh;
  overflow: hidden;
  background: #05060a;
  color: #f1f5f9;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
  -webkit-tap-highlight-color: transparent;
}

/* ============================================================
 *  背景
 * ============================================================ */
.bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.bg__stars {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.bg__glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(100px);
  opacity: 0.55;
  will-change: transform;
}

.bg__glow--1 {
  width: 380px;
  height: 380px;
  top: -140px;
  right: -120px;
  background: radial-gradient(circle, #7c6bff 0%, transparent 70%);
  animation: drift1 16s ease-in-out infinite alternate;
}

.bg__glow--2 {
  width: 340px;
  height: 340px;
  bottom: -120px;
  left: -100px;
  background: radial-gradient(circle, #4f8cff 0%, transparent 70%);
  animation: drift2 20s ease-in-out infinite alternate;
}

.bg__glow--3 {
  width: 260px;
  height: 260px;
  top: 40%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: radial-gradient(circle, rgba(255, 92, 141, 0.5) 0%, transparent 70%);
  opacity: 0.28;
  animation: drift3 24s ease-in-out infinite alternate;
}

@keyframes drift1 {
  0% {
    transform: translate(0, 0) scale(1);
  }

  100% {
    transform: translate(-40px, 40px) scale(1.18);
  }
}

@keyframes drift2 {
  0% {
    transform: translate(0, 0) scale(1);
  }

  100% {
    transform: translate(40px, -40px) scale(1.15);
  }
}

@keyframes drift3 {
  0% {
    transform: translate(-50%, -50%) scale(1);
  }

  100% {
    transform: translate(-50%, -50%) scale(1.35);
  }
}

/* 网格纹理 */
.bg__grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(124, 107, 255, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(124, 107, 255, 0.04) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(ellipse at 50% 35%, #000 20%, transparent 75%);
  -webkit-mask-image: radial-gradient(ellipse at 50% 35%, #000 20%, transparent 75%);
}

/* 噪点 */
.bg__noise {
  position: absolute;
  inset: 0;
  opacity: 0.03;
  mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='3'/></filter><rect width='200' height='200' filter='url(%23n)'/></svg>");
}

/* ============================================================
 *  内容布局
 * ============================================================ */
.content {
  position: relative;
  z-index: 1;
  min-height: 100vh;
  min-height: 100dvh;
  max-width: 440px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  padding: calc(env(safe-area-inset-top, 0px) + 44px) 24px calc(env(safe-area-inset-bottom, 0px) + 20px);
  gap: 26px;
}

/* ============================================================
 *  品牌区
 * ============================================================ */
.brand {
  text-align: center;
  animation: brandIn 0.9s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

@keyframes brandIn {
  0% {
    opacity: 0;
    transform: translateY(20px) scale(0.96);
  }

  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.brand__mark {
  position: relative;
  width: 104px;
  height: 104px;
  margin: 0 auto 20px;
  display: grid;
  place-items: center;
}

.brand__halo {
  position: absolute;
  inset: -12px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(124, 107, 255, 0.55) 0%, transparent 65%);
  animation: haloPulse 3.2s ease-in-out infinite;
}

.brand__halo--2 {
  inset: -24px;
  background: radial-gradient(circle, rgba(79, 140, 255, 0.35) 0%, transparent 65%);
  animation-delay: 1.6s;
  animation-duration: 4s;
}

@keyframes haloPulse {

  0%,
  100% {
    transform: scale(1);
    opacity: 0.65;
  }

  50% {
    transform: scale(1.18);
    opacity: 1;
  }
}

.brand__logo {
  position: relative;
  width: 84px;
  height: 84px;
  border-radius: 26px;
  background: linear-gradient(135deg, #7c6bff 0%, #4f8cff 100%);
  display: grid;
  place-items: center;
  padding-left: 5px;
  box-shadow:
    0 24px 60px -12px rgba(124, 107, 255, 0.85),
    0 0 0 1px rgba(255, 255, 255, 0.12) inset,
    0 1px 0 rgba(255, 255, 255, 0.35) inset;
  transition: transform 0.3s;
}

.brand__logo::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 26px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.15), transparent 50%);
  pointer-events: none;
}

.brand__name {
  margin: 0;
  font-size: 38px;
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 1.05;
  display: flex;
  justify-content: center;
  align-items: baseline;
}

.brand__name-c {
  background: linear-gradient(180deg, #ffffff 0%, #c7bfff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.brand__name-w {
  background: linear-gradient(180deg, #9b8fff 0%, #5a8fff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.brand__slogan {
  margin: 12px 0 0;
  font-size: 13px;
  color: #8b95a8;
  letter-spacing: 0.02em;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.brand__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 8px #22c55e;
  animation: dotPulse 2s ease-in-out infinite;
}

@keyframes dotPulse {

  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }

  50% {
    opacity: 0.5;
    transform: scale(0.85);
  }
}

/* ============================================================
 *  卡片
 * ============================================================ */
.card {
  position: relative;
  padding: 22px;
  background: rgba(255, 255, 255, 0.04);
  backdrop-filter: blur(28px) saturate(150%);
  -webkit-backdrop-filter: blur(28px) saturate(150%);
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow: hidden;
  transition: border-color 0.3s, box-shadow 0.3s;
  box-shadow:
    0 30px 60px -20px rgba(0, 0, 0, 0.85),
    0 1px 0 rgba(255, 255, 255, 0.06) inset;
  animation: cardIn 0.9s cubic-bezier(0.34, 1.56, 0.64, 1) 0.15s both;
}

@keyframes cardIn {
  0% {
    opacity: 0;
    transform: translateY(24px);
  }

  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

.card--focused {
  border-color: rgba(124, 107, 255, 0.45);
  box-shadow:
    0 30px 60px -20px rgba(0, 0, 0, 0.85),
    0 0 0 4px rgba(124, 107, 255, 0.08),
    0 1px 0 rgba(255, 255, 255, 0.06) inset;
}

/* 顶部流光 */
.card__shine {
  position: absolute;
  top: 0;
  left: -40%;
  width: 40%;
  height: 2px;
  background: linear-gradient(90deg,
      transparent,
      rgba(124, 107, 255, 0.8),
      rgba(79, 140, 255, 0.6),
      transparent);
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

.card__header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.card__step {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.card__step-num {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: #7c6bff;
  font-variant-numeric: tabular-nums;
}

.card__step-line {
  width: 24px;
  height: 1px;
  background: linear-gradient(90deg, #7c6bff, transparent);
}

.card__label {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.14em;
}

/* ============================================================
 *  输入框
 * ============================================================ */
.input-wrap {
  position: relative;
  display: flex;
  align-items: center;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  overflow: hidden;
  transition: border-color 0.25s, background 0.25s;
}

.input-wrap.is-focused {
  border-color: rgba(124, 107, 255, 0.6);
  background: rgba(124, 107, 255, 0.05);
}

.input-wrap__prefix {
  padding: 0 4px 0 18px;
  font-size: 17px;
  font-weight: 700;
  color: #7c6bff;
  user-select: none;
  transition: color 0.25s;
}

.input-wrap.is-focused .input-wrap__prefix {
  color: #a89bff;
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
  padding: 16px 18px 16px 8px;
  letter-spacing: 0.02em;
}

.input-wrap input::placeholder {
  color: #3f4a5c;
  font-weight: 500;
}

/* 底部滑动条 */
.input-wrap__underline {
  position: absolute;
  left: 50%;
  bottom: 0;
  width: 0;
  height: 2px;
  background: linear-gradient(90deg, #7c6bff, #4f8cff);
  border-radius: 1px;
  transform: translateX(-50%);
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.input-wrap.is-focused .input-wrap__underline {
  width: 100%;
}

/* ============================================================
 *  进入按钮
 * ============================================================ */
.btn-enter {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  background: linear-gradient(135deg, #7c6bff 0%, #4f8cff 100%);
  color: #fff;
  border: none;
  border-radius: 14px;
  padding: 17px 22px;
  font-size: 15px;
  font-weight: 700;
  font-family: inherit;
  letter-spacing: 0.02em;
  cursor: pointer;
  overflow: hidden;
  box-shadow:
    0 16px 40px -10px rgba(124, 107, 255, 0.8),
    0 1px 0 rgba(255, 255, 255, 0.2) inset;
  transition: transform 0.15s, box-shadow 0.2s, opacity 0.2s;
}

.btn-enter::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, #8b7aff 0%, #5f9aff 100%);
  opacity: 0;
  transition: opacity 0.2s;
}

.btn-enter:hover::before {
  opacity: 1;
}

.btn-enter:active:not(:disabled) {
  transform: scale(0.98);
  box-shadow:
    0 6px 20px -6px rgba(124, 107, 255, 0.7),
    0 1px 0 rgba(255, 255, 255, 0.2) inset;
}

.btn-enter:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  box-shadow: none;
}

.btn-enter__text,
.btn-enter__icon {
  position: relative;
  z-index: 1;
  transition: transform 0.2s;
}

.btn-enter:hover:not(:disabled) .btn-enter__icon {
  transform: translateX(4px);
}

/* 按钮流光 */
.btn-enter__shine {
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg,
      transparent,
      rgba(255, 255, 255, 0.28),
      transparent);
  animation: btnShine 2.6s ease-in-out infinite;
  pointer-events: none;
  z-index: 0;
}

@keyframes btnShine {
  0% {
    left: -100%;
  }

  50%,
  100% {
    left: 100%;
  }
}

/* spinner */
.btn-enter__spinner {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  animation: spin 0.8s linear infinite;
  position: relative;
  z-index: 1;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* ============================================================
 *  卡片底部提示
 * ============================================================ */
.card__footer {
  display: flex;
  justify-content: center;
  padding-top: 4px;
}

.card__hint {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
  color: #64748b;
}

.card__hint-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #7c6bff;
  box-shadow: 0 0 6px #7c6bff;
  animation: dotPulse 2s ease-in-out infinite;
}

/* ============================================================
 *  特性行
 * ============================================================ */
.features {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 0 4px;
  animation: cardIn 0.9s cubic-bezier(0.34, 1.56, 0.64, 1) 0.3s both;
}

.feature {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: #64748b;
  white-space: nowrap;
}

.feature__icon {
  width: 22px;
  height: 22px;
  border-radius: 7px;
  background: rgba(124, 107, 255, 0.1);
  border: 1px solid rgba(124, 107, 255, 0.18);
  display: grid;
  place-items: center;
  color: #7c6bff;
  flex: none;
}

.feature__divider {
  width: 1px;
  height: 12px;
  background: rgba(255, 255, 255, 0.06);
  margin: 0 8px;
}

/* ============================================================
 *  底部
 * ============================================================ */
.footer {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  animation: cardIn 0.9s cubic-bezier(0.34, 1.56, 0.64, 1) 0.45s both;
}

.footer__line {
  width: 36px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.12), transparent);
}

.footer__text {
  font-size: 11px;
  color: #3f4a5c;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 600;
}
</style>