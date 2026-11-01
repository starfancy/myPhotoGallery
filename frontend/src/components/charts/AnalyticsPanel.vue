<template>
  <section>
    <h2 class="mb-2 text-sm font-medium text-ink-2">拍摄数据分析</h2>

    <div v-if="loading" class="text-sm text-ink-2">加载中...</div>

    <div v-else-if="error" role="alert" class="flex flex-wrap items-center gap-2 text-sm">
      <span class="text-danger-text">{{ error }}</span>
      <button type="button"
              class="rounded bg-surface-3 px-2 py-1 text-xs hover:bg-surface-4"
              @click="load">重试</button>
    </div>

    <template v-else-if="data">
      <p class="mb-3 text-xs text-ink-2">
        基于 EXIF · 共 {{ data.total.toLocaleString() }} 张，
        {{ data.with_exif.toLocaleString() }} 张含拍摄参数
      </p>

      <div v-if="data.total === 0" class="rounded-lg bg-surface p-4 text-sm text-ink-2">
        暂无已扫描的图片
      </div>

      <template v-else>
        <div class="grid gap-4 sm:grid-cols-2">
          <div class="rounded-lg bg-surface p-4">
            <h3 class="mb-3 text-xs font-medium text-ink-2">相机厂商 (Top 8)</h3>
            <HBarChart title="相机厂商" :items="withDim(data.makes)" :total="data.total" />
          </div>
          <div class="rounded-lg bg-surface p-4">
            <h3 class="mb-3 text-xs font-medium text-ink-2">相机机型 (Top 8)</h3>
            <HBarChart title="相机机型" :items="withDim(data.cameras)" :total="data.total" />
          </div>
          <div class="rounded-lg bg-surface p-4">
            <h3 class="mb-3 text-xs font-medium text-ink-2">焦段分布</h3>
            <DonutChart title="焦段分布" label="张" :total="data.total"
                        :segments="focalSegments" />
          </div>
          <div class="rounded-lg bg-surface p-4">
            <h3 class="mb-3 text-xs font-medium text-ink-2">光圈分布</h3>
            <DonutChart title="光圈分布" label="张" :total="data.total"
                        :segments="apertureSegments" />
          </div>
        </div>

        <div class="mt-4 rounded-lg bg-surface p-4">
          <h3 class="mb-3 flex items-center justify-between text-xs font-medium text-ink-2">
            <span>拍摄趋势（按年-月）</span>
            <span v-if="data.without_taken_at > 0" class="font-normal text-ink-2">
              无拍摄日期 {{ data.without_taken_at.toLocaleString() }} 张
            </span>
          </h3>
          <MonthChart :months="data.months" />
        </div>
      </template>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue"
import { apiGet, errorMessage } from "../../api"
import DonutChart from "./DonutChart.vue"
import HBarChart from "./HBarChart.vue"
import MonthChart from "./MonthChart.vue"

interface NameCount { name: string; count: number }
interface Segment { key: string; name: string; count: number }

interface AnalyticsResponse {
  total: number
  with_exif: number
  without_taken_at: number
  makes: NameCount[]
  cameras: NameCount[]
  focal_ranges: Segment[]
  apertures: Segment[]
  months: { month: string; count: number }[]
}

const MUTED = "rgb(var(--color-ink-muted) / 0.5)"
const cssVar = (name: string) => `rgb(var(--color-${name}))`

const FOCAL_COLORS: Record<string, string> = {
  wide: cssVar("chart-1"),
  standard: cssVar("chart-2"),
  tele: cssVar("chart-3"),
  unknown: MUTED,
}

const APERTURE_COLORS: Record<string, string> = {
  f28: cssVar("chart-1"),
  f4: cssVar("chart-2"),
  f56: cssVar("chart-3"),
  f8: cssVar("chart-4"),
  f11plus: cssVar("chart-5"),
  unknown: MUTED,
}

const data = ref<AnalyticsResponse | null>(null)
const loading = ref(true)
const error = ref("")

async function load() {
  loading.value = true
  error.value = ""
  try {
    data.value = await apiGet<AnalyticsResponse>("/api/admin/analytics")
  } catch (err) {
    error.value = errorMessage(err, "统计数据加载失败")
  } finally {
    loading.value = false
  }
}

onMounted(load)

function withDim(items: NameCount[]): (NameCount & { dimmed: boolean })[] {
  return items.map((i) => ({
    ...i,
    dimmed: i.name === "其他" || i.name === "未知",
  }))
}

function withColor(segments: Segment[], map: Record<string, string>) {
  return segments.map((s) => ({ ...s, color: map[s.key] ?? MUTED }))
}

const focalSegments = ref<ReturnType<typeof withColor>>([])
const apertureSegments = ref<ReturnType<typeof withColor>>([])

// data 到达后给分段着色（颜色映射固定，色值本身是 CSS 变量，明暗主题自动生效）
watch(data, (d) => {
  if (!d) return
  focalSegments.value = withColor(d.focal_ranges, FOCAL_COLORS)
  apertureSegments.value = withColor(d.apertures, APERTURE_COLORS)
})
</script>
