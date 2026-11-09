<template>
  <div class="fp-page">
    <header class="fp-topbar">
      <span class="fp-name">{{ name }}</span>
    </header>

    <main class="fp-stage">
      <canvas ref="canvasEl" class="fp-canvas"></canvas>
      <div v-if="fallbackMsg" class="fp-fallback">{{ fallbackMsg }}</div>
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
    </section>

    <section class="fp-strip">
      <button
        v-for="f in filters" :key="f.id"
        class="fp-thumb" :class="{ active: f.id === activeId }"
        :disabled="!rendererReady"
        @click="pick(f)"
      >
        <img v-if="thumbs[f.id]" :src="thumbs[f.id]" :alt="f.label" />
        <span class="fp-thumb-label">{{ f.label }}</span>
      </button>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue"
import { useRoute } from "vue-router"
import { LutRenderer } from "../lib/lutRenderer"
import { parseCube } from "../lib/lutParser"
import type { LutData } from "../lib/lutParser"

interface FilterEntry { id: string; label: string; file: string }

const route = useRoute()
const sha1 = String(route.query.sha1 ?? "")
const name = String(route.query.name ?? "")

const canvasEl = ref<HTMLCanvasElement | null>(null)
const fallbackMsg = ref("")
const rendererReady = ref(false)
const filters = ref<FilterEntry[]>([])
const thumbs = ref<Record<string, string>>({})
const activeId = ref<string | null>(null)
const mixPct = ref(0)

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
  renderer.render(currentMix)
  const blob = await renderer.exportJpeg()
  const a = document.createElement("a")
  const base = name.replace(/\.[^.]+$/, "") || "photo"
  a.href = URL.createObjectURL(blob)
  a.download = `${base}-${activeId.value ?? "original"}.jpg`
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 0)
}

onMounted(async () => {
  if (!sha1) {
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
  // 2. 加载图片（1600 长边缩略图）。存到 lastImg 供离屏小样渲染器复用。
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
  // 3. 加载滤镜清单与每支 LUT。manifest 整体失败才置空；单支 LUT 失败
  // 只跳过该支（小样位置无图，label 仍在），不影响其他滤镜。
  try {
    const res = await fetch("/filters/manifest.json")
    if (cancelled) return
    filters.value = await res.json()
  } catch {
    if (!cancelled) filters.value = []
    return
  }
  for (const f of filters.value) {
    if (cancelled) return
    try {
      const cubeText = await (await fetch(`/filters/${f.file}`)).text()
      if (cancelled) return
      lutCache.set(f.id, parseCube(cubeText))
    } catch {
      if (cancelled) return
      // 该支 LUT 损坏：从清单剔除，避免 UI 点到空白
      filters.value = filters.value.filter((x) => x.id !== f.id)
    }
  }
  // 4. 小样条：离屏 192×128 小 canvas + 独立第二个 LutRenderer（另一个 gl
  // context），避免反复对主 1600px canvas toDataURL 堆全尺寸 dataURL。
  // 缩到 192×128 由 GL LINEAR 采样完成。失败（如 context 耗尽）只跳过小样，
  // 主预览不受影响。
  if (cancelled || !renderer || !lastImg) return
  const thumbCanvas = document.createElement("canvas")
  thumbCanvas.width = 192
  thumbCanvas.height = 128
  let thumbRenderer: LutRenderer | null = null
  try {
    thumbRenderer = new LutRenderer(thumbCanvas)
    thumbRenderer.setImage(lastImg)
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
})
</script>

<style scoped>
.fp-page {
  display: flex; flex-direction: column;
  height: 100vh; background: #111; color: #eee;
}
.fp-topbar {
  padding: 10px 16px; font-size: 14px;
  border-bottom: 1px solid #222;
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
  display: flex; gap: 8px; padding: 10px 16px;
  overflow-x: auto; border-top: 1px solid #222;
}
.fp-thumb {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  background: transparent; border: 2px solid transparent;
  padding: 4px; cursor: pointer; border-radius: 6px;
}
.fp-thumb.active { border-color: #3b82f6; }
.fp-thumb img {
  width: 96px; height: 64px; object-fit: cover; border-radius: 4px;
  background: #333; display: block;
}
.fp-thumb-label { font-size: 12px; color: #ccc; }
</style>
