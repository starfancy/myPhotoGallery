<script setup lang="ts">
/** 场景筛选下拉（tags Phase 2）：一级 + 联动二级。
 *  选项来自 /api/tags/stats（只列出图库中实际存在的标签）；
 *  一级固定 9 类，二级按选中一级动态加载。 */
import { onMounted, ref, watch } from "vue"
import { apiGet } from "../api"

const props = defineProps<{
  major: string
  minor: string
}>()
const emit = defineEmits<{
  (e: "update:major", v: string): void
  (e: "update:minor", v: string): void
}>()

interface MinorGroup { name: string; count: number }
interface MajorGroup { name: string; count: number; minors: MinorGroup[] }

const majors = ref<MajorGroup[]>([])
const loading = ref(false)

async function loadStats() {
  loading.value = true
  try {
    const r = await apiGet<{ majors: MajorGroup[] }>("/api/tags/stats")
    majors.value = r.majors
  } catch {
    majors.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadStats)

const currentMinors = ref<MinorGroup[]>([])
watch(
  () => props.major,
  (m) => {
    const group = majors.value.find((g) => g.name === m)
    currentMinors.value = group ? group.minors : []
    // 切换一级时，旧二级失效
    if (props.minor) emit("update:minor", "")
  },
  { immediate: true },
)
// stats 晚到时也要刷新二级列表
watch(majors, () => {
  const group = majors.value.find((g) => g.name === props.major)
  currentMinors.value = group ? group.minors : []
})

function onMajor(e: Event) {
  emit("update:major", (e.target as HTMLSelectElement).value)
}
function onMinor(e: Event) {
  emit("update:minor", (e.target as HTMLSelectElement).value)
}
function clear() {
  emit("update:major", "")
  emit("update:minor", "")
}
</script>

<template>
  <div class="flex items-center gap-1.5 text-sm" role="group" aria-label="场景筛选">
    <select
      :value="major"
      class="min-h-11 rounded bg-surface-2 px-2 py-1 text-ink"
      :aria-label="loading ? '场景分类（加载中）' : '场景分类'"
      @change="onMajor"
    >
      <option value="">全部场景</option>
      <option v-for="m in majors" :key="m.name" :value="m.name">
        {{ m.name }}（{{ m.count }}）
      </option>
    </select>
    <select
      v-if="major"
      :value="minor"
      class="min-h-11 rounded bg-surface-2 px-2 py-1 text-ink"
      aria-label="细分场景"
      @change="onMinor"
    >
      <option value="">全部{{ major }}</option>
      <option v-for="m in currentMinors" :key="m.name" :value="m.name">
        {{ m.name }}（{{ m.count }}）
      </option>
    </select>
    <button
      v-if="major"
      type="button"
      class="min-h-11 rounded px-1.5 py-1 text-ink-2 hover:text-ink"
      title="清除场景筛选"
      aria-label="清除场景筛选"
      @click="clear"
    >
      ×
    </button>
  </div>
</template>
