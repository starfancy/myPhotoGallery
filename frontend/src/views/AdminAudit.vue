<template>
  <div>
    <AppHeader>
      <template #title><span class="text-ink-2">管理 · 审计日志</span></template>
    </AppHeader>
    <main class="space-y-4 p-4">
      <!-- 过滤工具条（Task 8 接入导出按钮） -->
      <div class="flex flex-wrap items-center gap-3">
        <label for="audit-action" class="text-sm text-ink-2">事件</label>
        <select id="audit-action" v-model="filterAction"
                class="rounded bg-surface-2 px-2 py-1 text-sm text-ink"
                @change="reload">
          <option :value="null">全部事件</option>
          <option v-for="label in actionOptions" :key="label.value" :value="label.value">
            {{ label.label }}
          </option>
        </select>

        <label for="audit-from" class="text-sm text-ink-2">起</label>
        <input id="audit-from" type="date" v-model="filterFrom"
               class="rounded bg-surface-2 px-2 py-1 text-sm text-ink" @change="reload">
        <label for="audit-to" class="text-sm text-ink-2">止</label>
        <input id="audit-to" type="date" v-model="filterTo"
               class="rounded bg-surface-2 px-2 py-1 text-sm text-ink" @change="reload">

        <button type="button" ref="exportBtn" disabled
                class="rounded bg-surface-2 px-3 py-1.5 text-sm text-ink-muted">
          导出 CSV
        </button>
      </div>

      <div v-if="loading" class="text-ink-2">加载中...</div>
      <div v-else-if="error" class="flex items-center gap-3 text-danger-text">
        <span>{{ error }}</span>
        <button type="button" class="rounded bg-surface-2 px-2 py-1 text-xs"
                @click="reload">重试</button>
      </div>
      <template v-else>
        <p v-if="entries.length === 0" class="text-sm text-ink-muted">暂无审计记录</p>
        <div v-else class="overflow-x-auto rounded-lg bg-surface">
          <table class="w-full min-w-[860px] text-left text-sm">
            <thead class="border-b border-line text-xs text-ink-muted">
              <tr>
                <th class="px-3 py-2">时间</th>
                <th class="px-3 py-2">操作人</th>
                <th class="px-3 py-2">IP</th>
                <th class="px-3 py-2">事件</th>
                <th class="px-3 py-2">目标</th>
                <th class="px-3 py-2">详情</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-for="e in entries" :key="e.id" class="hover:bg-surface-2/60">
                <td class="whitespace-nowrap px-3 py-2 text-xs">{{ formatDateTime(e.ts) }}</td>
                <td class="px-3 py-2">{{ actorLabel(e) }}</td>
                <td class="px-3 py-2 text-xs">{{ e.actor_ip }}</td>
                <td class="px-3 py-2">{{ auditActionLabel(e.action) }}</td>
                <td class="max-w-[200px] truncate px-3 py-2 font-mono text-xs" :title="e.target ?? ''">
                  {{ e.target ?? "" }}
                </td>
                <td class="max-w-[320px] truncate px-3 py-2 font-mono text-xs text-ink-muted"
                    :title="e.detail ?? ''">
                  {{ e.detail ?? "" }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="nextCursor !== null" class="text-center">
          <button type="button"
                  class="rounded bg-surface-2 px-3 py-1.5 text-sm hover:bg-surface-3 disabled:opacity-40"
                  :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? "加载中..." : "加载更多" }}
          </button>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { apiGet, HttpError } from "../api"
import { formatDateTime } from "../utils/datetime"
import { AUDIT_ACTION_LABELS, auditActionLabel } from "../utils/audit"

interface AuditEntry {
  id: number
  ts: number
  actor_user_id: number | null
  actor_ip: string
  action: string
  target: string | null
  detail: string | null
}
interface UserRow { id: number; username: string }

const PAGE_SIZE = 100

const entries = ref<AuditEntry[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(true)
const loadingMore = ref(false)
const error = ref("")

const filterAction = ref<string | null>(null)
const filterFrom = ref("")  // YYYY-MM-DD
const filterTo = ref("")

const users = ref<Map<number, string>>(new Map())
const usersFailed = ref(false)

// 事件下拉：全部 + 标签表（按中文标签排序便于查找）
const actionOptions = Object.entries(AUDIT_ACTION_LABELS)
  .map(([value, label]) => ({ value, label }))
  .sort((a, b) => a.label.localeCompare(b.label, "zh"))

function actorLabel(e: AuditEntry): string {
  if (e.actor_user_id === null) {
    return e.action === "login_fail" ? "匿名" : "系统"
  }
  const name = users.value.get(e.actor_user_id)
  if (name) return name
  return usersFailed.value ? `#${e.actor_user_id}` : `#${e.actor_user_id}（已删除）`
}

function dayBounds(value: string, end: boolean): number {
  const [y, m, d] = value.split("-").map(Number)
  const dt = new Date(y, m - 1, d, end ? 23 : 0, end ? 59 : 0, end ? 59 : 0)
  return Math.floor(dt.getTime() / 1000)
}

// pageSize 可覆盖：页面浏览 100，CSV 导出 500（Task 8 使用）。
function buildQuery(cursor: string | null, pageSize: number = PAGE_SIZE): string {
  const p = new URLSearchParams()
  p.set("limit", String(pageSize))
  if (filterAction.value) p.set("action", filterAction.value)
  if (filterFrom.value) p.set("from", String(dayBounds(filterFrom.value, false)))
  if (filterTo.value) p.set("to", String(dayBounds(filterTo.value, true)))
  if (cursor) p.set("cursor", cursor)
  return `?${p.toString()}`
}

// 单调请求令牌：过滤变化/重试会使在途旧响应失效。
let seq = 0
async function reload() {
  const my = ++seq
  loading.value = true
  error.value = ""
  try {
    const r = await apiGet<{ entries: AuditEntry[]; next_cursor: string | null }>(
      `/api/admin/audit${buildQuery(null)}`,
    )
    if (my !== seq) return
    entries.value = r.entries
    nextCursor.value = r.next_cursor
  } catch (err) {
    if (my === seq) error.value = (err as HttpError).message || "加载失败"
  } finally {
    if (my === seq) loading.value = false
  }
}

async function loadMore() {
  if (nextCursor.value === null) return
  const my = seq
  loadingMore.value = true
  try {
    const r = await apiGet<{ entries: AuditEntry[]; next_cursor: string | null }>(
      `/api/admin/audit${buildQuery(nextCursor.value)}`,
    )
    if (my !== seq) return
    entries.value.push(...r.entries)
    nextCursor.value = r.next_cursor
  } catch (err) {
    if (my === seq) error.value = (err as HttpError).message || "加载失败"
  } finally {
    if (my === seq) loadingMore.value = false
  }
}

async function loadUsers() {
  try {
    const rows = await apiGet<UserRow[]>("/api/admin/users")
    users.value = new Map(rows.map((r) => [r.id, r.username]))
  } catch {
    // 用户列表失败不阻断审计列表；操作人列回退显示 #id
    usersFailed.value = true
    users.value = new Map()
  }
}

// Task 8 接入导出时替换占位按钮；先暴露给测试/后续 task 的锚点。
const exportBtn = ref<HTMLElement | null>(null)

onMounted(async () => {
  await Promise.all([loadUsers(), reload()])
})
</script>
