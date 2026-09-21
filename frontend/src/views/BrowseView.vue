<template>
  <div>
    <AppHeader>
      <template #title>
        <Breadcrumb v-if="crumbs.length" :crumbs="crumbs" :gid="gid" :rid="rid" />
      </template>
    </AppHeader>
    <main class="p-3">
      <!-- 选择模式工具栏（admin only） -->
      <div v-if="auth.isAdmin && images.length" class="mb-2 flex items-center gap-2 text-sm">
        <button v-if="!selectionMode"
                type="button"
                class="rounded bg-neutral-800 px-2 py-1 text-neutral-300 hover:bg-neutral-700"
                @click="enterSelectionMode">
          选择
        </button>
        <template v-else>
          <span class="text-neutral-400">已选 {{ selectedIds.size }} 项</span>
          <button type="button"
                  class="rounded bg-neutral-800 px-2 py-1 text-neutral-300 hover:bg-neutral-700"
                  @click="selectAll">
            {{ isAllSelected ? "取消全选" : "全选" }}
          </button>
        </template>
      </div>

      <SubfolderStrip v-if="folders.length" :folders="folders" :gid="gid" :rid="rid" />
      <JustifiedGrid v-if="images.length" :items="images"
                     :selection-mode="selectionMode"
                     :selected-ids="selectedIds"
                     @open="onOpen"
                     @menu-action="onGridMenuAction"
                     @toggle-select="onToggleSelect" />
      <div v-else-if="!loading && !folders.length" class="mt-8 text-center text-neutral-500">
        此目录暂无图片
      </div>
      <PaginationBar v-if="totalPages > 1" :page="page" :total-pages="totalPages"
                     @change="changePage" />

      <!-- 选择模式底部浮动工具条 -->
      <div v-if="selectionMode"
           class="fixed inset-x-0 bottom-0 z-50 flex items-center justify-between gap-3 border-t border-neutral-800 bg-neutral-900/95 px-4 py-3 backdrop-blur">
        <span class="text-sm text-neutral-300">已选 {{ selectedIds.size }} 项</span>
        <div class="flex items-center gap-2">
          <button type="button"
                  :disabled="selectedIds.size === 0 || batchDeleting"
                  class="rounded bg-red-700 px-3 py-1.5 text-sm hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-40"
                  @click="onBatchDelete">
            {{ batchDeleting ? "移入中..." : "移入回收站" }}
          </button>
          <button type="button"
                  class="rounded bg-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-600"
                  @click="exitSelectionMode">
            取消
          </button>
        </div>
      </div>
    </main>
    <ImageLightbox v-if="lightboxId !== null" :items="images" :start-id="lightboxId"
                    @close="onLightboxClose" @change="onLightboxChange"
                    @deleted="onImageDeleted" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import AppHeader from "../components/AppHeader.vue"
import Breadcrumb from "../components/Breadcrumb.vue"
import SubfolderStrip from "../components/SubfolderStrip.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import PaginationBar from "../components/PaginationBar.vue"
import ImageLightbox from "../components/ImageLightbox.vue"
import { apiGet, apiDelete, apiPost, HttpError } from "../api"
import { useBrowseStore, PAGE_SIZE, type BrowseKey, type ImageRow } from "../stores/browse"
import { useAuthStore } from "../stores/auth"

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const gid = computed(() => Number(route.params.gid))
const rid = computed(() => Number(route.params.rid))
const path = computed(() => {
  const raw = route.params.path
  const p = Array.isArray(raw) ? raw.join("/") : String(raw || "")
  return p.replace(/\/?image\/\d+$/, "").replace(/\/+$/, "")
})
const lightboxId = computed(() => {
  const iid = route.params.iid
  return iid ? Number(iid) : null
})
function onLightboxClose() {
  const suffix = path.value ? `/${path.value}` : ""
  router.push(`/galleries/${gid.value}/r/${rid.value}${suffix}`)
}
function onLightboxChange(id: number) {
  const suffix = path.value ? `/${path.value}` : ""
  router.replace(`/galleries/${gid.value}/r/${rid.value}${suffix}/image/${id}`)
}
const sort = ref("name_asc")

const crumbs = ref<{ name: string; relative_path: string }[]>([])
const folders = ref<any[]>([])
const images = ref<ImageRow[]>([])
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

const browse = useBrowseStore()

function currentKey(): BrowseKey {
  return { gid: gid.value, rid: rid.value, path: path.value, sort: sort.value }
}

// ---------- selection mode ----------

const selectionMode = ref(false)
const selectedIds = ref(new Set<number>())
const batchDeleting = ref(false)

