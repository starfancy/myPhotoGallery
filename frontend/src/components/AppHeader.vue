<template>
  <header class="sticky top-0 z-40 flex items-center gap-4 border-b border-line bg-surface/95 px-4 py-3 backdrop-blur">
    <router-link to="/galleries" class="font-semibold">myPhotoGallery</router-link>
    <div class="flex-1 min-w-0 overflow-hidden">
      <slot name="title"></slot>
    </div>
    <div v-if="auth.user" class="flex items-center gap-2 text-sm">
      <div v-if="auth.isAdmin" ref="adminMenuRef" class="relative">
        <button type="button"
          class="min-h-11 min-w-11 rounded px-2 py-1 text-ink-2 hover:bg-surface-2 hover:text-ink md:min-h-0 md:min-w-0"
          :class="{ 'bg-surface-2 text-ink': adminOpen }"
          :aria-expanded="adminOpen"
          aria-haspopup="menu"
          @click="adminOpen = !adminOpen">
          管理
        </button>
        <div v-if="adminOpen" role="menu"
             class="absolute right-0 top-full z-50 mt-1 min-w-40 overflow-hidden rounded-md border border-line bg-surface shadow-lg">
          <router-link to="/admin" role="menuitem"
            class="flex min-h-11 items-center px-3 py-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
            @click="adminOpen = false">
            概览
          </router-link>
          <router-link to="/admin/galleries" role="menuitem"
            class="flex min-h-11 items-center px-3 py-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
            @click="adminOpen = false">
            图库
          </router-link>
          <router-link to="/admin/trash" role="menuitem"
            class="flex min-h-11 items-center px-3 py-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
            @click="adminOpen = false">
            回收站
          </router-link>
          <router-link to="/admin/users" role="menuitem"
            class="flex min-h-11 items-center px-3 py-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
            @click="adminOpen = false">
            用户
          </router-link>
          <router-link to="/admin/audit" role="menuitem"
            class="flex min-h-11 items-center px-3 py-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
            @click="adminOpen = false">
            审计日志
          </router-link>
          <router-link to="/admin/settings" role="menuitem"
            class="flex min-h-11 items-center px-3 py-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
            @click="adminOpen = false">
            设置
          </router-link>
        </div>
      </div>
      <div ref="menuRef" class="relative">
        <button type="button"
          class="flex min-h-11 min-w-11 items-center gap-1 rounded px-2 py-1 text-ink-2 hover:bg-surface-2 hover:text-ink md:min-h-0 md:min-w-0"
          :class="{ 'bg-surface-2 text-ink': open }"
          :aria-expanded="open"
          aria-haspopup="menu"
          @click="open = !open">
          <!-- P4: 访问域徽标（依账号的 access_scope 属性；不是当前请求的源 IP） -->
          <span v-if="auth.accessScope === 'lan_only'"
                class="rounded bg-surface-3 px-1.5 py-0.5 text-xs font-medium text-ink"
                :title="`账号仅限局域网访问`">
            LAN
          </span>
          <span v-else-if="auth.accessScope === 'remote_allowed'"
                class="rounded bg-warning-soft/60 px-1.5 py-0.5 text-xs font-medium text-warning"
                :title="`账号允许远程访问`">
            远程
          </span>
          <span>{{ auth.user.username }}</span>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none"
               class="transition-transform"
               :class="{ 'rotate-180': open }"
               aria-hidden="true">
            <path d="M2.5 4.5 L6 8 L9.5 4.5" stroke="currentColor" stroke-width="1.5"
                  stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
        <div v-if="open" role="menu"
             class="absolute right-0 top-full z-50 mt-1 min-w-40 overflow-hidden rounded-md border border-line bg-surface shadow-lg">
          <router-link to="/settings/password" role="menuitem"
            class="flex min-h-11 items-center px-3 py-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
            @click="open = false">
            修改密码
          </router-link>
          <button type="button" role="menuitem"
            class="flex min-h-11 w-full items-center px-3 py-2 text-left text-ink-2 hover:bg-surface-2 hover:text-ink"
            @click="onLogout">
            登出
          </button>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { useAuthStore } from "../stores/auth"

const auth = useAuthStore()
const router = useRouter()

const open = ref(false)
const menuRef = ref<HTMLElement | null>(null)
const adminOpen = ref(false)
const adminMenuRef = ref<HTMLElement | null>(null)

function onDocClick(e: MouseEvent) {
  if (open.value) {
    const el = menuRef.value
    if (el && !el.contains(e.target as Node)) open.value = false
  }
  if (adminOpen.value) {
    const el = adminMenuRef.value
    if (el && !el.contains(e.target as Node)) adminOpen.value = false
  }
}
function onEsc(e: KeyboardEvent) {
  if (e.key === "Escape") {
    open.value = false
    adminOpen.value = false
  }
}
onMounted(() => {
  document.addEventListener("click", onDocClick)
  document.addEventListener("keydown", onEsc)
})
onBeforeUnmount(() => {
  document.removeEventListener("click", onDocClick)
  document.removeEventListener("keydown", onEsc)
})

async function onLogout() {
  open.value = false
  await auth.logout()
  router.replace("/login")
}
</script>
