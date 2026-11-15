<template>
  <div>
    <AppHeader>
      <template #title>
        <Breadcrumb v-if="crumbs.length" :crumbs="crumbs" :gid="gid" :rid="rid"
                    :query="sceneQuery" />
      </template>
    </AppHeader>
    <main id="main-content" class="p-3">
      <!-- 工具栏：左侧选择操作（所有角色；viewer 仅可下载），右侧排版切换。
           hasScene/hasDate 也要保留工具栏：筛选全空时仍需能清除筛选条件。 -->
      <div v-if="images.length || folders.length || searchQ || hasScene || hasDate"
           class="mb-2 flex flex-wrap items-center gap-2 text-sm">
        <button v-if="!selectionMode"
                type="button"
                class="min-h-11 rounded bg-surface-2 px-2 py-1 text-ink hover:bg-surface-3"
                @click="enterSelectionMode">
          选择
        </button>
        <template v-else>
          <span class="text-ink-2">已选 {{ selectedIds.size }} 项</span>
          <button type="button"
                  class="min-h-11 rounded bg-surface-2 px-2 py-1 text-ink hover:bg-surface-3"
                  @click="selectAll">
            {{ isAllSelected ? "取消全选" : "全选" }}
          </button>
        </template>
        <div class="ml-auto flex flex-wrap items-center gap-1.5">
          <button type="button"
                  class="flex min-h-11 min-w-11 items-center justify-center rounded px-1.5 py-1"
                  :class="(searchPanelOpen || hasSearchCondition)
                          ? 'bg-surface-3 text-ink'
                          : 'text-ink-2 hover:text-ink'"
                  :title="searchPanelOpen ? '收起搜索' : '展开搜索'"
                  :aria-label="searchPanelOpen ? '收起搜索' : '展开搜索'"
                  :aria-expanded="searchPanelOpen"
                  aria-controls="search-panel"
                  @click="searchPanelOpen = !searchPanelOpen">
            <!-- 放大镜（feather search，16px） -->
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2" stroke-linecap="round"
                 stroke-linejoin="round" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </button>
          <SceneFilter
            :major="sceneMajor"
            :minor="sceneMinor"
            :gid="gid"
            :rid="rid"
            :path="effectivePath"
            @update:major="onSceneMajor"
            @update:minor="onSceneMinor"
          />
          <GridLayoutSwitch v-model="gridLayout" />
          <button type="button"
                  class="flex min-h-11 min-w-11 items-center justify-center rounded px-1.5 py-1"
                  :class="showFilenames
                          ? 'bg-surface-3 text-ink'
                          : 'text-ink-2 hover:text-ink'"
                  title="缩略图上显示文件名"
                  aria-label="缩略图上显示文件名"
                  :aria-pressed="showFilenames"
                  @click="showFilenames = !showFilenames">
            <!-- 图片卡片 + 底部文字行 -->
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
                 stroke="currentColor" stroke-width="1.2" stroke-linecap="round"
                 aria-hidden="true">
              <rect x="1.5" y="1.5" width="13" height="13" rx="1.5" />
              <path d="M5 11h6" />
            </svg>
          </button>
          <button type="button"
                  class="flex min-h-11 min-w-11 items-center justify-center rounded px-1.5 py-1"
                  :class="showScene
                          ? 'bg-surface-3 text-ink'
                          : 'text-ink-2 hover:text-ink'"
                  title="缩略图上显示场景分类标签"
                  aria-label="缩略图上显示场景分类标签"
                  :aria-pressed="showScene"
                  @click="showScene = !showScene">
            <!-- 标签图标：圆角矩形 + 文字 -->
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
                 stroke="currentColor" stroke-width="1.2" stroke-linecap="round"
                 aria-hidden="true">
              <rect x="1.5" y="4" width="13" height="8" rx="1.5" />
              <path d="M4 7.5h8M4 9.5h5" />
            </svg>
          </button>
        </div>
      </div>

      <!-- 搜索折叠面板：默认收起；URL 带 q/日期条件时自动展开 -->
      <div v-if="searchPanelOpen"
           id="search-panel"
           class="mb-2 flex flex-wrap items-center gap-2 rounded bg-surface-2/60 p-2">
        <DateRangeFilter
          :date-from="dateFrom"
          :date-to="dateTo"
          @update:date-from="onDateFrom"
          @update:date-to="onDateTo"
        />
        <SearchBox
          :model-value="searchQ"
          :scope-all="scopeAll"
          :is-root="path === ''"
          @update:model-value="onSearchQuery"
          @update:scope-all="onScopeAll"
        />
      </div>

      <template v-if="!searchQ">
        <SubfolderStrip v-if="folders.length" :folders="folders" :gid="gid" :rid="rid"
                        :query="sceneQuery"
                        :can-exclude="auth.isAdmin"
                        @exclude="onExcludeFolder" />
        <component :is="gridComponent" v-if="images.length" :items="images"
                       :selection-mode="selectionMode"
                       :selected-ids="selectedIds"
                       :show-filename="showFilenames"
                       :show-scene="showScene"
                       @open="onOpen"
                       @menu-action="onGridMenuAction"
                       @toggle-select="onToggleSelect" />
        <!-- 筛选态：本文件夹无匹配图片但还有子文件夹可下钻 -->
        <div v-else-if="(hasScene || hasDate) && folders.length && !loading"
             class="mt-4 text-center text-sm text-ink-2" role="status">
          当前文件夹内没有匹配当前筛选条件的图片，可进入下方子文件夹查看
        </div>
        <!-- 筛选态：图片和子文件夹都无匹配 → 给清除入口，避免困在空页 -->
        <div v-else-if="(hasScene || hasDate) && !folders.length && !loading"
             class="mt-8 flex flex-col items-center gap-3 text-center text-ink-2"
             role="status">
          <span>没有匹配当前筛选条件的图片或子文件夹</span>
          <button type="button"
                  class="min-h-11 rounded bg-surface-2 px-3 py-1 text-sm text-ink hover:bg-surface-3"
                  @click="clearAllFilters">
            清除筛选
          </button>
        </div>
        <div v-else-if="!loading && !folders.length" class="mt-8 text-center text-ink-2"
             role="status">
          此目录暂无图片
        </div>
        <PaginationBar v-if="totalPages > 1" :page="page" :total-pages="totalPages"
                       @change="changePage" />
      </template>
      <SearchResults
        v-else
        ref="resultsRef"
        :gid="gid"
        :rid="rid"
        :q="searchQ"
        :path="scopeAll ? '' : path"
        :grid="gridLayout"
        :selection-mode="selectionMode"
        :selected-ids="selectedIds"
        :show-filename="showFilenames"
        :show-scene="showScene"
        :scene-major="sceneMajor"
        :scene-minor="sceneMinor"
        :date-from="dateFrom"
        :date-to="dateTo"
        @open="onSearchOpen"
        @toggle-select="onToggleSelect"
        @menu-action="onSearchMenuAction"
        @items-change="onSearchItems"
      />

      <!-- 选择模式底部浮动工具条 -->
      <div v-if="selectionMode"
           class="fixed inset-x-0 bottom-0 z-50 flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface/95 px-4 py-3 backdrop-blur">
        <span class="text-sm text-ink">已选 {{ selectedIds.size }} 项</span>
        <div class="flex flex-wrap items-center gap-2">
          <button type="button"
                  :disabled="selectedIds.size === 0 || downloading"
                  class="min-h-11 rounded bg-primary px-3 py-1.5 text-sm text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-40"
                  @click="onBatchDownload">
            {{ downloading ? "准备中..." : `下载 ZIP（${selectedIds.size}）` }}
          </button>
          <button v-if="auth.isAdmin"
                  type="button"
                  :disabled="selectedIds.size === 0 || batchDeleting"
                  class="min-h-11 rounded bg-danger px-3 py-1.5 text-sm text-white hover:bg-danger-hover disabled:cursor-not-allowed disabled:opacity-40"
                  @click="onBatchDelete">
            {{ batchDeleting ? "移入中..." : "移入回收站" }}
          </button>
          <button type="button"
                  class="min-h-11 rounded bg-surface-3 px-3 py-1.5 text-sm hover:bg-surface-4"
                  @click="exitSelectionMode">
            取消
          </button>
        </div>
      </div>
    </main>
    <ImageLightbox v-if="lightboxId !== null && !searchQ" :items="images" :start-id="lightboxId"
                    @close="onLightboxClose" @change="onLightboxChange"
                    @deleted="onImageDeleted" />
    <ImageLightbox
      v-else-if="searchImageId !== null && searchItems.some((it) => it.id === searchImageId)"
      :items="searchItems"
      :start-id="searchImageId"
      :location-resolver="searchLocation"
      @close="onSearchLightboxClose"
      @change="onSearchLightboxChange"
      @view-in-folder="onViewInFolder"
      @deleted="onSearchImageDeleted"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import AppHeader from "../components/AppHeader.vue"
