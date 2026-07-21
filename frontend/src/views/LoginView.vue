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
      <p v-if="errorMsg" class="text-sm text-red-400">{{ errorMsg }}</p>
      <button type="submit" :disabled="submitting"
              class="w-full rounded bg-blue-600 py-2 font-medium hover:bg-blue-500 disabled:opacity-50">
        {{ submitting ? "登录中..." : "登录" }}
      </button>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useRouter } from "vue-router"
import { useAuthStore } from "../stores/auth"
import { HttpError } from "../api"

const auth = useAuthStore()
const router = useRouter()
const username = ref("")
const password = ref("")
const errorMsg = ref("")
const submitting = ref(false)

const CODE_MSG: Record<string, string> = {
  invalid_credentials: "用户名或密码错误",
  login_locked: "登录尝试过多，请稍后再试",
  network_error: "网络错误",
}

async function onSubmit() {
  errorMsg.value = ""
  submitting.value = true
  try {
    await auth.login(username.value, password.value)
    router.replace((router.currentRoute.value.query.next as string) || "/galleries")
  } catch (err) {
    if (err instanceof HttpError) {
      errorMsg.value = CODE_MSG[err.code] ?? err.message
    } else {
      errorMsg.value = "未知错误"
    }
  } finally {
    submitting.value = false
  }
}
</script>
