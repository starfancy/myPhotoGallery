# 人物页网格信息开关与灯箱翻页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 人物页照片区改用图库同款 justified 网格，提供文件名/位置信息开关，点击缩略图在全簇图片范围内开灯箱翻页，并支持跳回所在文件夹与 admin 删除。

**Architecture:** 后端先给簇图片接口补 join 字段（图库/根/目录 + 灯箱所需 ImageRow 字段），响应外壳不变；前端 PersonClusterView 消费扩字段后的接口，复用现成 JustifiedGrid（网格）与 ImageLightbox（灯箱）两个共享组件，二者零改动，只做 props/events 接线。

**Tech Stack:** FastAPI + SQLAlchemy（后端，pytest）；Vue 3 `<script setup>` + UnoCSS + vitest/@vue/test-utils（前端，pnpm）

## Global Constraints

- 共享组件 `ImageLightbox.vue`、`JustifiedGrid.vue`、`PhotoCell.vue` 零改动，只在 PersonClusterView 与后端路由接线。
- 后端 `GET /api/tags/clusters/{cid}/images` 的响应外壳 `{groups, total}`、年/月分桶与排序（`taken_at desc nullslast, id desc`）保持不变，只扩每个图片项的字段。
- 信息开关 localStorage 键固定为 `people.grid.showInfo`，值 `"1"`/`"0"`，默认关；不得复用图库页的 `browse.grid.showFilenames`。
- 灯箱打开状态不进 URL、不新增路由。
- 只本地 commit，不 push（用户另有手动推送约定）。
- 后端测试命令（仓库根目录）：`.venv/Scripts/python -m pytest backend/tests/test_routes_tags.py -v`
- 前端测试命令：`cd frontend && pnpm test`（全量）；过滤单文件：`cd frontend && pnpm test person-cluster`
- 前端类型检查+构建：`cd frontend && pnpm build`

---

### Task 1: 后端簇图片接口补全灯箱与位置字段（TDD）

**Files:**

- Modify: `backend/src/myphoto/routes_tags.py`（imports 与 `cluster_images`）
- Test: `backend/tests/test_routes_tags.py`（新增 2 个测试）

**Interfaces:**

- Consumes: 现有模型关联 `Image.root_id → GalleryRoot.id`、`GalleryRoot.gallery_id → Gallery.id`、`Image.relative_path`（含文件名的 posix 路径）。
- Produces: `GET /api/tags/clusters/{cid}/images` 的每个图片项在旧 6 字段（id/filename/width/height/sha1/taken_at）之外，新增 `size_bytes: int`、`mtime: int`、`is_raw: bool`、`scene_major: str|null`、`scene_minor: str|null`、`gallery_id: int`、`root_id: int`、`gallery_name: str`、`folder_path: str`（目录部分，根目录图片为 `""`）。Task 2/3 的前端类型以此为准。

- [ ] **Step 1: 写两个失败测试**

在 `backend/tests/test_routes_tags.py` 文件末尾追加：

