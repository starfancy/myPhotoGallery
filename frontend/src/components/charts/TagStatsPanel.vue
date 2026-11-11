<script setup lang="ts">
/** 标签分布面板（tags Phase 2 §4.3）：一级分类横向条形图，展开看二级。
 *  数据来自 /api/tags/stats；未打标时静默渲染空。 */
import { onMounted, ref } from "vue"
import { apiGet } from "../../api"

interface MinorGroup { name: string; count: number }
interface MajorGroup { name: string; count: number; minors: MinorGroup[] }

const majors = ref<MajorGroup[]>([])
const loading = ref(true)
const expanded = ref<Set<string>>(new Set())

async function load() {
  loading.value = true
  try {
    const r = await apiGet<{ majors?: MajorGroup[] }>("/api/tags/stats")
    majors.value = Array.isArray(r.majors) ? r.majors : []
  } catch {
    majors.value = []
  } finally {
    loading.value = false
  }
}
onMounted(load)

const maxCount = () =>
  majors.value.reduce((m, g) => Math.max(m, g.count), 0)

function toggle(name: string) {
  const next = new Set(expanded.value)
  if (next.has(name)) next.delete(name)
  else next.add(name)
  expanded.value = next
}
</script>

<template>
  <section class="rounded-lg bg-surface p-4">
    <h2 class="mb-3 text-sm font-medium text-ink-2">
      标签分布
      <span v-if="!loading && majors.length" class="ml-2 text-xs text-ink-muted">
        共 {{ majors.reduce((s, g) => s + g.count, 0).toLocaleString() }} 张已打标
      </span>
    </h2>
    <div v-if="loading" class="text-sm text-ink-2" role="status">加载中...</div>
    <div v-else-if="majors.length === 0" class="text-sm text-ink-2">
      暂无已打标图片（用 <code>myphoto tag run</code> 打标后显示）
    </div>
    <ul v-else class="space-y-2">
      <li v-for="g in majors" :key="g.name">
        <button
          type="button"
          class="flex w-full items-center gap-2 text-left"
          :aria-expanded="expanded.has(g.name)"
          @click="toggle(g.name)"
        >
          <span class="w-20 shrink-0 text-sm text-ink">{{ g.name }}</span>
          <span class="relative h-4 flex-1 overflow-hidden rounded bg-surface-2">
            <span
              class="absolute inset-y-0 left-0 rounded bg-primary/70"
              :style="{ width: (g.count / Math.max(maxCount(), 1)) * 100 + '%' }"
            />
          </span>
          <span class="w-16 shrink-0 text-right text-xs text-ink-2">{{ g.count }}</span>
          <span class="w-3 shrink-0 text-xs text-ink-muted">{{ expanded.has(g.name) ? "−" : "+" }}</span>
        </button>
        <ul v-if="expanded.has(g.name)" class="ml-22 mt-1 space-y-1 pl-2">
          <li
            v-for="m in g.minors"
            :key="m.name"
            class="flex items-center gap-2 text-xs text-ink-2"
          >
            <span class="w-24 shrink-0">{{ m.name }}</span>
            <span class="text-ink-muted">{{ m.count }}</span>
          </li>
        </ul>
      </li>
    </ul>
  </section>
</template>
