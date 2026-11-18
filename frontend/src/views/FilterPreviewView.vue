<template>
  <div
    class="fp-page"
    :class="{ 'is-resizing': dragging || sideDragging, 'is-dragover': dragOver }"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <header class="fp-topbar">
      <span class="fp-name">{{ name || (isLocal ? "本地图片（未选择）" : "") }}</span>
      <input ref="fileInputEl" type="file" accept="image/*" @change="onPickLocal" hidden />
      <button v-if="isLocal" class="fp-pick-local" @click="fileInputEl?.click()">
        选择本地图片
      </button>
    </header>

    <div class="fp-body">
      <aside
        v-show="sideOpen"
        class="fp-side"
        ref="sideEl"
        :style="sideStyle"
      >
        <LutGroupList :groups="groups" :thumbs="thumbs"
                      :active-id="activeId" :renderer-ready="rendererReady"
                      @pick="pick" />
      </aside>
      <!-- 手柄作为 flex 兄弟项放在滚动容器外，位于滚动条右侧而非压在轨道上 -->
      <div
        v-show="sideOpen"
        class="fp-side-handle"
        :class="{ active: sideDragging }"
        role="separator"
        tabindex="0"
        aria-label="调节左侧滤镜栏宽度"
        aria-orientation="vertical"
        :aria-valuenow="sideAriaNow"
        :aria-valuemin="sideMin ?? 0"
        :aria-valuemax="sideMax"
        @pointerdown="onSidePointerDown"
        @pointermove="onSidePointerMove"
        @pointerup="onSidePointerUp"
        @pointercancel="onSidePointerUp"
        @keydown="onSideKeydown"
      ></div>
      <main class="fp-stage">
        <canvas ref="canvasEl" class="fp-canvas"></canvas>
        <div v-if="fallbackMsg" class="fp-fallback">{{ fallbackMsg }}</div>
        <div v-if="isLocal && !rendererReady && !fallbackMsg" class="fp-fallback">
          从上方"选择本地图片"按钮选一张照片，或直接把图片拖到页面（多张时只打开第一张），纯前端处理，不上传服务器
        </div>
      </main>
    </div>

    <section class="fp-controls">
      <button
        type="button"
        class="fp-side-toggle"
        :class="{ active: sideOpen }"
        data-test="side-toggle"
        :title="sideOpen ? '收起左侧滤镜列表' : '左侧展开滤镜列表'"
        :aria-label="sideOpen ? '收起左侧滤镜列表' : '左侧展开滤镜列表'"
        :aria-pressed="sideOpen"
        @click="toggleSide"
      >{{ sideOpen ? "▶ 收起" : "◀ 滤镜" }}</button>
      <div class="fp-controls-center">
        <label class="fp-strength">
          强度
          <input
            type="range" min="0" max="100"
            :value="mixPct"
            :disabled="!rendererReady"
            @input="onMixInput"
          />
          <span>{{ mixPct }}%</span>
        </label>
        <button
          :disabled="!rendererReady"
          @pointerdown="holdStart"
          @pointerup="holdEnd"
          @pointercancel="holdEnd"
          @pointerleave="holdEnd"
        >按住看原图</button>
        <button :disabled="!rendererReady" @click="onDownload">下载 JPEG</button>
        <button
          v-if="!isLocal"
          :disabled="!rendererReady || !imageId || downloadingOriginal"
          @click="onDownloadOriginal"
        >{{ downloadingOriginal ? "处理中..." : "下载原尺寸 JPEG" }}</button>
      </div>
      <button
        class="fp-strip-toggle"
        :class="{ active: stripOpen }"
        :title="stripOpen ? '收起滤镜列表' : '展开滤镜列表'"
        data-test="strip-toggle"
        :aria-pressed="stripOpen"
        @click="toggleStrip"
      >{{ stripOpen ? "▲ 收起" : "▼ 滤镜" }}</button>
    </section>

    <section v-show="stripOpen" class="fp-strip" ref="stripEl" :style="stripStyle">
      <div
        class="fp-resize-handle"
        :class="{ active: dragging }"
        role="separator"
        tabindex="0"
        aria-label="调节滤镜列表高度"
        aria-orientation="horizontal"
        :aria-valuenow="ariaNow"
        :aria-valuemin="minHeight ?? 0"
        :aria-valuemax="maxHeight"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
        @keydown="onKeydown"
      ></div>
      <!-- 滚动职责在内层：手柄留在不滚动的 section 上，列表滚动时不会随之移出视口 -->
      <div class="fp-strip-scroll">
        <LutGroupList :groups="groups" :thumbs="thumbs"
                      :active-id="activeId" :renderer-ready="rendererReady"
                      @pick="pick" />
      </div>
    </section>

    <div v-if="isLocal && dragOver" class="fp-drop-hint">松开鼠标，打开第一张图片</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import { useRoute } from "vue-router"
