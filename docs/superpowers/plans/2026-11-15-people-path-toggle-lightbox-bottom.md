# 人物页位置开关拆分与灯箱路径底部居中 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 人物页把文件名/位置单开关拆成两个独立持久化开关；灯箱路径标注从顶部栏移到底部居中，文件名维持原位，图库灯箱零变化。

**Architecture:** 纯前端改动。人物页复用 PhotoCell 现成的文件名层与 badge 角标机制，只改 PersonClusterView 的状态与按钮；灯箱只改 `location-label` 一个注册元素的挂载点（`appendTo: "wrapper"`）与对应 CSS，resolver 门控不变，共享组件的其余行为不动。

**Tech Stack:** Vue 3 `<script setup>` + UnoCSS + PhotoSwipe v5（vitest/@vue/test-utils，pnpm）

## Global Constraints

- localStorage 键固定为 `people.grid.showFilenames` 与 `people.grid.showLocation`，值 `"1"`/`"0"`，默认关；旧键 `people.grid.showInfo` 不读取、不迁移、不清理。
- 两个开关按钮的 aria-label 逐字为「缩略图上显示文件名」与「缩略图上显示所在位置」。
- 灯箱 `filename-label` 的注册与 CSS 一行不改；只改 `location-label`。
- `location-label` 仍在 `if (props.locationResolver)` 分支内，图库普通浏览灯箱不得出现该元素。
- PhotoCell、JustifiedGrid 零改动；后端零改动。
- 只本地 commit，不 push（用户另有手动推送约定）。
- 前端过滤测试：`cd frontend && pnpm test person-cluster` / `pnpm test lightbox-location`；全量：`cd frontend && pnpm test && pnpm build`
- 后端全量回归（仓库根目录）：`.venv/Scripts/python -m pytest backend/tests/`

---

### Task 1: 人物页文件名/位置双独立开关（TDD）

**Files:**

- Modify: `frontend/src/tests/person-cluster-view.spec.ts`（替换信息开关用例）
- Modify: `frontend/src/views/PersonClusterView.vue`（状态、按钮、网格接线）

**Interfaces:**

- Consumes: JustifiedGrid 的 `showFilename?: boolean` 与 `badgeFor?: (item: ImageRow) => string | null`（均为现成 props）；PhotoCell 的 `.lb-cell-filename` / `.lb-cell-badge` 渲染类。
- Produces: `showFilenames: Ref<boolean>`（键 `people.grid.showFilenames`）、`showLocation: Ref<boolean>`（键 `people.grid.showLocation`）；旧 `showInfo`/`people.grid.showInfo` 完全移除。

- [ ] **Step 1: 改写测试——把单开关用例替换为两个独立用例**

在 `frontend/src/tests/person-cluster-view.spec.ts` 中，删除整个用例
`it("信息开关：显示文件名与位置角标，文本区分根目录/子目录并持久化", ...)`
（从该 `it(` 到其闭合 `})`），替换为以下两个用例：

```ts
  it("文件名开关：独立控制文件名叠加层并持久化", async () => {
    let { w } = await mountView()
    const toggle = w.get('button[aria-label="缩略图上显示文件名"]')
    await toggle.trigger("click")
    await flushPromises()
    expect(w.findAll(".lb-cell-filename").length).toBe(3)
    // 文件名开关不影响位置角标
    expect(w.findAll(".lb-cell-badge").length).toBe(0)
    expect(localStorage.getItem("people.grid.showFilenames")).toBe("1")
    // 重新挂载：localStorage 中的开启态被恢复
    ;({ w } = await mountView({ preserveStorage: true }))
    expect(w.findAll(".lb-cell-filename").length).toBe(3)
  })

  it("位置开关：独立控制路径角标，文本区分根目录/子目录并持久化", async () => {
    let { w } = await mountView()
    const toggle = w.get('button[aria-label="缩略图上显示所在位置"]')
    await toggle.trigger("click")
    await flushPromises()
    expect(w.findAll(".lb-cell-badge").length).toBe(3)
    // 位置开关不影响文件名层
    expect(w.findAll(".lb-cell-filename").length).toBe(0)
    const badges = w.findAll(".lb-cell-badge").map((b) => b.text()).sort()
    expect(badges).toEqual(
      ["家庭相册", "家庭相册", "家庭相册/2024/旅行"].sort(),
    )
    expect(localStorage.getItem("people.grid.showLocation")).toBe("1")
    // 重新挂载：localStorage 中的开启态被恢复
    ;({ w } = await mountView({ preserveStorage: true }))
    expect(w.findAll(".lb-cell-badge").length).toBe(3)
  })
```

