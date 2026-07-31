<template>
  <div>
    <AppHeader>
      <template #title><span class="text-neutral-400">管理 · 用户</span></template>
    </AppHeader>
    <main class="p-4 space-y-6">
      <div v-if="loading" class="text-neutral-400">加载中...</div>
      <div v-else-if="error" class="text-red-400">{{ error }}</div>
      <template v-else>
        <section class="flex items-center gap-2">
          <button @click="openCreate" data-testid="new-user-btn"
                  class="rounded bg-blue-600 px-3 py-2 text-sm hover:bg-blue-500">
            新建用户
          </button>
        </section>

        <section>
          <h2 v-if="users.length > 0" class="mb-2 text-sm font-medium text-neutral-400">
            {{ users.length }} 个用户
          </h2>
          <div v-else class="text-sm text-neutral-500">暂无用户</div>
          <div v-if="users.length > 0" class="overflow-hidden rounded-lg bg-neutral-900">
            <table class="w-full text-sm">
              <thead class="bg-neutral-800/60 text-left text-xs uppercase text-neutral-500">
                <tr>
                  <th class="px-3 py-2">用户名</th>
                  <th class="px-3 py-2">角色</th>
                  <th class="px-3 py-2">访问域</th>
                  <th class="px-3 py-2">启用</th>
                  <th class="px-3 py-2">图库</th>
                  <th class="px-3 py-2">最近登录</th>
                  <th class="px-3 py-2 text-right">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-neutral-800">
                <tr v-for="u in users" :key="u.id" :data-testid="`user-row-${u.username}`">
                  <td class="px-3 py-2 font-medium">{{ u.username }}</td>
                  <td class="px-3 py-2">
                    <span :class="u.role === 'admin' ? 'bg-purple-900/60 text-purple-200' : 'bg-neutral-700 text-neutral-200'"
                          class="rounded px-2 py-0.5 text-xs">
                      {{ u.role === "admin" ? "管理员" : "访客" }}
                    </span>
                  </td>
                  <td class="px-3 py-2">
                    <span :class="u.access_scope === 'lan_only'
                                   ? 'bg-neutral-700 text-neutral-200'
                                   : 'bg-orange-900/60 text-orange-200'"
                          class="rounded px-2 py-0.5 text-xs">
                      {{ u.access_scope === "lan_only" ? "LAN" : "远程" }}
                    </span>
                  </td>
                  <td class="px-3 py-2">
                    <span :class="u.enabled ? 'text-green-400' : 'text-neutral-500'">
                      {{ u.enabled ? "是" : "否" }}
                    </span>
                  </td>
                  <td class="px-3 py-2 text-neutral-400">{{ u.gallery_count }}</td>
                  <td class="px-3 py-2 text-xs text-neutral-500">
                    {{ u.last_login_at ? formatTs(u.last_login_at) : "—" }}
                  </td>
                  <td class="px-3 py-2 text-right">
                    <div class="flex justify-end gap-2">
                      <button @click="openEdit(u)"
                              :data-testid="`edit-btn-${u.username}`"
                              class="rounded bg-neutral-700 px-2 py-1 text-xs hover:bg-neutral-600">
                        编辑
                      </button>
                      <button @click="openResetPw(u)"
                              :data-testid="`resetpw-btn-${u.username}`"
                              class="rounded bg-neutral-700 px-2 py-1 text-xs hover:bg-neutral-600">
                        重置密码
                      </button>
                      <button @click="toggleEnabled(u)"
                              :data-testid="`toggle-btn-${u.username}`"
                              :disabled="u.id === currentUserId"
                              :class="u.enabled
                                       ? 'bg-yellow-800 hover:bg-yellow-700'
                                       : 'bg-green-800 hover:bg-green-700'"
                              class="rounded px-2 py-1 text-xs disabled:opacity-40">
                        {{ u.enabled ? "禁用" : "启用" }}
                      </button>
                      <button @click="confirmDelete(u)"
                              :data-testid="`delete-btn-${u.username}`"
                              :disabled="u.id === currentUserId"
                              class="rounded bg-red-800 px-2 py-1 text-xs hover:bg-red-700 disabled:opacity-40">
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </main>

    <!-- Create / Edit modal -->
    <div v-if="modal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
         @click.self="closeModal" data-testid="user-modal">
      <div class="w-full max-w-md rounded-lg bg-neutral-900 p-6">
        <h3 class="mb-4 text-lg font-medium">
          {{ modal.mode === "create" ? "新建用户" : "编辑用户" }}
        </h3>
        <div class="space-y-3">
          <label class="block">
            <span class="text-xs text-neutral-500">用户名 (3-32 字符)</span>
            <input v-model="modal.username" :disabled="modal.mode === 'edit'"
                   data-testid="modal-username"
                   class="mt-1 w-full rounded bg-neutral-800 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50" />
          </label>

          <div v-if="modal.mode === 'create'">
            <label class="block">
              <span class="text-xs text-neutral-500">密码 (留空 → 自动生成)</span>
              <input v-model="modal.password" type="password" data-testid="modal-password"
                     class="mt-1 w-full rounded bg-neutral-800 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500" />
            </label>
          </div>

          <fieldset>
            <legend class="text-xs text-neutral-500">角色</legend>
            <div class="mt-1 flex gap-4 text-sm">
              <label class="flex items-center gap-1.5">
                <input v-model="modal.role" type="radio" value="admin" data-testid="modal-role-admin" />
                管理员
              </label>
              <label class="flex items-center gap-1.5">
                <input v-model="modal.role" type="radio" value="viewer" data-testid="modal-role-viewer" />
                访客
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend class="text-xs text-neutral-500">访问域</legend>
            <div class="mt-1 flex gap-4 text-sm">
              <label class="flex items-center gap-1.5">
                <input v-model="modal.access_scope" type="radio" value="lan_only" />
                LAN
              </label>
              <label class="flex items-center gap-1.5">
                <input v-model="modal.access_scope" type="radio" value="remote_allowed" />
                远程
              </label>
            </div>
          </fieldset>

          <div v-if="modal.role === 'viewer'">
            <span class="text-xs text-neutral-500">授权图库 (多选)</span>
            <div v-if="allGalleries.length === 0" class="mt-1 text-xs text-neutral-500">
              尚无图库可选
            </div>
            <div v-else class="mt-1 max-h-40 space-y-1 overflow-y-auto rounded bg-neutral-800 p-2">
              <label v-for="g in allGalleries" :key="g.id"
                     class="flex items-center gap-2 text-sm">
                <input type="checkbox" :value="g.id" v-model="modal.gallery_ids"
                       :data-testid="`modal-gallery-${g.id}`" />
                {{ g.name }}
              </label>
            </div>
          </div>
          <div v-else class="text-xs text-neutral-500">
            管理员自动可见所有图库，无需授权
          </div>

          <div v-if="modal.error" class="text-sm text-red-400" data-testid="modal-error">
            {{ modal.error }}
          </div>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button @click="closeModal" class="rounded bg-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-600">
            取消
          </button>
          <button @click="submitModal" :disabled="modal.submitting"
                  data-testid="modal-submit"
                  class="rounded bg-blue-600 px-3 py-1.5 text-sm hover:bg-blue-500 disabled:opacity-50">
            {{ modal.submitting ? "提交中..." : (modal.mode === "create" ? "创建" : "保存") }}
          </button>
        </div>
      </div>
    </div>

    <!-- Reset password modal -->
    <div v-if="resetModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
         @click.self="closeResetModal" data-testid="reset-pw-modal">
      <div class="w-full max-w-md rounded-lg bg-neutral-900 p-6">
        <h3 class="mb-4 text-lg font-medium">重置密码 — {{ resetModal.username }}</h3>
        <label class="block">
          <span class="text-xs text-neutral-500">新密码 (留空 → 自动生成)</span>
          <input v-model="resetModal.password" type="password" data-testid="reset-pw-input"
                 class="mt-1 w-full rounded bg-neutral-800 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500" />
        </label>
        <div v-if="resetModal.error" class="mt-2 text-sm text-red-400">{{ resetModal.error }}</div>
        <div class="mt-5 flex justify-end gap-2">
          <button @click="closeResetModal" class="rounded bg-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-600">
            取消
          </button>
          <button @click="submitReset" :disabled="resetModal.submitting"
                  data-testid="reset-pw-submit"
                  class="rounded bg-blue-600 px-3 py-1.5 text-sm hover:bg-blue-500 disabled:opacity-50">
            {{ resetModal.submitting ? "重置中..." : "重置" }}
          </button>
        </div>
      </div>
    </div>

    <!-- Initial password / reset result modal (one-time display) -->
    <div v-if="revealModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
         @click.self="closeReveal" data-testid="reveal-pw-modal">
      <div class="w-full max-w-md rounded-lg bg-neutral-900 p-6">
        <h3 class="mb-2 text-lg font-medium">{{ revealModal.title }}</h3>
        <p class="mb-3 text-sm text-amber-300">
          {{ revealModal.subtitle }}
        </p>
        <div class="rounded bg-neutral-800 px-3 py-2 font-mono text-lg text-neutral-100"
             data-testid="reveal-pw-value">
          {{ revealModal.password }}
        </div>
        <div class="mt-5 flex justify-end">
          <button @click="closeReveal" data-testid="reveal-pw-close"
                  class="rounded bg-blue-600 px-3 py-1.5 text-sm hover:bg-blue-500">
            我已保存
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, computed } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { apiDelete, apiGet, apiPatch, apiPost, HttpError } from "../api"
import { useAuthStore } from "../stores/auth"

