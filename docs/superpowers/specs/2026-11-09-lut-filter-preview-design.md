# LUT 风格滤镜预览 — 设计文档

日期：2026-11-09
状态：待实现

## 目标

在单图浏览灯箱（PhotoSwipe）顶栏新增"风格滤镜"按钮，点击后在独立标签页打开滤镜预览页。用户可在预览页：

- 从一组免费可分发的胶片模拟 `.cube` LUT 中选择滤镜
- 实时调整滤镜强度（0–100% 混合原图）
- 长按"看原图"按钮对比效果
- 通过底部缩略条（当前图套用各滤镜的小样）快速切换
- 下载处理后的 1600 长边 JPEG

**只处理当前这一张 1600 长边缩略图，不做任何预处理或批量渲染**。

## 非目标（v1 明确不做）

- 不做后端改动。缩略图 URL 现有 `/api/thumb/{sha1}?size=1600` 已够用。
- 不把滤镜持久化到数据库 / 不影响相册默认显示。
- 不做胶片颗粒 shader、不做分区色调曲线精调、不做 HSL 调整。
- 不支持上传用户自己的 LUT 文件。
- 不做 WebGL 不可用的 CPU fallback（v1 只显示降级提示）。
- 灯箱内不做内联滤镜预览——一律独立标签页。

## 技术选型

**手写一个极简 WebGL 2 LUT 渲染器（无新增 npm 依赖）**。

已调研的候选：

| 候选 | 结论 |
|---|---|
| `webgl-lut-filter` (npm, 6.1KB) | 每次调用新建 gl context、shader 硬编码无 mix uniform、输入是 512×512 PNG LUT 图而非 `.cube`。**不采用**，但它的 shader 是标准实现 |
| PixiJS Filters | 无内置 3D-LUT filter，且引入 ~120KB gzip 渲染引擎只为画一个 quad。**不采用** |
| glfx.js | 2015 年废弃，shader 硬编码，无 LUT 支持。**不采用** |
| CSS `filter()` 链 | 无法加载 `.cube`，只能手写滤镜近似。**不采用** |

**为什么手写而不是用现成库**：LUT 应用本质是"一张图 + 一个 3D 查找表 + 一次 shader 采样"，shadertoy 级别约 30 行代码，生态里没有恰好匹配的轻量组件。手写一个 ~150 行的 `lib/lutRenderer.ts` 反而最干净——复用 gl context、缓存 program、支持 mix uniform。

## 架构

### 入口

`frontend/src/components/ImageLightbox.vue` 顶栏新增按钮（`order: 13`，图标调色板），点击：

```ts
const it = props.items[pswp.currIndex]
window.open(
  `/filter-preview?sha1=${it.sha1}&w=${it.width}&h=${it.height}&name=${encodeURIComponent(it.filename)}`,
  "_blank",
  "noopener",
)
```

URL 用 query 参数传递。sha1 本身就是 `/api/thumb` 的 capability 路径的一部分，光箱的 `ImageRow` 已持有这些字段。authGuard 复用现有登录校验。

### 新路由

`frontend/src/router.ts` 新增：

```ts
{ path: "/filter-preview", component: () => import("./views/FilterPreviewView.vue") },
```

### LUT 资产

目录：`frontend/public/filters/`

```
filters/
  manifest.json          # 滤镜清单
  kodak-2383.cube
  impulz.cube
  cinestill-800t.cube
  fuji-velvia.cube
  tri-x.cube
  hp5.cube
  LICENSE.md             # 每支 LUT 的来源与许可证
```

`manifest.json` 结构：

```json
[
  { "id": "kodak-2383", "label": "Kodak 2383 电影感", "file": "kodak-2383.cube" },
  { "id": "impulz",    "label": "Impulz 胶片",      "file": "impulz.cube" },
  ...
]
```

首批 6 支（免费可分发）：Kodak 2383 / VisionColor Impulz / CineStill 800T / Fuji Velvia / Kodak Tri-X (黑白) / Ilford HP5 (黑白)。

### 预览页布局 (`FilterPreviewView.vue`)

- **主区域**：WebGL `<canvas>` 铺满，显示当前图 + 当前 LUT + 当前强度。
- **底部横向缩略条**：每张滤镜一张 ~200px 宽的小样（当前图套用该滤镜渲染到离屏 canvas）。首次打开一次性渲染全部 6 张小样（<50ms）。点击小样切换主预览的滤镜。
- **控件条**（主区域下方）：
  - 强度滑块（0–100%）
  - "按住看原图"按钮（按住时 mix 强制为 0，松开恢复）
  - "下载 JPEG"按钮

### LUT 渲染器模块 (`frontend/src/lib/lutRenderer.ts`)

导出 `LutRenderer` 类：