import Breadcrumb from "../components/Breadcrumb.vue"
import SubfolderStrip from "../components/SubfolderStrip.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import MasonryGrid from "../components/MasonryGrid.vue"
import GridLayoutSwitch from "../components/GridLayoutSwitch.vue"
import type { GridLayout } from "../components/GridLayoutSwitch.vue"
import PaginationBar from "../components/PaginationBar.vue"
import ImageLightbox from "../components/ImageLightbox.vue"
import SearchBox from "../components/SearchBox.vue"
import SearchResults from "../components/SearchResults.vue"
import SceneFilter from "../components/SceneFilter.vue"
import DateRangeFilter from "../components/DateRangeFilter.vue"
import { apiGet, apiDelete, apiPost, HttpError, errorMessage } from "../api"
import { useBrowseStore, PAGE_SIZE, type BrowseKey, type ImageRow } from "../stores/browse"
import { useAuthStore } from "../stores/auth"
import { useToastStore } from "../stores/toast"
import { encodePathSegments } from "../utils/path"
import { dayEndEpoch, dayStartEpoch } from "../utils/filters"

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const toast = useToastStore()

/** 前端选择集硬上限（下载 API Pydantic 上限同为 200）。 */
const SELECT_HARD_LIMIT = 200
const downloading = ref(false)
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
  // 保留 query（场景筛选 scene_*、搜索 q 等），关灯箱不丢筛选状态
  router.push({
    path: `/galleries/${gid.value}/r/${rid.value}${suffix}`,
    query: queryWithoutImage(),
  })
}
function onLightboxChange(id: number) {
  const suffix = path.value ? `/${path.value}` : ""
  router.replace({
    path: `/galleries/${gid.value}/r/${rid.value}${suffix}/image/${id}`,
    query: queryWithoutImage(),
  })
}

