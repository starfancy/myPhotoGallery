<template>
  <div>
    <AppHeader>
      <template #title><span class="text-neutral-400">管理 · 回收站</span></template>
    </AppHeader>
    <main class="p-4 space-y-4">
      <!-- Filter + bulk toolbar -->
      <div class="flex flex-wrap items-center gap-3">
        <label class="text-sm text-neutral-400">图库</label>
        <select v-model="filterGalleryId"
                class="rounded bg-neutral-800 px-2 py-1 text-sm text-neutral-100"
                @change="reload">
          <option :value="null">全部</option>
          <option v-for="g in galleries" :key="g.id" :value="g.id">{{ g.name }}</option>
        </select>

        <div class="flex-1"></div>

        <span v-if="selectedIds.size > 0" class="text-sm text-neutral-400">
          已选 {{ selectedIds.size }} 项
        </span>
        <button type="button"
                :disabled="selectedIds.size === 0 || restoring"
                class="rounded bg-blue-600 px-3 py-1.5 text-sm hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
                @click="doBatchRestore">
          {{ restoring ? "恢复中..." : "恢复选中" }}
        </button>
        <button type="button"
                :disabled="selectedIds.size === 0 || deleting"
                class="rounded bg-red-700 px-3 py-1.5 text-sm hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-40"
                @click="doBatchDelete">
          {{ deleting ? "删除中..." : "删除选中" }}
        </button>
        <button type="button"
                :disabled="entries.length === 0 || purging"
                class="rounded bg-red-900 px-3 py-1.5 text-sm hover:bg-red-800 disabled:cursor-not-allowed disabled:opacity-40"
                @click="doPurge">
          {{ purging ? "清空中..." : "清空所有" }}
        </button>
      </div>

      <div v-if="loading" class="text-neutral-400">加载中...</div>
      <div v-else-if="error" class="text-red-400">{{ error }}</div>
      <template v-else>
        <p v-if="entries.length === 0" class="text-sm text-neutral-500">
          回收站为空
        </p>
        <div v-else class="overflow-x-auto rounded-lg bg-neutral-900">
          <table class="w-full min-w-[720px] text-left text-sm">
            <thead class="border-b border-neutral-800 text-xs text-neutral-500">
              <tr>
                <th class="w-10 px-3 py-2">
                  <input type="checkbox" :checked="allSelected"
                         :indeterminate.prop="someSelected && !allSelected"
                         @change="toggleAll" />
                </th>
                <th class="px-3 py-2">预览</th>
                <th class="px-3 py-2">原路径</th>
                <th class="px-3 py-2">图库</th>
                <th class="px-3 py-2">删除时间</th>
                <th class="px-3 py-2">到期时间</th>
                <th class="w-40 px-3 py-2">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-neutral-800">
              <tr v-for="e in entries" :key="e.id" class="hover:bg-neutral-800/60">
                <td class="px-3 py-2">
                  <input type="checkbox"
                         :checked="selectedIds.has(e.id)"
                         @change="toggleOne(e.id)" />
                </td>
                <td class="px-3 py-2">
                  <!-- 缩略图；文件缺失或后端 403/404 时 fallback 为占位符 -->
                  <div class="lb-trash-thumb">
                    <img v-if="!thumbFailed.has(e.id)"
                         :src="`/api/trash/${e.id}/thumb?size=200`"
                         :alt="basename(e.original_relative_path)"
                         loading="lazy"
                         @error="thumbFailed.add(e.id)"
                         class="h-full w-full object-cover" />
                    <span v-else class="text-neutral-500 text-[10px] text-center px-1">
                      无预览
                    </span>
                  </div>
                </td>
                <td class="px-3 py-2">
                  <div class="font-medium">{{ basename(e.original_relative_path) }}</div>
                  <div class="text-xs text-neutral-500 truncate max-w-md"
                       :title="e.original_relative_path">
                    {{ e.original_relative_path }}
                  </div>
                </td>
                <td class="px-3 py-2 text-xs text-neutral-400">
                  {{ galleryName(e.gallery_id) }}
                </td>
                <td class="px-3 py-2 text-xs text-neutral-500">
                  {{ formatTs(e.deleted_at) }}
                </td>
                <td class="px-3 py-2 text-xs text-neutral-500">
                  {{ formatTs(e.purge_after) }}
                </td>
                <td class="px-3 py-2 space-x-2">
                  <button type="button"
                          class="rounded bg-blue-600 px-2 py-1 text-xs hover:bg-blue-500"
                          @click="doRestore(e.id)">
                    恢复
                  </button>
                  <button type="button"
                          class="rounded bg-red-800 px-2 py-1 text-xs hover:bg-red-700"
                          @click="doDeleteOne(e.id)">
                    立即删除
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="nextCursor !== null" class="text-center">
          <button type="button"
                  class="rounded bg-neutral-800 px-3 py-1.5 text-sm hover:bg-neutral-700"
                  :disabled="loadingMore"
                  @click="loadMore">
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
import { apiGet, apiPost, apiDelete, HttpError } from "../api"

