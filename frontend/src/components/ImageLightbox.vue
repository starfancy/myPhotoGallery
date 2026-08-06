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
import {
  computeHistogramFromUrl,
  drawHistogram,
  type Histogram,
} from "../lib/histogram"

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
let sidePanelsEl: HTMLElement | null = null
let exifPanelEl: HTMLElement | null = null
let histPanelEl: HTMLElement | null = null
// "更多操作"下拉菜单 DOM
let moreDropdownEl: HTMLElement | null = null
// EXIF 缓存：image_id -> exif dict（避免翻页反复请求同一张）
const exifCache = new Map<number, Record<string, unknown>>()
// 直方图缓存：image_id -> Histogram（RGB 256 桶）
const histCache = new Map<number, Histogram>()
// 翻页切图时用递增序号丢弃过时的异步结果
let exifSeq = 0
let histSeq = 0
// 直方图请求可中止，避免快速翻页时旧图片仍在下载
let histAbort: AbortController | null = null

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
  Software: "软件",
  Flash: "闪光灯",
  WhiteBalance: "白平衡",
  ColorSpace: "色彩空间",
  ExposureProgram: "曝光程序",
  MeteringMode: "测光模式",
  ExposureBiasValue: "曝光补偿",
}

// 抽取出来但不在面板展示的 EXIF 字段：信息量低或用户觉得干扰。
// 后端仍在 exif_json 里保留（面向 API 消费者），前端仅隐藏。
const EXIF_HIDDEN_TAGS = new Set(["Orientation", "SceneCaptureType", "FileSource"])

