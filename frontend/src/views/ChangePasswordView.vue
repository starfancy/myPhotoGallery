<template>
  <div>
    <AppHeader>
      <template #title><span class="text-neutral-400">修改密码</span></template>
    </AppHeader>
    <main class="mx-auto max-w-sm p-4">
      <form @submit.prevent="onSubmit" class="space-y-4 rounded-lg bg-neutral-900 p-6">
        <div>
          <label class="block text-xs text-neutral-500">当前密码</label>
          <input v-model="oldPassword" type="password" autocomplete="current-password" required
                 class="mt-1 w-full rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500" />
        </div>
        <div>
          <label class="block text-xs text-neutral-500">新密码（至少 8 位）</label>
          <input v-model="newPassword" type="password" autocomplete="new-password" required minlength="8"
                 class="mt-1 w-full rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500" />
        </div>
        <div>
          <label class="block text-xs text-neutral-500">确认新密码</label>
          <input v-model="confirmPassword" type="password" autocomplete="new-password" required
                 class="mt-1 w-full rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500" />
        </div>
        <div v-if="confirmPassword && newPassword !== confirmPassword" class="text-xs text-red-400">
          两次输入的密码不一致
        </div>
        <div v-if="error" class="text-xs text-red-400">{{ error }}</div>
        <div v-if="success" class="text-xs text-green-400">密码已修改</div>
        <button type="submit" :disabled="submitting || !valid"
                class="w-full rounded bg-blue-600 px-3 py-2 text-sm hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50">
          {{ submitting ? "修改中..." : "修改密码" }}
        </button>
      </form>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { apiPost, HttpError } from "../api"

const oldPassword = ref("")
const newPassword = ref("")
const confirmPassword = ref("")
const submitting = ref(false)
const error = ref("")
const success = ref(false)

const valid = computed(() => {
  return (
    oldPassword.value.length > 0 &&
    newPassword.value.length >= 8 &&
    confirmPassword.value === newPassword.value
  )
})

async function onSubmit() {
  if (!valid.value) return
  submitting.value = true
  error.value = ""
  success.value = false
  try {
    await apiPost("/api/auth/change-password", {
      old_password: oldPassword.value,
      new_password: newPassword.value,
    })
    success.value = true
    oldPassword.value = ""
    newPassword.value = ""
    confirmPassword.value = ""
  } catch (err) {
    error.value = (err as HttpError).message || "修改失败"
  } finally {
    submitting.value = false
  }
}
</script>
