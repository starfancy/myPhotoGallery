# 空文件夹借用直接子文件夹封面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 文件夹自身无图但直接子文件夹含图时，子文件夹卡片借用第一个含图子项的封面，并在封面底部渐变条上标注来源子文件夹名。

**Architecture:** 纯前端方案（spec 方案 C），后端零改动。BrowseView 拿到 `/folders` 主响应后，对 `image_count === 0 && descendant_count > 0` 的文件夹 fire-and-forget 并行补查一次同一接口（path 指向该文件夹），取返回中第一个自身含图且有封面的子项回填 `cover_thumb_sha1` 与新增字段 `cover_source_name`；SubfolderStrip 在封面容器底部渲染渐变条白字。

**Tech Stack:** Vue 3 `<script setup>` + TypeScript、UnoCSS（工具类）、vitest 1.4 + @vue/test-utils 2.4（jsdom）、vue-router memory history。

## Global Constraints

- 不改动任何后端文件、数据库、扫描器；只新增/修改 `frontend/` 下文件。
- 只看**直接子文件夹**，不递归；直接子项全都自身无图时保持灰色占位。
- 补查条件：`image_count === 0 && descendant_count > 0`；补查单项失败必须静默吞掉，不阻塞分页加载、不产生未捕获异常。
- 卡片跳转行为不变（进入文件夹自身）；普通卡片（自身有图）DOM 与行为零变化。
- 提交信息沿用仓库的 Conventional Commits 英文风格（如 `feat(frontend): ...`）。
- 测试命令：`npx vitest run <路径>`；全量 `npm test`；类型检查 `npx vue-tsc --noEmit`（在 `frontend/` 目录下执行）。

## File Structure

- 修改 `frontend/src/components/SubfolderStrip.vue`
  - 封面容器加 `relative`，新增 `.lb-folder-source` 渐变条（仅 `cover_source_name` 有值时渲染）；props 项类型加 `cover_source_name?: string | null`；新增 scoped 渐变样式。
- 修改 `frontend/src/views/BrowseView.vue`
  - 新增 `enrichBorrowedCovers()`；在 `loadAll()` 中 `folders.value = f` 之后以 `void` 方式触发，不 await。
- 新增 `frontend/src/tests/subfolder-strip.spec.ts` — 渐变条显隐的组件测试（Task 1）。
- 新增 `frontend/src/tests/folder-cover-enrichment.spec.ts` — 补查触发、回填、无候选、失败处理的视图测试（Task 2）。

---

### Task 1: SubfolderStrip 封面底部来源名渐变条

**Files:**
- Modify: `frontend/src/components/SubfolderStrip.vue`
- Test: `frontend/src/tests/subfolder-strip.spec.ts`（新建）

**Interfaces:**
- Consumes: folder 项上的可选字段 `cover_source_name?: string | null`（Task 2 回填；缺失时行为与现状一致）。
- Produces: `.lb-folder-source` 元素（有来源名时存在），供测试与视觉锚定。

- [ ] **Step 1: 写失败测试**

新建 `frontend/src/tests/subfolder-strip.spec.ts`：

```ts
import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import SubfolderStrip from "../components/SubfolderStrip.vue"

interface FolderCard {
  name: string
  relative_path: string
  image_count: number
  descendant_count: number
  cover_thumb_sha1: string | null
  cover_source_name?: string | null
}

function mountWith(folders: FolderCard[]) {
  return mount(SubfolderStrip, {
    props: { folders, gid: 1, rid: 1 },
    global: { stubs: { RouterLink: true } },
  })
}

describe("SubfolderStrip borrowed-cover label", () => {
  it("renders the source child name as a bottom gradient label", () => {
    const w = mountWith([
      {
        name: "2024旅行",
        relative_path: "trip",
        image_count: 0,
        descendant_count: 128,
        cover_thumb_sha1: "sha-gz",
        cover_source_name: "广州",
      },
    ])
    const label = w.find(".lb-folder-source")
    expect(label.exists()).toBe(true)
    expect(label.text()).toContain("广州")
    expect(label.attributes("title")).toBe("广州")
  })

  it("renders no label for normal folders without cover_source_name", () => {
    const w = mountWith([
      {
        name: "日常",
        relative_path: "daily",
        image_count: 12,
        descendant_count: 12,
        cover_thumb_sha1: "sha-daily",
      },
    ])
    expect(w.find(".lb-folder-source").exists()).toBe(false)
  })

  it("renders no label when cover_source_name is null", () => {
    const w = mountWith([
      {
        name: "真空",
        relative_path: "nope",
        image_count: 0,
        descendant_count: 0,
        cover_thumb_sha1: null,
        cover_source_name: null,
      },
    ])
    expect(w.find(".lb-folder-source").exists()).toBe(false)
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/tests/subfolder-strip.spec.ts`
Expected: FAIL — 三个用例都找不到 `.lb-folder-source`（第一个 exists 为 false）。