import LutGroupList, {
  type FilterEntry,
  type LutGroup,
} from "../components/LutGroupList.vue"
import { LutRenderer } from "../lib/lutRenderer"
import {
  RESIZE_STEP,
  clampHeight,
  draggedHeight,
  draggedWidth,
  steppedHeight,
} from "../lib/resize"
import { parseCube } from "../lib/lutParser"
import type { LutData } from "../lib/lutParser"
import { injectExif } from "../lib/exif"

const route = useRoute()
const isLocal = route.query.local === "1"
const sha1 = String(route.query.sha1 ?? "")
const name = ref(String(route.query.name ?? ""))
const imageId = route.query.image_id ? Number(route.query.image_id) : null

const canvasEl = ref<HTMLCanvasElement | null>(null)
const fileInputEl = ref<HTMLInputElement | null>(null)
const fallbackMsg = ref("")
const rendererReady = ref(false)
const filters = ref<FilterEntry[]>([])
const groups = ref<LutGroup[]>([])
const thumbs = ref<Record<string, string>>({})
const activeId = ref<string | null>(null)
const mixPct = ref(0)
const stripOpen = ref(true)
const sideOpen = ref(false)
const downloadingOriginal = ref(false)

// ---- 本地模式拖拽选图 ----
const dragOver = ref(false)
/** dragenter/dragleave 配对计数：子元素间移动会冒泡 leave，归零才隐藏提示层 */
let dragDepth = 0
/** 当前本地源文件字节，下载时用于把 EXIF 搬回导出 JPEG */
let localSourceBytes: ArrayBuffer | null = null

// ---- 滤镜条可调高度 ----
const stripEl = ref<HTMLElement | null>(null)
/** null = 未手动调节，沿用 CSS 默认 max-height；数字 = 显式像素高度 */
const stripHeight = ref<number | null>(null)
const minHeight = ref<number | null>(null)
const dragging = ref(false)
const maxHeight = computed(() => Math.round(window.innerHeight / 2))
// 显式高度必须同时覆盖 CSS 默认的 max-height:280px，否则 >280 的拖拽结果被钳回去
const stripStyle = computed(() =>
  stripHeight.value === null
    ? {}
    : { height: `${stripHeight.value}px`, maxHeight: "50vh" },
)
const ariaNow = computed(() =>
  stripHeight.value === null ? undefined : Math.round(stripHeight.value),
)

/** 首次交互时实测一行（组标题+缩略图行）所需最小高度，只算一次。 */
function ensureMin(): number {
  if (minHeight.value !== null) return minHeight.value
  const strip = stripEl.value
  const group = strip?.querySelector<HTMLElement>(".fp-group")
  if (!strip || !group) {
    minHeight.value = 120
    return minHeight.value
  }
  const cs = getComputedStyle(strip)
  // || 0 兜底：jsdom 不解析 scoped CSS 时 padding 返回空串
  const pt = parseInt(cs.paddingTop, 10) || 0
  const pb = parseInt(cs.paddingBottom, 10) || 0
  minHeight.value = group.offsetHeight + pt + pb
  return minHeight.value
}

let dragStartY = 0
let dragStartH = 0

function onPointerDown(e: PointerEvent) {
  const min = ensureMin()
  const max = maxHeight.value
  dragStartY = e.clientY
  dragStartH = clampHeight(
    stripHeight.value ?? stripEl.value!.getBoundingClientRect().height,
    min,
    max,
  )
  stripHeight.value = dragStartH
  dragging.value = true
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  stripHeight.value = clampHeight(
    draggedHeight(dragStartH, dragStartY, e.clientY),
    ensureMin(),
    maxHeight.value,
  )
}

function onPointerUp(e: PointerEvent) {
  if (!dragging.value) return
  dragging.value = false
  ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
}

