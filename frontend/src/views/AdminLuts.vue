<template>
  <div class="al-page">
    <header class="al-head">
      <h2>滤镜 LUT 管理</h2>
      <button data-test="rescan" @click="onRescan" :disabled="scanning">
        {{ scanning ? "扫描中..." : "重新扫描磁盘" }}
      </button>
    </header>
    <p class="al-hint">
      新增 .cube 文件需放到 <code>backend/data/luts/&lt;group&gt;/</code> 后点"重新扫描"。
    </p>

    <div v-for="g in grouped" :key="g.group" class="al-group">
      <h3>{{ groupLabel(g.group) }}</h3>
      <table>
        <thead>
          <tr><th>启用</th><th>名称</th><th>排序</th><th>文件</th><th>来源 / 许可</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in g.items" :key="row.slug" :class="{ disabled: !row.enabled }">
            <td>
              <button
                aria-label="toggle-enabled"
                @click="onToggle(row)"
              >{{ row.enabled ? "✓" : "·" }}</button>
            </td>
            <td>
              <div class="al-label">{{ row.label }}</div>
              <input v-model="row.label" @change="onLabel(row)" aria-label="编辑名称" />
            </td>
            <td>
              <input type="number" v-model.number="row.sort_order" @change="onSort(row)" style="width:70px" />
            </td>
            <td><code>{{ row.file_path }}</code></td>
            <td class="al-meta">{{ row.source || "—" }} {{ row.license ? "· " + row.license : "" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { groupLabel } from "../lib/lutGroups"

interface LutRow {
  slug: string; label: string; group: string
  enabled: number; sort_order: number
  source: string; license: string; file_path: string; created_at: number
}

const rows = ref<LutRow[]>([])
const scanning = ref(false)

const grouped = computed(() => {
  const m = new Map<string, LutRow[]>()
  for (const r of rows.value) {
    if (!m.has(r.group)) m.set(r.group, [])
    m.get(r.group)!.push(r)
  }
  return Array.from(m.entries()).map(([group, items]) => ({ group, items }))
})

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

<style scoped>
.al-page { padding: 20px; color: #eee; background: #111; min-height: 100vh; }
.al-head { display: flex; justify-content: space-between; align-items: center; }
.al-hint { color: #999; font-size: 13px; }
.al-group { margin-top: 20px; }
.al-group h3 { font-size: 14px; color: #ccc; }
table { width: 100%; border-collapse: collapse; margin-top: 8px; }
td, th { padding: 6px 8px; border-bottom: 1px solid #222; text-align: left; font-size: 13px; }
tr.disabled { opacity: 0.45; }
.al-meta { color: #888; font-size: 12px; }
.al-label { font-size: 13px; color: #eee; margin-bottom: 2px; }
td input { background: #1a1a1a; color: #eee; border: 1px solid #333; padding: 2px 4px; font-size: 13px; }
button { cursor: pointer; }
</style>