```python
def test_cluster_images_include_lightbox_and_location_fields(client):
    """图片项包含灯箱所需 ImageRow 字段与图库/位置字段；夹具图片都在 root 根。"""
    c, gid, rid = client
    body = c.get("/api/tags/clusters/P001/images").json()
    # 分组按 (年,月) 倒序，第一个分组是 2024-01 的 a.jpg
    img = body["groups"][0]["images"][0]
    assert img["filename"] == "a.jpg"
    # 与浏览接口 _image_payload 对齐的灯箱字段
    assert img["size_bytes"] == 100
    assert isinstance(img["mtime"], int)
    assert img["is_raw"] is False
    assert img["scene_major"] is None
    assert img["scene_minor"] is None
    # 位置字段
    assert img["gallery_id"] == gid
    assert img["root_id"] == rid
    assert img["gallery_name"] == "G"
    assert img["folder_path"] == ""


def test_cluster_images_folder_path_uses_directory_part(client):
    """子目录图片的 folder_path 是 relative_path 的目录部分；根目录图片为空串。"""
    c, _gid, _rid = client
    app = c.app

    async def _add_subfolder_face():
        from sqlalchemy import select
        from myphoto.models import FaceEmbedding, Folder, GalleryRoot, Image

        async with app.state.sessionmaker() as s:
            root = (await s.execute(select(GalleryRoot))).scalar_one()
            sub = Folder(
                root_id=root.id, relative_path="sub", name="sub",
                image_count=1, descendant_count=1,
            )
            s.add(sub)
            await s.flush()
            img = Image(
                root_id=root.id, folder_id=sub.id,
                relative_path="sub/x.jpg", filename="x.jpg", ext="jpg",
                size_bytes=100, sha1="sha_x", mtime=int(time.time()),
                taken_at=1704067200, indexed_at=int(time.time()),
            )
            s.add(img)
            await s.flush()
            s.add(FaceEmbedding(
                image_id=img.id, face_index=0, bbox="[0,0,10,10]",
                embedding=b"\x00" * 20, confidence=0.9,
                cluster_id="P001", model_version="v1", created_at=int(time.time()),
            ))
            await s.commit()

    c.portal.call(_add_subfolder_face)
    body = c.get("/api/tags/clusters/P001/images").json()
    by_name = {im["filename"]: im for g in body["groups"] for im in g["images"]}
    assert by_name["x.jpg"]["folder_path"] == "sub"
    assert by_name["a.jpg"]["folder_path"] == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
.venv/Scripts/python -m pytest backend/tests/test_routes_tags.py -v
```

Expected: 两个新测试 FAIL（`KeyError: 'size_bytes'` / `'folder_path'`），既有 5 个测试仍 PASS。

- [ ] **Step 3: 加 Gallery import**

`backend/src/myphoto/routes_tags.py` 顶部模型导入改为：

```python
from myphoto.models import (
    FaceCluster,
    FaceEmbedding,
    Gallery,
    GalleryRoot,
    Image,
    User,
)
```

- [ ] **Step 4: 查询 join 图库/根并补全输出字段**

把 `cluster_images` 中的单表查询：

```python
        rows = (await s.execute(
            select(Image)
            .where(Image.id.in_(image_ids))
            .order_by(Image.taken_at.desc().nullslast(), Image.id.desc())
            .limit(limit)
        )).scalars().all()
```

替换为：

```python
        rows = (await s.execute(
            select(Image, GalleryRoot, Gallery)
            .join(GalleryRoot, GalleryRoot.id == Image.root_id)
            .join(Gallery, Gallery.id == GalleryRoot.gallery_id)
            .where(Image.id.in_(image_ids))
            .order_by(Image.taken_at.desc().nullslast(), Image.id.desc())
            .limit(limit)
        )).all()
```

紧接着把分桶循环：

```python
        groups: dict[tuple[int, int], list[dict]] = {}
        for img in rows:
            if img.taken_at:
                lt = time.localtime(img.taken_at)
                key = (lt.tm_year, lt.tm_mon)
            else:
                key = (0, 0)
            item = {
                "id": img.id,
                "filename": img.filename,
                "width": img.width,
                "height": img.height,
                "sha1": img.sha1,
                "taken_at": img.taken_at,
            }
            groups.setdefault(key, []).append(item)
```

替换为：

```python
        groups: dict[tuple[int, int], list[dict]] = {}
        for img, root, gallery in rows:
            if img.taken_at:
                lt = time.localtime(img.taken_at)
                key = (lt.tm_year, lt.tm_mon)
            else:
                key = (0, 0)
            item = {
                "id": img.id,
                "filename": img.filename,
                "width": img.width,
                "height": img.height,
                "sha1": img.sha1,
                "taken_at": img.taken_at,
                "size_bytes": img.size_bytes,
                "mtime": img.mtime,
                "is_raw": bool(img.is_raw),
                "scene_major": img.scene_major,
                "scene_minor": img.scene_minor,
                "gallery_id": gallery.id,
                "root_id": root.id,
                "gallery_name": gallery.name,
                # "2024/a.jpg" → "2024"；根目录 "a.jpg" → ""
                "folder_path": img.relative_path.rpartition("/")[0],
            }
            groups.setdefault(key, []).append(item)
```