- [ ] **Step 3: 实现渐变条**

修改 `frontend/src/components/SubfolderStrip.vue`。

3a. props 类型加字段（`folders` 数组项类型中增加一行）：

```ts
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
```

3b. 把封面区 `<div class="h-24 w-full overflow-hidden bg-neutral-700">` 改为相对定位容器并加入渐变条，整段替换为：

```html
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
```

3c. 文件末尾新增 scoped 样式（渐变用 CSS 保证，不依赖 UnoCSS 渐变工具类是否启用）：

```html
<style scoped>
/* 借来的封面：图底黑色渐变，托住白色来源名 */
.lb-folder-source {
  background: linear-gradient(to top, rgba(0, 0, 0, 0.75), rgba(0, 0, 0, 0));
}
</style>
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/tests/subfolder-strip.spec.ts`
Expected: PASS（3 个用例）。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/SubfolderStrip.vue frontend/src/tests/subfolder-strip.spec.ts
git commit -m "feat(frontend): label borrowed folder cover with source child name"
```

---

### Task 2: BrowseView 对空文件夹并行补查借用封面

**Files:**
- Modify: `frontend/src/views/BrowseView.vue`（`loadAll` 在 206-226 行附近）
- Test: `frontend/src/tests/folder-cover-enrichment.spec.ts`（新建）

**Interfaces:**
- Consumes: 现有 `apiGet<any[]>(...)`（`frontend/src/api.ts`，非 2xx 抛 `HttpError`）；现有接口 `GET /api/galleries/{gid}/roots/{rid}/folders?path=<rel>` 返回按 name 升序的直接子项，每项含 `name / relative_path / image_count / descendant_count / cover_thumb_sha1`。
- Produces: 回填到 folders 响应式数组项上的 `cover_thumb_sha1: string | null` 与 `cover_source_name: string`（Task 1 渲染）。

- [ ] **Step 1: 写失败测试**

新建 `frontend/src/tests/folder-cover-enrichment.spec.ts`：

```ts
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import BrowseView from "../views/BrowseView.vue"
import SubfolderStrip from "../components/SubfolderStrip.vue"
import { useAuthStore } from "../stores/auth"

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

function response(body: unknown, status = 200) {
  const isNull = body === null || body === undefined
  return new Response(isNull ? null : JSON.stringify(body), {
    status,
    headers: isNull ? {} : { "content-type": "application/json" },
  })
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/galleries/:gid/r/:rid/:path(.*)*", component: BrowseView },
    ],
  })
}

interface FetchOpts {
  /** path(相对路径片段) -> 该空文件夹补查返回的直接子项列表 */
  children: Record<string, unknown[]>
  /** 需要让补查返回 500 的 path 集合 */
  failPaths?: string[]
}