首个用例「按年/月组渲染 justified 网格，默认不显示文件名与位置角标」保持不变，
它已覆盖两个开关默认都关的断言。

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
cd frontend && pnpm test person-cluster
```

Expected: 两个新用例 FAIL（找不到对应 aria-label 的按钮，当前仍是单开关），其余 5 个用例 PASS。

- [ ] **Step 3: 替换 script 中的开关状态**

把 `frontend/src/views/PersonClusterView.vue` 中的：

```ts
/** 信息开关：缩略图文件名 + 所在图库/文件夹位置；偏好独立于图库页持久化。 */
const SHOW_INFO_KEY = "people.grid.showInfo"
const showInfo = ref(localStorage.getItem(SHOW_INFO_KEY) === "1")
watch(showInfo, (v) => localStorage.setItem(SHOW_INFO_KEY, v ? "1" : "0"))
```

替换为：

```ts
/** 文件名开关：偏好独立持久化，默认关。 */
const SHOW_FILENAMES_KEY = "people.grid.showFilenames"
const showFilenames = ref(localStorage.getItem(SHOW_FILENAMES_KEY) === "1")
watch(showFilenames, (v) => localStorage.setItem(SHOW_FILENAMES_KEY, v ? "1" : "0"))

/** 所在位置开关：默认关。 */
const SHOW_LOCATION_KEY = "people.grid.showLocation"
const showLocation = ref(localStorage.getItem(SHOW_LOCATION_KEY) === "1")
watch(showLocation, (v) => localStorage.setItem(SHOW_LOCATION_KEY, v ? "1" : "0"))
```

- [ ] **Step 4: 替换模板中的单按钮为两个图库式按钮**

把模板里现有的整个 showInfo 按钮：

```vue
            <button type="button"
                    class="ml-auto flex min-h-11 min-w-11 items-center justify-center rounded px-1.5 py-1"
                    :class="showInfo
                            ? 'bg-surface-3 text-ink'
                            : 'text-ink-2 hover:text-ink'"
                    title="缩略图上显示文件名与所在位置"
                    aria-label="缩略图上显示文件名与所在位置"
                    :aria-pressed="showInfo"
                    @click="showInfo = !showInfo">
              <!-- 图片卡片 + 底部文字行（与图库文件名开关同款图标） -->
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
                   stroke="currentColor" stroke-width="1.2" stroke-linecap="round"
                   aria-hidden="true">
                <rect x="1.5" y="1.5" width="13" height="13" rx="1.5" />
                <path d="M5 11h6" />
              </svg>
            </button>