- [ ] **Step 5: 跑后端测试确认全绿**

Run:

```bash
.venv/Scripts/python -m pytest backend/tests/test_routes_tags.py -v
```

Expected: 7 个测试全部 PASS（原 5 + 新 2）。

- [ ] **Step 6: Commit**

```bash
git add backend/src/myphoto/routes_tags.py backend/tests/test_routes_tags.py
git commit -m "feat(tags): enrich cluster images with location and lightbox fields"
```

---

### Task 2: 前端 justified 网格 + 信息开关（TDD）

**Files:**

- Create: `frontend/src/tests/person-cluster-view.spec.ts`
- Modify: `frontend/src/views/PersonClusterView.vue`（全量重写，本任务结束态不含灯箱）

**Interfaces:**

- Consumes: Task 1 扩字段后的 `/api/tags/clusters/{cid}/images`；`JustifiedGrid` 的 props `items: ImageRow[]`、`showFilename?: boolean`、`badgeFor?: (item: ImageRow) => string | null` 与事件 `open(id)`、`menuAction(id, "delete")`；`ImageRow` 类型（`frontend/src/stores/browse.ts`）。
- Produces: `ClusterImage extends ImageRow`（附加 `gallery_id/root_id/gallery_name/folder_path`）、`locationText(it: ImageRow): string`（Task 3 灯箱复用）、`showInfo` 开关（localStorage 键 `people.grid.showInfo`）。

- [ ] **Step 1: 写失败测试文件**

创建 `frontend/src/tests/person-cluster-view.spec.ts`：

```ts
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent } from "vue"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import PersonClusterView from "../views/PersonClusterView.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import { useAuthStore } from "../stores/auth"

beforeAll(() => {
  // jsdom 缺 ResizeObserver（JustifiedGrid 排版依赖）
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

const CLUSTERS = [
  { cluster_id: "P001", display_name: "张三", sample_face_id: null, image_count: 3 },
]

const IMG_11 = {
  id: 11, filename: "a.jpg", width: 400, height: 300, sha1: "s11",
  taken_at: 1709251200, size_bytes: 100, mtime: 1700000000, is_raw: false,
  scene_major: null, scene_minor: null,
  gallery_id: 7, root_id: 9, gallery_name: "家庭相册", folder_path: "2024/旅行",
}
const IMG_12 = {
  ...IMG_11, id: 12, filename: "b.jpg", sha1: "s12", folder_path: "",
}
const IMG_13 = {
  ...IMG_11, id: 13, filename: "c.jpg", sha1: "s13", taken_at: null, folder_path: "",
}

const GROUP_RESPONSE = {
  total: 3,
  groups: [
    { year: 2024, month: 3, images: [IMG_11, IMG_12] },
    { year: 0, month: 0, images: [IMG_13] },
  ],
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

// 视图在 Task 3 才挂载真灯箱；桩提前注册，未匹配时无副作用
const LightboxStub = defineComponent({
  name: "ImageLightbox",
  props: ["items", "startId", "locationResolver"],
  emits: ["close", "change", "deleted", "viewInFolder"],
  template: `<div class="lb-stub" />`,
})

async function mountView(opts: { preserveStorage?: boolean } = {}) {
  const fetchFn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const u = String(input)
    const method = init?.method ?? "GET"
    if (method === "DELETE" && u.includes("/api/images/")) {
      return new Response(null, { status: 204 })
    }
    if (u.includes("/api/tags/clusters/P001/images")) return json(GROUP_RESPONSE)
    if (u.includes("/api/tags/clusters")) return json(CLUSTERS)
    return json({ error: { code: "not_found", message: "x" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({
    user: { id: 1, username: "u", role: "admin", access_scope: "lan_only" },
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/people", component: { template: "<div/>" } },
      { path: "/galleries", component: { template: "<div/>" } },
      { path: "/galleries/:gid/r/:rid/:path(.*)*", component: { template: "<div/>" } },
    ],
  })
  await router.push("/people")
  // 默认每次挂载给干净的 localStorage；持久化用例需要预置值时传 preserveStorage
  if (!opts.preserveStorage) localStorage.clear()
  const w = mount(PersonClusterView, {
    global: { plugins: [router], stubs: { ImageLightbox: LightboxStub } },
  })
  await flushPromises()
  await flushPromises()
  return { w, router, fetchFn }
}

describe("PersonClusterView", () => {
  beforeEach(() => {
    // unstub 会清掉 beforeAll 的 ResizeObserver 桩，必须立刻重建，
    // 否则 JustifiedGrid 挂载时 new ResizeObserver 抛错（同 browse-search 模式）
    vi.unstubAllGlobals()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
    localStorage.clear()
  })

  it("按年/月组渲染 justified 网格，默认不显示文件名与位置角标", async () => {
    const { w } = await mountView()
    expect(w.findAllComponents(JustifiedGrid).length).toBe(2)
    expect(w.text()).toContain("2024年3月")
    expect(w.text()).toContain("未知日期")
    expect(w.findAll("img").some((im) => im.attributes("alt") === "a.jpg")).toBe(true)
    expect(w.findAll(".lb-cell-filename").length).toBe(0)
    expect(w.findAll(".lb-cell-badge").length).toBe(0)
  })

  it("信息开关：显示文件名与位置角标，文本区分根目录/子目录并持久化", async () => {
    let { w } = await mountView()
    const toggle = w.get('button[aria-label="缩略图上显示文件名与所在位置"]')
    await toggle.trigger("click")
    await flushPromises()
    expect(w.findAll(".lb-cell-filename").length).toBe(3)
    const badges = w.findAll(".lb-cell-badge").map((b) => b.text()).sort()
    expect(badges).toEqual(
      ["家庭相册", "家庭相册", "家庭相册/2024/旅行"].sort(),
    )
    expect(localStorage.getItem("people.grid.showInfo")).toBe("1")
    // 再点一次关闭
    await toggle.trigger("click")
    expect(w.findAll(".lb-cell-badge").length).toBe(0)
    // 重新挂载：localStorage 中的开启态被恢复
    localStorage.setItem("people.grid.showInfo", "1")
    ;({ w } = await mountView({ preserveStorage: true }))
    expect(w.findAll(".lb-cell-filename").length).toBe(3)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
cd frontend && pnpm test person-cluster
```