function onKeydown(e: KeyboardEvent) {
  const min = ensureMin()
  const max = maxHeight.value
  const cur =
    stripHeight.value ??
    Math.round(stripEl.value!.getBoundingClientRect().height)
  if (e.key === "ArrowUp") {
    stripHeight.value = steppedHeight(cur, 1, min, max)
  } else if (e.key === "ArrowDown") {
    stripHeight.value = steppedHeight(cur, -1, min, max)
  } else if (e.key === "Home") {
    stripHeight.value = min
  } else if (e.key === "End") {
    stripHeight.value = max
  } else {
    return
  }
  e.preventDefault()
}

// ---- 左侧滤镜栏可调宽度 ----
const sideEl = ref<HTMLElement | null>(null)
/** null = 未手动调节，沿用 CSS 默认 120px；数字 = 显式像素宽度 */
const sideWidth = ref<number | null>(null)
const sideMin = ref<number | null>(null)
const sideDragging = ref(false)
const sideMax = computed(() => Math.round(window.innerWidth / 2))
const sideStyle = computed(() =>
  sideWidth.value === null
    ? {}
    : { width: `${sideWidth.value}px`, maxWidth: "50vw" },
)
const sideAriaNow = computed(() =>
  sideWidth.value === null ? undefined : Math.round(sideWidth.value),
)

/** 首次交互实测一列缩略图所需最小宽度，只算一次。 */
function ensureSideMin(): number {
  if (sideMin.value !== null) return sideMin.value
  const side = sideEl.value
  const thumb = side?.querySelector<HTMLElement>(".fp-thumb")
  if (!side) {
    sideMin.value = 120
    return sideMin.value
  }
  const cs = getComputedStyle(side)
  const pl = parseInt(cs.paddingLeft, 10) || 0
  const pr = parseInt(cs.paddingRight, 10) || 0
  // 无缩略图时 offsetWidth 取不到，回退默认
  sideMin.value = thumb ? thumb.offsetWidth + pl + pr : 120
  return sideMin.value
}

let dragStartX = 0
let dragStartW = 0

function onSidePointerDown(e: PointerEvent) {
  const min = ensureSideMin()
  const max = sideMax.value
  dragStartX = e.clientX
  dragStartW = clampHeight(
    sideWidth.value ?? sideEl.value!.getBoundingClientRect().width,
    min,
    max,
  )
  sideWidth.value = dragStartW
  sideDragging.value = true
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

function onSidePointerMove(e: PointerEvent) {
  if (!sideDragging.value) return
  sideWidth.value = clampHeight(
    draggedWidth(dragStartW, dragStartX, e.clientX),
    ensureSideMin(),
    sideMax.value,
  )
}

function onSidePointerUp(e: PointerEvent) {
  if (!sideDragging.value) return
  sideDragging.value = false
  ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
}

function onSideKeydown(e: KeyboardEvent) {
  const min = ensureSideMin()
  const max = sideMax.value
  const cur =
    sideWidth.value ?? Math.round(sideEl.value!.getBoundingClientRect().width)
  if (e.key === "ArrowRight") {
    sideWidth.value = clampHeight(cur + RESIZE_STEP, min, max)
  } else if (e.key === "ArrowLeft") {
    sideWidth.value = clampHeight(cur - RESIZE_STEP, min, max)
  } else if (e.key === "Home") {
    sideWidth.value = min
  } else if (e.key === "End") {
    sideWidth.value = max
  } else {
    return
  }
  e.preventDefault()
}

// ---- 面板互斥状态机：同一时刻只显示侧栏或底部条 ----
function toggleSide() {
  if (sideOpen.value) sideOpen.value = false
  else { sideOpen.value = true; stripOpen.value = false }
}
function toggleStrip() {
  if (stripOpen.value) stripOpen.value = false
  else { stripOpen.value = true; sideOpen.value = false }
}

let renderer: LutRenderer | null = null
let lastImg: HTMLImageElement | null = null
let currentMix = 0
let heldMix: number | null = null
const lutCache = new Map<string, LutData>()

let cancelled = false
onUnmounted(() => {
  cancelled = true
  renderer?.dispose()
  renderer = null
})

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error("image load failed"))
    img.src = url
  })
}

function onMixInput(e: Event) {
  mixPct.value = Number((e.target as HTMLInputElement).value)
  applyMix()
}

function applyMix() {
  currentMix = mixPct.value / 100
  renderer?.render(currentMix)
}

function holdStart() {
  heldMix = currentMix
  renderer?.render(0)
}
function holdEnd() {
  if (heldMix === null) return
  renderer?.render(heldMix)
  heldMix = null
}