const isAllSelected = computed(() =>
  images.value.length > 0 && images.value.every((it) => selectedIds.value.has(it.id)),
)

function enterSelectionMode() {
  selectionMode.value = true
  selectedIds.value = new Set()
}

function exitSelectionMode() {
  selectionMode.value = false
  selectedIds.value = new Set()
}

function onToggleSelect(id: number) {
  const s = new Set(selectedIds.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedIds.value = s
}

function selectAll() {
  if (isAllSelected.value) {
    selectedIds.value = new Set()
  } else {
    selectedIds.value = new Set(images.value.map((it) => it.id))
  }
}

async function onBatchDelete() {
  const ids = Array.from(selectedIds.value)
  if (ids.length === 0) return
  const msg = `确定将已选 ${ids.length} 项移入回收站？\n\n30 天内可从「回收站」恢复。`
  if (!window.confirm(msg)) return
  batchDeleting.value = true
  try {
    const r = await apiPost<{ deleted: number[]; failed: { id: number; error: string }[] }>(
      "/api/images/batch-delete",
      { image_ids: ids },
    )
    if (r.deleted.length > 0) {
      await reloadAfterChange()
    }
    if (r.failed.length > 0) {
      window.alert(`部分删除失败：${r.failed.length} 项`)
    }
    exitSelectionMode()
  } catch (err) {
    const m = err instanceof HttpError ? err.message : "删除失败"
    window.alert(`删除失败：${m}`)
  } finally {
    batchDeleting.value = false
  }
}

// ---------- single-image actions ----------

async function onImageDeleted(_id: number) {
  await reloadAfterChange()
}

/** 删除等导致后续页位移的操作后：丢弃缓存页并重新拉取当前页。 */
async function reloadAfterChange() {
  const key = currentKey()
  browse.invalidate(key)
  await renderPage(key, page.value)
}

async function onGridMenuAction(id: number, action: "delete") {
  if (action !== "delete") return
  const image = images.value.find((it) => it.id === id)
  if (!image) return
  const msg = `确定将「${image.filename}」移入回收站？\n\n30 天内可从「回收站」恢复。`
  if (!window.confirm(msg)) return
  try {
    await apiDelete(`/api/images/${id}`)
  } catch (err) {
    const m = err instanceof HttpError ? err.message : "删除失败"
    window.alert(`删除失败：${m}`)
    return
  }
  await onImageDeleted(id)
}

async function loadAll() {
  loading.value = true
  try {
    const key = currentKey()
    const [c, f] = await Promise.all([
      apiGet<any[]>(`/api/galleries/${gid.value}/roots/${rid.value}/breadcrumbs?path=${encodeURIComponent(path.value)}`),
      apiGet<any[]>(`/api/galleries/${gid.value}/roots/${rid.value}/folders?path=${encodeURIComponent(path.value)}`),
    ])
    crumbs.value = c
    folders.value = f
    page.value = 1
    await renderPage(key, 1)
    // restore scroll
    const entry = browse.get(key)
    if (entry?.scrollY) {
      requestAnimationFrame(() => window.scrollTo({ top: entry.scrollY }))
    }
  } finally {
    loading.value = false
  }
}

/**
 * 拉取并渲染某一页。末页仅剩的图片被删时，请求的页会变空，
 * 此时自动回退到上一页。
 */
async function renderPage(key: BrowseKey, p: number) {
  const r = await browse.loadPage(key, p)
  if (r.items.length === 0 && p > 1) {
    page.value = p - 1
    const r2 = await browse.loadPage(key, p - 1)
    images.value = r2.items
    total.value = r2.total
    return
  }
  images.value = r.items
  total.value = r.total
}

async function changePage(p: number) {
  if (p === page.value || p < 1 || p > totalPages.value) return
  exitSelectionMode()
  const key = currentKey()
  page.value = p
  await renderPage(key, p)
  window.scrollTo({ top: 0 })
}

function onOpen(id: number) {
  const suffix = path.value ? `/${path.value}` : ""
  router.push(`/galleries/${gid.value}/r/${rid.value}${suffix}/image/${id}`)
}

function onScroll() {
  browse.saveScroll(
    { gid: gid.value, rid: rid.value, path: path.value, sort: sort.value },
    window.scrollY,
  )
}

onMounted(() => {
  window.addEventListener("scroll", onScroll, { passive: true })
  loadAll()
})
onUnmounted(() => {
  window.removeEventListener("scroll", onScroll)
})
// 切换目录/图库/根目录时退出选择模式，避免旧选中 id 混入新数据
watch([gid, rid, path], () => {
  exitSelectionMode()
  loadAll()
})
</script>
