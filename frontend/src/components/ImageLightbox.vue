<template>
  <div ref="rootEl"></div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue"
import PhotoSwipe from "photoswipe"
import "photoswipe/style.css"
import type { ImageRow } from "../stores/browse"

const props = defineProps<{
  items: ImageRow[]
  startId: number
}>()

const emit = defineEmits<{
  (e: "close"): void
  (e: "change", id: number): void
}>()

const rootEl = ref<HTMLElement | null>(null)
let pswp: PhotoSwipe | null = null

function open() {
  const idx = props.items.findIndex((it) => it.id === props.startId)
  if (idx < 0) return
  const dataSource = props.items.map((it) => ({
    src: `/api/thumb/${it.sha1}?size=1600`,
    width: it.width ?? 1600,
    height: it.height ?? 1200,
    alt: it.filename,
    image_id: it.id,
  }))
  pswp = new PhotoSwipe({
    dataSource,
    index: idx,
    appendToEl: document.body,
    showHideAnimationType: "fade",
  })
  pswp.on("change", () => {
    if (pswp) emit("change", props.items[pswp.currIndex].id)
  })
  pswp.on("close", () => emit("close"))
  pswp.on("uiRegister", () => {
    pswp!.ui!.registerElement({
      name: "original-image",
      ariaLabel: "查看原图",
      order: 8,
      isButton: true,
      html: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="15 3 21 3 21 9" />
        <polyline points="9 21 3 21 3 15" />
        <line x1="21" y1="3" x2="14" y2="10" />
        <line x1="3" y1="21" x2="10" y2="14" />
      </svg>`,
      onClick: () => {
        const id = pswp!.currSlide?.data?.image_id
        if (id) window.open(`/api/image/${id}`, "_blank")
      },
    })
  })
  pswp.init()
}

onMounted(open)
onUnmounted(() => {
  pswp?.destroy()
  pswp = null
})

watch(() => props.startId, (nid) => {
  if (!pswp) return
  const idx = props.items.findIndex((it) => it.id === nid)
  if (idx >= 0 && idx !== pswp.currIndex) pswp.goTo(idx)
})
</script>
