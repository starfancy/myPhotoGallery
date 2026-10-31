<template>
  <div class="min-h-screen bg-base text-ink">
    <RouterView />
    <ToastHost />
  </div>
</template>

<script setup lang="ts">
import ToastHost from "./components/ToastHost.vue"
</script>
