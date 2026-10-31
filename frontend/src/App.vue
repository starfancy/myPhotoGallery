<template>
  <div class="min-h-screen bg-base text-ink">
    <a href="#main-content" class="skip-link">跳到主内容</a>
    <RouterView />
    <ToastHost />
  </div>
</template>

<script setup lang="ts">
import ToastHost from "./components/ToastHost.vue"
</script>