Expected: FAIL——当前视图没有 JustifiedGrid，也没有开关按钮（找不到 aria-label 选择器）。

- [ ] **Step 3: 全量重写 PersonClusterView.vue（本任务结束态：网格 + 开关，无灯箱）**

用以下内容整体替换 `frontend/src/views/PersonClusterView.vue`（侧栏滚动 class 保留）：

```vue
<script setup lang="ts">
/** 人物簇页（tags Phase 3 §4.4）：左侧簇列表（按照片数降序），右侧选中簇
 *  的照片按年/月分组，组内使用与图库一致的 justified 网格。点击簇名可重命名。 */
import { onMounted, ref, watch } from "vue"
import AppHeader from "../components/AppHeader.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import { apiGet, apiPut } from "../api"
import type { ImageRow } from "../stores/browse"

interface Cluster {
  cluster_id: string
  display_name: string | null
  sample_face_id: number | null
  image_count: number
}
interface ClusterImage extends ImageRow {
  gallery_id: number
  root_id: number
  gallery_name: string
  folder_path: string
}
interface Group { year: number; month: number; images: ClusterImage[] }

const clusters = ref<Cluster[]>([])
const groups = ref<Group[]>([])
const selectedId = ref<string>("")
const loading = ref(false)
const renaming = ref(false)
const renameInput = ref("")
const loadError = ref("")

/** 信息开关：缩略图文件名 + 所在图库/文件夹位置；偏好独立于图库页持久化。 */
const SHOW_INFO_KEY = "people.grid.showInfo"
const showInfo = ref(localStorage.getItem(SHOW_INFO_KEY) === "1")
watch(showInfo, (v) => localStorage.setItem(SHOW_INFO_KEY, v ? "1" : "0"))

async function loadClusters() {
  loadError.value = ""
  try {
    clusters.value = await apiGet<Cluster[]>("/api/tags/clusters")
    if (!selectedId.value && clusters.value.length) {
      selectCluster(clusters.value[0].cluster_id)
    }
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : "加载失败"
  }
}

function clusterLabel(c: Cluster) {
  return c.display_name || c.cluster_id
}

async function selectCluster(cid: string) {
  selectedId.value = cid
  loading.value = true
  try {
    const r = await apiGet<{ groups: Group[]; total: number }>(
      `/api/tags/clusters/${cid}/images`,
    )
    groups.value = r.groups
  } finally {
    loading.value = false
  }
}

function startRename() {
  const c = clusters.value.find((x) => x.cluster_id === selectedId.value)
  renameInput.value = c?.display_name ?? ""
  renaming.value = true
}

async function saveRename() {
  if (!selectedId.value) return
  await apiPut(`/api/tags/clusters/${selectedId.value}`, {
    display_name: renameInput.value,
  })
  renaming.value = false
  await loadClusters()
}

function groupTitle(g: Group) {
  if (g.year === 0) return "未知日期"
  return `${g.year}年${g.month}月`
}

/** 位置文本：网格角标与（Task 3 的）灯箱标注共用；根目录图片只显示图库名。
 *  共享组件的函数类型以 ImageRow 为参数，内部收窄访问扩展字段。 */
function locationText(it: ImageRow): string {
  const c = it as ClusterImage
  return c.folder_path ? `${c.gallery_name}/${c.folder_path}` : c.gallery_name
}

onMounted(loadClusters)
</script>

<template>
  <div>
    <AppHeader>
      <template #title><span class="text-ink-2">人物</span></template>
    </AppHeader>
    <main id="main-content" class="p-3">
      <div v-if="loadError" class="mt-8 text-center text-danger-text" role="alert">
        加载人物簇失败：{{ loadError }}
      </div>
      <div v-else-if="clusters.length === 0" class="mt-8 text-center text-ink-2" role="status">
        暂无人物簇（打标完成后自动聚类）
      </div>
      <div v-else class="flex gap-4">
        <!-- 左：簇列表 -->
        <aside
          class="w-56 shrink-0 space-y-1 overflow-y-auto
                 sticky top-[81px] md:top-[65px]
                 max-h-[calc(100vh-93px)] md:max-h-[calc(100vh-77px)]"
        >
          <button
            v-for="c in clusters"
            :key="c.cluster_id"
            type="button"
            class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm"
            :class="c.cluster_id === selectedId
                     ? 'bg-primary/10 text-ink'
                     : 'text-ink-2 hover:bg-surface-2 hover:text-ink'"
            :aria-pressed="c.cluster_id === selectedId"
            @click="selectCluster(c.cluster_id)"
          >
            <img
              :src="`/api/tags/clusters/${c.cluster_id}/face.jpg`"
              :alt="clusterLabel(c)"
              class="h-10 w-10 shrink-0 rounded-full object-cover"
              loading="lazy"
            />
            <span class="min-w-0 flex-1 truncate">{{ clusterLabel(c) }}</span>
            <span class="ml-2 shrink-0 text-xs text-ink-muted">{{ c.image_count }}</span>
          </button>
        </aside>

        <!-- 右：照片按年/月分组，组内与图库同款 justified 网格 -->
        <section class="min-w-0 flex-1">
          <div v-if="selectedId" class="mb-2 flex items-center gap-2">
            <h2 class="text-sm font-medium text-ink">
              {{ clusters.find((c) => c.cluster_id === selectedId)?.display_name || selectedId }}
            </h2>
            <button
              v-if="!renaming"
              type="button"
              class="min-h-11 rounded px-2 py-1 text-xs text-ink-2 hover:text-ink"
              @click="startRename"
            >
              重命名
            </button>
            <form v-else class="flex items-center gap-1.5" @submit.prevent="saveRename">
              <input
                v-model="renameInput"
                class="min-h-11 w-40 rounded bg-surface-2 px-2 text-sm text-ink"
                placeholder="名字（留空=未命名）"
                aria-label="簇名"
              />
              <button type="submit"
                      class="min-h-11 rounded bg-primary px-2 py-1 text-sm text-white">
                保存
              </button>
              <button type="button"
                      class="min-h-11 rounded px-2 py-1 text-sm text-ink-2"
                      @click="renaming = false">
                取消
              </button>
            </form>
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
          </div>

          <div v-if="loading" class="text-sm text-ink-2" role="status">加载中...</div>
          <div v-else-if="groups.length === 0" class="text-sm text-ink-2">该簇暂无照片</div>
          <div v-for="g in groups" :key="`${g.year}-${g.month}`" class="mb-4">
            <h3 class="mb-1.5 text-xs font-medium text-ink-2">{{ groupTitle(g) }}</h3>
            <JustifiedGrid
              :items="g.images"
              :show-filename="showInfo"
              :badge-for="showInfo ? locationText : undefined"
            />
          </div>
        </section>
      </div>
    </main>
  </div>
</template>
```

