import { createRouter, createWebHashHistory } from 'vue-router'
import HomeView from './views/HomeView.vue'
import BroadcastView from './views/BroadcastView.vue'
import WatchView from './views/WatchView.vue'

export default createRouter({
  // ★ 关键：用 hash 模式，Python 端不用配 SPA fallback
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/broadcast', name: 'broadcast', component: BroadcastView },
    { path: '/watch', name: 'watch', component: WatchView },
  ],
})