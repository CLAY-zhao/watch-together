<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { App as CapApp } from '@capacitor/app'
import { Capacitor } from '@capacitor/core'
import { getHistory, clearHistory, getStats } from '@/utils/watchHistory'

const router = useRouter()
const version = ref('1.0.0')
const stats = ref({ totalSessions: 0, totalHours: 0 })

onMounted(async () => {
    if (Capacitor.isNativePlatform()) {
        try {
            const info = await CapApp.getInfo()
            version.value = info.version || '1.0.0'
        } catch (e) { }
    } else {
        // 浏览器里从环境变量读
        version.value = import.meta.env.VITE_APP_VERSION || '1.0.0'
    }
    stats.value = getStats()
})

function handleClearHistory() {
    if (!confirm('确定清空所有观影记录吗？此操作不可恢复')) return
    clearHistory()
    stats.value = getStats()
    alert('已清空')
}

function goBack() {
    router.push('/home')
}
</script>

<template>
    <div class="profile-tab">

        <!-- 头部 -->
        <header class="profile-header">
            <h1 class="profile-header__title">👤 我的</h1>
        </header>

        <!-- 用户卡片 -->
        <div class="user-card">
            <div class="user-card__glow"></div>

            <div class="user-card__avatar">
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.8"
                    stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="8" r="4" />
                    <path d="M4 20a8 8 0 0 1 16 0" />
                </svg>
            </div>

            <div class="user-card__info">
                <div class="user-card__name">观影搭子</div>
                <div class="user-card__meta">
                    已看 {{ stats.totalSessions }} 部 · {{ stats.totalHours }} 小时
                </div>
            </div>
        </div>

        <!-- 设置 -->
        <section class="profile-section">
            <div class="profile-section__title">设置</div>

            <div class="menu-list">
                <div class="menu-item">
                    <div class="menu-item__icon">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M11 5 6 9H2v6h4l5 4V5z" />
                            <path d="M15.5 8.5a5 5 0 0 1 0 7" />
                        </svg>
                    </div>
                    <div class="menu-item__body">
                        <div class="menu-item__title">音量设置</div>
                        <div class="menu-item__sub">在观影页点 ⚙️ 设置</div>
                    </div>
                </div>

                <div class="menu-item">
                    <div class="menu-item__icon">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 2 15 8l7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z" />
                        </svg>
                    </div>
                    <div class="menu-item__body">
                        <div class="menu-item__title">成就进度</div>
                        <div class="menu-item__sub">在「回忆」页查看</div>
                    </div>
                </div>
            </div>
        </section>

        <!-- 数据 -->
        <section class="profile-section">
            <div class="profile-section__title">数据</div>

            <div class="menu-list">
                <div class="menu-item menu-item--danger" @click="handleClearHistory">
                    <div class="menu-item__icon">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="3 6 5 6 21 6" />
                            <path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6" />
                            <path d="M10 11v6M14 11v6" />
                        </svg>
                    </div>
                    <div class="menu-item__body">
                        <div class="menu-item__title">清空观影记录</div>
                        <div class="menu-item__sub">删除所有历史数据</div>
                    </div>
                </div>
            </div>
        </section>

        <!-- 关于 -->
        <section class="profile-section">
            <div class="profile-section__title">关于</div>

            <div class="menu-list">
                <div class="menu-item">
                    <div class="menu-item__icon">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="10" />
                            <line x1="12" y1="16" x2="12" y2="12" />
                            <line x1="12" y1="8" x2="12.01" y2="8" />
                        </svg>
                    </div>
                    <div class="menu-item__body">
                        <div class="menu-item__title">版本</div>
                        <div class="menu-item__sub">v{{ version }}</div>
                    </div>
                </div>

                <div class="menu-item">
                    <div class="menu-item__icon">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.5-7 10-7 10Z" />
                        </svg>
                    </div>
                    <div class="menu-item__body">
                        <div class="menu-item__title">关于 CoWatch</div>
                        <div class="menu-item__sub">与朋友同步观影，无需付费</div>
                    </div>
                </div>
            </div>
        </section>

        <!-- 底部 -->
        <p class="profile-footer">
            Made with 💜
        </p>

        <div style="height: 20px"></div>
    </div>
</template>

<style scoped>
.profile-tab {
    padding: calc(env(safe-area-inset-top, 0px) + 24px) 16px 24px;
    display: flex;
    flex-direction: column;
    gap: 18px;
    max-width: 480px;
    margin: 0 auto;
}

.profile-header__title {
    margin: 0;
    font-size: 26px;
    font-weight: 800;
    color: #f1f5f9;
    letter-spacing: -0.02em;
    padding: 0 4px;
}

/* 用户卡片 */
.user-card {
    position: relative;
    padding: 20px;
    border-radius: 20px;
    background: linear-gradient(135deg,
            rgba(124, 107, 255, 0.14) 0%,
            rgba(79, 140, 255, 0.08) 100%);
    border: 1px solid rgba(124, 107, 255, 0.28);
    display: flex;
    align-items: center;
    gap: 16px;
    overflow: hidden;
    box-shadow:
        0 20px 50px -20px rgba(124, 107, 255, 0.5),
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

.user-card__glow {
    position: absolute;
    top: -50%;
    left: -10%;
    width: 160px;
    height: 160px;
    background: radial-gradient(circle, rgba(124, 107, 255, 0.45) 0%, transparent 65%);
    filter: blur(40px);
    pointer-events: none;
}

.user-card__avatar {
    position: relative;
    width: 64px;
    height: 64px;
    flex: none;
    border-radius: 20px;
    display: grid;
    place-items: center;
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    color: #fff;
    box-shadow:
        0 12px 30px -8px rgba(124, 107, 255, 0.8),
        0 0 0 1px rgba(255, 255, 255, 0.12) inset;
}

.user-card__info {
    flex: 1;
    min-width: 0;
}

.user-card__name {
    font-size: 18px;
    font-weight: 700;
    color: #f1f5f9;
}

.user-card__meta {
    margin-top: 4px;
    font-size: 12px;
    color: #94a3b8;
}

/* 分区 */
.profile-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
    animation: cardIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) 0.05s both;
}

.profile-section__title {
    padding: 0 8px;
    font-size: 11.5px;
    font-weight: 700;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

.menu-list {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 16px;
    overflow: hidden;
}

.menu-item {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 16px;
    cursor: pointer;
    transition: background 0.15s;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.menu-item:last-child {
    border-bottom: none;
}

.menu-item:active {
    background: rgba(255, 255, 255, 0.04);
}

.menu-item__icon {
    width: 36px;
    height: 36px;
    flex: none;
    border-radius: 11px;
    display: grid;
    place-items: center;
    background: rgba(124, 107, 255, 0.12);
    border: 1px solid rgba(124, 107, 255, 0.22);
    color: #a89bff;
}

.menu-item--danger .menu-item__icon {
    background: rgba(255, 77, 109, 0.12);
    border-color: rgba(255, 77, 109, 0.3);
    color: #ff8ba0;
}

.menu-item__body {
    flex: 1;
    min-width: 0;
}

.menu-item__title {
    font-size: 14px;
    font-weight: 600;
    color: #f1f5f9;
}

.menu-item--danger .menu-item__title {
    color: #ff8ba0;
}

.menu-item__sub {
    font-size: 11.5px;
    color: #64748b;
    margin-top: 2px;
}

.profile-footer {
    text-align: center;
    font-size: 11.5px;
    color: #475569;
    margin: 12px 0 0;
    letter-spacing: 0.08em;
}
</style>