<template>
  <nav class="flex items-center gap-1 overflow-x-auto whitespace-nowrap text-sm text-neutral-400" aria-label="面包屑">
    <template v-for="(c, i) in crumbs" :key="c.relative_path">
      <router-link :to="linkFor(c.relative_path)" class="rounded px-2 py-1 hover:bg-neutral-800 hover:text-neutral-100">
        {{ c.name }}
      </router-link>
      <span v-if="i < crumbs.length - 1" class="text-neutral-600">›</span>
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
