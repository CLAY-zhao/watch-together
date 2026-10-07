import { createRouter, createWebHashHistory } from 'vue-router'

import MainLayout from './views/MainLayout.vue'
import HomeTab from './views/HomeTab.vue'
import MemoryTab from './views/MemoryTab.vue'
import ProfileTab from './views/ProfileTab.vue'
import WatchView from './views/WatchView.vue'
import BroadcastView from './views/BroadcastView.vue'

/**
 * 根据运行环境决定默认首页
 * - 手机端（Android / iOS / Capacitor App）→ /home
 * - 电脑端（桌面浏览器 / PyWebView）→ /broadcast
 */
function getDefaultRoute() {
  const ua = (navigator.userAgent || '').toLowerCase()
  const isMobile = /android|iphone|ipad|ipod|mobile/.test(ua)
  const isNative = window.Capacitor?.isNativePlatform?.() || false

  if (isMobile || isNative) {
    return '/home'
  }
  return '/broadcast'
}

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    // ============ 手机端（带底部 Tab）============
    {
      path: '/',
      component: MainLayout,
      children: [
        { path: 'home', name: 'home', component: HomeTab },
        { path: 'memory', name: 'memory', component: MemoryTab },
        { path: 'profile', name: 'profile', component: ProfileTab },
      ],
    },

    // ============ 观看页 ============
    { path: '/watch', name: 'watch', component: WatchView },

    // ============ 投屏端 ============
    { path: '/broadcast', name: 'broadcast', component: BroadcastView },
  ],
})

// ★ 全局前置守卫：处理所有未匹配的路径 + 根路径智能分流
router.beforeEach((to, from, next) => {
  // 根路径（#/）或空路径 → 智能分流
  if (to.path === '/' || to.path === '') {
    return next(getDefaultRoute())
  }
  // 完全匹配不到任何路由 → 智能分流
  if (to.matched.length === 0) {
    return next(getDefaultRoute())
  }
  next()
})

export default router