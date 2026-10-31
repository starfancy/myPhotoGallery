<template>
  <div>
    <AppHeader>
      <template #title>
        <span class="text-ink-2">管理 · {{ galleryName || "图库" }}</span>
      </template>
    </AppHeader>
    <main class="p-4 space-y-6">
      <div v-if="loading" class="text-ink-2">加载中...</div>
      <div v-else-if="error" class="text-danger-text">{{ error }}</div>
      <template v-else-if="data">
        <!-- Back link -->
        <section>
          <router-link to="/admin/galleries"
                       class="text-xs text-ink-2 hover:text-ink">
            ← 返回图库列表
          </router-link>
        </section>

        <!-- Gallery edit form -->
        <section class="rounded-lg bg-surface p-4">
          <h2 class="mb-3 text-sm font-medium text-ink-2">图库信息</h2>
          <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div class="flex-1">
              <label class="block text-xs text-ink-muted">名称</label>
              <input v-model="editName"
                     class="mt-1 w-full rounded bg-surface-2 px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-primary" />
            </div>
            <div class="flex-1">
              <label class="block text-xs text-ink-muted">描述</label>
              <input v-model="editDescription"
                     class="mt-1 w-full rounded bg-surface-2 px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-primary" />
            </div>
            <button @click="saveGallery"
                    :disabled="saving"
                    class="shrink-0 rounded bg-primary px-4 py-1.5 text-sm text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50">
              {{ saving ? "保存中..." : "保存" }}
            </button>
          </div>
          <div v-if="saveSuccess" class="mt-2 text-xs text-success">已保存</div>
          <div v-if="saveError" class="mt-2 text-xs text-danger-text">{{ saveError }}</div>
        </section>

        <!-- Root cards -->
        <section>
          <h2 class="mb-2 text-sm font-medium text-ink-2">根目录</h2>
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div v-for="r in data.roots" :key="r.id"
                 class="flex flex-col gap-2 rounded-lg bg-surface p-4">
              <div class="font-medium">{{ r.label }}</div>
              <div class="truncate text-xs text-ink-muted" :title="r.absolute_path">{{ r.absolute_path }}</div>
              <div class="flex items-center gap-2 text-xs">
                <span>{{ r.image_count }} 张</span>
                <span :class="scanStatusClass(r.status)">{{ scanStatusLabel(r.status) }}</span>
                <span v-if="!r.enabled" class="text-warning">已禁用</span>
              </div>
              <div v-if="isRunning(r)" class="mt-1 space-y-1">
                <div class="h-1 w-full overflow-hidden rounded bg-surface-2"
                     role="progressbar"
                     :aria-valuemin="0"
                     :aria-valuemax="100"
                     :aria-valuenow="scanPercent(r)">
                  <div class="h-1 rounded bg-primary"
                       :style="{ width: scanPercent(r) + '%' }"></div>
                </div>
                <div class="flex items-center justify-between gap-2 text-xs text-ink-muted">
                  <span>{{ r.processed_files ?? 0 }} / {{ r.total_files ?? 0 }} ({{ scanPercent(r) }}%)</span>
                  <span v-if="r.current_path" class="truncate" :title="r.current_path">
                    {{ r.current_path }}
                  </span>
                </div>
              </div>
              <div v-if="r.last_scan_at" class="text-xs text-ink-muted">
                上次扫描: {{ formatTs(r.last_scan_at) }}
              </div>
              <div v-if="r.last_scan_error" class="truncate text-xs text-danger-text" :title="r.last_scan_error">
                {{ r.last_scan_error }}
              </div>
              <div class="mt-1 flex gap-2">
                <button @click="rescanRoot(r.id)"
                        class="rounded bg-surface-3 px-2 py-1 text-xs hover:bg-surface-4">
                  重扫
                </button>
                <button @click="toggleRoot(r.id, r.enabled)"
                        class="rounded bg-surface-3 px-2 py-1 text-xs hover:bg-surface-4">
                  {{ r.enabled ? "禁用" : "启用" }}
                </button>
                <button @click="toggleExclusions(r.id)"
                        class="rounded bg-surface-3 px-2 py-1 text-xs hover:bg-surface-4">
                  排除目录
                </button>
                <button @click="confirmRemoveRoot(r.id, r.label)"
                        class="ml-auto rounded bg-danger px-2 py-1 text-xs text-white hover:bg-danger-hover">
                  移除
                </button>
              </div>
              <div v-if="exclusionPanels[r.id]" class="mt-2 rounded bg-surface-2/50 p-2">
                <div v-if="exclusionsLoading[r.id]" class="text-xs text-ink-2">加载中...</div>
                <div v-else-if="exclusionsError[r.id]" class="text-xs text-danger-text">
                  {{ exclusionsError[r.id] }}
                </div>
                <template v-else>
                  <ul v-if="(exclusions[r.id] || []).length"
                      class="divide-y divide-line text-xs">
                    <li v-for="e in exclusions[r.id]" :key="e.id"
                        class="flex items-center gap-2 py-1.5">
                      <span class="min-w-0 flex-1 truncate font-mono" :title="e.relative_path">
                        {{ e.relative_path }}
                      </span>
                      <span v-if="e.reason" class="truncate text-ink-muted" :title="e.reason">
                        {{ e.reason }}
                      </span>
                      <span class="shrink-0 text-ink-muted">{{ e.excluded_by_username || "—" }}</span>
                      <span class="shrink-0 text-ink-muted">排除于 {{ formatDateTime(e.excluded_at) }}</span>
                      <button @click="removeExclusion(r, e)"
                              class="shrink-0 rounded bg-surface-3 px-2 py-0.5 hover:bg-surface-4">
                        解除
                      </button>
                    </li>
                  </ul>
                  <div v-else class="py-1 text-xs text-ink-muted">尚未排除任何目录</div>
                  <button @click="openExclusionChooser(r)"
                          class="mt-2 rounded bg-surface-3 px-2 py-1 text-xs hover:bg-surface-4">
                    + 添加排除目录
                  </button>
                </template>
              </div>
            </div>

            <!-- Dashed add card -->
            <button @click="showChooser = true"
                    class="flex items-center justify-center rounded-lg border-2 border-dashed border-line-strong p-6 text-ink-muted hover:border-line-strong hover:text-ink">
              <span class="text-2xl">+</span>
            </button>
          </div>
        </section>
      </template>
    </main>

    <!-- DirectoryChooser modals -->
    <DirectoryChooser v-model="showChooser" @confirm="onPathChosen" />
    <DirectoryChooser v-model="showExclusionChooser"
                      :start-path="chooserStartPath"
                      :root-id="chooserRootId ?? undefined"
                      @confirm="onExclusionChosen" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue"