// EXIF 枚举值到人类可读名称的映射。EXIF 规范定义了每个 tag 的编码方式；
// 数字值单独放这里查询，未命中则回退到原始数字。
const EXIF_ENUM_MAP: Record<string, Record<number, string>> = {
  // EXIF ColorSpace: 1=sRGB, 2=Adobe RGB (Exif 2.3 扩展), 0xFFFF=Uncalibrated
  ColorSpace: {
    1: "sRGB",
    2: "Adobe RGB",
    0xFFFF: "Uncalibrated",
  },
  // ExposureProgram: 0..8 见 EXIF 2.3 §4.6.5
  ExposureProgram: {
    0: "未定义",
    1: "手动",
    2: "程序 AE",
    3: "光圈优先",
    4: "快门优先",
    5: "创意程序",
    6: "运动程序",
    7: "肖像",
    8: "风景",
  },
  // MeteringMode: 0..6, 255
  MeteringMode: {
    0: "未知",
    1: "平均",
    2: "中央重点",
    3: "点测光",
    4: "多点",
    5: "评价",
    6: "局部",
    255: "其它",
  },
  // WhiteBalance: 0=自动, 1=手动
  WhiteBalance: {
    0: "自动",
    1: "手动",
  },
  // Flash: 位掩码，这里只做常见组合的展示；其他值回落到数字
  Flash: {
    0x0: "未闪光",
    0x1: "闪光",
    0x5: "闪光，未检测到回闪",
    0x7: "闪光，检测到回闪",
    0x8: "未闪光（未开启）",
    0x9: "闪光（强制）",
    0x10: "未闪光（关闭）",
    0x18: "未闪光（自动模式）",
    0x19: "闪光（自动模式）",
    0x20: "无闪光功能",
  },
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

// ---------- side panels container ----------
// EXIF 与直方图共享一个右上角固定容器，宽度对齐、顺序固定为 EXIF 在上、
// 直方图在下。任一子面板首次显示时创建容器；最后一个子面板关闭时销毁。

function ensureSidePanels() {
  if (sidePanelsEl) return
  const el = document.createElement("aside")
  el.className = "lb-side-panels"
  el.setAttribute("aria-label", "Lightbox 侧边面板")
  document.body.appendChild(el)
  sidePanelsEl = el
}

function maybeRemoveSidePanels() {
  if (!sidePanelsEl) return
  if (exifPanelEl || histPanelEl) return
  sidePanelsEl.remove()
  sidePanelsEl = null
}

function ensureExifPanel() {
  ensureSidePanels()
  if (exifPanelEl) return
  const el = document.createElement("section")
  el.className = "lb-side-panel lb-exif-panel"
  // EXIF 永远排在容器最前（直方图之上），无论谁先打开
  sidePanelsEl!.insertBefore(el, sidePanelsEl!.firstChild)
  exifPanelEl = el
}

function ensureHistPanel() {
  ensureSidePanels()
  if (histPanelEl) return
  const el = document.createElement("section")
  el.className = "lb-side-panel lb-hist-panel"
  // 直方图总是排在末尾
  sidePanelsEl!.appendChild(el)
  histPanelEl = el
}

function closeExifPanel() {
  if (!exifPanelEl) return
  exifPanelEl.remove()
  exifPanelEl = null
  maybeRemoveSidePanels()
}

function closeHistPanel() {
  if (!histPanelEl) return
  histPanelEl.remove()
  histPanelEl = null
  histAbort?.abort()
  histAbort = null
  maybeRemoveSidePanels()
}

function closeAllSidePanels() {
  closeExifPanel()
  closeHistPanel()
}

// ---------- EXIF panel ----------

function formatExifValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return "-"
  if (Array.isArray(value)) return value.map((v) => formatExifValue(key, v)).join(", ")
  if (typeof value === "object") return JSON.stringify(value)
  if (typeof value === "number") {
    // 枚举先查表，命中则以 "名称 (原值)" 展示；未命中回落到原值
    const enumMap = EXIF_ENUM_MAP[key]
    if (enumMap && enumMap[value] !== undefined) return enumMap[value]
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
    if (EXIF_HIDDEN_TAGS.has(k)) continue
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
  const seq = ++exifSeq
  try {
    const r = await apiGet<{ image_id: number; filename: string; exif: Record<string, unknown> }>(
      `/api/images/${it.id}/exif`,
    )
    exifCache.set(it.id, r.exif ?? {})
    // 若期间用户已切到别的图，忽略这份过时数据
    if (seq !== exifSeq) return
    const now = currentSlideItem()
    if (exifPanelEl && now && now.id === r.image_id) {
      renderExifPanel(r.image_id, r.exif ?? {}, null)
    }
  } catch (err) {
    if (seq !== exifSeq) return
    const msg = err instanceof HttpError ? err.message : "加载 EXIF 失败"
    renderExifPanel(it.id, null, msg)
  }
}

// slide 切换时若面板打开，自动刷新
function refreshExifPanelIfOpen() {
  if (!exifPanelEl) return
  openExifPanel()
}

// ---------- Histogram panel ----------

function renderHistPanel(imageId: number, hist: Histogram | null, msg: string | null) {
  if (!histPanelEl) return
  histPanelEl.dataset.imageId = String(imageId)
  const bodyHtml = msg
    ? `<div class="lb-hist-msg">${msg}</div>`
    : hist
      ? `
          <canvas class="lb-hist-canvas" width="288" height="140"></canvas>
          <dl class="lb-hist-stats">
            <div class="lb-hist-stat"><dt>R 均值</dt><dd>${hist.meanR.toFixed(1)}</dd></div>
            <div class="lb-hist-stat"><dt>G 均值</dt><dd>${hist.meanG.toFixed(1)}</dd></div>
            <div class="lb-hist-stat"><dt>B 均值</dt><dd>${hist.meanB.toFixed(1)}</dd></div>
          </dl>`
      : `<div class="lb-hist-msg">计算中...</div>`
  histPanelEl.innerHTML = `
    <div class="lb-side-head">
      <span>直方图</span>
      <button class="lb-side-close lb-hist-close" aria-label="关闭">×</button>
    </div>
    <div class="lb-hist-body">${bodyHtml}</div>`
  const closeBtn = histPanelEl.querySelector<HTMLButtonElement>(".lb-hist-close")
  closeBtn?.addEventListener("click", closeHistPanel)
  if (hist) {
    const canvas = histPanelEl.querySelector<HTMLCanvasElement>(".lb-hist-canvas")
    if (canvas) drawHistogram(canvas, hist)
  }
}

async function openHistPanel() {
  const it = currentSlideItem()
  if (!it) return
  ensureHistPanel()
  const cached = histCache.get(it.id)
  if (cached) {
    renderHistPanel(it.id, cached, null)
    return
  }
  renderHistPanel(it.id, null, null)
  // 采样源：用 400 缩图（后端 ALLOWED_SIZES = {200, 400, 1600}）。
  // 计算成本约 5–10ms；桶分布和 1600 版本几乎一致，视觉上肉眼看不出差别。
  const url = `/api/thumb/${it.sha1}?size=400`
  histAbort?.abort()
  histAbort = new AbortController()
  const seq = ++histSeq
  try {
    const hist = await computeHistogramFromUrl(url, {
      stride: 2,
      signal: histAbort.signal,
    })
    if (seq !== histSeq) return
    histCache.set(it.id, hist)
    const now = currentSlideItem()
    if (histPanelEl && now && now.id === it.id) {
      renderHistPanel(it.id, hist, null)
    }
  } catch (err) {
    if (seq !== histSeq) return
    if (err instanceof DOMException && err.name === "AbortError") return
    renderHistPanel(it.id, null, "直方图计算失败")
  }
}

function refreshHistPanelIfOpen() {
  if (!histPanelEl) return
  openHistPanel()
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

// ---------- more dropdown ----------

function getPswpRoot(): HTMLElement | null {
  return (pswp as unknown as { template?: HTMLElement })?.template ?? null
}

function closeMoreDropdown() {
  if (!moreDropdownEl) return
  moreDropdownEl.remove()
  moreDropdownEl = null
  document.removeEventListener("click", onDocClickForMore)
  getPswpRoot()?.classList.remove("pswp--more-open")
}

function onDocClickForMore(e: MouseEvent) {
  if (!moreDropdownEl) return
  const t = e.target as HTMLElement
  // 点击下拉菜单内部或 ⋮ 按钮本身时不关闭
  if (moreDropdownEl.contains(t)) return
  if (t.closest(".pswp__button--more-actions")) return
  closeMoreDropdown()
}

function openMoreDropdown() {
  if (moreDropdownEl) return
  const btn = document.querySelector<HTMLElement>(".pswp__button--more-actions")
  if (!btn) return

  const dropdown = document.createElement("div")
  dropdown.className = "lb-more-dropdown"
  dropdown.setAttribute("role", "menu")
  dropdown.innerHTML = `
    <button class="lb-more-dropdown-item" role="menuitem">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="3 6 5 6 21 6" />
        <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
        <path d="M10 11v6" />
        <path d="M14 11v6" />
        <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
      </svg>
      <span>移入回收站</span>
    </button>`

  // 定位：对齐到 ⋮ 按钮右边缘的正下方
  const rect = btn.getBoundingClientRect()
  dropdown.style.position = "fixed"
  dropdown.style.top = `${rect.bottom + 6}px`
  dropdown.style.right = `${window.innerWidth - rect.right}px`

  dropdown.addEventListener("click", (e) => {
    if ((e.target as HTMLElement).closest(".lb-more-dropdown-item")) {
      closeMoreDropdown()
      onDeleteClicked()
    }
  })

  document.body.appendChild(dropdown)
  moreDropdownEl = dropdown
  getPswpRoot()?.classList.add("pswp--more-open")

  // 下一帧再绑定 outside-click，避免本次点击立即触发关闭
  requestAnimationFrame(() => {
    document.addEventListener("click", onDocClickForMore)
  })
}

function toggleMoreDropdown() {
  if (moreDropdownEl) {
    closeMoreDropdown()
  } else {
    openMoreDropdown()
  }
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
    // 切图时自动折叠下拉菜单，避免下一张误触
    closeMoreDropdown()
    refreshExifPanelIfOpen()
    refreshHistPanelIfOpen()
  })
  pswp.on("close", () => {
    closeMoreDropdown()
    closeAllSidePanels()
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
    // 直方图按钮
    pswp!.ui!.registerElement({
      name: "histogram",
      ariaLabel: "直方图",
      order: 11,
      isButton: true,
      html: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="4" y1="20" x2="4" y2="12" />
        <line x1="9" y1="20" x2="9" y2="4" />
        <line x1="14" y1="20" x2="14" y2="9" />
        <line x1="19" y1="20" x2="19" y2="14" />
      </svg>`,
      onClick: () => openHistPanel(),
    })
    // "更多操作"折叠按钮——仅 admin 可见，点击在正下方弹出下拉菜单
    if (auth.isAdmin) {
      pswp!.ui!.registerElement({
        name: "more-actions",
        ariaLabel: "更多操作",
        order: 12,
        isButton: true,
        html: `<svg width="24" height="24" viewBox="0 0 24 24" fill="white">
          <circle cx="5" cy="12" r="2" />
          <circle cx="12" cy="12" r="2" />
          <circle cx="19" cy="12" r="2" />
        </svg>`,
        onClick: () => toggleMoreDropdown(),
      })
    }
  })
  pswp.init()
}

// 组件挂载时尝试打开；若 items 尚未加载（例如页面刷新直达 /image/:iid，
// 父组件的 loadAll() 还在异步中），open() 会因找不到 startId 而 no-op。
// 下面的 watch 会在 items 到达后再尝试一次。
onMounted(open)

onUnmounted(() => {
  closeMoreDropdown()
  closeAllSidePanels()
  originalPswp?.destroy()
  originalPswp = null
  pswp?.destroy()
  pswp = null
})

// 单个 watch 统一处理两种情况：
//  1) pswp 已开：startId 变化 → goTo 目标索引
//  2) pswp 未开：items 加载完 / startId 首次可解析 → 补一次 open()
watch(
  [() => props.startId, () => props.items],
  ([nid]) => {
    if (!pswp) {
      // 挂载时 items 为空的情况，等到 items 到齐后自动补开
      open()
      return
    }
    const idx = props.items.findIndex((it) => it.id === nid)
    if (idx >= 0 && idx !== pswp.currIndex) pswp.goTo(idx)
  },
)
</script>

<style>
/* ---- "更多操作"下拉菜单 ---- */

/* ⋮ 按钮激活态：蓝色高亮背景，与常态形成明显区分 */
.pswp--more-open .pswp__button--more-actions {
  background: rgba(59, 130, 246, 0.35);
  border-radius: 6px;
}

/* 下拉菜单容器：浮在灯箱工具栏正下方 */
.lb-more-dropdown {
  z-index: 100020; /* 高于侧边面板的 100010 */
  background: rgba(24, 24, 27, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(8px);
  padding: 4px;
  min-width: 160px;
}
.lb-more-dropdown-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #fca5a5; /* 红色调提示这是危险操作 */
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}
.lb-more-dropdown-item:hover {
  background: rgba(255, 255, 255, 0.1);
}
.lb-more-dropdown-item:active {
  background: rgba(255, 255, 255, 0.15);
}

/* 侧边面板共享容器：附着在 body 顶层，右上角固定，浮在 PhotoSwipe 之上。
   内部子面板（EXIF、直方图）垂直排列，宽度一致。 */
.lb-side-panels {
  position: fixed;
  top: 60px;
  /* PhotoSwipe 右翻页按钮宽 75px 贴在 right:0，留出 88px 避免遮挡 */
  right: 88px;
  width: 320px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  /* PhotoSwipe v5 根 z-index = --pswp-root-z-index (默认 100000)，
     必须比它高才能覆盖在灯箱之上。 */
  z-index: 100010;
  pointer-events: none; /* 容器本身不吃事件，子面板单独启用 */
}
.lb-side-panel {
  background: rgba(20, 20, 22, 0.94);
  color: #f3f4f6;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  font-size: 13px;
  line-height: 1.5;
  backdrop-filter: blur(6px);
  pointer-events: auto;
}
.lb-side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  font-weight: 600;
}
.lb-side-close {
  background: transparent;
  border: 0;
  color: inherit;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  padding: 0 4px;
}
.lb-side-close:hover { color: #fff; }

/* --- EXIF 子面板（沿用旧类名，容器已由 .lb-side-panels 管理） --- */
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

/* --- 直方图子面板 --- */
.lb-hist-body { padding: 8px 12px 12px; }
.lb-hist-msg {
  padding: 24px 8px;
  text-align: center;
  color: #9ca3af;
}
.lb-hist-canvas {
  display: block;
  width: 100%;
  height: 140px;
  background: rgba(0, 0, 0, 0.35);
  border-radius: 4px;
}
.lb-hist-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  margin: 8px 0 0;
  font-size: 12px;
}
.lb-hist-stat {
  text-align: center;
  padding: 4px 0;
}
.lb-hist-stat dt {
  color: #9ca3af;
  margin-bottom: 2px;
}
.lb-hist-stat dd {
  margin: 0;
  color: #f3f4f6;
  font-variant-numeric: tabular-nums;
}

/* 独立 EXIF 面板（旧类名兼容）——当只有 EXIF 打开时视觉一致 */
.lb-exif-panel { /* 现在只是 .lb-side-panel 的一个变体，无需重复背景等 */ }
</style>
