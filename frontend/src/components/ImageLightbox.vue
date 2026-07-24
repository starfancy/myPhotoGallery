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
// 100% 原图查看器（内嵌一个独立的 PhotoSwipe 实例，天然支持双指捏合、拖动、双击缩放）
let originalPswp: PhotoSwipe | null = null

function currentSlideItem(): ImageRow | null {
  if (!pswp) return null
  return props.items[pswp.currIndex] ?? null
}

function openOriginal() {
  const it = currentSlideItem()
  if (!it || originalPswp) return
  const url = `/api/image/${it.id}`
  originalPswp = new PhotoSwipe({
    dataSource: [{
      src: url,
      // 先用已经加载好的 1600 缩略图作为占位，等原图下载后自动切换
      msrc: `/api/thumb/${it.sha1}?size=1600`,
      width: it.width ?? 1600,
      height: it.height ?? 1200,
      alt: it.filename,
    }],
    index: 0,
    // 初始按 1:1 显示（即 100% 原始尺寸），用户可再捏合放大/缩小
    initialZoomLevel: 1,
    secondaryZoomLevel: "fit",
    maxZoomLevel: 4,
    appendToEl: document.body,
    showHideAnimationType: "fade",
    bgOpacity: 0.95,
    // 关闭滑动手势，避免和外层灯箱冲突
    closeOnVerticalDrag: false,
    pinchToClose: false,
    // 加一个自定义类，样式里用它渲染浅色外框，与外层灯箱视觉区分
    mainClass: "pswp--original",
  })
  originalPswp.on("uiRegister", () => {
    originalPswp!.ui!.registerElement({
      name: "open-newtab",
      ariaLabel: "在新标签页打开",
      order: 8,
      isButton: true,
      html: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
        <polyline points="15 3 21 3 21 9" />
        <line x1="10" y1="14" x2="21" y2="3" />
      </svg>`,
      onClick: () => window.open(url, "_blank", "noopener"),
    })
  })
  originalPswp.on("destroy", () => {
    originalPswp = null
  })
  originalPswp.init()
}

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
    // 在原页弹窗中显示 100% 原图（默认操作）
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
      onClick: () => openOriginal(),
    })
    // 在新标签页打开原图
    pswp!.ui!.registerElement({
      name: "original-image-newtab",
      ariaLabel: "在新标签页打开原图",
      order: 9,
      isButton: true,
      html: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
        <polyline points="15 3 21 3 21 9" />
        <line x1="10" y1="14" x2="21" y2="3" />
      </svg>`,
      onClick: () => {
        const id = pswp!.currSlide?.data?.image_id
        if (id) window.open(`/api/image/${id}`, "_blank", "noopener")
      },
    })
  })
  pswp.init()
}

// 组件挂载时打开外层灯箱
onMounted(open)

onUnmounted(() => {
  originalPswp?.destroy()
  originalPswp = null
  pswp?.destroy()
  pswp = null
})

watch(() => props.startId, (nid) => {
  if (!pswp) return
  const idx = props.items.findIndex((it) => it.id === nid)
  if (idx >= 0 && idx !== pswp.currIndex) pswp.goTo(idx)
})
</script>
