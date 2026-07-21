<template>
  <div>
    <AppHeader>
      <template #title><span class="text-neutral-400">图库</span></template>
    </AppHeader>
    <main class="p-4">
      <div v-if="loading" class="text-neutral-400">加载中...</div>
      <div v-else-if="error" class="text-red-400">{{ error }}</div>
      <div v-else class="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <router-link v-for="g in items" :key="g.id" :to="`/galleries/${g.id}`"
                     class="block rounded-lg bg-neutral-900 p-4 hover:ring-2 hover:ring-blue-500">
          <div class="font-medium">{{ g.name }}</div>
          <div class="mt-1 text-sm text-neutral-400">
            {{ g.image_count }} 张 · {{ g.root_count }} 个根目录
          </div>
        </router-link>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { apiGet, HttpError } from "../api"

interface Gallery {
  id: number
  name: string
  description: string | null
  root_count: number
  image_count: number
}

const items = ref<Gallery[]>([])
const loading = ref(true)
const error = ref("")

onMounted(async () => {
  try {
    items.value = await apiGet<Gallery[]>("/api/galleries")
  } catch (err) {
    error.value = (err as HttpError).message
  } finally {
    loading.value = false
  }
})
</script>
