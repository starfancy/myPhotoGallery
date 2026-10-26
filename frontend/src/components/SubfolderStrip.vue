<template>
  <div v-if="folders.length" class="lb-folder-grid py-2">
    <router-link v-for="f in folders" :key="f.relative_path"
                 :to="linkFor(f.relative_path)"
                 class="group flex w-full flex-col overflow-hidden rounded bg-neutral-800 text-sm hover:ring-2 hover:ring-blue-500">
      <div class="relative h-24 w-full overflow-hidden bg-neutral-700">
        <img v-if="f.cover_thumb_sha1"
             :src="`/api/thumb/${f.cover_thumb_sha1}?size=200`"
             class="h-full w-full"
             :class="portrait[f.cover_thumb_sha1] ? 'object-contain' : 'object-cover'"
             loading="lazy"
             :alt="f.name"
             @load="onCoverLoad(f.cover_thumb_sha1, $event)" />
        <!-- 封面借自某个直接子文件夹时，图底渐变条标注来源名 -->
        <div v-if="f.cover_source_name"
             class="lb-folder-source pointer-events-none absolute inset-x-0 bottom-0 flex h-8 items-end px-1.5 pb-0.5"
             :title="f.cover_source_name">
          <span class="truncate text-xs text-white">{{ f.cover_source_name }}</span>
        </div>
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
    cover_source_name?: string | null
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

<style scoped>
/*
 * auto-fill + 1fr：卡片等比拉伸铺满整行，左右边缘与图片网格
 * （JustifiedGrid/MasonryGrid 均为内容区满宽）严格对齐；
 * 最小列宽 128（原 w-32），间距与图片网格同为 12px。
 */
.lb-folder-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(128px, 1fr));
  gap: 12px;
}
/* 借来的封面：图底黑色渐变，托住白色来源名 */
.lb-folder-source {
  background: linear-gradient(to top, rgba(0, 0, 0, 0.75), rgba(0, 0, 0, 0));
}
</style>