async function mountView(opts: FetchOpts) {
  const folders = [
    { name: "有图文件夹", relative_path: "has", image_count: 5, descendant_count: 5, cover_thumb_sha1: "sha-has" },
    { name: "真空文件夹", relative_path: "empty", image_count: 0, descendant_count: 0, cover_thumb_sha1: null },
    { name: "借封面文件夹", relative_path: "borrow", image_count: 0, descendant_count: 3, cover_thumb_sha1: null },
  ]
  const fetchFn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : (input as Request).url ?? String(input)
    const method = init?.method ?? "GET"
    if (method === "GET" && url.includes("/breadcrumbs")) {
      return response([{ name: "R", relative_path: "" }])
    }
    if (method === "GET" && url.includes("/folders")) {
      const p = new URL(url, "http://test/").searchParams.get("path") ?? ""
      if (p === "") return response(folders)
      if (opts.failPaths?.includes(p)) return response({ error: { code: "internal_error", message: "x" } }, 500)
      return response(opts.children[p] ?? [])
    }
    if (method === "GET" && url.includes("/images")) {
      return response({ items: [], total: 0 })
    }
    return response({ error: { code: "not_found", message: "not mocked" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)

  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({ user: { id: 1, username: "u", role: "viewer", access_scope: "lan_only" } })

  const router = makeRouter()
  await router.push("/galleries/1/r/1")
  const w = mount(BrowseView, {
    global: { plugins: [router], stubs: { ImageLightbox: true } },
  })
  await flushPromises()
  await flushPromises()
  return { w, fetchFn, folders }
}

function folderCalls(fetchFn: ReturnType<typeof vi.fn>) {
  return (fetchFn.mock.calls as unknown as Array<[string]>).flatMap((c) => {
    const url = c[0]
    if (!url.includes("/folders")) return []
    return [new URL(url, "http://test/").searchParams.get("path") ?? ""]
  })
}

describe("BrowseView borrowed folder covers", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  it("fetches only for empty-with-descendants folders and borrows first child with images", async () => {
    const { w, fetchFn } = await mountView({
      children: {
        // 第一个子项自身无图、无封面；第二个才有 -> 应借第二个
        borrow: [
          { name: "中山", relative_path: "borrow/zs", image_count: 0, descendant_count: 0, cover_thumb_sha1: null },
          { name: "广州", relative_path: "borrow/gz", image_count: 2, descendant_count: 2, cover_thumb_sha1: "sha-gz" },
        ],
      },
    })

    const paths = folderCalls(fetchFn)
    // 1 次主列表 + 仅 borrow 1 次补查；has 与 empty 不触发
    expect(paths).toEqual(["", "borrow"])

    const strip = w.findComponent(SubfolderStrip)
    const items = strip.props("folders") as Array<Record<string, unknown>>
    expect(items[0].cover_thumb_sha1).toBe("sha-has")
    expect(items[0].cover_source_name).toBeUndefined()
    expect(items[1].cover_thumb_sha1).toBeNull()
    expect(items[2].cover_thumb_sha1).toBe("sha-gz")
    expect(items[2].cover_source_name).toBe("广州")
  })

  it("issues one enrichment request per candidate folder in a single load", async () => {
    // 两候选（a、b 自身无图但后代有图）+ 一个自身有图的 c
    const folders = [
      { name: "A", relative_path: "a", image_count: 0, descendant_count: 1, cover_thumb_sha1: null },
      { name: "B", relative_path: "b", image_count: 0, descendant_count: 2, cover_thumb_sha1: null },
      { name: "C", relative_path: "c", image_count: 3, descendant_count: 3, cover_thumb_sha1: "sha-c" },
    ]
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url ?? String(input)
      if (url.includes("/breadcrumbs")) return response([{ name: "R", relative_path: "" }])
      if (url.includes("/folders")) {
        const p = new URL(url, "http://test/").searchParams.get("path") ?? ""
        if (p === "") return response(folders)
        return response([
          { name: `${p}-child`, relative_path: `${p}/x`, image_count: 1, descendant_count: 1, cover_thumb_sha1: `sha-${p}` },
        ])
      }
      if (url.includes("/images")) return response({ items: [], total: 0 })
      return response(null, 404)
    })
    vi.stubGlobal("fetch", fetchFn)

    setActivePinia(createPinia())
    useAuthStore().$patch({ user: { id: 1, username: "u", role: "viewer", access_scope: "lan_only" } })

    const router = makeRouter()
    await router.push("/galleries/1/r/1")
    const w = mount(BrowseView, {
      global: { plugins: [router], stubs: { ImageLightbox: true } },
    })
    await flushPromises()
    await flushPromises()

    // 1 次主列表 + a、b 各 1 次补查；自身有图的 c 不补查
    expect(folderCalls(fetchFn).sort()).toEqual(["", "a", "b"])
    const items = w.findComponent(SubfolderStrip).props("folders") as Array<Record<string, unknown>>
    expect(items[0].cover_thumb_sha1).toBe("sha-a")
    expect(items[0].cover_source_name).toBe("a-child")
    expect(items[1].cover_thumb_sha1).toBe("sha-b")
    expect(items[1].cover_source_name).toBe("b-child")
    expect(items[2].cover_thumb_sha1).toBe("sha-c")
    expect(items[2].cover_source_name).toBeUndefined()
  })

  it("keeps grey placeholder when no direct child has images of its own", async () => {
    const { w } = await mountView({
      children: {
        borrow: [
          { name: "只有孙级有图", relative_path: "borrow/deep", image_count: 0, descendant_count: 9, cover_thumb_sha1: null },
        ],
      },
    })
    const items = w.findComponent(SubfolderStrip).props("folders") as Array<Record<string, unknown>>
    expect(items[2].cover_thumb_sha1).toBeNull()
    expect(items[2].cover_source_name).toBeUndefined()
  })

  it("survives a failed enrichment request without breaking the list", async () => {
    const { w } = await mountView({ children: {}, failPaths: ["borrow"] })
    const items = w.findComponent(SubfolderStrip).props("folders") as Array<Record<string, unknown>>
    // 三个文件夹名照常渲染
    expect(w.text()).toContain("借封面文件夹")
    expect(items[2].cover_thumb_sha1).toBeNull()
    expect(items[2].cover_source_name).toBeUndefined()
  })
})
```

第二个用例需要两个候选、与 `mountView` 的固定数据不同，因此内联自建 fetch 与挂载（含独立的 pinia/auth 初始化）。最终文件共 4 个 `it`：①仅候选触发并取首个含图子项；②每个候选各发一次补查；③无含图直接子项保持灰块；④补查 500 不炸列表。

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/tests/folder-cover-enrichment.spec.ts`
Expected: FAIL — 用例①断言 `paths` 实际为 `[""]`（没有补查发生），回填字段也不存在。

