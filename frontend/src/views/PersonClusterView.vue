<script setup lang="ts">
/** 人物簇页（tags Phase 3 §4.4）：左侧簇列表（按照片数降序），右侧选中簇
 *  的照片按年/月分组，组内使用与图库一致的 justified 网格。点击簇名可重命名。 */
import { computed, onMounted, ref, watch } from "vue"
import { useRouter } from "vue-router"
import AppHeader from "../components/AppHeader.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import ImageLightbox from "../components/ImageLightbox.vue"
import { apiDelete, apiGet, apiPut, HttpError } from "../api"
import type { ImageRow } from "../stores/browse"
import { encodePathSegments } from "../utils/path"

interface Cluster {
  cluster_id: string
  display_name: string | null
  sample_face_id: number | null
  image_count: number
}
interface ClusterImage extends ImageRow {
  gallery_id: number
  root_id: number
  gallery_name: string
  folder_path: string
}
interface Group { year: number; month: number; images: ClusterImage[] }

const clusters = ref<Cluster[]>([])
const groups = ref<Group[]>([])
const selectedId = ref<string>("")
const loading = ref(false)
const renaming = ref(false)
const renameInput = ref("")
const loadError = ref("")
const router = useRouter()

/** 信息开关：缩略图文件名 + 所在图库/文件夹位置；偏好独立于图库页持久化。 */
const SHOW_INFO_KEY = "people.grid.showInfo"
const showInfo = ref(localStorage.getItem(SHOW_INFO_KEY) === "1")
watch(showInfo, (v) => localStorage.setItem(SHOW_INFO_KEY, v ? "1" : "0"))

async function loadClusters() {
  loadError.value = ""
  try {
    clusters.value = await apiGet<Cluster[]>("/api/tags/clusters")
    if (!selectedId.value && clusters.value.length) {
      selectCluster(clusters.value[0].cluster_id)
    }
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : "加载失败"
  }
}

function clusterLabel(c: Cluster) {
  return c.display_name || c.cluster_id
}

async function selectCluster(cid: string) {
  selectedId.value = cid
  loading.value = true
  try {
    const r = await apiGet<{ groups: Group[]; total: number }>(
      `/api/tags/clusters/${cid}/images`,
    )
    groups.value = r.groups
  } finally {
    loading.value = false
  }
}

function startRename() {
  const c = clusters.value.find((x) => x.cluster_id === selectedId.value)
  renameInput.value = c?.display_name ?? ""
  renaming.value = true
}

async function saveRename() {
  if (!selectedId.value) return
  await apiPut(`/api/tags/clusters/${selectedId.value}`, {
    display_name: renameInput.value,
  })
  renaming.value = false
  await loadClusters()
}

function groupTitle(g: Group) {
  if (g.year === 0) return "未知日期"
  return `${g.year}年${g.month}月`
}

/** 位置文本：网格角标与灯箱标注共用；根目录图片只显示图库名。
 *  共享组件的函数类型以 ImageRow 为参数，内部收窄访问扩展字段。 */
function locationText(it: ImageRow): string {
  const c = it as ClusterImage
  return c.folder_path ? `${c.gallery_name}/${c.folder_path}` : c.gallery_name
}

/** 全簇图片按分组顺序拍平：灯箱以此作为完整图片集，翻页可跨年/月组。 */
const flatImages = computed(() => groups.value.flatMap((g) => g.images))

/** 灯箱当前起点图片 id；null = 关闭。状态刻意不进 URL（人物页无图片路由）。 */
const lightboxId = ref<number | null>(null)

function openLightbox(id: number) {
  lightboxId.value = id
}

/** 灯箱「在所在文件夹中查看」：数据自带 gallery_id/root_id，跨图库也能跳回。 */
function onViewInFolder(row: ImageRow) {
  const it = row as ClusterImage
  const suffix = encodePathSegments(it.folder_path)
  router.push(
    suffix
      ? `/galleries/${it.gallery_id}/r/${it.root_id}/${suffix}`
      : `/galleries/${it.gallery_id}/r/${it.root_id}`,
  )
}

/** 网格三点/右键菜单删除：确认后走统一图片删除接口（灯箱内删除由其自行发请求）。 */
async function onGridMenuAction(id: number, action: "delete") {
  if (action !== "delete") return
  const image = flatImages.value.find((it) => it.id === id)
  if (!image) return
  if (!window.confirm(`确定将「${image.filename}」移入回收站？\n\n30 天内可从「回收站」恢复。`)) return
  try {
    await apiDelete(`/api/images/${id}`)
  } catch (err) {
    const m = err instanceof HttpError ? err.message : "删除失败"
    window.alert(`删除失败：${m}`)
    return
  }
  await onImageDeleted(id)
}