interface TrashEntry {
  id: number
  gallery_id: number
  root_id: number
  original_relative_path: string
  trash_relative_path: string
  sha1: string
  size_bytes: number
  deleted_by: number
  deleted_at: number
  purge_after: number
}

interface GalleryItem {
  id: number
  name: string
  description: string | null
  root_count: number
  image_count: number
}

const galleries = ref<GalleryItem[]>([])
const entries = ref<TrashEntry[]>([])
const nextCursor = ref<number | null>(null)
const loading = ref(true)
const loadingMore = ref(false)
const error = ref("")

const filterGalleryId = ref<number | null>(null)
const selectedIds = ref(new Set<number>())
// 缩略图加载失败的 trash id 集合——每次 reload 清空，避免重试
const thumbFailed = ref(new Set<number>())

const restoring = ref(false)
const deleting = ref(false)
const purging = ref(false)

// ---------- computed ----------

const allSelected = computed(() =>
  entries.value.length > 0 && entries.value.every((e) => selectedIds.value.has(e.id)),
)
const someSelected = computed(() =>
  entries.value.some((e) => selectedIds.value.has(e.id)),
)

function galleryName(gid: number): string {
  return galleries.value.find((g) => g.id === gid)?.name ?? `#${gid}`
}

// ---------- loading ----------

async function loadGalleries() {
  try {
    galleries.value = await apiGet<GalleryItem[]>("/api/admin/galleries")
  } catch {
    // 图库列表加载失败不阻断回收站；表格仍能显示 gallery_id
    galleries.value = []
  }
}

function buildQuery(cursor: number | null): string {
  const params = new URLSearchParams()
  if (filterGalleryId.value !== null) {
    params.set("gallery_id", String(filterGalleryId.value))
  }
  if (cursor !== null) params.set("cursor", String(cursor))
  params.set("limit", "100")
  const q = params.toString()
  return q ? `?${q}` : ""
}

