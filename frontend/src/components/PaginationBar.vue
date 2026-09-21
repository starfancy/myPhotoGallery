<template>
  <nav class="mx-auto my-4 flex flex-wrap items-center justify-center gap-1 text-sm"
       aria-label="分页">
    <button type="button"
            class="rounded bg-neutral-800 px-3 py-1 text-neutral-300 hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="page <= 1"
            @click="emit('change', page - 1)">上一页</button>
    <template v-for="(p, i) in pageItems" :key="i">
      <span v-if="p === ELLIPSIS" class="px-2 text-neutral-500" aria-hidden="true">…</span>
      <button v-else type="button"
              class="min-w-[34px] rounded px-2 py-1"
              :class="p === page
                ? 'bg-blue-700 text-white'
                : 'bg-neutral-800 text-neutral-300 hover:bg-neutral-700'"
              :aria-current="p === page ? 'page' : undefined"
              @click="emit('change', p)">{{ p }}</button>
    </template>
    <button type="button"
            class="rounded bg-neutral-800 px-3 py-1 text-neutral-300 hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="page >= totalPages"
            @click="emit('change', page + 1)">下一页</button>
  </nav>
</template>

<script setup lang="ts">
import { computed } from "vue"

const props = defineProps<{
  page: number
  totalPages: number
}>()

const emit = defineEmits<{
  (e: "change", page: number): void
}>()

/** 省略号占位（页码不会为负数）。 */
const ELLIPSIS = -1

/**
 * 页码窗口：始终显示首页、末页和当前页相邻页，
 * 不连续处用省略号填充。例如当前第 5 页 / 共 12 页：
 *   1 … 4 [5] 6 … 12
 */
const pageItems = computed<number[]>(() => {
  const tp = props.totalPages
  const cur = props.page
  const wanted = new Set<number>([1, tp, cur - 1, cur, cur + 1])
  const sorted = [...wanted].filter((p) => p >= 1 && p <= tp).sort((a, b) => a - b)
  const out: number[] = []
  let prev = 0
  for (const p of sorted) {
    if (p - prev > 1) out.push(ELLIPSIS)
    out.push(p)
    prev = p
  }
  return out
})
</script>