```ts
export class LutRenderer {
  constructor(canvas: HTMLCanvasElement)
  /** 加载并解析 .cube 文本，缓存为 3D texture。同一 id 只上传一次。 */
  async loadLut(id: string, cubeText: string): Promise<void>
  /** 上传图片为 2D texture（1600 长边缩略图）。 */
  setImage(img: HTMLImageElement): void
  /** 渲染一帧：mix=0 输出原图，mix=1 输出全滤镜。 */
  render(mix: number): void
  /** 下载/导出用：把当前帧画到离屏 canvas 并 toBlob。 */
  exportJpeg(quality?: number): Promise<Blob>
  dispose(): void
}
```

**实现要点**：

- 用 WebGL 2 `TEXTURE_3D` 直接上传 3D LUT，shader 里一次 `texture(u_LUT, rgb)` 采样（WebGL 1 的 8×8 grid PNG 方案已被弃用，原因见"调研"节）。
- shader 核心一行：`vec3 graded = texture(u_LUT, textureColor.rgb).rgb; gl_FragColor = vec4(mix(textureColor.rgb, graded, u_mix), 1.0);`
- **同一个 gl context 生命周期内复用 program 与 vertex buffer**。切换 LUT 时只新建/替换一个 3D texture，切换 mix 时只改 uniform——零重编译。
- 缩略条小样渲染：复用同一类实例（创建离屏 canvas 后 swap），或者更简单——用主 renderer 在小尺寸 viewport 各渲一次后 readPixels / toDataURL。
- 不设 `preserveDrawingBuffer: true`；下载时先 `render()` 立即同步 `canvas.toBlob()`（在同一事件循环 tick 内）。

### `.cube` 解析

`.cube` 是纯文本，典型格式：

```
LUT_3D_SIZE 33
DOMAIN_MIN 0 0 0
DOMAIN_MAX 1 1 1
# 之后每行一个 RGB 浮点三元组（0.0–1.0），按 B 最快变化的顺序排列
0.123 0.456 0.789
...
```

解析器约 40 行：跳注释/头行 → 读 `LUT_3D_SIZE` → 收集 N³ 个三元组 → 打包成 `Uint8Array` 上传为 3D texture。

## 数据流

```
用户在灯箱点开"风格滤镜"
  → window.open(/filter-preview?sha1=...&w=...&h=...&name=...)
  → FilterPreviewView 挂载
  → fetch(manifest.json) → 得到滤镜清单
  → loadImage(/api/thumb/{sha1}?size=1600) → setImage
  → 对每支 LUT：fetch(.cube) → loadLut(id, text) → 渲一张 200px 小样
  → 用户点小样 / 拖滑块 / 按住原图 / 下载
```

所有 LUT 是小文本（33³ × 3 × 4B ≈ 66KB/支），一次性全部加载也只 ~400KB。

## 错误处理

- **WebGL 2 不可用**：主区域显示降级文案"当前浏览器不支持 WebGL 2，无法预览滤镜"。不阻塞页面其他控件。
- **图片加载失败**（sha1 无效 / 已删除）：主区域显示"图片加载失败"，控件禁用。
- **某支 LUT 加载失败**：该支小样位置显示灰色占位 + label，不影响其他滤镜。
- **下载失败**（canvas 污染等）：toBlob reject → 页面 toast 一行错误，不 crash。

## 测试策略

参考现有 `frontend/src/tests/lightbox-*.spec.ts` 的模式：

- **`lut-parser.spec.ts`**：喂一段典型 `.cube` 文本，断言解析出的 size、RGB 数组顺序、越界行跳过。jsdom 环境跑（不用真 WebGL）。
- **`filter-preview-url.spec.ts`**：模拟灯箱按钮点击 → 断言 `window.open` 收到的 URL query 编码正确（sha1、w/h、name）。
- **`filter-preview-view.spec.ts`**：mock `LutRenderer` 类（不真启动 WebGL），断言 manifest 加载、小样渲染调用次数、切换滤镜时 mix 传参正确。

LUT 渲染器本身的视觉正确性不进自动化测试（jsdom 无真 WebGL），靠手工验收。

## 手工验收清单

1. 灯箱顶栏出现调色板按钮；点击后新标签页打开 `/filter-preview?sha1=...`。
2. 主画布显示当前 1600 缩略图；首屏**不应用任何滤镜**（mix=0），由用户主动点小样选择。
3. 底部 6 张小样全部渲染，各自视觉差异明显（黑白、电影感、暖调等）。
4. 拖滑块从 0 → 100% 平滑过渡，无掉帧。
5. 按住"看原图"按钮立刻回到原始图，松开恢复。
6. 点"下载 JPEG"得到一张 1600 长边、当前滤镜效果的 JPEG 文件，文件名 `<原文件名>-<滤镜id>.jpg`。
7. 切到没有 WebGL 2 的环境（可通过浏览器 flag 模拟）显示降级提示。

## 工作量估计

- `lutRenderer.ts` + `.cube` 解析：~1 天
- `FilterPreviewView.vue` + 布局 + 控件：~1 天
- 灯箱按钮 + 路由接入：~2 小时
- 首批 6 支 LUT 收集 + LICENSE 整理：~2 小时（非开发）
- 测试 + 手工验收：~半天

合计约 3 天。