/** 删除成功统一收尾：本地摘除、关灯箱、刷新左栏簇计数；当前簇被删空则切走。 */
async function onImageDeleted(id: number) {
  groups.value = groups.value
    .map((g) => ({ ...g, images: g.images.filter((it) => it.id !== id) }))
    .filter((g) => g.images.length > 0)
  lightboxId.value = null
  await loadClusters()
  if (!clusters.value.some((c) => c.cluster_id === selectedId.value)) {
    if (clusters.value.length) await selectCluster(clusters.value[0].cluster_id)
    else groups.value = []
  }
}

onMounted(loadClusters)
</script>

<template>
  <div>
    <AppHeader>
      <template #title><span class="text-ink-2">人物</span></template>
    </AppHeader>
    <main id="main-content" class="p-3">
      <div v-if="loadError" class="mt-8 text-center text-danger-text" role="alert">
        加载人物簇失败：{{ loadError }}
      </div>
      <div v-else-if="clusters.length === 0" class="mt-8 text-center text-ink-2" role="status">
        暂无人物簇（打标完成后自动聚类）
      </div>
      <div v-else class="flex gap-4">
        <!-- 左：簇列表 -->
        <aside
          class="w-56 shrink-0 space-y-1 overflow-y-auto
                 sticky top-[81px] md:top-[65px]
                 max-h-[calc(100vh-93px)] md:max-h-[calc(100vh-77px)]"
        >
          <button
            v-for="c in clusters"
            :key="c.cluster_id"
            type="button"
            class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm"
            :class="c.cluster_id === selectedId
                     ? 'bg-primary/10 text-ink'
                     : 'text-ink-2 hover:bg-surface-2 hover:text-ink'"
            :aria-pressed="c.cluster_id === selectedId"
            @click="selectCluster(c.cluster_id)"
          >
            <img
              :src="`/api/tags/clusters/${c.cluster_id}/face.jpg`"
              :alt="clusterLabel(c)"
              class="h-10 w-10 shrink-0 rounded-full object-cover"
              loading="lazy"
            />
            <span class="min-w-0 flex-1 truncate">{{ clusterLabel(c) }}</span>
            <span class="ml-2 shrink-0 text-xs text-ink-muted">{{ c.image_count }}</span>
          </button>
        </aside>

        <!-- 右：照片按年/月分组，组内与图库同款 justified 网格 -->
        <section class="min-w-0 flex-1">
          <div v-if="selectedId" class="mb-2 flex items-center gap-2">
            <h2 class="text-sm font-medium text-ink">
              {{ clusters.find((c) => c.cluster_id === selectedId)?.display_name || selectedId }}
            </h2>
            <button
              v-if="!renaming"
              type="button"
              class="min-h-11 rounded px-2 py-1 text-xs text-ink-2 hover:text-ink"
              @click="startRename"
            >
              重命名
            </button>
            <form v-else class="flex items-center gap-1.5" @submit.prevent="saveRename">
              <input
                v-model="renameInput"
                class="min-h-11 w-40 rounded bg-surface-2 px-2 text-sm text-ink"
                placeholder="名字（留空=未命名）"
                aria-label="簇名"
              />
              <button type="submit"
                      class="min-h-11 rounded bg-primary px-2 py-1 text-sm text-white">
                保存
              </button>
              <button type="button"
                      class="min-h-11 rounded px-2 py-1 text-sm text-ink-2"
                      @click="renaming = false">
                取消
              </button>
            </form>
            <button type="button"
                    class="ml-auto flex min-h-11 min-w-11 items-center justify-center rounded px-1.5 py-1"
                    :class="showInfo
                            ? 'bg-surface-3 text-ink'
                            : 'text-ink-2 hover:text-ink'"
                    title="缩略图上显示文件名与所在位置"
                    aria-label="缩略图上显示文件名与所在位置"
                    :aria-pressed="showInfo"
                    @click="showInfo = !showInfo">
              <!-- 图片卡片 + 底部文字行（与图库文件名开关同款图标） -->
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
                   stroke="currentColor" stroke-width="1.2" stroke-linecap="round"
                   aria-hidden="true">
                <rect x="1.5" y="1.5" width="13" height="13" rx="1.5" />
                <path d="M5 11h6" />
              </svg>
            </button>
          </div>

          <div v-if="loading" class="text-sm text-ink-2" role="status">加载中...</div>
          <div v-else-if="groups.length === 0" class="text-sm text-ink-2">该簇暂无照片</div>
          <div v-for="g in groups" :key="`${g.year}-${g.month}`" class="mb-4">
            <h3 class="mb-1.5 text-xs font-medium text-ink-2">{{ groupTitle(g) }}</h3>
            <JustifiedGrid
              :items="g.images"
              :show-filename="showInfo"
              :badge-for="showInfo ? locationText : undefined"
              @open="openLightbox"
              @menu-action="onGridMenuAction"
            />
          </div>
        </section>
      </div>
    </main>
    <ImageLightbox
      v-if="lightboxId !== null && flatImages.some((it) => it.id === lightboxId)"
      :items="flatImages"
      :start-id="lightboxId"
      :location-resolver="locationText"
      @close="lightboxId = null"
      @deleted="onImageDeleted"
      @view-in-folder="onViewInFolder"
    />
  </div>
</template>