async function reload() {
  loading.value = true
  error.value = ""
  selectedIds.value = new Set()
  thumbFailed.value = new Set()
  try {
    const r = await apiGet<{ entries: TrashEntry[]; next_cursor: number | null }>(
      `/api/trash${buildQuery(null)}`,
    )
    entries.value = r.entries
    nextCursor.value = r.next_cursor
  } catch (err) {
    error.value = (err as HttpError).message || "加载失败"
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (nextCursor.value === null) return
  loadingMore.value = true
  try {
    const r = await apiGet<{ entries: TrashEntry[]; next_cursor: number | null }>(
      `/api/trash${buildQuery(nextCursor.value)}`,
    )
    entries.value.push(...r.entries)
    nextCursor.value = r.next_cursor
  } catch (err) {
    error.value = (err as HttpError).message || "加载失败"
  } finally {
    loadingMore.value = false
  }
}

// ---------- selection ----------

function toggleOne(id: number) {
  const s = new Set(selectedIds.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedIds.value = s
}

function toggleAll() {
  if (allSelected.value) {
    selectedIds.value = new Set()
  } else {
    selectedIds.value = new Set(entries.value.map((e) => e.id))
  }
}

// ---------- actions ----------

async function doRestore(id: number) {
  try {
    await apiPost(`/api/trash/${id}/restore`)
    entries.value = entries.value.filter((e) => e.id !== id)
    selectedIds.value.delete(id)
  } catch (err) {
    window.alert((err as HttpError).message || "恢复失败")
  }
}

async function doDeleteOne(id: number) {
  if (!window.confirm("确定立即物理删除该文件？此操作不可撤销。")) return
  try {
    await apiDelete(`/api/trash/${id}`)
    entries.value = entries.value.filter((e) => e.id !== id)
    selectedIds.value.delete(id)
  } catch (err) {
    window.alert((err as HttpError).message || "删除失败")
  }
}

async function doBatchRestore() {
  const ids = Array.from(selectedIds.value)
  if (ids.length === 0) return
  restoring.value = true
  try {
    const r = await apiPost<{ restored: unknown[]; failed: { id: number; error: string }[] }>(
      "/api/trash/batch-restore",
      { trash_ids: ids },
    )
    const restoredIds = new Set(ids.filter((id) => !r.failed.some((f) => f.id === id)))
    entries.value = entries.value.filter((e) => !restoredIds.has(e.id))
    selectedIds.value = new Set()
    if (r.failed.length > 0) {
      window.alert(`部分恢复失败：${r.failed.length} 条`)
    }
  } catch (err) {
    window.alert((err as HttpError).message || "恢复失败")
  } finally {
    restoring.value = false
  }
}

async function doBatchDelete() {
  const ids = Array.from(selectedIds.value)
  if (ids.length === 0) return
  if (!window.confirm(`确定立即物理删除已选 ${ids.length} 条？此操作不可撤销。`)) return
  deleting.value = true
  const failed: number[] = []
  for (const id of ids) {
    try {
      await apiDelete(`/api/trash/${id}`)
    } catch {
      failed.push(id)
    }
  }
  const removed = new Set(ids.filter((id) => !failed.includes(id)))
  entries.value = entries.value.filter((e) => !removed.has(e.id))
  selectedIds.value = new Set()
  deleting.value = false
  if (failed.length > 0) window.alert(`部分删除失败：${failed.length} 条`)
}

async function doPurge() {
  if (!window.confirm(
    "确定清空所有已到期条目？\n\n" +
    "本操作只清理 purge_after 时间已到的条目，未到期的仍保留。",
  )) return
  purging.value = true
  try {
    const r = await apiPost<{ purged: number; blocked: number; missing: number; errors: number }>(
      "/api/trash/purge",
      { confirm: true, gallery_id: filterGalleryId.value ?? undefined },
    )
    await reload()
    window.alert(
      `清理完成\n清除: ${r.purged}  拦截: ${r.blocked}  缺失: ${r.missing}  错误: ${r.errors}`,
    )
  } catch (err) {
    window.alert((err as HttpError).message || "清理失败")
  } finally {
    purging.value = false
  }
}

// ---------- helpers ----------

function basename(rel: string): string {
  const i = rel.lastIndexOf("/")
  return i >= 0 ? rel.slice(i + 1) : rel
}

function formatTs(ts: number): string {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, "0")
  return (
    d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
    " " + pad(d.getHours()) + ":" + pad(d.getMinutes())
  )
}

onMounted(async () => {
  await loadGalleries()
  await reload()
})
</script>

<style scoped>
.lb-trash-thumb {
  width: 64px;
  height: 64px;
  border-radius: 4px;
  background: rgb(23 23 23);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
</style>
