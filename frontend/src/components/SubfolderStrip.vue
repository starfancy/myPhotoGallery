<template>
  <div v-if="folders.length" class="flex flex-wrap gap-3 px-1 py-2">
    <router-link v-for="f in folders" :key="f.relative_path"
                 :to="linkFor(f.relative_path)"
                 class="group flex w-32 flex-none flex-col overflow-hidden rounded bg-neutral-800 text-sm hover:ring-2 hover:ring-blue-500">
      <div class="h-24 w-full overflow-hidden bg-neutral-700">
        <img v-if="f.cover_thumb_sha1"
             :src="`/api/thumb/${f.cover_thumb_sha1}?size=200`"
             class="h-full w-full"
             :class="portrait[f.cover_thumb_sha1] ? 'object-contain' : 'object-cover'"
             loading="lazy"
             :alt="f.name"
             @load="onCoverLoad(f.cover_thumb_sha1, $event)" />
      </div>
      <div class="truncate p-2">
        <div class="truncate font-medium">{{ f.name }}</div>
        <div class="text-xs text-neutral-400">{{ f.descendant_count }} 张</div>
      </div>
    </router-link>
  </div>
</template>

<script setup lang="ts">
import { reactive } from "vue"

const props = defineProps<{
  folders: Array<{
    name: string
    relative_path: string
    image_count: number
    descendant_count: number
    cover_thumb_sha1: string | null
  }>
  gid: number
  rid: number
}>()

// 记录每张封面缩略图是否为竖版（宽 < 高）。key 为 sha1，多个文件夹复用同一封面时可共享判定。
const portrait = reactive<Record<string, boolean>>({})

function onCoverLoad(sha1: string | null, e: Event) {
  if (!sha1) return
  const img = e.target as HTMLImageElement
  portrait[sha1] = img.naturalWidth < img.naturalHeight
}

function linkFor(rel: string) {
  return `/galleries/${props.gid}/r/${props.rid}/${rel}`
}
</script>
