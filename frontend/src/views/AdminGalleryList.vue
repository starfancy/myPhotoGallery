<template>
  <div>
    <AppHeader>
      <template #title><span class="text-neutral-400">管理 · 图库列表</span></template>
    </AppHeader>
    <main class="p-4 space-y-6">
      <div v-if="loading" class="text-neutral-400">加载中...</div>
      <div v-else-if="error" class="text-red-400">{{ error }}</div>
      <template v-else>
        <!-- Create gallery -->
        <section>
          <button v-if="!showCreateForm"
                  @click="openCreateForm"
                  class="rounded bg-blue-600 px-3 py-2 text-sm hover:bg-blue-500">
            新建图库
          </button>
          <div v-else class="rounded-lg bg-neutral-900 p-4">
            <h3 class="mb-3 text-sm font-medium text-neutral-400">新建图库</h3>
            <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div class="flex-1">
                <label class="block text-xs text-neutral-500">名称</label>
                <input v-model="newName"
                       class="mt-1 w-full rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                       placeholder="图库名称" />
              </div>
              <div class="flex-1">
                <label class="block text-xs text-neutral-500">描述（可选）</label>
                <input v-model="newDescription"
                       class="mt-1 w-full rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                       placeholder="简短描述" />
              </div>
              <button @click="createGallery"
                      :disabled="creating || !newName.trim()"
                      class="shrink-0 rounded bg-blue-600 px-4 py-1.5 text-sm hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50">
                {{ creating ? "创建中..." : "创建" }}
              </button>
              <button @click="cancelCreateForm"
                      class="shrink-0 rounded bg-neutral-700 px-4 py-1.5 text-sm hover:bg-neutral-600">
                取消
              </button>
            </div>
            <div v-if="createError" class="mt-2 text-xs text-red-400">{{ createError }}</div>
          </div>
        </section>

        <!-- Gallery list -->
        <section>
          <h2 v-if="galleries.length > 0" class="mb-2 text-sm font-medium text-neutral-400">
            {{ galleries.length }} 个图库
          </h2>
          <div v-if="galleries.length === 0" class="text-sm text-neutral-500">
            暂无图库，点击上方按钮创建
          </div>
          <div v-else class="divide-y divide-neutral-800 rounded-lg bg-neutral-900">
            <div v-for="g in galleries" :key="g.id"
                 class="flex flex-col gap-2 p-4 sm:flex-row sm:items-center">
              <div class="min-w-0 flex-1">
                <router-link :to="`/admin/galleries/${g.id}`"
                             class="font-medium text-blue-400 hover:text-blue-300">
                  {{ g.name }}
                </router-link>
                <div v-if="g.description" class="truncate text-xs text-neutral-500">
                  {{ g.description }}
                </div>
              </div>
              <div class="flex items-center gap-4 text-xs text-neutral-500">
                <span>{{ g.root_count }} 个根目录</span>
                <span>{{ g.image_count }} 张图片</span>
              </div>
              <div class="flex items-center gap-2">
                <router-link :to="`/admin/galleries/${g.id}`"
                             class="rounded bg-neutral-700 px-2 py-1 text-xs hover:bg-neutral-600">
                  编辑
                </router-link>
                <button @click="confirmDelete(g.id, g.name)"
                        class="rounded bg-red-800 px-2 py-1 text-xs hover:bg-red-700">
                  删除
                </button>
              </div>
            </div>
          </div>
        </section>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { apiGet, apiPost, apiDelete, HttpError } from "../api"

interface GalleryItem {
  id: number
  name: string
  description: string | null
  root_count: number
  image_count: number
}

const galleries = ref<GalleryItem[]>([])
const loading = ref(true)
const error = ref("")

// ---- create form state ----
const showCreateForm = ref(false)
const newName = ref("")
const newDescription = ref("")
const creating = ref(false)
const createError = ref("")

async function loadGalleries() {
  loading.value = true
  error.value = ""
  try {
    galleries.value = await apiGet<GalleryItem[]>("/api/admin/galleries")
  } catch (err) {
    error.value = (err as HttpError).message || "加载失败"
  } finally {
    loading.value = false
  }
}

function openCreateForm() {
  showCreateForm.value = true
  newName.value = ""
  newDescription.value = ""
  createError.value = ""
}

function cancelCreateForm() {
  showCreateForm.value = false
  newName.value = ""
  newDescription.value = ""
  createError.value = ""
}

async function createGallery() {
  creating.value = true
  createError.value = ""
  try {
    const body: Record<string, string> = { name: newName.value.trim() }
    if (newDescription.value.trim()) body.description = newDescription.value.trim()
    await apiPost("/api/admin/galleries", body)
    showCreateForm.value = false
    newName.value = ""
    newDescription.value = ""
    await loadGalleries()
  } catch (err) {
    createError.value = (err as HttpError).message || "创建失败"
  } finally {
    creating.value = false
  }
}

async function confirmDelete(gid: number, name: string) {
  if (!window.confirm(`确定删除图库「${name}」？\n\n此操作将删除该图库下的所有根目录索引和图片索引，不可撤销。`)) return
  try {
    await apiDelete(`/api/admin/galleries/${gid}`)
    galleries.value = galleries.value.filter(g => g.id !== gid)
  } catch (err) {
    error.value = (err as HttpError).message || "删除失败"
  }
}

onMounted(loadGalleries)
</script>
