<template>
  <div>
    <AppHeader>
      <template #title><span class="text-ink-2">管理 · 图库列表</span></template>
    </AppHeader>
    <main id="main-content" class="p-4 space-y-6">
      <div v-if="loading" class="text-ink-2">加载中...</div>
      <div v-else-if="error" role="alert" class="text-danger-text">{{ error }}</div>
      <template v-else>
        <!-- Create gallery -->
        <section>
          <button v-if="!showCreateForm"
                  @click="openCreateForm"
                  class="rounded bg-primary px-3 py-2 text-sm text-white hover:bg-primary-hover">
            新建图库
          </button>
          <div v-else class="rounded-lg bg-surface p-4">
            <h3 class="mb-3 text-sm font-medium text-ink-2">新建图库</h3>
            <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div class="flex-1">
                <label class="block text-xs text-ink-2">名称</label>
                <input v-model="newName"
                       class="mt-1 w-full rounded bg-surface-2 px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-primary"
                       placeholder="图库名称" />
              </div>
              <div class="flex-1">
                <label class="block text-xs text-ink-2">描述（可选）</label>
                <input v-model="newDescription"
                       class="mt-1 w-full rounded bg-surface-2 px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-primary"
                       placeholder="简短描述" />
              </div>
              <button @click="createGallery"
                      :disabled="creating || !newName.trim()"
                      class="shrink-0 rounded bg-primary px-4 py-1.5 text-sm text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50">
                {{ creating ? "创建中..." : "创建" }}
              </button>
              <button @click="cancelCreateForm"
                      class="shrink-0 rounded bg-surface-3 px-4 py-1.5 text-sm hover:bg-surface-4">
                取消
              </button>
            </div>
            <div v-if="createError" role="alert" class="mt-2 text-xs text-danger-text">{{ createError }}</div>
          </div>
        </section>

        <!-- Gallery list -->
        <section>
          <h2 v-if="galleries.length > 0" class="mb-2 text-sm font-medium text-ink-2">
            {{ galleries.length }} 个图库
          </h2>
          <div v-if="galleries.length === 0" class="text-sm text-ink-2" role="status">
            暂无图库，点击上方按钮创建
          </div>
          <div v-else class="divide-y divide-line rounded-lg bg-surface">
            <div v-for="g in galleries" :key="g.id"
                 class="flex flex-col gap-2 p-4 sm:flex-row sm:items-center">
              <div class="min-w-0 flex-1">
                <router-link :to="`/admin/galleries/${g.id}`"
                             class="font-medium text-primary-text hover:text-primary-text">
                  {{ g.name }}
                </router-link>
                <div v-if="g.description" class="truncate text-xs text-ink-2">
                  {{ g.description }}
                </div>
              </div>
              <div class="flex items-center gap-4 text-xs text-ink-2">
                <span>{{ g.root_count }} 个根目录</span>
                <span>{{ g.image_count }} 张图片</span>
              </div>
              <div class="flex items-center gap-2">
                <router-link :to="`/admin/galleries/${g.id}`"
                             class="rounded bg-surface-3 px-2 py-1 text-xs hover:bg-surface-4">
                  编辑
                </router-link>
                <button @click="confirmDelete(g.id, g.name)"
                        class="rounded bg-danger px-2 py-1 text-xs text-white hover:bg-danger-hover">
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
