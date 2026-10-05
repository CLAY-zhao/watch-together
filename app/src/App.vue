<template>
  <router-view v-slot="{ Component }">
    <transition name="page" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>
</template>

<style>
/* ★ 全局黑底，杜绝灰色格子 */
html,
body,
#app {
  margin: 0;
  padding: 0;
  height: 100%;
  background: #000;
  color: #fff;
  overflow: hidden;
  overscroll-behavior: none;
  -webkit-tap-highlight-color: transparent;
}

* {
  box-sizing: border-box;
}

.page-enter-active,
.page-leave-active {
  transition: opacity .18s ease;
}

.page-enter-from,
.page-leave-to {
  opacity: 0;
}
</style>