<script setup lang="ts">
/** 场景筛选下拉（tags Phase 2）：一级 + 联动二级。
 *  选项来自 /api/tags/stats，按当前浏览文件夹范围过滤；
 *  一级固定 9 类，二级按选中一级动态加载。 */
import { onMounted, ref, watch } from "vue"
import { apiGet } from "../api"

const props = defineProps<{
  major: string
  minor: string
  /** 当前浏览范围（用于限定统计只显示此文件夹下的分类） */
  gid?: number
  rid?: number
  path?: string
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
    const params = new URLSearchParams()
    if (props.rid) params.set("root_id", String(props.rid))
    if (props.path) params.set("path", props.path)
    else if (props.gid) params.set("gallery_id", String(props.gid))
    const query = params.toString() ? `?${params.toString()}` : ""
    const r = await apiGet<{ majors: MajorGroup[] }>(`/api/tags/stats${query}`)
    majors.value = r.majors
  } catch {
    majors.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadStats)

const currentMinors = ref<MinorGroup[]>([])
// 只在 major【实际变化】时清空 minor；immediate 初次运行不能清，
// 否则带 scene_minor 的 URL（分享链接/刷新）一挂载就被抹掉二级筛选。
let lastMajor = props.major
watch(
  () => props.major,
  (m) => {
    const group = majors.value.find((g) => g.name === m)
    currentMinors.value = group ? group.minors : []
    if (m !== lastMajor) {
      lastMajor = m
      if (props.minor) emit("update:minor", "")
    }
  },
  { immediate: true },
)
watch(majors, () => {
  const group = majors.value.find((g) => g.name === props.major)
  currentMinors.value = group ? group.minors : []
})
// 浏览范围变化时重新拉取当前文件夹的分类分布
watch(() => [props.rid, props.path], loadStats)

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
