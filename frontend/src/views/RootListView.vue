<template>
  <div>
    <AppHeader>
      <template #title>
        <div class="truncate text-neutral-400">
          <router-link to="/galleries" class="hover:text-neutral-100">图库</router-link>
          <span class="mx-1 text-neutral-600">›</span>
          <span class="text-neutral-100">{{ galleryName }}</span>
        </div>
      </template>
    </AppHeader>
    <main class="p-4">
      <div v-if="loading" class="text-neutral-400">加载中...</div>
      <div v-else class="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <router-link v-for="r in roots" :key="r.id" :to="`/galleries/${gid}/r/${r.id}/`"
                     class="block rounded-lg bg-neutral-900 p-4 hover:ring-2 hover:ring-blue-500">
          <div class="font-medium">{{ r.label }}</div>
          <div class="mt-1 text-sm text-neutral-400">{{ r.image_count }} 张</div>
          <div v-if="r.offline" class="mt-1 text-xs text-yellow-400">离线 / 上次扫描出错</div>
        </router-link>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, computed } from "vue"
import { useRoute, useRouter } from "vue-router"
import AppHeader from "../components/AppHeader.vue"
import { apiGet } from "../api"

interface RootInfo {
  id: number
  label: string
  image_count: number
  offline: boolean
  enabled: boolean
}

const route = useRoute()
const router = useRouter()
const gid = computed(() => Number(route.params.gid))
const galleryName = ref("")
const roots = ref<RootInfo[]>([])
const loading = ref(true)

onMounted(async () => {
  const detail = await apiGet<{ gallery: { name: string }; roots: RootInfo[] }>(`/api/galleries/${gid.value}`)
  galleryName.value = detail.gallery.name
  roots.value = detail.roots
  if (roots.value.length === 1) {
    router.replace(`/galleries/${gid.value}/r/${roots.value[0].id}/`)
    return
  }
  loading.value = false
})
</script>