- [ ] **Step 4: 跑新测试确认通过**

Run:

```bash
cd frontend && pnpm test person-cluster
```

Expected: 2 个测试 PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/PersonClusterView.vue frontend/src/tests/person-cluster-view.spec.ts
git commit -m "feat(people): justified grid and info toggle on cluster photos"
```

---

### Task 3: 灯箱翻页、跳回所在文件夹、删除接线（TDD）

**Files:**

- Modify: `frontend/src/views/PersonClusterView.vue`（5 处定向修改，不全量重写）
- Test: `frontend/src/tests/person-cluster-view.spec.ts`（追加 4 个测试）

**Interfaces:**

- Consumes: Task 2 的 `ClusterImage`、`locationText`；`ImageLightbox` props `items: ImageRow[]`、`startId: number`、`locationResolver?: (item: ImageRow) => string | null`，事件 `close`、`deleted(id)`、`viewInFolder(item: ImageRow)`；`JustifiedGrid` 事件 `open(id)`、`menuAction(id, "delete")`；`apiDelete`（`frontend/src/api.ts`，204 正常返回）；`encodePathSegments(rel)`（`frontend/src/utils/path.ts`，空串原样返回）。
- Produces: `flatImages: ComputedRef<ClusterImage[]>`（全簇按分组顺序拍平）、`lightboxId: Ref<number|null>`、`openLightbox(id)`、`onViewInFolder(row)`、`onGridMenuAction(id, action)`、`onImageDeleted(id)`。

- [ ] **Step 1: 追加 4 个失败测试**

在 `frontend/src/tests/person-cluster-view.spec.ts` 的 `describe` 块内、最后一个 `it(...)` 之后追加：

```ts
  /** 打开第一张缩略图对应的灯箱（PhotoCell 内无 aria-label 的主按钮）。 */
  async function openFirstCellLightbox(w: Awaited<ReturnType<typeof mountView>>["w"]) {
    const cellBtn = w.findAll(".lb-grid-cell button")
      .find((b) => !b.attributes("aria-label"))!
    await cellBtn.trigger("click")
    await flushPromises()
    return w.findComponent(LightboxStub)
  }

  it("点缩略图开灯箱：items 为全簇拍平列表、startId 为所点图片", async () => {
    const { w } = await mountView()
    const lb = await openFirstCellLightbox(w)
    expect(lb.exists()).toBe(true)
    const ids = (lb.props("items") as Array<{ id: number }>).map((it) => it.id)
    expect(ids).toEqual([11, 12, 13])
    expect(lb.props("startId")).toBe(11)
  })

  it("locationResolver：子目录返回图库/路径，根目录只返回图库名", async () => {
    const { w } = await mountView()
    const lb = await openFirstCellLightbox(w)
    const resolver = lb.props("locationResolver") as (it: typeof IMG_11) => string
    expect(resolver(IMG_11)).toBe("家庭相册/2024/旅行")
    expect(resolver(IMG_12)).toBe("家庭相册")
  })

  it("viewInFolder 跳到对应图库/根/文件夹，根目录路径无尾斜杠", async () => {
    const { w, router } = await mountView()
    const lb = await openFirstCellLightbox(w)
    lb.vm.$emit("viewInFolder", IMG_11)
    await flushPromises()
    expect(router.currentRoute.value.path).toBe(
      "/galleries/7/r/9/2024/%E6%97%85%E8%A1%8C",
    )
    lb.vm.$emit("viewInFolder", IMG_12)
    await flushPromises()
    expect(router.currentRoute.value.path).toBe("/galleries/7/r/9")
  })

  it("网格菜单删除：确认后调 DELETE、本地摘除图片并重拉簇列表", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const { w, fetchFn } = await mountView()
    const menuBtn = w.findAll(".lb-cell-menu-btn")[0]
    await menuBtn.trigger("click")
    await flushPromises()
    await w.get(".lb-cell-menu-item").trigger("click")
    await flushPromises()
    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    expect(calls.some(
      ([u, init]) => init?.method === "DELETE" && u.includes("/api/images/11"),
    )).toBe(true)
    expect(w.findAll("img").some((im) => im.attributes("alt") === "a.jpg")).toBe(false)
    // 初始 1 次簇列表 + 删除收尾再拉 1 次（images 路径不以 bare clusters 结尾）
    const clusterCalls = calls.filter(([u]) => u.endsWith("/api/tags/clusters"))
    expect(clusterCalls.length).toBeGreaterThanOrEqual(2)
  })

  it("灯箱 deleted 事件：摘除图片并关闭灯箱", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const { w } = await mountView()
    let lb = await openFirstCellLightbox(w)
    expect(lb.exists()).toBe(true)
    lb.vm.$emit("deleted", 11)
    await flushPromises()
    lb = w.findComponent(LightboxStub)
    expect(lb.exists()).toBe(false)
    expect(w.findAll("img").some((im) => im.attributes("alt") === "a.jpg")).toBe(false)
  })