interface UserRow {
  id: number
  username: string
  role: "admin" | "viewer"
  access_scope: "lan_only" | "remote_allowed"
  enabled: number
  gallery_count: number
  last_login_at: number | null
  created_at: number
}

interface UserDetail extends UserRow {
  gallery_ids: number[]
}

interface GalleryOption {
  id: number
  name: string
}

type ModalMode = "create" | "edit"

interface UserModal {
  mode: ModalMode
  user_id: number | null
  username: string
  password: string
  role: "admin" | "viewer"
  access_scope: "lan_only" | "remote_allowed"
  gallery_ids: number[]
  submitting: boolean
  error: string
}

interface ResetPwModal {
  user_id: number
  username: string
  password: string
  submitting: boolean
  error: string
}

interface RevealModal {
  title: string
  subtitle: string
  password: string
}

const auth = useAuthStore()
const currentUserId = computed(() => auth.user?.id ?? null)

const users = ref<UserRow[]>([])
const allGalleries = ref<GalleryOption[]>([])
const loading = ref(true)
const error = ref("")

const modal = ref<UserModal | null>(null)
const resetModal = ref<ResetPwModal | null>(null)
const revealModal = ref<RevealModal | null>(null)

async function loadUsers() {
  loading.value = true
  error.value = ""
  try {
    const [u, g] = await Promise.all([
      apiGet<UserRow[]>("/api/admin/users"),
      apiGet<GalleryOption[]>("/api/admin/galleries"),
    ])
    users.value = u
    allGalleries.value = g
  } catch (err) {
    error.value = errorMessage(err, "加载失败")
  } finally {
    loading.value = false
  }
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof HttpError) return err.message || fallback
  return fallback
}

