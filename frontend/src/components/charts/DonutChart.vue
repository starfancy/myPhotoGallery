<template>
  <div>
    <div v-if="total > 0">
      <div class="flex items-center gap-4" role="img" :aria-label="ariaLabel">
        <div class="relative h-32 w-32 shrink-0">
          <svg viewBox="0 0 120 120" class="h-full w-full -rotate-90" aria-hidden="true">
            <circle cx="60" cy="60" :r="RADIUS" fill="none"
                    stroke="rgb(var(--color-surface-2))" :stroke-width="STROKE" />
            <circle v-for="seg in drawn" :key="seg.key"
                    cx="60" cy="60" :r="RADIUS" fill="none"
                    :stroke="seg.color" :stroke-width="STROKE"
                    :stroke-dasharray="seg.dash"
                    :stroke-dashoffset="seg.offset" />
          </svg>
          <div class="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span class="text-xl font-medium leading-none tabular-nums">{{ total.toLocaleString() }}</span>
            <span class="mt-1 text-xs text-ink-2">{{ label }}</span>
          </div>
        </div>
        <ul class="min-w-0 flex-1 space-y-1">
          <li v-for="seg in segments" :key="seg.key"
              class="flex items-center gap-2 text-xs"
              :class="seg.count === 0 ? 'opacity-40' : ''">
            <span class="h-2.5 w-2.5 shrink-0 rounded-sm" :style="{ backgroundColor: seg.color }"></span>
            <span class="min-w-0 truncate text-ink-2">{{ seg.name }}</span>
            <span class="ml-auto shrink-0 tabular-nums text-ink-2">{{ seg.count.toLocaleString() }}</span>
            <span class="w-11 shrink-0 text-right tabular-nums text-ink-2">{{ pct(seg.count) }}%</span>
          </li>
        </ul>
      </div>
      <!-- 屏幕阅读器数据表：与图形同源数据，视觉隐藏 -->
      <table class="sr-only">
        <caption>{{ title }}</caption>
        <thead>
          <tr><th scope="col">分类</th><th scope="col">张数</th><th scope="col">占比</th></tr>
        </thead>
        <tbody>
          <tr v-for="seg in segments" :key="seg.key">
            <td>{{ seg.name }}</td>
            <td>{{ seg.count }}</td>
            <td>{{ pct(seg.count) }}%</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="text-sm text-ink-2">暂无数据</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"

interface Segment {
  key: string
  name: string
  count: number
  color: string
}

const props = defineProps<{
  title: string
  label: string
  total: number
  segments: Segment[]
}>()

const RADIUS = 40
const STROKE = 14
const C = 2 * Math.PI * RADIUS
const GAP = 2 // 段间间隔 px；单段时不加间隔

interface DrawnSegment extends Segment {
  dash: string
  offset: number
}

const drawn = computed<DrawnSegment[]>(() => {
  const visible = props.segments.filter((s) => s.count > 0)
  const gap = visible.length > 1 ? GAP : 0
  let acc = 0
  return visible.map((seg) => {
    const frac = seg.count / props.total
    const len = Math.max(0, frac * C - gap)
    const out: DrawnSegment = {
      ...seg,
      dash: `${len} ${C - len}`,
      offset: -acc,
    }
    acc += frac * C
    return out
  })
})

function pct(count: number): number {
  return props.total > 0 ? Math.round((count / props.total) * 100) : 0
}

const ariaLabel = computed(() => {
  const parts = props.segments
    .filter((s) => s.count > 0)
    .map((s) => `${s.name} ${s.count.toLocaleString()} 张 ${pct(s.count)}%`)
  return `${props.title}，共 ${props.total.toLocaleString()} 张：${parts.join("，")}`
})
</script>