```

- [ ] **Step 2: 跑测试确认新用例失败**

Run:

```bash
cd frontend && pnpm test person-cluster
```

Expected: Task 2 的 2 个 PASS，新 4 个 FAIL（灯箱未挂载、没有删除处理）。

- [ ] **Step 3: 修改 imports**

把 `frontend/src/views/PersonClusterView.vue` 的导入区：

```ts
import { onMounted, ref, watch } from "vue"
import AppHeader from "../components/AppHeader.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import { apiGet, apiPut } from "../api"
import type { ImageRow } from "../stores/browse"
```

替换为：

```ts
import { computed, onMounted, ref, watch } from "vue"
import { useRouter } from "vue-router"
import AppHeader from "../components/AppHeader.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import ImageLightbox from "../components/ImageLightbox.vue"
import { apiDelete, apiGet, apiPut, HttpError } from "../api"
import type { ImageRow } from "../stores/browse"
import { encodePathSegments } from "../utils/path"
```

- [ ] **Step 4: 加 router、拍平列表与灯箱状态**

在 `const loadError = ref("")` 之后插入一行：

```ts
const router = useRouter()
```

在 `locationText` 函数之后、`onMounted(loadClusters)` 之前插入：

```ts
/** 全簇图片按分组顺序拍平：灯箱以此作为完整图片集，翻页可跨年/月组。 */
const flatImages = computed(() => groups.value.flatMap((g) => g.images))

