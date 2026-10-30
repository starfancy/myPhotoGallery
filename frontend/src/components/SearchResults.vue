<template>
  <div>
    <section v-if="folders.length" class="pb-3">
      <h2 class="mb-2 text-sm text-neutral-400">
        匹配的文件夹（{{ folders.length }}<template v-if="foldersTruncated">，仅显示前 50 个，请细化关键词</template>）
      </h2>
      <div class="lb-search-folder-grid">
        <router-link
          v-for="f in folders"
          :key="f.relative_path"
          :to="folderLink(f.relative_path)"
          class="flex flex-col overflow-hidden rounded bg-neutral-800 text-sm hover:ring-2 hover:ring-blue-500"
        >
          <div class="h-20 w-full overflow-hidden bg-neutral-700">
            <img
              v-if="f.cover_thumb_sha1"
              :src="`/api/thumb/${f.cover_thumb_sha1}?size=200`"
              :alt="f.name"
              loading="lazy"
              class="h-full w-full object-cover"
            >
          </div>
          <div class="truncate p-2">
            <div class="truncate font-medium">{{ f.name }}</div>
            <div class="text-xs text-neutral-400">{{ f.descendant_count }} 张</div>
          </div>
        </router-link>
      </div>
    </section>

    <div v-if="error"
         class="mb-2 rounded bg-red-900/30 px-3 py-2 text-sm text-red-300">
      {{ error }}
    </div>

    <component
      :is="gridComponent"
      v-if="items.length"
      :items="items"
      :badge-for="badgeFor"
      :selection-mode="selectionMode"
      :selected-ids="selectedIds"
      :show-filename="showFilename"
      @open="onOpen"
      @toggle-select="onToggleSelect"
      @menu-action="onMenuAction"
    />

    <div v-else-if="!loading && !folders.length"
         class="mt-8 text-center text-neutral-500">
      未找到匹配的图片或文件夹
    </div>

    <div v-if="nextCursor" class="py-4 text-center">
      <button
        type="button"
        class="rounded bg-neutral-800 px-3 py-1.5 text-sm hover:bg-neutral-700 disabled:opacity-50"
        :disabled="loadingMore"
        @click="loadMore"
      >
        {{ loadingMore ? "加载中..." : "加载更多" }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import JustifiedGrid from "./JustifiedGrid.vue"
import MasonryGrid from "./MasonryGrid.vue"
import type { GridLayout } from "./GridLayoutSwitch.vue"
import { apiGet, errorMessage } from "../api"
import type { ImageRow } from "../stores/browse"

interface SearchFolder {
  name: string
  relative_path: string
  image_count: number
  descendant_count: number
  cover_thumb_sha1: string | null
}

interface SearchResponse {
  q: string
  path: string
  folders: SearchFolder[]
  folders_truncated: boolean
  images: ImageRow[]
  next_cursor: string | null
}

const props = defineProps<{
  gid: number
  rid: number
  q: string
  /** 子树根；scope=all 时父组件传 "" */
  path: string
  grid: GridLayout
  selectionMode?: boolean
  selectedIds?: Set<number>
  showFilename?: boolean
}>()

const emit = defineEmits<{
  (e: "open", id: number): void
  (e: "toggleSelect", id: number): void
  (e: "menuAction", id: number, action: "delete"): void
  (e: "itemsChange", items: ImageRow[]): void
}>()

defineExpose({ reload })

// 模板里不写内联 TS 类型，用具名包装透传网格事件
function onOpen(id: number) {
  emit("open", id)
}
function onToggleSelect(id: number) {
  emit("toggleSelect", id)
}
function onMenuAction(id: number, action: "delete") {
  emit("menuAction", id, action)
}

const gridComponent = computed(() =>
  props.grid === "masonry" ? MasonryGrid : JustifiedGrid,
)

const folders = ref<SearchFolder[]>([])
const foldersTruncated = ref(false)
const items = ref<ImageRow[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(false)
const loadingMore = ref(false)
const error = ref("")

function dirOf(it: ImageRow): string | null {
  const p = it.relative_path ?? ""
  const i = p.lastIndexOf("/")
  return i >= 0 ? p.slice(0, i) : null
}

const badgeFor = dirOf

function folderLink(rel: string) {
  const enc = rel.split("/").map((seg) => encodeURIComponent(seg)).join("/")
  return `/galleries/${props.gid}/r/${props.rid}/${enc}`
}

function searchParams(cursor?: string | null) {
  const params = new URLSearchParams({
    q: props.q,
    path: props.path,
    limit: "100",
  })
  if (cursor) params.set("cursor", cursor)
  return params
}

async function loadFirst() {
  if (!props.q.trim()) return
  loading.value = true
  error.value = ""
  try {
    const r = await apiGet<SearchResponse>(
      `/api/galleries/${props.gid}/roots/${props.rid}/search?${searchParams()}`,
    )
    folders.value = r.folders
    foldersTruncated.value = r.folders_truncated
    items.value = r.images
    nextCursor.value = r.next_cursor
    emit("itemsChange", items.value)
  } catch (e) {
    error.value = errorMessage(e, "搜索失败")
    folders.value = []
    items.value = []
    nextCursor.value = null
    emit("itemsChange", [])
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (!nextCursor.value || loadingMore.value) return
  loadingMore.value = true
  try {
    const r = await apiGet<SearchResponse>(
      `/api/galleries/${props.gid}/roots/${props.rid}/search?${searchParams(nextCursor.value)}`,
    )
    items.value = [...items.value, ...r.images]
    nextCursor.value = r.next_cursor
    emit("itemsChange", items.value)
  } catch (e) {
    error.value = errorMessage(e, "搜索失败")
  } finally {
    loadingMore.value = false
  }
}

async function reload() {
  await loadFirst()
}

watch(
  () => [props.gid, props.rid, props.q, props.path] as const,
  () => {
    void loadFirst()
  },
  { immediate: true },
)
</script>

<style scoped>
.lb-search-folder-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(128px, 1fr));
  gap: 16px;
}
</style>