function pick(f: FilterEntry) {
  activeId.value = f.id
  const lut = lutCache.get(f.id)
  if (lut) renderer?.loadLut(f.id, lut)
  if (mixPct.value === 0) mixPct.value = 100
  applyMix()
}

async function onDownload() {
  if (!renderer) return
  try {
    renderer.render(currentMix)
    const blob = await renderer.exportJpeg()
    // 本地模式有源文件字节：把原 EXIF 搬回 canvas 导出（Orientation 已复位为 1）
    const out = localSourceBytes
      ? new Blob(
          [injectExif(localSourceBytes, new Uint8Array(await blob.arrayBuffer()))],
          { type: "image/jpeg" },
        )
      : blob
    triggerDownload(out, `${activeId.value ?? "original"}`)
  } catch (err) {
    console.warn("download failed", err)
    window.alert("下载失败")
  }
}

function triggerDownload(blob: Blob, suffix: string) {
  const a = document.createElement("a")
  const base = name.value.replace(/\.[^.]+$/, "") || "photo"
  a.href = URL.createObjectURL(blob)
  a.download = `${base}-${suffix}.jpg`
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 0)
}

async function onDownloadOriginal() {
  if (!renderer || !imageId || !lastImg) return
  downloadingOriginal.value = true
  try {
    // 1. 拉原图
    const res = await fetch(`/api/image/${imageId}`)
    if (!res.ok) throw new Error(`fetch original failed: ${res.status}`)
    const blob = await res.blob()
    // 原图字节在手：导出时保留原图 EXIF（无 EXIF 的格式 injectExif 会自动原样返回）
    const sourceBytes = await blob.arrayBuffer()
    const objectUrl = URL.createObjectURL(blob)
    try {
      const origImg = await loadImage(objectUrl)
      // 2. 临时把主 canvas 切到原图尺寸，套用当前 LUT + mix
      renderer.setImage(origImg)
      renderer.render(currentMix)
      const outBlob = await renderer.exportJpeg(0.95)
      const merged = injectExif(
        sourceBytes,
        new Uint8Array(await outBlob.arrayBuffer()),
      )
      triggerDownload(
        new Blob([merged], { type: "image/jpeg" }),
        `${activeId.value ?? "original"}-full`,
      )
    } finally {
      URL.revokeObjectURL(objectUrl)
      // 3. 恢复预览：切回 1600 缩略图
      if (!cancelled && renderer && lastImg) {
        renderer.setImage(lastImg)
        renderer.render(currentMix)
      }
    }
  } catch (err) {
    console.warn("original download failed", err)
    window.alert("原尺寸下载失败")
  } finally {
    downloadingOriginal.value = false
  }
}

async function loadLocalFile(file: File) {
  if (!renderer) return
  localSourceBytes = await file.arrayBuffer()
  const url = URL.createObjectURL(file)
  try {
    const img = await loadImage(url)
    if (cancelled) return
    name.value = file.name
    lastImg = img
    renderer.setImage(img)
    rendererReady.value = true
    renderer.render(0)
    // LUT 列表可能已加载完，补渲小样条
    if (filters.value.length > 0) await renderThumbs()
  } catch {
    window.alert("本地图片加载失败")
  } finally {
    URL.revokeObjectURL(url)
  }
}

function onPickLocal(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) void loadLocalFile(file)
  // 清空 value，否则再次选择同一个文件不会触发 change
  input.value = ""
}

function onDragEnter(e: DragEvent) {
  if (!isLocal) return
  if (!e.dataTransfer?.types?.includes("Files")) return
  e.preventDefault()
  dragDepth += 1
  dragOver.value = true
}

function onDragOver(e: DragEvent) {
  // 任何模式都禁止浏览器默认开文件行为（否则误拖文件会让整个 SPA 跳走）；
  // dragover preventDefault 是 drop 事件能够触发的前提
  e.preventDefault()
  if (isLocal && e.dataTransfer) e.dataTransfer.dropEffect = "copy"
}

function onDragLeave() {
  if (!isLocal) return
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) dragOver.value = false
}

async function onDrop(e: DragEvent) {
  // 任何模式都吞掉默认行为，避免浏览器直接打开文件导致 SPA 跳走
  e.preventDefault()
  dragDepth = 0
  dragOver.value = false
  if (!isLocal) return
  const files = Array.from(e.dataTransfer?.files ?? [])
  // 多张受支持图片只打开第一张；非图片混在前面时跳过它
  const first = files.find((f) => f.type.startsWith("image/"))
  if (first) await loadLocalFile(first)
}

