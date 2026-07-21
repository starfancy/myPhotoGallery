<template>
  <div ref="rootEl" class="w-full">
    <div v-for="(row, ri) in rows" :key="ri"
         class="flex gap-1"
         :style="{ marginBottom: `${gap}px` }">
      <button v-for="cell in row.items" :key="cell.id"
              class="relative overflow-hidden bg-neutral-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
              :style="{ width: `${cell.scaledW}px`, height: `${cell.scaledH}px` }"
              @click="$emit('open', cell.id)">
        <img :src="`/api/thumb/${cell.sha1}?size=400`"
             :srcset="`/api/thumb/${cell.sha1}?size=200 200w, /api/thumb/${cell.sha1}?size=400 400w`"
             sizes="(max-width: 640px) 200px, 400px"
             loading="lazy"
             :alt="cell.filename"
             class="h-full w-full object-cover" />
      </button>
    </div>
    <button v-if="canLoadMore" class="mx-auto my-4 block rounded bg-neutral-800 px-4 py-2 text-sm"
            @click="$emit('loadMore')">加载更多</button>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import type { ImageRow } from "../stores/browse"
import { justifiedRows, LayoutInput } from "../utils/layout"

const props = defineProps<{
  items: ImageRow[]
  canLoadMore: boolean
  targetHeight?: number
}>()

defineEmits<{
  (e: "open", id: number): void
  (e: "loadMore"): void
}>()

const rootEl = ref<HTMLElement | null>(null)
const width = ref(1000)

function measure() {
  if (rootEl.value) width.value = rootEl.value.clientWidth
}

let ro: ResizeObserver | null = null
onMounted(() => {
  measure()
  ro = new ResizeObserver(measure)
  if (rootEl.value) ro.observe(rootEl.value)
})
onUnmounted(() => ro?.disconnect())

const gap = 4

const rows = computed(() => {
  const input: (LayoutInput & { id: number; sha1: string; filename: string })[] = props.items.map((it) => ({
    id: it.id,
    sha1: it.sha1,
    filename: it.filename,
    w: it.width ?? 4,
    h: it.height ?? 3,
  }))
  const laid = justifiedRows(input, width.value, props.targetHeight ?? 200, gap)
  // attach id/sha1/filename back onto laid items (they are shallow copies via spread)
  return laid.map((row) => ({
    height: row.height,
    items: row.items as unknown as Array<{ id: number; sha1: string; filename: string; scaledW: number; scaledH: number }>,
  }))
})
</script>
