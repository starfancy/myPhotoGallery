<template>
  <div v-for="g in groups" :key="g.group" class="fp-group">
    <div class="fp-group-label">{{ groupLabel(g.group) }}</div>
    <div class="fp-group-items">
      <button
        v-for="f in g.items" :key="f.slug"
        class="fp-thumb" :class="{ active: f.slug === activeId }"
        :disabled="!rendererReady"
        :title="f.label"
        @click="$emit('pick', { id: f.slug, label: f.label, slug: f.slug })"
      >
        <img v-if="thumbs[f.slug]" :src="thumbs[f.slug]" :alt="f.label" />
        <span class="fp-thumb-label">{{ f.label }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { groupLabel } from "../lib/lutGroups"

export interface FilterEntry { id: string; label: string; slug: string }
export interface LutEntry { slug: string; label: string; sort_order: number }
export interface LutGroup { group: string; items: LutEntry[] }

defineProps<{
  groups: LutGroup[]
  thumbs: Record<string, string>
  activeId: string | null
  rendererReady: boolean
}>()
defineEmits<{ (e: "pick", entry: FilterEntry): void }>()
</script>

<style scoped>
.fp-group { margin-bottom: 10px; }
.fp-group:last-child { margin-bottom: 0; }
.fp-group-label {
  font-size: 12px; color: #999; margin-bottom: 6px;
}
.fp-group-items {
  display: flex; flex-wrap: wrap; gap: 8px;
}
.fp-thumb {
  /* 固定列宽：缩略图与下方名称严格按列对齐 */
  width: 96px;
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  background: transparent; border: 2px solid transparent;
  padding: 4px; cursor: pointer; border-radius: 6px;
}
.fp-thumb.active { border-color: #3b82f6; }
.fp-thumb img {
  width: 88px; height: 58px; object-fit: contain; border-radius: 4px;
  background: #333; display: block;
}
.fp-thumb-label {
  font-size: 11px; color: #ccc; text-align: center;
  width: 88px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
</style>
