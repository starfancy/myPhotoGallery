<template>
  <div ref="rootEl"></div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue"
import PhotoSwipe from "photoswipe"
import "photoswipe/style.css"
import type { ImageRow } from "../stores/browse"
import { useAuthStore } from "../stores/auth"
import { apiDelete, apiGet, HttpError } from "../api"

const props = defineProps<{
  items: ImageRow[]
  startId: number
}>()

const emit = defineEmits<{
  (e: "close"): void
  (e: "change", id: number): void
  (e: "deleted", id: number): void
}>()

const auth = useAuthStore()

const rootEl = ref<HTMLElement | null>(null)
let pswp: PhotoSwipe | null = null
// 100% 原图查看器（内嵌一个独立的 PhotoSwipe 实例，天然支持双指捏合、拖动、双击缩放）
let originalPswp: PhotoSwipe | null = null

// EXIF 侧边面板 DOM——附着在 body 上，只有当前 lightbox 打开时才存在
let exifPanelEl: HTMLElement | null = null
// EXIF 缓存：image_id -> exif dict（避免翻页反复请求同一张）
const exifCache = new Map<number, Record<string, unknown>>()

// 中文标签映射：PIL tag name -> 展示名。GPSInfo 单独展开成两行（经度/纬度）。
const EXIF_LABEL_ZH: Record<string, string> = {
  Make: "相机厂商",
  Model: "相机型号",
  DateTimeOriginal: "拍摄时间",
  ModifyDate: "修改时间",
  ExposureTime: "快门",
  FNumber: "光圈",
  ISOSpeedRatings: "ISO",
  FocalLength: "焦距",
  LensModel: "镜头",
  Orientation: "方向",
  Software: "软件",
  Flash: "闪光灯",
  WhiteBalance: "白平衡",
  ColorSpace: "色彩空间",
  ExposureProgram: "曝光程序",
  MeteringMode: "测光模式",
  ExposureBiasValue: "曝光补偿",
  SceneCaptureType: "场景类型",
  FileSource: "文件来源",
}

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

// ---------- EXIF panel ----------

function formatExifValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return "-"
  if (Array.isArray(value)) return value.map((v) => formatExifValue(key, v)).join(", ")
  if (typeof value === "object") return JSON.stringify(value)
  if (typeof value === "number") {
    if (key === "FNumber") return `f/${value}`
    if (key === "FocalLength") return `${value} mm`
    if (key === "ExposureBiasValue") return `${value >= 0 ? "+" : ""}${value} EV`
    return String(value)
  }
  const s = String(value)
  if (key === "ExposureTime") return `${s} s`
  return s
}

function buildExifRows(exif: Record<string, unknown>): Array<[string, string]> {
  const rows: Array<[string, string]> = []
  for (const [k, v] of Object.entries(exif)) {
    if (k === "GPSInfo" && v && typeof v === "object") {
      const gps = v as Record<string, unknown>
      const latRef = gps.GPSLatitudeRef ?? ""
      const lat = gps.GPSLatitude ?? ""
      const lonRef = gps.GPSLongitudeRef ?? ""
      const lon = gps.GPSLongitude ?? ""
      if (lat || lon) rows.push(["GPS", `${lat} ${latRef}, ${lon} ${lonRef}`.trim()])
      continue
    }
    const label = EXIF_LABEL_ZH[k] ?? k
    rows.push([label, formatExifValue(k, v)])
  }
  return rows
}

function renderExifPanel(imageId: number, exif: Record<string, unknown> | null, err: string | null) {
  if (!exifPanelEl) return
  // 更新当前显示的 image_id 属性，供测试与并发切图时的旧数据丢弃
  exifPanelEl.dataset.imageId = String(imageId)
  const rows = exif ? buildExifRows(exif) : []
  const body = err
    ? `<div class="lb-exif-msg">${err}</div>`
    : rows.length === 0
      ? `<div class="lb-exif-msg">无 EXIF 信息</div>`
      : `<dl class="lb-exif-list">${rows.map(([k, v]) => `
            <div class="lb-exif-row">
              <dt>${k}</dt><dd>${escapeHtml(v)}</dd>
            </div>`).join("")}</dl>`
  exifPanelEl.innerHTML = `
    <div class="lb-exif-head">
      <span>EXIF 信息</span>
      <button class="lb-exif-close" aria-label="关闭">×</button>
    </div>
    <div class="lb-exif-body">${body}</div>`
  const closeBtn = exifPanelEl.querySelector<HTMLButtonElement>(".lb-exif-close")
  closeBtn?.addEventListener("click", closeExifPanel)
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[c] as string)
}