// ---- create / edit modal ----

function openCreate() {
  modal.value = {
    mode: "create",
    user_id: null,
    username: "",
    password: "",
    role: "viewer",
    access_scope: "remote_allowed",
    gallery_ids: [],
    submitting: false,
    error: "",
  }
}

async function openEdit(u: UserRow) {
  // fetch detail to get gallery_ids
  let detail: UserDetail
  try {
    detail = await apiGet<UserDetail>(`/api/admin/users/${u.id}`)
  } catch (err) {
    error.value = errorMessage(err, "加载详情失败")
    return
  }
  modal.value = {
    mode: "edit",
    user_id: u.id,
    username: detail.username,
    password: "",
    role: detail.role,
    access_scope: detail.access_scope,
    gallery_ids: detail.gallery_ids,
    submitting: false,
    error: "",
  }
}

function closeModal() {
  modal.value = null
}

async function submitModal() {
  if (!modal.value) return
  const m = modal.value
  if (m.username.trim().length < 3) {
    m.error = "用户名至少 3 个字符"
    return
  }
  m.submitting = true
  m.error = ""
  try {
    if (m.mode === "create") {
      const body: Record<string, unknown> = {
        username: m.username.trim(),
        role: m.role,
        access_scope: m.access_scope,
      }
      if (m.password) body.password = m.password
      if (m.role === "viewer") body.gallery_ids = m.gallery_ids
      const r = await apiPost<{ id: number; initial_password?: string }>("/api/admin/users", body)
      if (r.initial_password) {
        revealModal.value = {
          title: "用户已创建",
          subtitle: `「${m.username}」的初始密码（请安全转交给用户；此提示只显示一次）：`,
          password: r.initial_password,
        }
      }
    } else {
      const body: Record<string, unknown> = {
        role: m.role,
        access_scope: m.access_scope,
      }
      if (m.role === "viewer") body.gallery_ids = m.gallery_ids
      await apiPatch(`/api/admin/users/${m.user_id}`, body)
    }
    closeModal()
    await loadUsers()
  } catch (err) {
    m.error = errorMessage(err, "保存失败")
  } finally {
    m.submitting = false
  }
}

