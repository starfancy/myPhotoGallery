<script setup lang="ts">
/** 人物簇页（tags Phase 3 §4.4）：左侧簇列表（按照片数降序），右侧选中簇
 *  的照片按年/月分组。点击簇名可重命名。 */
import { onMounted, ref } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { apiGet, apiPut } from "../api"

interface Cluster {
  cluster_id: string
  display_name: string | null
  sample_face_id: number | null
  image_count: number
}
interface ClusterImage {
  id: number
  filename: string
  width: number | null
  height: number | null
  sha1: string
  taken_at: number | null
}
interface Group { year: number; month: number; images: ClusterImage[] }

const clusters = ref<Cluster[]>([])
const groups = ref<Group[]>([])
const selectedId = ref<string>("")
const loading = ref(false)
const renaming = ref(false)
const renameInput = ref("")
const loadError = ref("")

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
        <aside class="w-48 shrink-0 space-y-1">
          <button
            v-for="c in clusters"
            :key="c.cluster_id"
            type="button"
            class="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm"
            :class="c.cluster_id === selectedId
                     ? 'bg-primary/10 text-ink'
                     : 'text-ink-2 hover:bg-surface-2 hover:text-ink'"
            :aria-pressed="c.cluster_id === selectedId"
            @click="selectCluster(c.cluster_id)"
          >
            <span class="truncate">{{ clusterLabel(c) }}</span>
            <span class="ml-2 shrink-0 text-xs text-ink-muted">{{ c.image_count }}</span>
          </button>
        </aside>

        <!-- 右：照片按年/月分组 -->
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
          </div>

          <div v-if="loading" class="text-sm text-ink-2" role="status">加载中...</div>
          <div v-else-if="groups.length === 0" class="text-sm text-ink-2">该簇暂无照片</div>
          <div v-for="g in groups" :key="`${g.year}-${g.month}`" class="mb-4">
            <h3 class="mb-1.5 text-xs font-medium text-ink-2">{{ groupTitle(g) }}</h3>
            <div class="flex flex-wrap gap-1.5">
              <img
                v-for="img in g.images"
                :key="img.id"
                :src="`/api/thumb/${img.sha1}?size=200`"
                :alt="img.filename"
                class="h-28 rounded object-cover"
                loading="lazy"
              />
            </div>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>