// ---------- 搜索态 ----------

const searchQ = computed(() => String(route.query.q ?? "").trim())
const scopeAll = computed(() => route.query.scope === "all")
const searchItems = ref<ImageRow[]>([])
const resultsRef = ref<InstanceType<typeof SearchResults> | null>(null)

const searchImageId = computed(() => {
  if (!searchQ.value || route.query.image === undefined) return null
  const n = Number(route.query.image)
  return Number.isInteger(n) && n > 0 ? n : null
})

function queryWithoutImage(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(route.query)) {
    if (k === "image" || v === undefined || v === null) continue
    out[k] = Array.isArray(v) ? v.join("/") : String(v)
  }
  return out
}

function onSearchQuery(q: string) {
  const query = queryWithoutImage()
  if (q) query.q = q
  else delete query.q
  router.replace({ query })
}

function onScopeAll(v: boolean) {
  const query = queryWithoutImage()
  if (v) query.scope = "all"
  else delete query.scope
  router.replace({ query })
}

function onSearchItems(items: ImageRow[]) {
  searchItems.value = items
}

function onSearchOpen(id: number) {
  router.replace({ query: { ...queryWithoutImage(), image: String(id) } })
}

function onSearchLightboxClose() {
  router.replace({ query: queryWithoutImage() })
}

function onSearchLightboxChange(id: number) {
  router.replace({ query: { ...queryWithoutImage(), image: String(id) } })
}

/** 图片 → 所在目录（root 根目录返回 ""，Lightbox 仍显示跳转按钮）。 */
function searchLocation(it: ImageRow): string {
  const p = it.relative_path ?? ""
  const i = p.lastIndexOf("/")
  return i >= 0 ? p.slice(0, i) : ""
}

