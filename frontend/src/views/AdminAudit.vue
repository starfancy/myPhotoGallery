<template>
  <div>
    <AppHeader>
      <template #title><span class="text-ink-2">管理 · 审计日志</span></template>
    </AppHeader>
    <main class="space-y-4 p-4">
      <!-- 过滤工具条（sticky 贴在 69px 高的 AppHeader 之下——Task 9 后头部触发器为 44px 高） -->
      <div class="sticky top-[69px] z-30 -mx-4 flex flex-wrap items-center gap-3 bg-surface px-4 py-2">
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

        <!-- 导出中按钮即「取消」，必须保持可点：禁用态只在非导出时覆盖 loading/error/空。
             opacity-40 也按同一条件显式绑定，保证导出中按钮不发灰。 -->
        <button type="button"
                :class="[
                  'rounded bg-primary px-3 py-1.5 text-sm text-white',
                  exportDisabled
                    ? 'cursor-not-allowed opacity-40'
                    : 'cursor-pointer hover:bg-primary-hover',
                ]"
                :disabled="exportDisabled"
                @click="onExportClick">
          <template v-if="!exporting">导出 CSV</template>
          <template v-else>导出中…（已拉取 {{ exportCount }} 条）<span class="ml-1 underline">取消</span></template>
        </button>
      </div>

      <div v-if="loading" class="text-ink-2">加载中...</div>
      <!-- 替换式错误条仅限首页失败（尚无数据）；已有数据时失败不吞表格 -->
      <div v-else-if="error && entries.length === 0" class="flex items-center gap-3 text-danger-text">
        <span>{{ error }}</span>
        <button type="button" class="rounded bg-surface-2 px-2 py-1 text-xs"
                @click="reload">重试</button>
      </div>
      <template v-else>
        <p v-if="entries.length === 0" class="text-sm text-ink-muted">暂无审计记录</p>
        <template v-else>
          <!-- 过滤/重试失败但已有数据：行内错误条，重试走 reload -->
          <div v-if="error" class="mb-2 flex items-center gap-3 text-danger-text">
            <span>{{ error }}</span>
            <button type="button" class="rounded bg-surface-2 px-2 py-1 text-xs"
                    @click="reload">重试</button>
          </div>
          <div class="overflow-x-auto rounded-lg bg-surface">
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
        </template>

        <!-- reload/首页错误期间整块隐藏：旧游标不得与新过滤参数混用，
             重试由上方行内 reload 错误条承接（loadMoreError 仅在无 reload 错误时可达） -->
        <div v-if="nextCursor !== null && !error" class="space-y-2 text-center">
          <!-- 分页失败：错误条紧邻「加载更多」，重试带同一游标再拉一次 -->
          <div v-if="loadMoreError" class="flex items-center justify-center gap-3 text-danger-text">
            <span>{{ loadMoreError }}</span>
            <button type="button" class="rounded bg-surface-2 px-2 py-1 text-xs"
                    @click="loadMore">重试</button>
          </div>
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
import { computed, onMounted, ref } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { apiGet, errorMessage } from "../api"
import { formatDateTime } from "../utils/datetime"
import { AUDIT_ACTION_LABELS, auditActionLabel } from "../utils/audit"
import {
  auditCsvFilename, collectAuditCsv, AuditExportAborted, AuditExportLimitError,
  AUDIT_EXPORT_PAGE_SIZE,
} from "../utils/csv"
import { useToastStore } from "../stores/toast"

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
// 分页错误独立于首页错误：失败时不替换已加载的表格
const loadMoreError = ref("")

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
  loadMoreError.value = ""
  // 过滤变化/重试会使在途 loadMore 失效；其 finally 被 seq 令牌挡住，
  // 必须在这里复位，否则按钮会永久停在「加载中...」。
  loadingMore.value = false
  try {
    const r = await apiGet<{ entries: AuditEntry[]; next_cursor: string | null }>(
      `/api/admin/audit${buildQuery(null)}`,
    )
    if (my !== seq) return
    entries.value = r.entries
    nextCursor.value = r.next_cursor
  } catch (err) {
    if (my === seq) error.value = errorMessage(err, "加载失败")
  } finally {
    if (my === seq) loading.value = false
  }
}

async function loadMore() {
  if (nextCursor.value === null) return
  const my = seq
  loadingMore.value = true
  loadMoreError.value = ""
  try {
    const r = await apiGet<{ entries: AuditEntry[]; next_cursor: string | null }>(
      `/api/admin/audit${buildQuery(nextCursor.value)}`,
    )
    if (my !== seq) return
    entries.value.push(...r.entries)
    nextCursor.value = r.next_cursor
  } catch (err) {
    // 失败不推进 nextCursor：重试以同一游标再拉
    if (my === seq) loadMoreError.value = errorMessage(err, "加载失败")
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

const toast = useToastStore()
const exporting = ref(false)
const exportCount = ref(0)
let exportAbort: AbortController | null = null

// 非导出态：loading / 错误 / 空数据时禁用；导出态恒可点（按钮即取消入口）。
const exportDisabled = computed(() =>
  !exporting.value && (loading.value || !!error.value || entries.value.length === 0))

async function onExportClick() {
  if (exporting.value) { exportAbort?.abort(); return }
  exportAbort = new AbortController()
  exporting.value = true
  exportCount.value = 0
  // 过滤条件在导出开始时快照一次：多页拉取期间用户改过滤，后续页不得把新参数
  // 与旧游标混用；游标页仅在快照 query 上追加 cursor。
  const queryBase = buildQuery(null, AUDIT_EXPORT_PAGE_SIZE)
  try {
    const csv = await collectAuditCsv(
      (cursor, signal) =>
        apiGet<{ entries: AuditEntry[]; next_cursor: string | null }>(
          `/api/admin/audit${queryBase}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
          signal,
        ),
      { signal: exportAbort.signal, onProgress: (n) => (exportCount.value = n) },
    )
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = auditCsvFilename()
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (err) {
    // 纵深防御：即使错误类未被 collectAuditCsv 归一（如 api.ts 包装的
    // network_error），只要 abort 已触发就静默——取消后无文件、无错误 toast。
    if (err instanceof AuditExportAborted || exportAbort?.signal.aborted) {
      // 用户主动取消，静默
    } else if (err instanceof AuditExportLimitError) {
      toast.push("error", "最多导出 10,000 条，请收窄时间范围后重试")
    } else {
      toast.push("error", "导出失败")
    }
  } finally {
    exporting.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadUsers(), reload()])
})
</script>