/** 灯箱当前起点图片 id；null = 关闭。状态刻意不进 URL（人物页无图片路由）。 */
const lightboxId = ref<number | null>(null)

function openLightbox(id: number) {
  lightboxId.value = id
}

/** 灯箱「在所在文件夹中查看」：数据自带 gallery_id/root_id，跨图库也能跳回。 */
function onViewInFolder(row: ImageRow) {
  const it = row as ClusterImage
  const suffix = encodePathSegments(it.folder_path)
  router.push(
    suffix
      ? `/galleries/${it.gallery_id}/r/${it.root_id}/${suffix}`
      : `/galleries/${it.gallery_id}/r/${it.root_id}`,
  )
}

/** 网格三点/右键菜单删除：确认后走统一图片删除接口（灯箱内删除由其自行发请求）。 */
async function onGridMenuAction(id: number, action: "delete") {
  if (action !== "delete") return
  const image = flatImages.value.find((it) => it.id === id)
  if (!image) return
  if (!window.confirm(`确定将「${image.filename}」移入回收站？\n\n30 天内可从「回收站」恢复。`)) return
  try {
    await apiDelete(`/api/images/${id}`)
  } catch (err) {
    const m = err instanceof HttpError ? err.message : "删除失败"
    window.alert(`删除失败：${m}`)
    return
  }
  await onImageDeleted(id)
}

