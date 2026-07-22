<template>
  <div>
    <AppHeader>
      <template #title>
        <span class="text-neutral-400">管理 · {{ galleryName || "图库" }}</span>
      </template>
    </AppHeader>
    <main class="p-4 space-y-6">
      <div v-if="loading" class="text-neutral-400">加载中...</div>
      <div v-else-if="error" class="text-red-400">{{ error }}</div>
      <template v-else-if="data">
        <!-- Gallery edit form -->
        <section class="rounded-lg bg-neutral-900 p-4">
          <h2 class="mb-3 text-sm font-medium text-neutral-400">图库信息</h2>
          <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div class="flex-1">
              <label class="block text-xs text-neutral-500">名称</label>
              <input v-model="editName"
                     class="mt-1 w-full rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500" />
            </div>
            <div class="flex-1">
              <label class="block text-xs text-neutral-500">描述</label>
              <input v-model="editDescription"
                     class="mt-1 w-full rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500" />
            </div>
            <button @click="saveGallery"
                    :disabled="saving"
                    class="shrink-0 rounded bg-blue-600 px-4 py-1.5 text-sm hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50">
              {{ saving ? "保存中..." : "保存" }}
            </button>
          </div>
          <div v-if="saveSuccess" class="mt-2 text-xs text-green-400">已保存</div>
          <div v-if="saveError" class="mt-2 text-xs text-red-400">{{ saveError }}</div>
        </section>

        <!-- Root cards -->
        <section>
          <h2 class="mb-2 text-sm font-medium text-neutral-400">根目录</h2>
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div v-for="r in data.roots" :key="r.id"
                 class="flex flex-col gap-2 rounded-lg bg-neutral-900 p-4">
              <div class="font-medium">{{ r.label }}</div>
              <div class="truncate text-xs text-neutral-500" :title="r.absolute_path">{{ r.absolute_path }}</div>
              <div class="flex items-center gap-2 text-xs">
                <span>{{ r.image_count }} 张</span>
                <span :class="scanStatusClass(r.status)">{{ scanStatusLabel(r.status) }}</span>
                <span v-if="!r.enabled" class="text-yellow-400">已禁用</span>
              </div>
              <div v-if="r.last_scan_at" class="text-xs text-neutral-500">
                上次扫描: {{ formatTs(r.last_scan_at) }}
              </div>
              <div v-if="r.last_scan_error" class="truncate text-xs text-red-400" :title="r.last_scan_error">
                {{ r.last_scan_error }}
              </div>
              <div class="mt-1 flex gap-2">
                <button @click="rescanRoot(r.id)"
                        class="rounded bg-neutral-700 px-2 py-1 text-xs hover:bg-neutral-600">
                  重扫
                </button>
                <button @click="toggleRoot(r.id, r.enabled)"
                        class="rounded bg-neutral-700 px-2 py-1 text-xs hover:bg-neutral-600">
                  {{ r.enabled ? "禁用" : "启用" }}
                </button>
                <button @click="confirmRemoveRoot(r.id, r.label)"
                        class="ml-auto rounded bg-red-800 px-2 py-1 text-xs hover:bg-red-700">
                  移除
                </button>
              </div>
            </div>

            <!-- Dashed add card -->
            <button @click="showChooser = true"
                    class="flex items-center justify-center rounded-lg border-2 border-dashed border-neutral-700 p-6 text-neutral-500 hover:border-neutral-500 hover:text-neutral-300">
              <span class="text-2xl">+</span>
            </button>
          </div>
        </section>
      </template>
    </main>

    <!-- DirectoryChooser modal -->
    <DirectoryChooser v-model="showChooser" @confirm="onPathChosen" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRoute } from "vue-router"
import AppHeader from "../components/AppHeader.vue"
import DirectoryChooser from "../components/DirectoryChooser.vue"
import { apiGet, apiPatch, apiPost, apiDelete, HttpError } from "../api"

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

async function loadGallery() {
  loading.value = true
  error.value = ""
  try {
    const d = await apiGet<GalleryDetail>(`/api/admin/galleries/${gid}`)
    data.value = d
    galleryName.value = d.name
    editName.value = d.name
    editDescription.value = d.description ?? ""
  } catch (err) {
    error.value = (err as HttpError).message || "加载失败"
  } finally {
    loading.value = false
  }
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

onMounted(loadGallery)

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
    case "running": return "text-blue-400"
    case "queued":  return "text-yellow-400"
    case "idle":    return "text-green-400"
    default:        return "text-neutral-400"
  }
}

function formatTs(ts: number): string {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>