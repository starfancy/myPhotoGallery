<template>
  <nav class="flex items-center gap-1 overflow-x-auto whitespace-nowrap text-sm text-ink-2" aria-label="面包屑">
    <template v-for="(c, i) in crumbs" :key="c.relative_path">
      <router-link :to="linkFor(c.relative_path)" class="rounded px-2 py-1 hover:bg-surface-2 hover:text-ink">
        {{ c.name }}
      </router-link>
      <span v-if="i < crumbs.length - 1" class="text-ink-muted">›</span>
    </template>
  </nav>
</template>

<script setup lang="ts">
const props = defineProps<{
  crumbs: Array<{ name: string; relative_path: string }>
  gid: number
  rid: number
}>()

function linkFor(rel: string) {
  const suffix = rel ? `/${rel}` : ""
  return `/galleries/${props.gid}/r/${props.rid}${suffix}`
}
</script>