onMounted(async () => {
  if (!isLocal && !sha1) {
    fallbackMsg.value = "缺少图片参数（sha1）"
    return
  }
  // 1. 初始化渲染器（WebGL2 不可用 → 降级提示）
  try {
    renderer = new LutRenderer(canvasEl.value!)
  } catch (err) {
    fallbackMsg.value = err instanceof Error ? err.message : "WebGL 初始化失败"
    return
  }
  // 2. gallery 模式：加载 1600 缩略图。本地模式：等用户选图（onPickLocal）。
  if (!isLocal) {
    try {
      const img = await loadImage(`/api/thumb/${sha1}?size=1600`)
      if (cancelled) return
      lastImg = img
      renderer!.setImage(img)
      rendererReady.value = true
      renderer!.render(0)
    } catch {
      if (!cancelled) fallbackMsg.value = "图片加载失败"
      return
    }
  }
  // 3. 从后端 /api/luts 拿已启用列表（按 group 分组）。整体失败才置空；
  // 单支 LUT 失败只跳过该支（小样位置无图，label 仍在），不影响其他滤镜。
  try {
    const res = await fetch("/api/luts")
    if (cancelled) return
    groups.value = (await res.json()) as LutGroup[]
  } catch {
    if (!cancelled) groups.value = []
    return
  }
  // 拍平成 filters 列表（保持现有小样缓存数据结构兼容，id = slug）
  filters.value = groups.value.flatMap((g) =>
    g.items.map((it) => ({ id: it.slug, label: it.label, slug: it.slug })),
  )
  // 4. 对每支 LUT 拉 cube 文本
  for (const f of filters.value) {
    if (cancelled) return
    try {
      const cubeText = await (await fetch(`/api/luts/${f.id}/cube`)).text()
      if (cancelled) return
      lutCache.set(f.id, parseCube(cubeText))
    } catch {
      if (cancelled) return
      // 该支 LUT 损坏：从清单剔除，避免 UI 点到空白
      filters.value = filters.value.filter((x) => x.id !== f.id)
      groups.value = groups.value
        .map((g) => ({ group: g.group, items: g.items.filter((it) => it.slug !== f.id) }))
        .filter((g) => g.items.length > 0)
    }
  }
  // 4. 小样条渲染（本地模式下 onPickLocal 选完图后也会调）
  await renderThumbs()
})

/** 离屏小 canvas + 独立第二个 LutRenderer 渲小样。
 *  buffer 按源图宽高比拟合进 192×128 盒内（等比缩放，不拉伸），
 *  显示端 .fp-thumb img 的 object-fit:contain 完整居中显示；
 *  本地模式 onMounted 时 lastImg 还是 null，由 onPickLocal 选图后补调。 */
async function renderThumbs() {
  if (cancelled || !renderer || !lastImg) return
  const srcW = lastImg.naturalWidth || lastImg.width
  const srcH = lastImg.naturalHeight || lastImg.height
  const scale = Math.min(192 / srcW, 128 / srcH)
  const tw = Math.max(1, Math.round(srcW * scale))
  const th = Math.max(1, Math.round(srcH * scale))
  const thumbCanvas = document.createElement("canvas")
  thumbCanvas.width = tw
  thumbCanvas.height = th
  let thumbRenderer: LutRenderer | null = null
  try {
    thumbRenderer = new LutRenderer(thumbCanvas)
    thumbRenderer.setImage(lastImg)
    thumbRenderer.setViewport(tw, th)
    for (const f of filters.value) {
      if (cancelled) break
      const lut = lutCache.get(f.id)
      if (!lut) continue
      thumbRenderer.loadLut(f.id, lut)
      thumbRenderer.render(1)
      thumbs.value[f.id] = thumbCanvas.toDataURL("image/jpeg", 0.7)
    }
  } catch {
    // 小样渲染失败不阻塞主预览
  } finally {
    thumbRenderer?.dispose()
  }
}
</script>