function ensureExifPanel() {
  if (exifPanelEl) return
  const el = document.createElement("aside")
  el.className = "lb-exif-panel"
  el.setAttribute("aria-label", "EXIF 面板")
  document.body.appendChild(el)
  exifPanelEl = el
}

function closeExifPanel() {
  if (!exifPanelEl) return
  exifPanelEl.remove()
  exifPanelEl = null
}

async function openExifPanel() {
  const it = currentSlideItem()
  if (!it) return
  ensureExifPanel()
  const cached = exifCache.get(it.id)
  if (cached !== undefined) {
    renderExifPanel(it.id, cached, null)
    return
  }
  renderExifPanel(it.id, null, null)
  // 占位
  if (exifPanelEl) {
    const body = exifPanelEl.querySelector(".lb-exif-body")
    if (body) body.innerHTML = `<div class="lb-exif-msg">加载中...</div>`
  }
  try {
    const r = await apiGet<{ image_id: number; filename: string; exif: Record<string, unknown> }>(
      `/api/images/${it.id}/exif`,
    )
    exifCache.set(it.id, r.exif ?? {})
    // 若期间用户已切到别的图，仍显示最新 image_id 对应的数据
    const now = currentSlideItem()
    if (exifPanelEl && now && now.id === r.image_id) {
      renderExifPanel(r.image_id, r.exif ?? {}, null)
    }
  } catch (err) {
    const msg = err instanceof HttpError ? err.message : "加载 EXIF 失败"
    renderExifPanel(it.id, null, msg)
  }
}

// slide 切换时若面板打开，自动刷新
function refreshExifPanelIfOpen() {
  if (!exifPanelEl) return
  openExifPanel()
}

// ---------- delete ----------

async function onDeleteClicked() {
  const it = currentSlideItem()
  if (!it) return
  if (!auth.isAdmin) return
  if (!window.confirm(`确定将「${it.filename}」移入回收站？\n\n30 天内可从"回收站"恢复。`)) return
  try {
    await apiDelete(`/api/images/${it.id}`)
  } catch (err) {
    const msg = err instanceof HttpError ? err.message : "删除失败"
    window.alert(`删除失败：${msg}`)
    return
  }
  emit("deleted", it.id)
  // 关闭 lightbox（父组件负责移除该图并更新 URL）
  pswp?.close()
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
    refreshExifPanelIfOpen()
  })
  pswp.on("close", () => {
    closeExifPanel()
    emit("close")
  })
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
    // EXIF 面板按钮
    pswp!.ui!.registerElement({
      name: "exif-info",
      ariaLabel: "EXIF 信息",
      order: 10,
      isButton: true,
      html: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="16" x2="12" y2="12" />
        <line x1="12" y1="8" x2="12.01" y2="8" />
      </svg>`,
      onClick: () => openExifPanel(),
    })
    // 删除按钮：仅 admin 可见
    if (auth.isAdmin) {
      pswp!.ui!.registerElement({
        name: "delete-image",
        ariaLabel: "移入回收站",
        order: 11,
        isButton: true,
        html: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
          <path d="M10 11v6" />
          <path d="M14 11v6" />
          <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
        </svg>`,
        onClick: () => onDeleteClicked(),
      })
    }
  })
  pswp.init()
}

// 组件挂载时打开外层灯箱
onMounted(open)

onUnmounted(() => {
  closeExifPanel()
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

<style>
/* EXIF 侧边面板：附着在 body 顶层，覆盖在 PhotoSwipe 之上 */
.lb-exif-panel {
  position: fixed;
  top: 60px;
  right: 12px;
  width: 320px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  background: rgba(20, 20, 22, 0.94);
  color: #f3f4f6;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 1600; /* PhotoSwipe 默认 1500 */
  font-size: 13px;
  line-height: 1.5;
  backdrop-filter: blur(6px);
}
.lb-exif-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  font-weight: 600;
}
.lb-exif-close {
  background: transparent;
  border: 0;
  color: inherit;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  padding: 0 4px;
}
.lb-exif-close:hover { color: #fff; }
.lb-exif-body { padding: 8px 12px 12px; }
.lb-exif-msg {
  padding: 24px 8px;
  text-align: center;
  color: #9ca3af;
}
.lb-exif-list { margin: 0; }
.lb-exif-row {
  display: grid;
  grid-template-columns: 92px 1fr;
  gap: 8px;
  padding: 4px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
.lb-exif-row:last-child { border-bottom: 0; }
.lb-exif-row dt {
  color: #9ca3af;
  font-weight: 500;
}
.lb-exif-row dd {
  margin: 0;
  color: #f3f4f6;
  overflow-wrap: anywhere;
}
</style>
