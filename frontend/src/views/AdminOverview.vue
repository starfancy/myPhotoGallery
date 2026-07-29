<template>
  <!--
    Deviation from spec §7.5:
      Spec calls for "3 overview cards + 2 space cards (thumbnail cache /
      trash) + active-scan list + recent 20 audit". The plan (P2-9) revises
      this to 4 stat cards (images/galleries/roots/users) + scan list +
      audit + manage-galleries link. Space cards require backend fields
      (cache size on disk, trash count) that /api/admin/status does not
      return today — they land in a later phase together with AdminTrash.
      Section order below matches the plan: stats -> scan -> audit -> link.
  -->
  <div>
    <AppHeader>
      <template #title><span class="text-neutral-400">管理</span></template>
    </AppHeader>
    <main class="p-4 space-y-6">
      <div v-if="loading" class="text-neutral-400">加载中...</div>
      <div v-else-if="error" class="text-red-400">{{ error }}</div>
      <template v-else-if="data">
        <!-- Stats cards -->
        <section class="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div class="rounded-lg bg-neutral-900 p-4">
            <div class="text-xs text-neutral-500">图片</div>
            <div class="mt-1 text-2xl font-medium">{{ data.stats.images.toLocaleString() }}</div>
          </div>
          <div class="rounded-lg bg-neutral-900 p-4">
            <div class="text-xs text-neutral-500">图库</div>
            <div class="mt-1 text-2xl font-medium">{{ data.stats.galleries.toLocaleString() }}</div>
          </div>
          <div class="rounded-lg bg-neutral-900 p-4">
            <div class="text-xs text-neutral-500">根目录</div>
            <div class="mt-1 text-2xl font-medium">{{ data.stats.roots.toLocaleString() }}</div>
          </div>
          <div class="rounded-lg bg-neutral-900 p-4">
            <div class="text-xs text-neutral-500">用户</div>
            <div class="mt-1 text-2xl font-medium">{{ data.stats.users.toLocaleString() }}</div>
          </div>
        </section>

        <!-- Scan status list -->
        <section>
          <h2 class="mb-2 text-sm font-medium text-neutral-400">扫描状态</h2>
          <div v-if="data.scan_statuses.length === 0" class="text-sm text-neutral-500">
            暂无根目录
          </div>
          <ul v-else class="divide-y divide-neutral-800 rounded-lg bg-neutral-900">
            <li v-for="s in data.scan_statuses" :key="s.root_id"
                class="flex flex-col gap-1 p-3 sm:flex-row sm:items-center sm:justify-between">
              <div class="min-w-0 flex-1">
                <div class="font-medium">{{ s.label }}</div>
                <div class="truncate text-xs text-neutral-500" :title="s.absolute_path">
                  {{ s.absolute_path }}
                </div>
              </div>
              <div class="flex items-center gap-3 text-xs">
                <span :class="scanStatusClass(s.status)">
                  {{ scanStatusLabel(s.status) }}
                </span>
                <span v-if="s.last_scan_at" class="text-neutral-500">
                  {{ formatTs(s.last_scan_at) }}
                </span>
                <span v-if="s.last_scan_error" class="max-w-xs truncate text-red-400"
                      :title="s.last_scan_error">
                  {{ s.last_scan_error }}
                </span>
              </div>
            </li>
          </ul>
        </section>

        <!-- Recent audit -->
        <section>
          <h2 class="mb-2 text-sm font-medium text-neutral-400">最近审计 (20 条)</h2>
          <div v-if="data.recent_audit.length === 0" class="text-sm text-neutral-500">
            暂无审计记录
          </div>
          <ul v-else class="divide-y divide-neutral-800 rounded-lg bg-neutral-900">
            <li v-for="a in data.recent_audit" :key="a.id"
                class="flex flex-col gap-1 p-3 text-sm sm:flex-row sm:items-baseline sm:gap-4">
              <span class="w-32 shrink-0 text-xs text-neutral-500">{{ formatTs(a.ts) }}</span>
              <span class="w-24 shrink-0 font-medium">{{ actionLabel(a.action) }}</span>
              <span class="w-36 shrink-0 truncate text-xs text-neutral-500"
                    :title="a.actor_ip">{{ a.actor_ip }}</span>
              <span class="min-w-0 flex-1 truncate text-xs text-neutral-400"
                    :title="auditDetailText(a)">
                {{ auditDetailText(a) }}
              </span>
            </li>
          </ul>
        </section>

        <!-- Manage galleries link (moved to end per plan wording) -->
        <section class="flex flex-wrap gap-2">
          <router-link to="/admin/galleries"
            class="inline-flex items-center rounded bg-blue-600 px-3 py-2 text-sm hover:bg-blue-500">
            管理图库
          </router-link>
          <router-link to="/admin/trash"
            class="inline-flex items-center rounded bg-neutral-700 px-3 py-2 text-sm hover:bg-neutral-600">
            回收站
          </router-link>
        </section>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { apiGet, HttpError } from "../api"

