<template>
  <div class="min-h-screen flex items-center justify-center px-4">
    <form class="w-full max-w-sm space-y-4 bg-neutral-900 rounded-lg p-6" @submit.prevent="onSubmit">
      <h1 class="text-xl font-semibold text-center">myPhotoGallery</h1>
      <label class="block">
        <span class="text-sm text-neutral-400">用户名</span>
        <input v-model="username" type="text" autocomplete="username" required
               class="mt-1 w-full rounded bg-neutral-800 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </label>
      <label class="block">
        <span class="text-sm text-neutral-400">密码</span>
        <input v-model="password" type="password" autocomplete="current-password" required
               class="mt-1 w-full rounded bg-neutral-800 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </label>
      <!-- P4: 按错误码渲染不同 banner 颜色 -->
      <div v-if="errorMsg"
           :class="['rounded px-3 py-2 text-sm', bannerClass]"
           role="alert">
        {{ errorMsg }}
      </div>
      <button type="submit" :disabled="submitting"
              class="w-full rounded bg-blue-600 py-2 font-medium hover:bg-blue-500 disabled:opacity-50">
        {{ submitting ? "登录中..." : "登录" }}
      </button>
    </form>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { useRouter } from "vue-router"
import { useAuthStore } from "../stores/auth"
import { HttpError, isAccessScopeViolation, errorMessage } from "../api"

const auth = useAuthStore()
const router = useRouter()
const username = ref("")
const password = ref("")
const errorMsg = ref("")
const errorKind = ref<"default" | "lan" | "locked">("default")
const submitting = ref(false)

const bannerClass = computed(() => {
  if (errorKind.value === "lan") return "bg-amber-950/40 text-amber-200 border border-amber-800/60"
  if (errorKind.value === "locked") return "bg-yellow-950/40 text-yellow-200 border border-yellow-800/60"
  return "bg-red-950/40 text-red-300 border border-red-800/60"
})

async function onSubmit() {
  errorMsg.value = ""
  errorKind.value = "default"
  submitting.value = true
  try {
    await auth.login(username.value, password.value)
    router.replace((router.currentRoute.value.query.next as string) || "/galleries")
  } catch (err) {
    if (err instanceof HttpError) {
      if (isAccessScopeViolation(err)) {
        errorKind.value = "lan"
      } else if (err.code === "login_locked") {
        errorKind.value = "locked"
      }
      errorMsg.value = errorMessage(err, "登录失败")
    } else {
      errorMsg.value = "未知错误"
    }
  } finally {
    submitting.value = false
  }
}
</script>
