<template>
  <div>
    <AppHeader>
      <template #title><span class="text-ink-2">修改密码</span></template>
    </AppHeader>
    <main id="main-content" class="mx-auto max-w-sm p-4">
      <form @submit.prevent="onSubmit" class="space-y-4 rounded-lg bg-surface p-6">
        <div>
          <label class="block text-xs text-ink-2" for="cpw-old">当前密码</label>
          <input id="cpw-old" v-model="oldPassword" type="password" autocomplete="current-password" required
                 :aria-invalid="error ? true : undefined"
                 :aria-describedby="error ? 'cpw-error' : undefined"
                 class="mt-1 w-full rounded bg-surface-2 px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <div>
          <label class="block text-xs text-ink-2" for="cpw-new">新密码（至少 8 位）</label>
          <input id="cpw-new" v-model="newPassword" type="password" autocomplete="new-password" required minlength="8"
                 :aria-invalid="error ? true : undefined"
                 :aria-describedby="error ? 'cpw-error' : undefined"
                 class="mt-1 w-full rounded bg-surface-2 px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <div>
          <label class="block text-xs text-ink-2" for="cpw-confirm">确认新密码</label>
          <input id="cpw-confirm" v-model="confirmPassword" type="password" autocomplete="new-password" required
                 :aria-invalid="(error || mismatch) ? true : undefined"
                 :aria-describedby="confirmDescribedBy"
                 class="mt-1 w-full rounded bg-surface-2 px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <div v-if="mismatch" id="cpw-mismatch" class="text-xs text-danger-text" role="alert">
          两次输入的密码不一致
        </div>
        <div v-if="error" id="cpw-error" class="text-xs text-danger-text" role="alert">{{ error }}</div>
        <div v-if="success" class="text-xs text-success" role="status">密码已修改</div>
        <button type="submit" :disabled="submitting || !valid"
                class="min-h-11 w-full rounded bg-primary px-3 py-2 text-sm text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto">
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

const mismatch = computed(() =>
  !!confirmPassword.value && newPassword.value !== confirmPassword.value,
)
const confirmDescribedBy = computed(() =>
  [mismatch.value ? "cpw-mismatch" : null, error.value ? "cpw-error" : null]
    .filter(Boolean)
    .join(" ") || undefined,
)

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