function onViewInFolder(it: ImageRow) {
  const dir = searchLocation(it)
  router.push({
    path: `/galleries/${gid.value}/r/${rid.value}${dir ? `/${encodePathSegments(dir)}` : ""}`,
    // 下钻到普通浏览视图时保留场景/日期筛选
    query: sceneQuery.value,
  })
}

async function onSearchMenuAction(id: number, action: "delete") {
  if (action !== "delete") return
  const image = searchItems.value.find((it) => it.id === id)
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
  await onSearchImageDeleted(id)
}

/** Lightbox 删除成功后的回调：Lightbox 内部已调过 DELETE，这里只做本地摘除 + 重拉。 */
async function onSearchImageDeleted(id: number) {
  searchItems.value = searchItems.value.filter((it) => it.id !== id)
  const s = new Set(selectedIds.value)
  s.delete(id)
  selectedIds.value = s
  // 删除项可能位于任意文件夹：普通浏览缓存无 TTL，整体清空，避免幽灵卡片
  browse.clearAll()
  await resultsRef.value?.reload()
}

const sort = ref("name_asc")

// 场景筛选（tags Phase 2）：状态放在 URL query（scene_major/scene_minor），
// 刷新/分享链接可保留；同 root 内下钻/上跳文件夹时筛选不重置。
const sceneMajor = computed(() => String(route.query.scene_major ?? ""))
const sceneMinor = computed(() => String(route.query.scene_minor ?? ""))
const hasScene = computed(() => sceneMajor.value !== "" || sceneMinor.value !== "")
/** 日期筛选（URL 存 YYYY-MM-DD），搜索态与浏览态共用 */
const dateFrom = computed(() => String(route.query.date_from ?? ""))
const dateTo = computed(() => String(route.query.date_to ?? ""))
const hasDate = computed(() => dateFrom.value !== "" || dateTo.value !== "")
/** URL 中存在搜索词或日期条件（scope 不算：它只能由面板内勾选产生）。 */
const hasSearchCondition = computed(
  () => Boolean(searchQ.value) || hasDate.value,
)
/** 挂载时按 URL 条件初始化：带条件进入自动展开，否则默认折叠。 */
const searchPanelOpen = ref(hasSearchCondition.value)
// 条件从无到有（输入搜索词、选日期、前进后退到带条件路由）自动展开；
// 条件清空或手动折叠都不强制关闭，用户可自由开关。
watch(hasSearchCondition, (v) => {
  if (v) searchPanelOpen.value = true
})
/** 搜索态勾选“整个 root”时有效路径是 root 根；SceneFilter 按此范围统计 */
const effectivePath = computed(() =>
  searchQ.value && scopeAll.value ? "" : path.value,
)
/** 给文件夹卡片/面包屑链接透传的筛选 query（场景+日期，空则无键） */
const sceneQuery = computed<Record<string, string>>(() => {
  const q: Record<string, string> = {}
  if (sceneMajor.value) q.scene_major = sceneMajor.value
  if (sceneMinor.value) q.scene_minor = sceneMinor.value
  if (dateFrom.value) q.date_from = dateFrom.value
  if (dateTo.value) q.date_to = dateTo.value
  return q
})

const crumbs = ref<{ name: string; relative_path: string }[]>([])
const folders = ref<any[]>([])
const images = ref<ImageRow[]>([])
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

const browse = useBrowseStore()

function currentKey(): BrowseKey {
  return {
    gid: gid.value, rid: rid.value, path: path.value, sort: sort.value,
    sceneMajor: sceneMajor.value, sceneMinor: sceneMinor.value,
    dateFrom: dateFrom.value, dateTo: dateTo.value,
  }
}

// ---------- grid layout preference ----------

const GRID_LAYOUT_KEY = "browse.grid.layout"

function loadGridLayout(): GridLayout {
  return localStorage.getItem(GRID_LAYOUT_KEY) === "masonry" ? "masonry" : "justified"
}

const gridLayout = ref<GridLayout>(loadGridLayout())
watch(gridLayout, (v) => localStorage.setItem(GRID_LAYOUT_KEY, v))

const gridComponent = computed(() =>
  gridLayout.value === "masonry" ? MasonryGrid : JustifiedGrid,
)