interface Stats {
  images: number
  galleries: number
  roots: number
  users: number
}

interface ScanStatus {
  root_id: number
  gallery_id: number
  label: string
  absolute_path: string
  enabled: boolean
  status: string
  last_scan_at: number | null
  last_scan_status: string | null
  last_scan_error: string | null
}

interface AuditEntry {
  id: number
  ts: number
  actor_user_id: number | null
  actor_ip: string
  action: string
  target: string | null
  detail: string | null
}

interface StatusResponse {
  stats: Stats
  scan_statuses: ScanStatus[]
  recent_audit: AuditEntry[]
}

const data = ref<StatusResponse | null>(null)
const loading = ref(true)
const error = ref("")

onMounted(async () => {
  try {
    data.value = await apiGet<StatusResponse>("/api/admin/status")
  } catch (err) {
    error.value = (err as HttpError).message || "加载失败"
  } finally {
    loading.value = false
  }
})

// ---- display helpers ----

const ACTION_LABELS: Record<string, string> = {
  login_success: "登录",
  login_fail: "登录失败",
  user_create: "创建用户",
  user_delete: "删除用户",
  user_disable: "禁用用户",
  user_update: "更新用户",
  password_reset: "重置密码",
  gallery_create: "创建图库",
  gallery_delete: "删除图库",
  gallery_update: "更新图库",
  root_add: "添加根目录",
  root_remove: "移除根目录",
  root_update: "更新根目录",
  exclusion_add: "新增排除",
  exclusion_remove: "解除排除",
  image_delete: "删除图片",
  image_restore: "恢复图片",
  trash_purge: "清理回收站",
  thumb_cache_purge: "清理缩略图缓存",
  scan_start: "扫描开始",
  scan_finish: "扫描完成",
  scan_error: "扫描失败",
  fs_browse: "浏览目录",
  settings_update: "更新设置",
}

function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action
}

const SCAN_STATUS_LABELS: Record<string, string> = {
  idle: "空闲",
  queued: "排队中",
  running: "扫描中",
}

function scanStatusLabel(status: string): string {
  return SCAN_STATUS_LABELS[status] ?? status
}

function scanStatusClass(status: string): string {
  switch (status) {
    case "running":
      return "text-blue-400"
    case "queued":
      return "text-yellow-400"
    case "idle":
      return "text-green-400"
    default:
      return "text-neutral-400"
  }
}

function auditDetailText(a: AuditEntry): string {
  // Combine target and detail into a single string so the tooltip and
  // visible column show the same content even when the row is truncated.
  const parts: string[] = []
  if (a.target) parts.push(a.target)
  if (a.detail) parts.push(a.detail)
  return parts.join(" · ")
}

function formatTs(ts: number): string {
  // Server timestamps are Unix seconds; render as YYYY-MM-DD HH:mm:ss in
  // the viewer's local timezone.
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, "0")
  return (
    d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
    " " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds())
  )
}
</script>
