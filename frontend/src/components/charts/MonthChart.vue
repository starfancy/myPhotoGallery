<template>
  <div v-if="months.length > 0">
    <div class="overflow-x-auto">
      <svg :width="svgWidth" :height="H" class="block" style="min-width: 720px"
           role="img" :aria-label="ariaLabel">
        <!-- 三条横向网格线：0 / 50% / 100% -->
        <line v-for="y in gridYs" :key="'g' + y"
              :x1="0" :x2="svgWidth" :y1="y" :y2="y"
              stroke="rgb(var(--color-surface-3))" stroke-width="1" />
        <text :x="2" :y="10" font-size="9"
              fill="rgb(var(--color-ink-2))">{{ maxCount }}</text>
        <text :x="2" :y="PLOT_H / 2 + 3" font-size="9"
              fill="rgb(var(--color-ink-2))">{{ halfCount }}</text>

        <!-- 零值月：透明全高命中区，只为悬停可读 -->
        <template v-for="(p, i) in months" :key="p.month">
          <rect :x="i * STEP" :y="0" :width="STEP" :height="PLOT_H"
                fill="transparent">
            <title>{{ p.month }} · {{ p.count }} 张</title>
          </rect>
          <rect v-if="p.count > 0" data-testid="bar"
                :x="i * STEP" :y="barY(p.count)" :width="BAR_W"
                :height="barHeight(p.count)"
                fill="rgb(var(--color-primary))" />
        </template>

        <text v-for="t in yearTicks" :key="t.label + t.x"
              data-testid="year-tick" :x="t.x" :y="H - 4" font-size="9"
              fill="rgb(var(--color-ink-2))">{{ t.label }}</text>
      </svg>
    </div>
    <table class="sr-only">
      <caption>拍摄趋势（按年-月）</caption>
      <thead>
        <tr><th scope="col">月份</th><th scope="col">张数</th></tr>
      </thead>
      <tbody>
        <tr v-for="p in nonZero" :key="p.month">
          <td>{{ p.month }}</td>
          <td>{{ p.count }}</td>
        </tr>
      </tbody>
    </table>
  </div>
  <p v-else class="text-sm text-ink-2">暂无数据</p>
</template>

<script setup lang="ts">
import { computed } from "vue"

interface MonthPoint {
  month: string
  count: number
}

const props = defineProps<{ months: MonthPoint[] }>()

const BAR_W = 3
const BAR_GAP = 1
const STEP = BAR_W + BAR_GAP
const PLOT_H = 120
const LABEL_H = 18
const H = PLOT_H + LABEL_H

const svgWidth = computed(() => Math.max(props.months.length * STEP, 1))
const maxCount = computed(() => props.months.reduce((m, p) => Math.max(m, p.count), 0))
const halfCount = computed(() => Math.round(maxCount.value / 2))
const totalCount = computed(() => props.months.reduce((s, p) => s + p.count, 0))
const nonZero = computed(() => props.months.filter((p) => p.count > 0))

const gridYs = [0, PLOT_H / 2, PLOT_H]

function barHeight(count: number): number {
  if (maxCount.value <= 0) return 0
  // 最小 2px，保证只占极小比例的月份也可见
  return Math.max(2, Math.round((count / maxCount.value) * PLOT_H))
}
function barY(count: number): number {
  return PLOT_H - barHeight(count)
}

const yearTicks = computed(() =>
  props.months
    .map((p, i) => ({ p, i }))
    .filter(({ p }) => p.month.endsWith("-01"))
    .map(({ p, i }) => ({ x: i * STEP, label: p.month.slice(0, 4) })),
)

const ariaLabel = computed(() => {
  if (props.months.length === 0) return "拍摄趋势：暂无数据"
  const first = props.months[0].month
  const last = props.months[props.months.length - 1].month
  const peak = props.months.reduce((a, b) => (b.count > a.count ? b : a))
  return `拍摄趋势：${first} 至 ${last}，共 ${totalCount.value.toLocaleString()} 张，` +
    `最多的月份 ${peak.month} 有 ${peak.count.toLocaleString()} 张`
})
</script>
