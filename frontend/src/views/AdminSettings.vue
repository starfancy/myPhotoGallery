<template>
  <div>
    <AppHeader>
      <template #title>
        <span class="text-neutral-400">管理 · 设置</span>
      </template>
    </AppHeader>
    <main class="mx-auto max-w-2xl space-y-6 p-4">
      <div v-if="loading" class="text-neutral-400">加载中...</div>
      <template v-else>
        <div v-if="error"
             class="rounded bg-red-900/30 px-3 py-2 text-sm text-red-300">
          {{ error }}
        </div>

        <!-- 回收站 -->
        <section class="rounded-lg bg-neutral-900 p-4">
          <h2 class="mb-3 text-sm font-medium text-neutral-400">回收站</h2>
          <div class="mb-2 text-xs text-neutral-500">自动清理前的保留时长</div>
          <div class="flex flex-wrap gap-4 text-sm">
            <!-- 故意用 :checked + @click 而非 v-model：jsdom 分离挂载（detached mount）的
                 spec 不会触发 radio 的 change 事件，而 click 绑定同时覆盖点 label 与键盘
                 （空格/回车）激活。在同步更新 admin-settings.spec.ts 之前，不要“简化”回 v-model。 -->
            <label v-for="opt in RETENTION_OPTIONS" :key="opt.value"
                   class="flex cursor-pointer items-center gap-1.5">
              <input type="radio" name="retention" class="accent-blue-600"
                     :value="opt.value"
                     :checked="form.trash_retention_days === opt.value"
                     @click="form.trash_retention_days = opt.value">
              {{ opt.label }}
            </label>
          </div>
          <p class="mt-2 text-xs text-neutral-500">
            对新删除的图片生效；已在回收站中的条目到期时间不变。
          </p>
        </section>

        <!-- 登录安全 -->
        <section class="rounded-lg bg-neutral-900 p-4">
          <h2 class="mb-3 text-sm font-medium text-neutral-400">登录安全</h2>
          <label class="block text-xs text-neutral-500">
            登录失败锁定阈值（1–100 次）
          </label>
          <input v-model.number="form.login_lockout_threshold"
                 type="number" min="1" max="100"
                 class="mt-1 w-28 rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500">
          <p class="mt-2 text-xs text-neutral-500">
            连续登录失败达到此次数后将被临时锁定；锁定时长在 config.toml 中配置。
          </p>

          <label class="mt-4 block text-xs text-neutral-500">会话时长（1–720 小时）</label>
          <input v-model.number="form.session_hours"
                 type="number" min="1" max="720"
                 class="mt-1 w-28 rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500">
          <p class="mt-2 text-xs text-neutral-500">对新登录生效。</p>
        </section>

        <!-- 可信代理 -->
        <section class="rounded-lg bg-neutral-900 p-4">
          <h2 class="mb-3 text-sm font-medium text-neutral-400">
            可信代理（trusted_proxies）
          </h2>
          <div class="space-y-2">
            <div v-for="(_, i) in form.trusted_proxies" :key="i"
                 class="flex items-center gap-2">
              <input v-model="form.trusted_proxies[i]"
                     placeholder="如 127.0.0.1 或 10.0.0.0/8"
                     class="min-w-0 flex-1 rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500">
              <button type="button" @click="removeProxy(i)"
                      class="shrink-0 rounded bg-neutral-700 px-2 py-1 text-xs hover:bg-neutral-600">
                删除
              </button>
            </div>
          </div>
          <button type="button" @click="addProxy"
                  class="mt-2 rounded bg-neutral-700 px-2 py-1 text-xs hover:bg-neutral-600">
            + 添加
          </button>
          <p class="mt-2 text-xs text-neutral-500">
            仅这些来源（IP 或 CIDR）转发的 X-Forwarded-For 会被采纳；留空表示不信任任何代理。
          </p>
        </section>

        <div class="flex items-center gap-3">
          <button @click="save" :disabled="!dirty || saving"
                  class="rounded bg-blue-600 px-4 py-1.5 text-sm hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50">
            {{ saving ? "保存中..." : "保存" }}
          </button>
          <span v-if="savedOk" class="text-xs text-green-400">已保存</span>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { apiGet, apiPatch, HttpError } from "../api"

interface SettingsForm {
  trash_retention_days: number
  login_lockout_threshold: number
  trusted_proxies: string[]
  session_hours: number
}

const RETENTION_OPTIONS = [
  { value: 7, label: "7 天" },
  { value: 30, label: "30 天" },
  { value: 90, label: "90 天" },
  { value: 0, label: "永不" },
]

const loading = ref(true)
const saving = ref(false)
const error = ref("")
const savedOk = ref(false)
const form = ref<SettingsForm>({
  trash_retention_days: 30,
  login_lockout_threshold: 5,
  trusted_proxies: [],
  session_hours: 8,
})
const loadedJson = ref("")

const dirty = computed(() => JSON.stringify(normalized()) !== loadedJson.value)

function normalized(): SettingsForm {
  return {
    trash_retention_days: form.value.trash_retention_days,
    login_lockout_threshold: form.value.login_lockout_threshold,
    trusted_proxies: form.value.trusted_proxies.map((s) => s.trim()).filter(Boolean),
    session_hours: form.value.session_hours,
  }
}

/** 数字输入框本地校验：清空字段时 v-model.number 会得到 ""（Number("") 又是 0，
 *  不能只靠 Number.isFinite(Number(v))）；非法输入则保留为原始字符串（Number → NaN）。 */
function isFiniteInput(v: unknown): boolean {
  return v !== "" && Number.isFinite(Number(v))
}

function addProxy() {
  form.value.trusted_proxies.push("")
}

function removeProxy(i: number) {
  form.value.trusted_proxies.splice(i, 1)
}

async function load() {
  loading.value = true
  error.value = ""
  try {
    const data = await apiGet<SettingsForm>("/api/admin/settings")
    form.value = {
      trash_retention_days: data.trash_retention_days,
      login_lockout_threshold: data.login_lockout_threshold,
      trusted_proxies: [...data.trusted_proxies],
      session_hours: data.session_hours,
    }
    loadedJson.value = JSON.stringify(normalized())
  } catch (err) {
    error.value = (err as HttpError).message || "加载失败"
  } finally {
    loading.value = false
  }
}

async function save() {
  error.value = ""
  savedOk.value = false
  // 仅拦截“空值/非有限数”，避免后端回裸 422；超范围（如 9999）照常发送，
  // 让后端 400 的校验信息透传给用户，这里不做 min/max 预检。
  if (
    !isFiniteInput(form.value.login_lockout_threshold) ||
    !isFiniteInput(form.value.session_hours)
  ) {
    error.value = "请填写有效的数字：锁定阈值和会话时长不能为空。"
    return
  }
  saving.value = true
  const body = normalized()
  try {
    // 以响应体为权威状态重建表单：服务端会对 trusted_proxies 去重，
    // 本地 body 可能比响应多出重复行，直接用本地值会导致表单一直 dirty。
    const data = await apiPatch<SettingsForm>("/api/admin/settings", body)
    form.value = {
      trash_retention_days: data.trash_retention_days,
      login_lockout_threshold: data.login_lockout_threshold,
      trusted_proxies: [...data.trusted_proxies],
      session_hours: data.session_hours,
    }
    loadedJson.value = JSON.stringify(normalized())
    savedOk.value = true
  } catch (err) {
    error.value = (err as HttpError).message || "保存失败"
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