const SHOW_FILENAMES_KEY = "browse.grid.showFilenames"
const showFilenames = ref(localStorage.getItem(SHOW_FILENAMES_KEY) === "1")
watch(showFilenames, (v) => localStorage.setItem(SHOW_FILENAMES_KEY, v ? "1" : "0"))

const SHOW_SCENE_KEY = "browse.grid.showScene"
const showScene = ref(localStorage.getItem(SHOW_SCENE_KEY) === "1")
watch(showScene, (v) => localStorage.setItem(SHOW_SCENE_KEY, v ? "1" : "0"))

// ---------- selection mode ----------

const selectionMode = ref(false)
const selectedIds = ref(new Set<number>())
const batchDeleting = ref(false)

/** 当前可见批次：搜索态为累积的搜索结果，普通浏览态为当前页图片。 */
const visibleItems = computed<ImageRow[]>(() =>
  searchQ.value ? searchItems.value : images.value,
)

const isAllSelected = computed(() =>
  visibleItems.value.length > 0 &&
  visibleItems.value.every((it) => selectedIds.value.has(it.id)),
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
  if (s.has(id)) {
    s.delete(id)
  } else {
    if (s.size >= SELECT_HARD_LIMIT) {
      toast.push("error", `一次最多选择 ${SELECT_HARD_LIMIT} 张`)
      return
    }
    s.add(id)
  }
  selectedIds.value = s
}

function selectAll() {
  const s = new Set(selectedIds.value)
  if (isAllSelected.value) {
    // 只摘除当前可见批次（普通页=当前页；搜索态=已加载结果），保留其他批次的勾选
    for (const it of visibleItems.value) s.delete(it.id)
  } else {
    // 与单张切换同一硬上限：只补未选项，按批次顺序最多补到 SELECT_HARD_LIMIT 张
    const room = Math.max(0, SELECT_HARD_LIMIT - s.size)
    const missing = visibleItems.value.filter((it) => !s.has(it.id))
    for (const it of missing.slice(0, room)) s.add(it.id)
    if (missing.length > room) toast.push("error", `一次最多选择 ${SELECT_HARD_LIMIT} 张`)
  }
  selectedIds.value = s
}

function triggerAnchorDownload(href: string, filename: string) {
  const a = document.createElement("a")
  a.href = href
  a.download = filename
  a.rel = "noopener"
  document.body.appendChild(a)
  a.click()
  a.remove()
}