<style scoped>
.fp-page {
  display: flex; flex-direction: column;
  height: 100vh; background: #111; color: #eee;
  position: relative; /* 拖放提示层的定位参照 */
}
.fp-topbar {
  padding: 10px 16px; font-size: 14px;
  border-bottom: 1px solid #222;
  display: flex; align-items: center; gap: 12px;
}
.fp-pick-local {
  padding: 4px 12px; background: #2a2a2a; color: #eee;
  border: 1px solid #444; border-radius: 6px; cursor: pointer; font-size: 13px;
}
.fp-name { color: #ccc; }
.fp-body {
  flex: 1; min-height: 0; display: flex;
}
.fp-side {
  flex: none;
  /* 默认两列：缩略图 96×2 + 列间距 8 = 200，左右 padding 12×2 = 24，
     另预留 ~24px 给垂直滚动条（overflow:auto 时滚动条占用内容区，
     不预留会因可用宽度不足 200 而换行成一列），合计 248px */
  width: 248px;
  max-width: 50vw;
  overflow-y: auto;
  border-right: 1px solid #222;
  padding: 8px 12px;
}
/* 手柄是 .fp-body 的 flex 兄弟项，位于侧栏滚动条右侧，不遮挡轨道 */
.fp-side-handle {
  flex: none;
  position: relative;
  width: 6px; /* 热区 */
  cursor: col-resize;
  touch-action: none;
}
.fp-side-handle::after {
  content: "";
  position: absolute;
  top: 0; bottom: 0; left: 2px;
  width: 2px;
  background: #444;
}
.fp-side-handle:hover::after,
.fp-side-handle:focus-visible::after,
.fp-side-handle.active::after {
  background: #3b82f6;
}
.fp-side-handle:focus-visible { outline: none; }
.fp-stage {
  flex: 1; min-width: 0;
  display: flex; align-items: center; justify-content: center;
  overflow: hidden; position: relative;
}
.fp-canvas {
  max-width: 100%; max-height: 100%;
  object-fit: contain;
}
.fp-fallback {
  position: absolute; padding: 24px; color: #f87171; text-align: center;
}
.fp-controls {
  display: flex; gap: 16px; align-items: center;
  padding: 10px 16px; border-top: 1px solid #222;
}
.fp-side-toggle { margin-right: auto; }
.fp-strip-toggle { margin-left: auto; }
.fp-controls-center {
  display: flex; gap: 16px; align-items: center;
}
.fp-side-toggle.active,
.fp-strip-toggle.active {
  border-color: #3b82f6;
}
.fp-strength {
  display: flex; align-items: center; gap: 8px; font-size: 13px;
}
.fp-strength input { width: 200px; }
.fp-controls button {
  min-height: 36px; padding: 6px 14px;
  background: #2a2a2a; color: #eee; border: 1px solid #444;
  border-radius: 6px; cursor: pointer;
}
.fp-controls button:disabled { opacity: 0.4; cursor: not-allowed; }
.fp-strip {
  position: relative; /* 手柄绝对定位的参照 */
  border-top: 1px solid #222;
  padding: 8px 16px 12px;
  /* 默认只露一行：padding 20 + 组标题 ~20 + 缩略图按钮 ~86 ≈ 126px；
     拖拽手柄后由内联 height 接管，小屏用 50vh 兜底 */
  max-height: min(126px, 50vh);
  /* 外层不滚动：绝对定位的手柄参照本元素，列表滚动时它钉在顶部不随之移动。
     滚动职责交给内层 .fp-strip-scroll（与左侧栏手柄同模式）。 */
  overflow: hidden;
  display: flex; flex-direction: column;
}
.fp-strip-scroll {
  flex: 1; min-height: 0;
  overflow-y: auto;
}
.fp-resize-handle {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 6px; /* 热区 */
  cursor: row-resize;
  touch-action: none; /* 触屏拖动不引发页面滚动 */
  z-index: 2;
}
.fp-resize-handle::after {
  content: "";
  position: absolute;
  left: 0; right: 0; top: 2px;
  height: 2px; /* 视觉线 */
  background: #444;
}
.fp-resize-handle:hover::after,
.fp-resize-handle:focus-visible::after,
.fp-resize-handle.active::after {
  background: #3b82f6;
}
.fp-resize-handle:focus-visible { outline: none; }
/* 拖拽期间禁止选中文本（在根节点切类，避免 :has 兼容问题） */
.fp-page.is-resizing { user-select: none; }
/* 本地模式拖拽悬停提示层：不接管指针事件，drop 始终落到页面根 */
.fp-drop-hint {
  position: absolute; inset: 12px; z-index: 20;
  display: flex; align-items: center; justify-content: center;
  border: 2px dashed #3b82f6; border-radius: 10px;
  background: rgba(17, 17, 17, 0.82);
  color: #93c5fd; font-size: 16px;
  pointer-events: none;
}
</style>