// ---- reset password modal ----

function openResetPw(u: UserRow) {
  resetModal.value = {
    user_id: u.id,
    username: u.username,
    password: "",
    submitting: false,
    error: "",
  }
}

function closeResetModal() {
  resetModal.value = null
}

async function submitReset() {
  if (!resetModal.value) return
  const m = resetModal.value
  m.submitting = true
  m.error = ""
  try {
    const body: Record<string, unknown> = {}
    if (m.password) body.new_password = m.password
    const r = await apiPost<{ new_password: string }>(
      `/api/admin/users/${m.user_id}/reset-password`,
      body,
    )
    revealModal.value = {
      title: "密码已重置",
      subtitle: `「${m.username}」的新密码（此提示只显示一次）：`,
      password: r.new_password,
    }
    closeResetModal()
  } catch (err) {
    m.error = errorMessage(err, "重置失败")
  } finally {
    m.submitting = false
  }
}

function closeReveal() {
  revealModal.value = null
}

// ---- enable / disable toggle ----

async function toggleEnabled(u: UserRow) {
  if (u.id === currentUserId.value) return  // cannot disable self
  const newEnabled = u.enabled ? 0 : 1
  try {
    await apiPatch(`/api/admin/users/${u.id}`, { enabled: newEnabled })
    u.enabled = newEnabled
  } catch (err) {
    error.value = errorMessage(err, "操作失败")
  }
}

// ---- delete with confirm ----

function confirmDelete(u: UserRow) {
  if (u.id === currentUserId.value) return
  const input = window.prompt(
    `删除用户「${u.username}」？\n此操作不可撤销。\n\n请输入用户名以确认：`,
  )
  if (input !== u.username) return
  apiDelete(`/api/admin/users/${u.id}`).then(
    () => loadUsers(),
    (err: unknown) => { error.value = errorMessage(err, "删除失败") },
  )
}

function formatTs(ts: number): string {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, "0")
  return (
    d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
    " " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds())
  )
}

onMounted(loadUsers)
</script>