async function onBatchDownload() {
  const ids = Array.from(selectedIds.value)
  if (ids.length === 0) return
  const limit = auth.user?.download_batch_limit ?? 100
  if (ids.length > limit) {
    window.alert(
      `当前设置单次最多下载 ${limit} 张（已选 ${ids.length} 张），请减少选择。` +
      (auth.isAdmin ? "管理员可在「设置」中调整，最高 200。" : ""),
    )
    return
  }
  downloading.value = true
  try {
    const r = await apiPost<{ ticket: string; filename: string; count: number }>(
      "/api/download-batch",
      { image_ids: ids },
    )
    triggerAnchorDownload(`/api/download-batch/${r.ticket}`, r.filename)
    // 浏览器原生下载已接管；无法感知完成，给 1s 防连点窗口
    await new Promise((res) => setTimeout(res, 1000))
  } catch (err) {
    window.alert(`下载失败：${errorMessage(err, "请稍后重试")}`)
  } finally {
    downloading.value = false
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
      if (searchQ.value) {
        // 搜索态：刷新可见结果（删除项可能跨目录）；清空普通浏览缓存防幽灵卡片
        browse.clearAll()
        await resultsRef.value?.reload()
      } else {
        await reloadAfterChange()
      }
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

/**
 * 退出搜索态后补拉当前目录普通视图：folders 在搜索期间已加载、无需重拉；
 * 先 invalidate 再渲染第 1 页，确保搜索结果里删除过的图片不会由旧缓存回显。
 */
async function loadNormalAfterSearch() {
  const key = currentKey()
  browse.invalidate(key)
  page.value = 1
  loading.value = true
  try {
    await renderPage(key, 1)
  } finally {
    loading.value = false
  }
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

/** 文件夹卡片快捷菜单：确认后走 P5 排除接口（仅清索引，不删磁盘文件）。 */
async function onExcludeFolder(folder: { name: string; relative_path: string }) {
  const msg =
    `确定排除文件夹「${folder.name}」？\n\n` +
    "该文件夹及其所有子文件夹、图片将从图库索引中移除，磁盘上的文件不会被删除。" +
    "之后可在「图库管理」中解除排除。"
  if (!window.confirm(msg)) return
  try {
    await apiPost(
      `/api/admin/galleries/${gid.value}/roots/${rid.value}/exclusions`,
      { relative_path: folder.relative_path },
    )
  } catch (err) {
    const m = err instanceof HttpError ? err.message : "排除失败"
    window.alert(`排除失败：${m}`)
    return
  }
  // 乐观更新：POST 只把重扫入队，Folder 行要等后台 worker 重扫完才删，
  // 此刻重拉 folders 会读到旧行、把卡片加回来。直接本地摘除；图片分页与
  // 滚动位置不动，下次进入目录时 loadAll 与服务端最终状态收敛。
  folders.value = folders.value.filter((f) => f.relative_path !== folder.relative_path)
}

/**
 * 只重拉面包屑与文件夹列表（含空文件夹借封面补查）。
 * 快捷排除成功后使用：不清图片分页缓存、不滚顶、不重置页码。
 */
async function loadFolders() {
  const params = new URLSearchParams({ path: path.value })
  if (sceneMajor.value) params.set("scene_major", sceneMajor.value)
  if (sceneMinor.value) params.set("scene_minor", sceneMinor.value)
  if (dayStartEpoch(dateFrom.value) !== null)
    params.set("date_from", String(dayStartEpoch(dateFrom.value)))
  if (dayEndEpoch(dateTo.value) !== null)
    params.set("date_to", String(dayEndEpoch(dateTo.value)))
  const [c, f] = await Promise.all([
    apiGet<any[]>(`/api/galleries/${gid.value}/roots/${rid.value}/breadcrumbs?path=${encodeURIComponent(path.value)}`),
    apiGet<any[]>(`/api/galleries/${gid.value}/roots/${rid.value}/folders?${params.toString()}`),
  ])
  crumbs.value = c
  folders.value = f
  // 空文件夹（自身无图、后代有图）借用直接子文件夹封面：单项失败静默处理。
  await enrichBorrowedCovers()
}

async function loadAll() {
  loading.value = true
  try {
    const key = currentKey()
    await loadFolders()
    if (searchQ.value) return // 搜索结果由 SearchResults 自取
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
 * 自身无图但后代有图的文件夹，补查其直接子文件夹并借用第一个自身含图
 * 子项的封面，同时在封面标注来源子文件夹名。仅查直接子级，不递归。
 * folders.value 中的项是响应式代理，直接改属性即可触发卡片更新。
 */
async function enrichBorrowedCovers() {
  const candidates = folders.value.filter(
    (f) => f.image_count === 0 && f.descendant_count > 0,
  )
  if (candidates.length === 0) return
  await Promise.all(
    candidates.map(async (folder) => {
      try {
        const params = new URLSearchParams({ path: folder.relative_path })
        if (sceneMajor.value) params.set("scene_major", sceneMajor.value)
        if (sceneMinor.value) params.set("scene_minor", sceneMinor.value)
        if (dayStartEpoch(dateFrom.value) !== null)
          params.set("date_from", String(dayStartEpoch(dateFrom.value)))
        if (dayEndEpoch(dateTo.value) !== null)
          params.set("date_to", String(dayEndEpoch(dateTo.value)))
        const children = await apiGet<any[]>(
          `/api/galleries/${gid.value}/roots/${rid.value}/folders?${params.toString()}`,
        )
        const donor = children.find(
          (ch) => (ch.matching_count ?? ch.image_count) > 0 && ch.cover_thumb_sha1 != null,
        )
        if (donor) {
          folder.cover_thumb_sha1 = donor.cover_thumb_sha1
          folder.cover_source_name = donor.name
        }
      } catch {
        // 补查失败：该文件夹保持灰色占位，不影响其余内容
      }
    }),
  )
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
  // 跨页累积选择：翻页不清空选择集（切换 gid/rid/path 时仍由 watcher 清空）
  const key = currentKey()
  page.value = p
  await renderPage(key, p)
  window.scrollTo({ top: 0 })
}

function onOpen(id: number) {
  const suffix = path.value ? `/${path.value}` : ""
  router.push({
    path: `/galleries/${gid.value}/r/${rid.value}${suffix}/image/${id}`,
    query: queryWithoutImage(),
  })
}

function onScroll() {
  browse.saveScroll(
    { gid: gid.value, rid: rid.value, path: path.value, sort: sort.value },
    window.scrollY,
  )
}

onMounted(() => {
  sceneWatcherLoc.value = `${gid.value}/${rid.value}`
  window.addEventListener("scroll", onScroll, { passive: true })
  loadAll()
})
onUnmounted(() => {
  window.removeEventListener("scroll", onScroll)
})
// 位置（图库/根/目录）与搜索词合并监听：view-in-folder 可能在同一 tick
// 同时改 path 和清 q，必须合并成一次判定，避免普通视图被拉两遍。
watch([gid, rid, path, searchQ], (now, old) => {
  exitSelectionMode()
  const [ogid, orid, opath, oq] = old ?? [0, 0, "", ""]
  const locChanged =
    now[0] !== ogid || now[1] !== orid || now[2] !== opath
  if (locChanged) {
    // loadAll 在搜索态会跳过 /images，由 SearchResults 自取
    sceneWatcherLoc.value = `${gid.value}/${rid.value}`
    loadAll()
  } else if (oq && !now[3]) {
    // 同路径 q 由非空变空（刷新在 ?q= 页后清除、同目录 view-in-folder）：
    // 此前从未拉过普通页，补拉当前 key；走 invalidate 防缓存里残留已删图片
    void loadNormalAfterSearch()
  }
})
// 仅切换范围：结果集整体替换，旧选择不应保留；普通 /images 不得触发，
// SearchResults 靠自身 prop watcher 重查
watch(scopeAll, () => {
  exitSelectionMode()
})

// ---------- 场景筛选（tags Phase 2，状态存 URL query） ----------

/** 把场景筛选写进 URL（保留其余 query，如 q/scope），驱动 watcher 重拉。 */
function writeSceneQuery(major: string, minor: string) {
  const query = queryWithoutImage()
  delete query.scene_major
  delete query.scene_minor
  if (major) query.scene_major = major
  if (minor) query.scene_minor = minor
  router.replace({ query })
}

function onSceneMajor(v: string) {
  // 切一级时二级必须清空（旧二级在新一级下无意义）
  writeSceneQuery(v, "")
}
function onSceneMinor(v: string) {
  writeSceneQuery(sceneMajor.value, v)
}
function clearSceneFilter() {
  writeSceneQuery("", "")
}

function clearAllFilters() {
  const query = queryWithoutImage()
  delete query.scene_major
  delete query.scene_minor
  delete query.date_from
  delete query.date_to
  router.replace({ query })
}

function writeDateQuery(from: string, to: string) {
  const query = queryWithoutImage()
  delete query.date_from
  delete query.date_to
  if (from) query.date_from = from
  if (to) query.date_to = to
  router.replace({ query })
}
function onDateFrom(v: string) {
  writeDateQuery(v, dateTo.value)
}
function onDateTo(v: string) {
  writeDateQuery(dateFrom.value, v)
}

// 场景 query 变化：文件夹（分面过滤）+ 图片都重拉，回到第 1 页。
// 同 root 内路径变化时 query 保持不变 → 此 watcher 不触发，筛选自然保留；
// 跨 root/图库导航的链接不带 scene query → 自动回到无筛选态，且由 loc
// watcher 的 loadAll 统一处理，这里靠 sceneWatcherLoc 跳过避免重复请求。
const sceneWatcherLoc = ref("")
watch([sceneMajor, sceneMinor, dateFrom, dateTo], () => {
  if (searchQ.value) return
  const loc = `${gid.value}/${rid.value}`
  if (loc !== sceneWatcherLoc.value) {
    sceneWatcherLoc.value = loc
    return
  }
  exitSelectionMode()
  page.value = 1
  void reloadSceneScope()
})

async function reloadSceneScope() {
  const key = currentKey()
  browse.invalidate(key)
  await loadFolders()
  await renderPage(key, 1)
}
</script>
