import { createRouter, createWebHashHistory } from 'vue-router'
import MainLayout from './views/MainLayout.vue'
import HomeTab from './views/HomeTab.vue'
import MemoryTab from './views/MemoryTab.vue'
import ProfileTab from './views/ProfileTab.vue'
import WatchView from './views/WatchView.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      component: MainLayout,
      children: [
        { path: '', redirect: '/home' },
        { path: 'home', name: 'home', component: HomeTab },
        { path: 'memory', name: 'memory', component: MemoryTab },
        { path: 'profile', name: 'profile', component: ProfileTab },
      ],
    },
    { path: '/watch', name: 'watch', component: WatchView },
    // 兜底
    { path: '/:pathMatch(.*)*', redirect: '/home' },
  ],
})