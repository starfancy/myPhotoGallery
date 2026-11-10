<template>
  <div class="fp-page">
    <header class="fp-topbar">
      <span class="fp-name">{{ name || (isLocal ? "本地图片（未选择）" : "") }}</span>
      <input ref="fileInputEl" type="file" accept="image/*" @change="onPickLocal" hidden />
      <button v-if="isLocal" class="fp-pick-local" @click="fileInputEl?.click()">
        选择本地图片
      </button>
    </header>

    <main class="fp-stage">
      <canvas ref="canvasEl" class="fp-canvas"></canvas>
      <div v-if="fallbackMsg" class="fp-fallback">{{ fallbackMsg }}</div>
      <div v-if="isLocal && !rendererReady && !fallbackMsg" class="fp-fallback">
        从上方"选择本地图片"按钮选一张照片，纯前端处理，不上传服务器
      </div>
    </main>

    <section class="fp-controls">
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
      <button
        class="fp-strip-toggle"
        :title="stripOpen ? '收起滤镜列表' : '展开滤镜列表'"
        data-test="strip-toggle"
        @click="stripOpen = !stripOpen"
      >{{ stripOpen ? "▲ 收起" : "▼ 滤镜" }}</button>
    </section>

    <section v-show="stripOpen" class="fp-strip">
      <div v-for="g in groups" :key="g.group" class="fp-group">
        <div class="fp-group-label">{{ groupLabel(g.group) }}</div>
        <div class="fp-group-items">
          <button
            v-for="f in g.items" :key="f.slug"
            class="fp-thumb" :class="{ active: f.slug === activeId }"
            :disabled="!rendererReady"
            :title="f.label"
            @click="pick({ id: f.slug, label: f.label, slug: f.slug })"
          >
            <img v-if="thumbs[f.slug]" :src="thumbs[f.slug]" :alt="f.label" />
            <span class="fp-thumb-label">{{ f.label }}</span>
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue"
import { useRoute } from "vue-router"
import { LutRenderer } from "../lib/lutRenderer"
import { parseCube } from "../lib/lutParser"
import type { LutData } from "../lib/lutParser"
import { groupLabel } from "../lib/lutGroups"

interface FilterEntry { id: string; label: string; slug: string }
interface LutEntry { slug: string; label: string; sort_order: number }
interface LutGroup { group: string; items: LutEntry[] }

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
const downloadingOriginal = ref(false)

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
    triggerDownload(blob, `${activeId.value ?? "original"}`)
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
    const objectUrl = URL.createObjectURL(blob)
    try {
      const origImg = await loadImage(objectUrl)
      // 2. 临时把主 canvas 切到原图尺寸，套用当前 LUT + mix
      renderer.setImage(origImg)
      renderer.render(currentMix)
      const outBlob = await renderer.exportJpeg(0.95)
      triggerDownload(outBlob, `${activeId.value ?? "original"}-full`)
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

async function onPickLocal(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file || !renderer) return
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

/** 离屏 192×128 小 canvas + 独立第二个 LutRenderer 渲小样。
 *  本地模式 onMounted 时 lastImg 还是 null，由 onPickLocal 选图后补调。 */
async function renderThumbs() {
  if (cancelled || !renderer || !lastImg) return
  const thumbCanvas = document.createElement("canvas")
  thumbCanvas.width = 192
  thumbCanvas.height = 128
  let thumbRenderer: LutRenderer | null = null
  try {
    thumbRenderer = new LutRenderer(thumbCanvas)
    thumbRenderer.setImage(lastImg)
    thumbRenderer.setViewport(192, 128)
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
.fp-stage {
  flex: 1; display: flex; align-items: center; justify-content: center;
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
.fp-strip-toggle { margin-left: auto; }
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
  border-top: 1px solid #222;
  padding: 8px 16px 12px;
  /* 两行缩略图 + 分组标题 + group 间距：约 280px */
  max-height: 280px; overflow-y: auto;
}
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
  width: 88px; height: 58px; object-fit: cover; border-radius: 4px;
  background: #333; display: block;
}
.fp-thumb-label {
  font-size: 11px; color: #ccc; text-align: center;
  width: 88px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
</style>