import { useRoute } from "vue-router"
import AppHeader from "../components/AppHeader.vue"
import DirectoryChooser from "../components/DirectoryChooser.vue"
import { apiGet, apiPatch, apiPost, apiDelete, HttpError, errorMessage } from "../api"
import { formatDateTime } from "../utils/datetime"

interface RootInfo {
  id: number
  label: string
  absolute_path: string
  enabled: boolean
  image_count: number
  status: string
  last_scan_at: number | null
  last_scan_status: string | null
  last_scan_error: string | null
  phase?: string
  total_files?: number
  processed_files?: number
  current_path?: string | null
  started_at?: number | null
}

interface GalleryDetail {
  id: number
  name: string
  description: string | null
  roots: RootInfo[]
}

const route = useRoute()
const gid = String(route.params.gid)

const data = ref<GalleryDetail | null>(null)
const loading = ref(true)
const error = ref("")

const galleryName = ref("")
const editName = ref("")
const editDescription = ref("")
const saving = ref(false)
const saveSuccess = ref(false)
const saveError = ref("")

const showChooser = ref(false)

interface ExclusionEntry {
  id: number
  relative_path: string
  reason: string | null
  excluded_by: number | null
  excluded_by_username: string | null
  excluded_at: number
}

const exclusionPanels = ref<Record<number, boolean>>({})
const exclusions = ref<Record<number, ExclusionEntry[]>>({})
const exclusionsLoading = ref<Record<number, boolean>>({})
const exclusionsError = ref<Record<number, string>>({})
const showExclusionChooser = ref(false)
const chooserRootId = ref<number | null>(null)
const chooserStartPath = ref("")

function exclusionUrl(rid: number) {
  return `/api/admin/galleries/${gid}/roots/${rid}/exclusions`
}

async function loadExclusions(rid: number) {
  exclusionsLoading.value[rid] = true
  exclusionsError.value[rid] = ""
  try {
    const d = await apiGet<{ root_id: number; entries: ExclusionEntry[] }>(
      exclusionUrl(rid),
    )
    exclusions.value[rid] = d.entries
  } catch (err) {
    exclusionsError.value[rid] = errorMessage(err, "加载失败")
  } finally {
    exclusionsLoading.value[rid] = false
  }
}

async function toggleExclusions(rid: number) {
  const open = !exclusionPanels.value[rid]
  exclusionPanels.value[rid] = open
  if (open && (exclusions.value[rid] === undefined || exclusionsError.value[rid])) {
    exclusionsError.value[rid] = ""
    await loadExclusions(rid)
  }
}

async function removeExclusion(r: RootInfo, e: ExclusionEntry) {
  if (!window.confirm(
    `解除对「${e.relative_path}」的排除？\n\n该目录将在下次扫描时重新纳入图库，本地文件不会被改动。`,
  )) return
  try {
    await apiDelete(`${exclusionUrl(r.id)}/${e.id}`)
    // Fire the gallery reload first: both async calls dispatch their fetch
    // synchronously up to the first await, and tests queue gallery before
    // exclusions responses.
    await Promise.all([loadGallery(true), loadExclusions(r.id)])
  } catch (err) {
    exclusionsError.value[r.id] = errorMessage(err, "解除失败")
  }
}

