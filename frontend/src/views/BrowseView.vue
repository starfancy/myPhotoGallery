<template>
  <div>
    <AppHeader>
      <template #title>
        <Breadcrumb v-if="crumbs.length" :crumbs="crumbs" :gid="gid" :rid="rid" />
      </template>
    </AppHeader>
    <main class="p-3">
      <SubfolderStrip v-if="folders.length" :folders="folders" :gid="gid" :rid="rid" />
      <JustifiedGrid v-if="images.length" :items="images" :can-load-more="!!nextCursor"
                     @open="onOpen" @load-more="onLoadMore"
                     @menu-action="onGridMenuAction" />
      <div v-else-if="!loading && !folders.length" class="mt-8 text-center text-neutral-500">
        此目录暂无图片
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
import ImageLightbox from "../components/ImageLightbox.vue"
import { apiGet, apiDelete, HttpError } from "../api"
import { useBrowseStore, type ImageRow } from "../stores/browse"

const route = useRoute()
const router = useRouter()
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
const nextCursor = ref<string | null>(null)
const loading = ref(false)

const browse = useBrowseStore()

function onImageDeleted(id: number) {
  const key = { gid: gid.value, rid: rid.value, path: path.value, sort: sort.value }
  browse.removeImages(key, [id])
  const entry = browse.get(key)
  images.value = entry ? entry.items : []
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
  onImageDeleted(id)
}

async function loadAll() {
  loading.value = true
  try {
    const key = { gid: gid.value, rid: rid.value, path: path.value, sort: sort.value }
    const [c, f] = await Promise.all([
      apiGet<any[]>(`/api/galleries/${gid.value}/roots/${rid.value}/breadcrumbs?path=${encodeURIComponent(path.value)}`),
      apiGet<any[]>(`/api/galleries/${gid.value}/roots/${rid.value}/folders?path=${encodeURIComponent(path.value)}`),
    ])
    crumbs.value = c
    folders.value = f
    await browse.load(key)
    const entry = browse.get(key)!
    images.value = entry.items
    nextCursor.value = entry.nextCursor
    // restore scroll
    if (entry.scrollY) {
      requestAnimationFrame(() => window.scrollTo({ top: entry.scrollY }))
    }
  } finally {
    loading.value = false
  }
}

function onOpen(id: number) {
  const suffix = path.value ? `/${path.value}` : ""
  router.push(`/galleries/${gid.value}/r/${rid.value}${suffix}/image/${id}`)
}

async function onLoadMore() {
  const key = { gid: gid.value, rid: rid.value, path: path.value, sort: sort.value }
  await browse.loadMore(key)
  const entry = browse.get(key)!
  images.value = entry.items
  nextCursor.value = entry.nextCursor
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
watch([gid, rid, path], loadAll)
</script>