```

替换为（注意 `ml-auto` 只保留在第一个按钮上，把两个按钮整体推到右侧）：

```vue
            <button type="button"
                    class="ml-auto flex min-h-11 min-w-11 items-center justify-center rounded px-1.5 py-1"
                    :class="showFilenames
                            ? 'bg-surface-3 text-ink'
                            : 'text-ink-2 hover:text-ink'"
                    title="缩略图上显示文件名"
                    aria-label="缩略图上显示文件名"
                    :aria-pressed="showFilenames"
                    @click="showFilenames = !showFilenames">
              <!-- 图片卡片 + 底部文字行（与图库文件名开关同款图标） -->
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
                   stroke="currentColor" stroke-width="1.2" stroke-linecap="round"
                   aria-hidden="true">
                <rect x="1.5" y="1.5" width="13" height="13" rx="1.5" />
                <path d="M5 11h6" />
              </svg>
            </button>
            <button type="button"
                    class="flex min-h-11 min-w-11 items-center justify-center rounded px-1.5 py-1"
                    :class="showLocation
                            ? 'bg-surface-3 text-ink'
                            : 'text-ink-2 hover:text-ink'"
                    title="缩略图上显示所在位置"
                    aria-label="缩略图上显示所在位置"
                    :aria-pressed="showLocation"
                    @click="showLocation = !showLocation">
              <!-- 文件夹（与灯箱「在所在文件夹中查看」同款 feather folder 图标，缩到 16px） -->
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" stroke-width="2" stroke-linecap="round"
                   stroke-linejoin="round" aria-hidden="true">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              </svg>
            </button>
```

- [ ] **Step 5: 网格接线改用两个独立状态**

把：

```vue
            <JustifiedGrid
              :items="g.images"
              :show-filename="showInfo"
              :badge-for="showInfo ? locationText : undefined"
              @open="openLightbox"
              @menu-action="onGridMenuAction"
            />
```

替换为：

```vue
            <JustifiedGrid
              :items="g.images"
              :show-filename="showFilenames"
              :badge-for="showLocation ? locationText : undefined"
              @open="openLightbox"
              @menu-action="onGridMenuAction"
            />
```

- [ ] **Step 6: 跑人物页测试确认全绿**

Run:

```bash
cd frontend && pnpm test person-cluster
```

Expected: 8 个测试全部 PASS（原 7 个中 1 个被替换为 2 个，总数 7 − 1 + 2 = 8）。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/PersonClusterView.vue frontend/src/tests/person-cluster-view.spec.ts
git commit -m "feat(people): split filename and location into independent toggles"
```

---

### Task 2: 灯箱路径标注移到底部居中（TDD）

**Files:**

- Modify: `frontend/src/tests/lightbox-location.spec.ts`（接口字段 + 注册断言）
- Modify: `frontend/src/components/ImageLightbox.vue`（注册参数 + CSS）

**Interfaces:**

- Consumes: PhotoSwipe `ui.registerElement` 的 `appendTo: "wrapper"` 挂载点（现有缩放比例/拍摄时间胶囊已用此模式）。
- Produces: `location-label` 注册项新增 `appendTo: "wrapper"`；DOM 类名 `.pswp__location-label` 不变但样式变为底部居中胶囊。`filename-label` 无任何变化。

- [ ] **Step 1: 测试接口加字段并写失败断言**

在 `frontend/src/tests/lightbox-location.spec.ts` 中，把 `UIRegistration` 接口：

```ts
interface UIRegistration {
  name: string
  ariaLabel?: string
  isButton?: boolean
  onInit?: (el: HTMLElement) => void
  onClick?: () => void
}
```

改为：

```ts
interface UIRegistration {
  name: string
  ariaLabel?: string
  isButton?: boolean
  appendTo?: string
  onInit?: (el: HTMLElement) => void
  onClick?: () => void
}
```

然后把用例「传入 resolver：显示目录名，按钮 emit viewInFolder」中的：

```ts
    const label = findEl("location-label")
    expect(label).toBeDefined()
    expect(label!.isButton).toBe(false)
```

替换为：

```ts
    const label = findEl("location-label")
    expect(label).toBeDefined()
    expect(label!.isButton).toBe(false)
    // 路径标注挂到全屏 wrapper 做底部居中；文件名标签维持顶部栏注册
    expect(label!.appendTo).toBe("wrapper")
    expect(findEl("filename-label")?.appendTo).toBeUndefined()
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
cd frontend && pnpm test lightbox-location
```

Expected: 「传入 resolver」用例 FAIL（`appendTo` 当前为 undefined），另一个用例仍 PASS。

