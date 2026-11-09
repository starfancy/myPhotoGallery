<template>
  <div>
    <AppHeader>
      <template #title>
        <span class="text-ink-2">管理 · 滤镜 LUT</span>
      </template>
    </AppHeader>
    <main id="main-content" class="mx-auto max-w-4xl space-y-6 p-4">
      <section class="rounded-lg bg-surface p-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h2 class="text-sm font-medium text-ink-2">滤镜 LUT 管理</h2>
          <button type="button"
                  data-test="rescan"
                  @click="onRescan"
                  :disabled="scanning"
                  class="rounded bg-surface-3 px-3 py-1.5 text-sm text-ink hover:bg-surface-4 disabled:cursor-not-allowed disabled:opacity-50">
            {{ scanning ? "扫描中..." : "重新扫描磁盘" }}
          </button>
        </div>
        <p class="mt-2 text-xs text-ink-2">
          新增 .cube 文件需放到 <code>backend/data/luts/&lt;group&gt;/</code> 后点"重新扫描"。
        </p>
      </section>

      <section v-for="g in grouped" :key="g.group" class="rounded-lg bg-surface p-4">
        <!-- 分组头部：折叠按钮 + 名称 + 全选/取消全选 + 计数 -->
        <div class="mb-3 flex flex-wrap items-center gap-3">
          <button type="button"
                  class="flex h-6 w-6 items-center justify-center rounded bg-surface-2 text-ink hover:bg-surface-3"
                  :aria-expanded="!collapsed[g.group]"
                  :aria-label="collapsed[g.group] ? '展开分组' : '折叠分组'"
                  @click="toggleCollapse(g.group)">
            {{ collapsed[g.group] ? "▶" : "▼" }}
          </button>
          <h3 class="text-sm font-medium text-ink-2">{{ groupLabel(g.group) }}</h3>
          <span class="text-xs text-ink-2">{{ enabledCount(g) }}/{{ g.items.length }} 已启用</span>
          <label class="ml-auto flex items-center gap-2 text-xs text-ink-2">
            <input type="checkbox"
                   :checked="allEnabled(g)"
                   :indeterminate.prop="someEnabled(g) && !allEnabled(g)"
                   data-test="group-select-all"
                   @change="onSelectAll(g, ($event.target as HTMLInputElement).checked)" />
            全选
          </label>
        </div>

        <table v-if="!collapsed[g.group]" class="w-full border-collapse text-sm">
          <thead>
            <tr class="text-left text-xs text-ink-2">
              <th class="py-1 pr-2 font-medium">启用</th>
              <th class="py-1 pr-2 font-medium">名称</th>
              <th class="py-1 pr-2 font-medium">排序</th>
              <th class="py-1 pr-2 font-medium">文件</th>
              <th class="py-1 font-medium">来源 / 许可</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in g.items" :key="row.slug"
                class="border-t border-line align-top"
                :class="{ 'opacity-45': !row.enabled }">
              <td class="py-1.5 pr-2">
                <button type="button"
                        aria-label="toggle-enabled"
                        @click="onToggle(row)"
                        class="inline-flex h-7 w-7 items-center justify-center rounded bg-surface-2 text-ink hover:bg-surface-3">
                  {{ row.enabled ? "✓" : "·" }}
                </button>
              </td>
              <td class="py-1.5 pr-2">
                <div class="text-ink">{{ row.label }}</div>
                <input v-model="row.label" @change="onLabel(row)"
                       aria-label="编辑名称"
                       class="mt-1 w-full rounded bg-surface-2 px-2 py-1 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-primary" />
              </td>
              <td class="py-1.5 pr-2">
                <input type="number" v-model.number="row.sort_order" @change="onSort(row)"
                       class="w-20 rounded bg-surface-2 px-2 py-1 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-primary" />
              </td>
              <td class="py-1.5 pr-2">
                <code class="text-xs text-ink-2">{{ row.file_path }}</code>
              </td>
              <td class="py-1.5 text-xs text-ink-2">
                {{ row.source || "—" }} {{ row.license ? "· " + row.license : "" }}
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { groupLabel } from "../lib/lutGroups"

interface LutRow {
  slug: string; label: string; group: string
  enabled: number; sort_order: number
  source: string; license: string; file_path: string; created_at: number
}

const rows = ref<LutRow[]>([])
const scanning = ref(false)
// 默认全部折叠
const collapsed = reactive<Record<string, boolean>>({})

const grouped = computed(() => {
  const m = new Map<string, LutRow[]>()
  for (const r of rows.value) {
    if (!m.has(r.group)) m.set(r.group, [])
    m.get(r.group)!.push(r)
  }
  const arr = Array.from(m.entries()).map(([group, items]) => ({ group, items }))
  // 首次分组时默认折叠每个 group
  for (const g of arr) {
    if (!(g.group in collapsed)) collapsed[g.group] = true
  }
  return arr
})

function toggleCollapse(group: string) {
  collapsed[group] = !collapsed[group]
}

function enabledCount(g: { items: LutRow[] }): number {
  return g.items.filter(r => r.enabled).length
}
function allEnabled(g: { items: LutRow[] }): boolean {
  return g.items.length > 0 && g.items.every(r => r.enabled)
}
function someEnabled(g: { items: LutRow[] }): boolean {
  return g.items.some(r => r.enabled)
}

async function load() {
  const res = await fetch("/api/admin/luts")
  rows.value = await res.json()
}

async function patch(slug: string, body: Record<string, unknown>) {
  await fetch(`/api/admin/luts/${slug}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  })
}

function onToggle(row: LutRow) {
  row.enabled = row.enabled ? 0 : 1
  void patch(row.slug, { enabled: row.enabled })
}
function onLabel(row: LutRow) {
  void patch(row.slug, { label: row.label })
}
function onSort(row: LutRow) {
  void patch(row.slug, { sort_order: row.sort_order })
}

function onSelectAll(g: { items: LutRow[] }, enable: boolean) {
  const val = enable ? 1 : 0
  for (const row of g.items) {
    if (row.enabled !== val) {
      row.enabled = val
      void patch(row.slug, { enabled: val })
    }
  }
}

async function onRescan() {
  scanning.value = true
  try {
    await fetch("/api/admin/luts/rescan", { method: "POST" })
    await load()
  } finally {
    scanning.value = false
  }
}

onMounted(load)
</script>