- [ ] **Step 3: 实现补查逻辑**

修改 `frontend/src/views/BrowseView.vue` 的 `loadAll`，把：

```ts
    crumbs.value = c
    folders.value = f
    page.value = 1
    await renderPage(key, 1)
```

替换为：

```ts
    crumbs.value = c
    folders.value = f
    // 空文件夹（自身无图、后代有图）借用直接子文件夹封面：fire-and-forget，
    // 不阻塞分页加载；单项失败在函数内静默处理。
    void enrichBorrowedCovers()
    page.value = 1
    await renderPage(key, 1)
```

然后在 `loadAll` 函数**之后**新增函数（放在 `loadAll` 与 `renderPage` 之间）：

```ts
/**
 * 自身无图但后代有图的文件夹，补查其直接子文件夹并借用第一个自身含图
 * 子项的封面，同时在封面标注来源子文件夹名。仅查直接子级，不递归。
 * folders.value 中的项是响应式代理，直接改属性即可触发卡片更新。
 */
async function enrichBorrowedCovers() {
  const candidates = folders.value.filter(
    (f) => f.image_count === 0 && f.descendant_count > 0,
  )
  if (candidates.length === 0) return
  await Promise.all(
    candidates.map(async (folder) => {
      try {
        const children = await apiGet<any[]>(
          `/api/galleries/${gid.value}/roots/${rid.value}/folders?path=${encodeURIComponent(folder.relative_path)}`,
        )
        const donor = children.find(
          (ch) => ch.image_count > 0 && ch.cover_thumb_sha1 != null,
        )
        if (donor) {
          folder.cover_thumb_sha1 = donor.cover_thumb_sha1
          folder.cover_source_name = donor.name
        }
      } catch {
        // 补查失败：该文件夹保持灰色占位，不影响其余内容
      }
    }),
  )
}
```

- [ ] **Step 4: 运行新测试确认通过**

Run: `npx vitest run src/tests/folder-cover-enrichment.spec.ts`
Expected: PASS（4 个用例）。

- [ ] **Step 5: 全量测试与类型检查**

Run: `npm test`
Expected: 全部用例 PASS（含既有 browse-view-delete、subfolder-strip 等）。

Run: `npx vue-tsc --noEmit`
Expected: 无错误退出（folders 是 `ref<any[]>`，新增字段不产生类型错误）。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/BrowseView.vue frontend/src/tests/folder-cover-enrichment.spec.ts
git commit -m "feat(frontend): borrow cover from first child with images for empty folders"
```

---

## 人工验收（实现完成后）

1. `npm run dev`，进入一个含"自身无图、子文件夹有图"的目录层。
2. 对应卡片先短暂灰色，随后出现子文件夹封面，图底渐变条显示该子文件夹名；长名被单行截断，鼠标悬停 `title` 显示全名。
3. 点卡片仍进入空文件夹本身（不跳转）。
4. 普通文件夹卡片外观无变化；所有直接子项都自身无图（图在孙级）的文件夹仍为灰块。
