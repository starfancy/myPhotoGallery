<template>
  <div>
    <template v-if="items.length > 0">
      <ul class="space-y-1.5" role="img" :aria-label="ariaLabel">
        <li v-for="item in items" :key="item.name">
          <div class="flex items-baseline justify-between gap-2">
            <span class="min-w-0 truncate text-xs text-ink-2">{{ item.name }}</span>
            <span class="shrink-0 text-xs tabular-nums text-ink-2">{{ item.count.toLocaleString() }}</span>
          </div>
          <div data-testid="bar-track" class="mt-0.5 h-2 rounded bg-surface-2"
               :title="`${item.name}：${item.count.toLocaleString()} 张（${pct(item.count)}%）`">
            <div data-testid="bar-fill" class="h-2 rounded"
                 :class="item.dimmed ? 'bg-ink-muted/40' : 'bg-primary'"
                 :style="{ width: widthPct(item.count) + '%' }"></div>
          </div>
        </li>
      </ul>
      <!-- sr-only 数据表：与图形为兄弟节点（不嵌在 role=img 内） -->
      <table class="sr-only">
        <caption>{{ title }}</caption>
        <thead>
          <tr><th scope="col">名称</th><th scope="col">张数</th><th scope="col">占比</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.name">
            <td>{{ item.name }}</td>
            <td>{{ item.count }}</td>
            <td>{{ pct(item.count) }}%</td>
          </tr>
        </tbody>
      </table>
    </template>
    <p v-else class="text-sm text-ink-2">暂无数据</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"

interface BarItem {
  name: string
  count: number
  dimmed?: boolean
}

const props = defineProps<{
  title: string
  items: BarItem[]
  total: number
}>()

const maxCount = computed(() =>
  props.items.reduce((m, i) => Math.max(m, i.count), 0),
)

function widthPct(count: number): number {
  if (maxCount.value <= 0) return 0
  return Math.max(count > 0 ? 2 : 0, Math.round((count / maxCount.value) * 100))
}

function pct(count: number): number {
  return props.total > 0 ? Math.round((count / props.total) * 100) : 0
}

const ariaLabel = computed(() =>
  `${props.title}，共 ${props.total.toLocaleString()} 张：` +
  props.items.map((i) => `${i.name} ${i.count.toLocaleString()} 张`).join("，"),
)
</script>