function openExclusionChooser(r: RootInfo) {
  chooserRootId.value = r.id
  chooserStartPath.value = r.absolute_path
  showExclusionChooser.value = true
}

async function onExclusionChosen(path: string) {
  const rid = chooserRootId.value
  if (rid === null) return
  const reason = window.prompt("备注（可留空）：", "")
  if (reason === null) return // 用户取消 —— 不创建排除
  try {
    await apiPost(exclusionUrl(rid), {
      absolute_path: path,
      reason: reason.trim() ? reason.trim() : null,
    })
    await Promise.all([loadGallery(true), loadExclusions(rid)])
  } catch (err) {
    exclusionsError.value[rid] = errorMessage(err, "添加失败")
  }
}

async function loadGallery(silent = false) {
  if (!silent) loading.value = true
  error.value = ""
  try {
    const d = await apiGet<GalleryDetail>(`/api/admin/galleries/${gid}`)
    data.value = d
    galleryName.value = d.name
    // Background (silent) polls refresh scan progress but must not clobber
    // in-progress edits to the name/description fields.
    if (!silent) {
      editName.value = d.name
      editDescription.value = d.description ?? ""
    }
  } catch (err) {
    error.value = (err as HttpError).message || "加载失败"
  } finally {
    if (!silent) loading.value = false
  }
  schedulePoll()
}

async function saveGallery() {
  saving.value = true
  saveSuccess.value = false
  saveError.value = ""
  try {
    const body: Record<string, string> = {}
    if (editName.value !== data.value?.name) body.name = editName.value
    if (editDescription.value !== (data.value?.description ?? "")) body.description = editDescription.value
    if (Object.keys(body).length === 0) {
      saveSuccess.value = true
      return
    }
    const updated = await apiPatch<{ id: number; name: string; description: string | null }>(
      `/api/admin/galleries/${gid}`, body,
    )
    galleryName.value = updated.name
    if (data.value) {
      data.value.name = updated.name
      data.value.description = updated.description
    }
    saveSuccess.value = true
  } catch (err) {
    saveError.value = (err as HttpError).message || "保存失败"
  } finally {
    saving.value = false
  }
}

async function rescanRoot(rid: number) {
  try {
    await apiPost(`/api/admin/galleries/${gid}/roots/${rid}/rescan`)
    // Refresh to show updated status.
    await loadGallery()
  } catch (err) {
    // Silently surface via the next loadGallery error.
    error.value = (err as HttpError).message || "重扫失败"
  }
}

async function toggleRoot(rid: number, enabled: boolean) {
  try {
    await apiPatch(`/api/admin/galleries/${gid}/roots/${rid}`, { enabled: enabled ? 0 : 1 })
    await loadGallery()
  } catch (err) {
    error.value = (err as HttpError).message || "操作失败"
  }
}

async function confirmRemoveRoot(rid: number, label: string) {
  if (!window.confirm(`确定从图库中移除根目录「${label}」？\n\n本地文件不会被删除，仅清理索引。`)) return
  try {
    await apiDelete(`/api/admin/galleries/${gid}/roots/${rid}`)
    await loadGallery()
  } catch (err) {
    error.value = (err as HttpError).message || "移除失败"
  }
}

async function onPathChosen(path: string) {
  const label = window.prompt("请为这个根目录输入一个显示标签：", "我的照片")
  if (!label) return // user cancelled
  try {
    await apiPost(`/api/admin/galleries/${gid}/roots`, {
      label,
      absolute_path: path,
    })
    // Root creation triggers a scan automatically; reload to show it.
    await loadGallery()
  } catch (err) {
    error.value = (err as HttpError).message || "添加失败"
  }
}

let pollTimer: ReturnType<typeof setTimeout> | null = null

function anyRootRunning(): boolean {
  return data.value?.roots.some(
    (r) => r.status === "queued" || r.status === "running",
  ) ?? false
}

function schedulePoll() {
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
  if (anyRootRunning()) {
    pollTimer = setTimeout(() => {
      void loadGallery(true)
    }, 2000)
  }
}

function isRunning(r: RootInfo): boolean {
  return r.status === "queued" || r.status === "running"
}

function scanPercent(r: RootInfo): number {
  if (!r.total_files || r.total_files <= 0) return 0
  return Math.round(((r.processed_files ?? 0) / r.total_files) * 100)
}

onMounted(loadGallery)

onUnmounted(() => {
  if (pollTimer !== null) clearTimeout(pollTimer)
})

// ---- display helpers ----

const STATUS_LABELS: Record<string, string> = {
  idle: "空闲",
  queued: "排队中",
  running: "扫描中",
}

function scanStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

function scanStatusClass(status: string): string {
  switch (status) {
    case "running": return "text-primary-text"
    case "queued":  return "text-warning"
    case "idle":    return "text-success"
    default:        return "text-ink-2"
  }
}

function formatTs(ts: number): string {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>