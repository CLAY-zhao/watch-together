<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const TABS = [
    {
        key: 'home',
        label: '首页',
        path: '/home',
        icon: `<path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>`,
    },
    {
        key: 'memory',
        label: '回忆',
        path: '/memory',
        icon: `<path d="M12 2 15 8l7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z"/>`,
    },
    {
        key: 'profile',
        label: '我的',
        path: '/profile',
        icon: `<circle cx="12" cy="8" r="4"/><path d="M4 20a8 8 0 0 1 16 0"/>`,
    },
]

const activeKey = computed(() => {
    const p = route.path
    if (p.startsWith('/memory')) return 'memory'
    if (p.startsWith('/profile')) return 'profile'
    return 'home'
})

function go(tab) {
    if (route.path === tab.path) return
    router.push(tab.path)
}
</script>

<template>
    <div class="main-layout">
        <!-- 背景层 -->
        <div class="main-layout__bg">
            <div class="main-layout__glow main-layout__glow--1"></div>
            <div class="main-layout__glow main-layout__glow--2"></div>
            <div class="main-layout__grid"></div>
        </div>

        <!-- 内容区 -->
        <main class="main-layout__content">
            <router-view v-slot="{ Component }">
                <transition name="tab-fade" mode="out-in">
                    <component :is="Component" />
                </transition>
            </router-view>
        </main>

        <!-- 底部 Tab -->
        <nav class="tabbar">
            <div class="tabbar__bg"></div>

            <button v-for="t in TABS" :key="t.key" class="tab" :class="{ 'tab--active': activeKey === t.key }"
                @click="go(t)">
                <div class="tab__indicator" v-if="activeKey === t.key"></div>
                <svg class="tab__icon" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor"
                    stroke-width="2" stroke-linecap="round" stroke-linejoin="round" v-html="t.icon" />
                <span class="tab__label">{{ t.label }}</span>
            </button>
        </nav>
    </div>
</template>

<style scoped>
.main-layout {
    position: relative;
    width: 100%;
    height: 100vh;
    height: 100dvh;
    background: #05060a;
    color: #f1f5f9;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Microsoft YaHei", sans-serif;
    -webkit-font-smoothing: antialiased;
    -webkit-tap-highlight-color: transparent;
}

/* 背景 */
.main-layout__bg {
    position: absolute;
    inset: 0;
    pointer-events: none;
    overflow: hidden;
}

.main-layout__glow {
    position: absolute;
    border-radius: 50%;
    filter: blur(90px);
    opacity: 0.5;
}

.main-layout__glow--1 {
    width: 340px;
    height: 340px;
    top: -110px;
    right: -100px;
    background: radial-gradient(circle, #7c6bff 0%, transparent 70%);
    animation: drift1 18s ease-in-out infinite alternate;
}

.main-layout__glow--2 {
    width: 320px;
    height: 320px;
    bottom: 60px;
    left: -100px;
    background: radial-gradient(circle, #4f8cff 0%, transparent 70%);
    animation: drift2 22s ease-in-out infinite alternate;
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

.main-layout__grid {
    position: absolute;
    inset: 0;
    background-image:
        linear-gradient(rgba(124, 107, 255, 0.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(124, 107, 255, 0.035) 1px, transparent 1px);
    background-size: 44px 44px;
    mask-image: radial-gradient(ellipse at 50% 40%, #000 30%, transparent 75%);
    -webkit-mask-image: radial-gradient(ellipse at 50% 40%, #000 30%, transparent 75%);
}

/* 内容区 */
.main-layout__content {
    position: relative;
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 80px;
    /* 给 tabbar 留位置 */
}

.main-layout__content::-webkit-scrollbar {
    width: 0;
    display: none;
}

.main-layout__content {
    scrollbar-width: none;
}

/* Tab 栏 */
.tabbar {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 100;
    height: calc(66px + env(safe-area-inset-bottom, 0px));
    padding-bottom: env(safe-area-inset-bottom, 0px);
    display: flex;
    align-items: center;
    justify-content: space-around;
    background: rgba(10, 13, 18, 0.92);
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
    border-top: 1px solid rgba(124, 107, 255, 0.12);
}

.tabbar__bg {
    position: absolute;
    inset: 0;
    background:
        radial-gradient(400px 60px at 50% 0%, rgba(124, 107, 255, 0.12), transparent 70%);
    pointer-events: none;
}

.tab {
    position: relative;
    flex: 1;
    height: 66px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    background: transparent;
    border: none;
    color: #64748b;
    font-family: inherit;
    cursor: pointer;
    transition: color 0.2s, transform 0.15s;
}

.tab:active {
    transform: scale(0.92);
}

.tab--active {
    color: #a89bff;
}

.tab__indicator {
    position: absolute;
    top: 0;
    left: 50%;
    transform: translateX(-50%);
    width: 28px;
    height: 3px;
    border-radius: 0 0 3px 3px;
    background: linear-gradient(90deg, #7c6bff, #4f8cff);
    box-shadow: 0 2px 12px rgba(124, 107, 255, 0.8);
    animation: tabIn 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes tabIn {
    0% {
        transform: translateX(-50%) scaleX(0);
    }

    100% {
        transform: translateX(-50%) scaleX(1);
    }
}

.tab__icon {
    transition: transform 0.2s, filter 0.2s;
}

.tab--active .tab__icon {
    filter: drop-shadow(0 0 8px rgba(124, 107, 255, 0.8));
    transform: scale(1.1);
}

.tab__label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.02em;
}

/* 页面切换动画 */
.tab-fade-enter-active,
.tab-fade-leave-active {
    transition: opacity 0.2s ease, transform 0.2s ease;
}

.tab-fade-enter-from {
    opacity: 0;
    transform: translateY(8px);
}

.tab-fade-leave-to {
    opacity: 0;
    transform: translateY(-8px);
}
</style>