- [ ] **Step 3: 注册元素加 appendTo**

在 `frontend/src/components/ImageLightbox.vue` 中，把 `location-label` 的注册：

```ts
      pswp!.ui!.registerElement({
        name: "location-label",
        order: 7,
        isButton: false,
        tagName: "span",
        className: "pswp__location-label",
        onInit: (el) => {
          locationEl = el
          updateLocationLabel()
        },
      })
```

替换为：

```ts
      pswp!.ui!.registerElement({
        name: "location-label",
        order: 7,
        isButton: false,
        tagName: "span",
        className: "pswp__location-label",
        appendTo: "wrapper",
        onInit: (el) => {
          locationEl = el
          updateLocationLabel()
        },
      })
```

- [ ] **Step 4: 替换 CSS 为底部居中胶囊**

把 `<style>` 中现有的整条规则：

```css
/* 搜索结果态：文件名右侧的所在目录，弱化一档 */
.pswp__location-label {
  color: rgba(255, 255, 255, 0.75);
  font-size: 13px;
  line-height: 1;
  margin-inline-start: 10px;
  align-self: center;
  max-width: 40vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-shadow: 0 0 3px rgba(0, 0, 0, 0.8);
}
```

替换为：

```css
/* 搜索/人物灯箱专属：路径标注底部居中（仅传入 locationResolver 时才注册）。
   bottom 44px 抬高一档，避开左下拍摄时间与右下缩放比例两个贴底胶囊。 */
.pswp__location-label {
  position: absolute;
  left: 50%;
  bottom: 44px;
  transform: translateX(-50%);
  max-width: min(70vw, calc(100vw - 200px));
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.5);
  color: #fff;
  font-size: 13px;
  line-height: 20px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.8);
  user-select: none;
}
```

- [ ] **Step 5: 跑灯箱测试确认通过**

Run:

```bash
cd frontend && pnpm test lightbox-location
```

Expected: 2 个测试全部 PASS。

- [ ] **Step 6: 全量前端测试 + 类型检查/构建**

Run:

```bash
cd frontend && pnpm test && pnpm build
```

Expected: 全部测试文件 PASS（总数在 Task 1 后的基线上净增 1 个断言用例拆分变化，无 FAIL），`vue-tsc --noEmit` 无报错、`vite build` 成功。

- [ ] **Step 7: 后端全量回归（本次零改动，确认无外溢）**

Run:

```bash
.venv/Scripts/python -m pytest backend/tests/
```

Expected: `729 passed, 6 skipped`（与改动前基线一致）。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/ImageLightbox.vue frontend/src/tests/lightbox-location.spec.ts
git commit -m "feat(lightbox): move location caption to bottom center"
```

## Self-Review 结论

- **Spec coverage**：spec §1 双开关（Task 1 Step 3–5，状态/按钮/接线逐字落地，含 aria-label 与两个 localStorage 键）；四种显隐组合由 PhotoCell 现成机制承载，测试覆盖默认全关、单开文件名、单开位置三种（双开由现有 `lb-cell-badge--up` 既有测试与组件逻辑保证）；spec §2 路径底部居中、文件名不动（Task 2 Step 3–4，测试显式锁定 filename-label 无 appendTo）；resolver 门控与图库零变化由既有用例「不传 resolver 时不注册」保留覆盖；spec 边界表中的旧键废弃、长路径省略均在实现与 Global Constraints 中落实。无遗漏。
- **Placeholder scan**：无 TBD/TODO；所有改动给出完整 old/new 代码与精确锚点；命令与预期输出具体（含测试数量变化 7→8、后端 729/6 基线）。
- **Type consistency**：两个 ref 名（`showFilenames`/`showLocation`）、存储键、aria-label 在测试与实现中逐字一致；`appendTo: "wrapper"` 在注册、断言、CSS 定位三处一致；`.pswp__location-label` 类名保持不变，updateLocationLabel 逻辑不受影响。