/** 删除成功统一收尾：本地摘除、关灯箱、刷新左栏簇计数；当前簇被删空则切走。 */
async function onImageDeleted(id: number) {
  groups.value = groups.value
    .map((g) => ({ ...g, images: g.images.filter((it) => it.id !== id) }))
    .filter((g) => g.images.length > 0)
  lightboxId.value = null
  await loadClusters()
  if (!clusters.value.some((c) => c.cluster_id === selectedId.value)) {
    if (clusters.value.length) await selectCluster(clusters.value[0].cluster_id)
    else groups.value = []
  }
}
```

- [ ] **Step 5: 网格接 open/menuAction 事件**

把模板中的：

```vue
            <JustifiedGrid
              :items="g.images"
              :show-filename="showInfo"
              :badge-for="showInfo ? locationText : undefined"
            />
```

替换为：

```vue
            <JustifiedGrid
              :items="g.images"
              :show-filename="showInfo"
              :badge-for="showInfo ? locationText : undefined"
              @open="openLightbox"
              @menu-action="onGridMenuAction"
            />
```

- [ ] **Step 6: 挂载灯箱**

把模板结尾：

```vue
    </main>
  </div>
</template>
```

替换为：

```vue
    </main>
    <ImageLightbox
      v-if="lightboxId !== null && flatImages.some((it) => it.id === lightboxId)"
      :items="flatImages"
      :start-id="lightboxId"
      :location-resolver="locationText"
      @close="lightboxId = null"
      @deleted="onImageDeleted"
      @view-in-folder="onViewInFolder"
    />
  </div>
</template>
```

- [ ] **Step 7: 跑人物页测试确认 6 个全绿**

Run:

```bash
cd frontend && pnpm test person-cluster
```

Expected: 6 个测试全部 PASS。

- [ ] **Step 8: 全量前端测试 + 类型检查/构建**

Run:

```bash
cd frontend && pnpm test && pnpm build
```

Expected: 全部测试文件 PASS（在原 348 个用例基础上新增本文件 6 个），`vue-tsc --noEmit` 无报错、`vite build` 成功。

- [ ] **Step 9: Commit**

```bash
git add frontend/src/views/PersonClusterView.vue frontend/src/tests/person-cluster-view.spec.ts
git commit -m "feat(people): lightbox paging, in-folder navigation and delete"
```

## Self-Review 结论

- **Spec coverage**：spec §1 后端字段（Task 1 Step 4 逐字段列出，含 folder_path 派生）；§2 类型/拍平/位置函数（Task 2 Step 3 + Task 3 Step 4）；§3 开关与持久化（Task 2 Step 3，测试覆盖开关/角标文本/持久化）；§4 分组保留的 JustifiedGrid（Task 2 Step 3）；§5 灯箱拍平翻页、locationResolver、viewInFolder（Task 3 Step 4–6，三个测试）；§6 网格与灯箱两条删除路径 + 删空切簇（Task 3 Step 4，两个测试）；边界表中的根目录、viewer 无菜单、width/height 兜底均由现成组件逻辑覆盖。无遗漏。
- **Placeholder scan**：无 TBD/TODO；所有代码步骤给出完整可粘贴代码与精确 old/new 锚点；命令与预期输出具体。
- **Type consistency**：`ClusterImage` 四字段名与后端输出逐字一致（gallery_id/root_id/gallery_name/folder_path）；事件名 `open`/`menuAction`（模板 `@menu-action`）/`deleted`/`viewInFolder` 与共享组件定义一致；localStorage 键、localStorage 断言文本、aria-label 在测试与实现中逐字一致。
