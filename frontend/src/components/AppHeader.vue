<template>
  <header class="sticky top-0 z-40 flex items-center gap-4 border-b border-neutral-800 bg-neutral-900/95 px-4 py-3 backdrop-blur">
    <router-link to="/galleries" class="font-semibold">myPhotoGallery</router-link>
    <div class="flex-1 min-w-0 overflow-hidden">
      <slot name="title"></slot>
    </div>
    <div v-if="auth.user" class="flex items-center gap-2 text-sm">
      <router-link v-if="auth.isAdmin" to="/admin"
        class="rounded px-2 py-1 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100">
        管理
      </router-link>
      <span class="text-neutral-400">{{ auth.user.username }}</span>
      <button class="rounded px-2 py-1 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100" @click="onLogout">
        登出
      </button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { useRouter } from "vue-router"
import { useAuthStore } from "../stores/auth"

const auth = useAuthStore()
const router = useRouter()

async function onLogout() {
  await auth.logout()
  router.replace("/login")
}
</script>
