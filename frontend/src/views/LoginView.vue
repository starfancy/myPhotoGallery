<template>
  <main id="main-content" class="min-h-screen flex items-center justify-center px-4">
    <form class="w-full max-w-sm space-y-4 bg-surface rounded-lg p-6" @submit.prevent="onSubmit">
      <h1 class="text-xl font-semibold text-center">myPhotoGallery</h1>
      <label class="block">
        <span class="text-sm text-ink-2">用户名</span>
        <input v-model="username" type="text" autocomplete="username" required
               :aria-invalid="errorMsg ? true : undefined"
               :aria-describedby="errorMsg ? 'login-error' : undefined"
               class="mt-1 w-full rounded bg-surface-2 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary" />
      </label>
      <label class="block">
        <span class="text-sm text-ink-2">密码</span>
        <input v-model="password" type="password" autocomplete="current-password" required
               :aria-invalid="errorMsg ? true : undefined"
               :aria-describedby="errorMsg ? 'login-error' : undefined"
               class="mt-1 w-full rounded bg-surface-2 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary" />
      </label>
      <!-- P4: 按错误码渲染不同 banner 颜色 -->
      <div v-if="errorMsg"
           id="login-error"
           :class="['rounded px-3 py-2 text-sm', bannerClass]"
           role="alert">
        {{ errorMsg }}
      </div>
      <button type="submit" :disabled="submitting"
              class="min-h-11 w-full rounded bg-primary py-2 font-medium text-white hover:bg-primary-hover disabled:opacity-50 sm:w-auto sm:px-6">
        {{ submitting ? "登录中..." : "登录" }}
      </button>
    </form>
  </main>
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
  if (errorKind.value === "lan") return "bg-warning-soft/40 text-warning border border-warning-line/60"
  if (errorKind.value === "locked") return "bg-danger-soft text-danger-text border border-danger-line/60"
  return "bg-danger-soft/40 text-danger-text border border-danger-line/60"
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
