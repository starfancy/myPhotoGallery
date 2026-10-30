# 浏览页文件夹快捷排除菜单 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理员在浏览页悬停文件夹缩略图时右上角出现省略号，点击/长按/右键弹出「排除此文件夹」菜单，确认后经 P5 排除接口把该目录清出索引（不删磁盘文件）。

**Architecture:** 后端排除接口在既有 `absolute_path` 之外接受可选 `relative_path`（服务端拼 root 路径后复用同一套终态校验）。前端把图片卡片的单例菜单基建（useCellMenu + CellContextMenu）泛化为 key/action 可参数化，SubfolderStrip 以 `relative_path` 为 key 复用同一菜单并接出 `exclude` 事件，BrowseView 负责 confirm、POST 和文件夹列表局部刷新。

**Tech Stack:** FastAPI + SQLAlchemy（后端，pytest/TestClient）；Vue 3 `<script setup>` + Pinia + vue-router + vitest/@vue/test-utils + vue-tsc（前端）。

## Global Constraints

- 设计文档：`docs/superpowers/specs/2026-10-30-folder-exclude-quick-menu-design.md`（一切冲突以 spec 为准）。
- 工作分支：`folder-exclude-menu`（已建，spec 已提交）。
- 后端测试在**仓库根目录**运行：`python -m pytest backend/tests/test_routes_admin_exclusions.py -q`；全量：`python -m pytest -q`。
- 前端命令在 `frontend/` 目录运行：测试 `pnpm test`（vitest run）；类型门 `npx vue-tsc --noEmit`（不要只靠 vite，build 脚本含 vue-tsc）。
- TDD：每个任务先写/改测试看它失败，再写实现。
- 错误响应用 `AppError(code, http_status, message)`，形状 `{"error": {"code", "message"}}`。
- UI 文案为简体中文；三点按钮圆形半透明黑底，样式复刻 `PhotoCell` 的 `.lb-cell-menu-btn`。
- 提交信息沿用仓库 conventional 风格（如 `feat(browse): ...`、`test(...): ...`）。
- 不推送远程（用户走代理手动推）。

---

### Task 1: 后端排除接口支持 relative_path

**Files:**
- Modify: `backend/src/myphoto/routes_admin.py`（`ExclusionCreate` 约 429-431 行、`_validate_path_within_root` 约 458-481 行、`admin_create_exclusion` 约 510-562 行）
- Test: `backend/tests/test_routes_admin_exclusions.py`（文件尾部追加）

**Interfaces:**
- Consumes: 现有 `POST /api/admin/galleries/{gid}/roots/{rid}/exclusions`，现有 `Exclusion` 模型、`_get_root_or_404`、`AppError`。
- Produces: 请求体 `ExclusionCreate` 新增可选 `relative_path: str | None`；`absolute_path` 与 `relative_path` 恰好一个必填。响应/状态码/审计/rescan 行为不变。供 Task 4 前端 `apiPost(url, { relative_path })` 使用。

- [ ] **Step 1: 在测试文件尾部追加失败测试**

追加到 `backend/tests/test_routes_admin_exclusions.py` 末尾：

```python
# ---- relative_path 入口（2026-10-30 快捷排除菜单）----


def test_create_exclusion_relative_path_201(env_client):
    c, _app, gid, rid, photos = env_client
    (photos / "exports").mkdir()

    r = c.post(_ex_url(gid, rid), json={"relative_path": "exports"})
    assert r.status_code == 201
    e = r.json()
    assert e["relative_path"] == "exports"
    assert e["reason"] is None
    assert e["excluded_by_username"] == "admin"

    listed = c.get(_ex_url(gid, rid)).json()["entries"]
    assert [x["relative_path"] for x in listed] == ["exports"]


def test_relative_path_nested_backslash_normalized_to_posix(env_client):
    c, _app, gid, rid, photos = env_client
    (photos / "a" / "b").mkdir(parents=True)

    r = c.post(_ex_url(gid, rid), json={"relative_path": "a\\b"})
    assert r.status_code == 201
    assert r.json()["relative_path"] == "a/b"


def test_relative_path_dotdot_rejected(env_client):
    c, _app, gid, rid, _photos = env_client
    r = c.post(_ex_url(gid, rid), json={"relative_path": "../x"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


@pytest.mark.parametrize("raw", ["/etc/x", "C:/x", "a//b"])
def test_relative_path_absolute_or_double_slash_rejected(env_client, raw):
    c, _app, gid, rid, _photos = env_client
    r = c.post(_ex_url(gid, rid), json={"relative_path": raw})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


def test_exactly_one_path_field_required(env_client):
    c, _app, gid, rid, photos = env_client
    (photos / "exports").mkdir()

    neither = c.post(_ex_url(gid, rid), json={"reason": "x"})
    assert neither.status_code == 400
    assert neither.json()["error"]["code"] == "path_invalid"

    both = c.post(_ex_url(gid, rid), json={
        "absolute_path": str(photos / "exports"),
        "relative_path": "exports",
    })
    assert both.status_code == 400
    assert both.json()["error"]["code"] == "path_invalid"


def test_relative_path_nonexistent_rejected(env_client):
    c, _app, gid, rid, _photos = env_client
    r = c.post(_ex_url(gid, rid), json={"relative_path": "nope"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_not_readable"


def test_relative_path_duplicate_of_absolute_conflict(env_client):
    c, _app, gid, rid, photos = env_client
    (photos / "exports").mkdir()
    assert c.post(
        _ex_url(gid, rid), json={"absolute_path": str(photos / "exports")}
    ).status_code == 201
    r = c.post(_ex_url(gid, rid), json={"relative_path": "exports"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_relative_exclusion_triggers_rescan(env_client):
    c, _app, gid, rid, photos = env_client
    _wait_idle(c, gid, rid)
    (photos / "exports").mkdir()
    assert c.post(
        _ex_url(gid, rid), json={"relative_path": "exports"}
    ).status_code == 201
    _wait_idle(c, gid, rid)
    st = c.get(f"/api/admin/galleries/{gid}/roots/{rid}/scan-status").json()
    assert st["status"] == "idle"
```

- [ ] **Step 2: 运行新测试，确认失败**

Run: `python -m pytest backend/tests/test_routes_admin_exclusions.py -q`
Expected: 7 个新用例 FAIL（422 校验错误，或 neither/both 落到旧逻辑产生非预期状态码）；原有测试仍 PASS。

- [ ] **Step 3: 修改 `ExclusionCreate`**

在 `backend/src/myphoto/routes_admin.py` 中把：

```python
class ExclusionCreate(BaseModel):
    absolute_path: str = Field(min_length=1, max_length=4096)
    reason: str | None = Field(None, max_length=500)
```

改为：

```python
class ExclusionCreate(BaseModel):
    # absolute_path（管理页 DirectoryChooser）与 relative_path（浏览页快捷菜单）
    # 二选一；handler 中强制恰好提供一个。
    absolute_path: str | None = Field(None, min_length=1, max_length=4096)
    relative_path: str | None = Field(None, min_length=1, max_length=4096)
    reason: str | None = Field(None, max_length=500)
```

- [ ] **Step 4: 重构路径校验为「绝对入口 + 相对入口 + 共用终态校验」**

把现有 `_validate_path_within_root` 整个函数替换为下面三个函数：

```python
def _check_resolved_within_root(p: Path, root_p: Path, display: str) -> str:
    """两个入口共用的终态校验：拒符号链接、必须真实目录、不得等于 root
    本身、resolve 后必须落在 root 内。返回 posix 风格相对路径。"""
    try:
        if p.is_symlink():
            raise AppError("path_invalid", 400, "symlinks are not permitted")
    except OSError:
        raise AppError("path_not_readable", 400, f"path not readable: {display}")
    resolved = p.resolve()
    if resolved == root_p:
        raise AppError("path_invalid", 400, "cannot exclude the root itself")
    try:
        rel = resolved.relative_to(root_p)
    except ValueError:
        raise AppError("path_invalid", 400, "path is outside the root")
    if not resolved.exists() or not resolved.is_dir():
        raise AppError("path_not_readable", 400, f"path not readable: {display}")
    return rel.as_posix()


def _validate_path_within_root(raw_path: str, root: GalleryRoot) -> tuple[Path, str]:
    """管理页入口：入参为磁盘绝对路径。先拒 '..' 片段再走终态校验。"""
    if any(part == ".." for part in raw_path.replace("\\", "/").split("/")):
        raise AppError("path_invalid", 400, "path must not contain '..' segments")
    root_p = Path(root.absolute_path).resolve()
    p = Path(raw_path)
    rel_posix = _check_resolved_within_root(p, root_p, raw_path)
    return p, rel_posix


def _validate_relative_within_root(raw_rel: str, root: GalleryRoot) -> str:
    """浏览页快捷菜单入口：入参为相对 root 的 POSIX 风格路径
    （Windows 反斜杠会被归一化）。空片段（前导/重复斜杠）与 '..'
    在拼接前直接拒绝，避免任何绝对路径形式重置拼接结果。"""
    norm = raw_rel.replace("\\", "/")
    parts = norm.split("/")
    if any(part == ".." for part in parts):
        raise AppError("path_invalid", 400, "path must not contain '..' segments")
    if any(part == "" for part in parts):
        raise AppError("path_invalid", 400, "relative_path must not be absolute")
    root_p = Path(root.absolute_path).resolve()
    p = root_p / norm
    return _check_resolved_within_root(p, root_p, raw_rel)
```

- [ ] **Step 5: 修改 handler 的字段分派**

在 `admin_create_exclusion` 中把：

```python
        root = await _get_root_or_404(s, gid, rid)
        _, rel_posix = _validate_path_within_root(body.absolute_path, root)
```

改为：

```python
        if (body.absolute_path is None) == (body.relative_path is None):
            raise AppError(
                "path_invalid", 400,
                "provide exactly one of absolute_path / relative_path",
            )
        root = await _get_root_or_404(s, gid, rid)
        if body.absolute_path is not None:
            _, rel_posix = _validate_path_within_root(body.absolute_path, root)
        else:
            rel_posix = _validate_relative_within_root(body.relative_path, root)
```

其余（查重、IntegrityError→409、审计、`request_rescan`、返回 payload）不动。

- [ ] **Step 6: 运行该测试文件，全绿**

Run: `python -m pytest backend/tests/test_routes_admin_exclusions.py -q`
Expected: 全部 PASS（原有用例 + 7 个新用例；参数化展开为 9 个新测试结果行）。

- [ ] **Step 7: 后端全量回归**

Run: `python -m pytest -q`
Expected: 全绿（P5 后基线 461 passed/6 skipped，新增后数量相应增加，0 failed）。

- [ ] **Step 8: Commit**

```bash
git add backend/src/myphoto/routes_admin.py backend/tests/test_routes_admin_exclusions.py
git commit -m "feat(exclusions): accept relative_path in admin exclusion API"
```

---

### Task 2: 泛化单例菜单基建（useCellMenu / CellContextMenu）并接入两个网格

**Files:**
- Modify: `frontend/src/composables/useCellMenu.ts`
- Modify: `frontend/src/components/CellContextMenu.vue`
- Modify: `frontend/src/components/JustifiedGrid.vue`（第 21 行模板、第 53 行 composable 调用）
- Modify: `frontend/src/components/MasonryGrid.vue`（第 19 行模板、第 50 行 composable 调用）
- Test（既有，不修改）: `frontend/src/tests/justified-grid.spec.ts`、`frontend/src/tests/masonry-grid.spec.ts`、`frontend/src/tests/browse-view-delete.spec.ts`

**Interfaces:**
- Consumes: 无新依赖。
- Produces:
  - `useCellMenu<K extends string | number, A extends string>(emit)`，`emit: (e: "menuAction", key: K, action: A) => void`；返回 `{ menu, open, openAt, close, runAction }`，其中 `menu: Ref<CellMenuState<K> | null>`，`open(key: K, ev: MouseEvent)`，`openAt(key: K, x: number, y: number)`，`runAction(action: string)`（入参放宽为 string，内部以 `as A` 转交，使模板中 CellContextMenu 的 string 事件可直接绑定）。
  - `CellMenuItem<A>` = `{ action: A; label: string }`；`CellContextMenu` 新增必传 prop `items: CellMenuItem[]`，渲染一项一个 `.lb-cell-menu-item` 按钮，点击 emit `action`（string）。
  - 图片网格对外事件签名不变：`menuAction(id: number, action: "delete")`；菜单项文案不变「移入回收站」。

- [ ] **Step 1: 重写 `frontend/src/composables/useCellMenu.ts`**

整文件替换为：

```ts
import { onMounted, onUnmounted, ref } from "vue"

export type CellMenuKey = string | number

export interface CellMenuState<K extends CellMenuKey = CellMenuKey> {
  key: K
  x: number
  y: number
}

export interface CellMenuItem<A extends string = string> {
  action: A
  label: string
}

type MenuActionEmit<K extends CellMenuKey, A extends string> = (
  e: "menuAction", key: K, action: A,
) => void

/**
 * 缩略图三点菜单 / 右键 / 移动端长按共用的单例弹出菜单：
 * 管菜单状态、视口坐标换算与全局点击关闭。
 * K/A 由调用方收窄（图片网格：number/"delete"；文件夹条：string/"exclude"）。
 */
export function useCellMenu<K extends CellMenuKey = CellMenuKey, A extends string = string>(
  emit: MenuActionEmit<K, A>,
) {
  const menu = ref<CellMenuState<K> | null>(null)

  function openAt(key: K, clientX: number, clientY: number) {
    // 使用相对文档的坐标，避免叠加页面卷动
    menu.value = { key, x: clientX + window.scrollX, y: clientY + window.scrollY }
  }

  function open(key: K, ev: MouseEvent) {
    openAt(key, ev.clientX, ev.clientY)
  }

  function close() {
    menu.value = null
  }

  function runAction(action: string) {
    if (!menu.value) return
    const key = menu.value.key
    menu.value = null
    // 组件把自己的 A 收窄在 emit 签名里；菜单组件只认 string。
    emit("menuAction", key, action as A)
  }

  onMounted(() => window.addEventListener("click", close))
  onUnmounted(() => window.removeEventListener("click", close))

  return { menu, open, openAt, close, runAction }
}
```

- [ ] **Step 2: 重写 `frontend/src/components/CellContextMenu.vue` 的 template/script（style 原样保留）**

```vue
<template>
  <div v-if="menu"
       class="lb-cell-menu"
       :style="{ top: `${menu.y}px`, left: `${menu.x}px` }"
       @click.stop>
    <button v-for="item in items" :key="item.action"
            type="button" class="lb-cell-menu-item"
            @click="$emit('action', item.action)">
      {{ item.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import type { CellMenuItem, CellMenuState } from "../composables/useCellMenu"

defineProps<{
  menu: CellMenuState | null
  items: CellMenuItem[]
}>()
defineEmits<{
  (e: "action", action: string): void
}>()
</script>
```

`<style>` 块（`.lb-cell-menu*`，当前第 22-49 行）保持不动。

- [ ] **Step 3: JustifiedGrid 传入菜单项并显式收窄泛型**

`frontend/src/components/JustifiedGrid.vue`：

模板第 21 行改为：

```vue
    <CellContextMenu :menu="menu"
                     :items="[{ action: 'delete', label: '移入回收站' }]"
                     @action="runAction" />
```

script 第 53 行改为：

```ts
const { menu, open, openAt, runAction } = useCellMenu<number, "delete">(emit)
```

- [ ] **Step 4: MasonryGrid 同样修改**

`frontend/src/components/MasonryGrid.vue`：

模板第 19 行改为：

```vue
    <CellContextMenu :menu="menu"
                     :items="[{ action: 'delete', label: '移入回收站' }]"
                     @action="runAction" />
```

script 第 50 行改为：

```ts
const { menu, open, openAt, runAction } = useCellMenu<number, "delete">(emit)
```

- [ ] **Step 5: 类型门**

Run（在 `frontend/`）: `npx vue-tsc --noEmit`
Expected: 无错误。若有报错，最可能是某调用点未显式给泛型实参——两个网格必须是 `useCellMenu<number, "delete">(emit)`。

- [ ] **Step 6: 跑既有菜单相关测试，确认行为零变化**

Run（在 `frontend/`）: `pnpm test -- justified-grid masonry-grid browse-view-delete`
Expected: 三个 spec 全 PASS（含「emits menuAction 'delete' … toEqual([2, "delete"])」断言）。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/composables/useCellMenu.ts frontend/src/components/CellContextMenu.vue frontend/src/components/JustifiedGrid.vue frontend/src/components/MasonryGrid.vue
git commit -m "refactor(browse): generalize cell menu to keyed items"
```

---

### Task 3: SubfolderStrip 文件夹卡片省略号按钮 / 右键 / 长按菜单

**Files:**
- Modify: `frontend/src/components/SubfolderStrip.vue`
- Test: `frontend/src/tests/folder-exclude-menu.spec.ts`（新建，组件级用例放此文件）

**Interfaces:**
- Consumes: Task 2 的 `useCellMenu<string, "exclude">` 与 `CellContextMenu`（items 传 `[{ action: "exclude", label: "排除此文件夹" }]`）。
- Produces: SubfolderStrip 新增可选 prop `canExclude?: boolean`；新增事件 `(e: "exclude", folder: FolderItem): void`，其中 FolderItem 即现有 folders 数组元素类型（含 `name`/`relative_path` 等）。省略号按钮 selector：`.lb-folder-menu-btn`，aria-label 前缀「排除文件夹 」。供 Task 4 BrowseView 接线。

- [ ] **Step 1: 新建组件级失败测试 `frontend/src/tests/folder-exclude-menu.spec.ts`**

```ts
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import SubfolderStrip from "../components/SubfolderStrip.vue"

interface FolderCard {
  name: string
  relative_path: string
  image_count: number
  descendant_count: number
  cover_thumb_sha1: string | null
  cover_source_name?: string | null
}

// VTU 的默认 RouterLink stub 不渲染插槽；用透传默认插槽的 a 标签占位。
const RouterLinkSlotStub = { template: "<a><slot /></a>" }

const FOLDERS: FolderCard[] = [
  { name: "旅行", relative_path: "trip", image_count: 3, descendant_count: 3, cover_thumb_sha1: null },
  { name: "日常", relative_path: "daily", image_count: 9, descendant_count: 9, cover_thumb_sha1: null },
]

function mountStrip(canExclude: boolean) {
  return mount(SubfolderStrip, {
    props: { folders: FOLDERS, gid: 1, rid: 1, canExclude },
    global: { stubs: { RouterLink: RouterLinkSlotStub } },
  })
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

describe("SubfolderStrip exclude menu", () => {
  beforeEach(() => vi.clearAllMocks())

  it("renders no three-dot button when canExclude is false/omitted", () => {
    const w = mountStrip(false)
    expect(w.findAll(".lb-folder-menu-btn").length).toBe(0)
  })

  it("opens the menu with a single '排除此文件夹' item for admins", async () => {
    const w = mountStrip(true)
    const btns = w.findAll(".lb-folder-menu-btn")
    expect(btns.length).toBe(2)

    await btns[0].trigger("click")
    await flushPromises()
    const items = w.findAll(".lb-cell-menu-item")
    expect(items.length).toBe(1)
    expect(items[0].text()).toBe("排除此文件夹")
  })

  it("emits exclude with the folder whose card opened the menu", async () => {
    const w = mountStrip(true)
    await w.findAll(".lb-folder-menu-btn")[1].trigger("click")
    await flushPromises()
    await w.get(".lb-cell-menu-item").trigger("click")

    const events = w.emitted("exclude") ?? []
    expect(events.length).toBe(1)
    expect(events[0]).toEqual([FOLDERS[1]])
  })

  it("opens on right-click (contextmenu) when canExclude", async () => {
    const w = mountStrip(true)
    await w.findAll(".lb-folder-card")[0].trigger("contextmenu", { clientX: 12, clientY: 34 })
    await flushPromises()
    expect(w.find(".lb-cell-menu").exists()).toBe(true)
  })

  it("does not open a menu on right-click for non-admins", async () => {
    const w = mountStrip(false)
    await w.findAll(".lb-folder-card")[0].trigger("contextmenu")
    await flushPromises()
    expect(w.find(".lb-cell-menu").exists()).toBe(false)
  })

  it("opens on 550ms touch long-press", async () => {
    vi.useFakeTimers()
    try {
      const w = mountStrip(true)
      const card = w.findAll(".lb-folder-card")[0]
      // jsdom 无 TouchEvent 构造器：手工派发带 touches 的冒泡事件
      const ev = new Event("touchstart", { bubbles: true }) as Event & {
        touches: Array<{ clientX: number; clientY: number }>
      }
      ev.touches = [{ clientX: 10, clientY: 20 }]
      card.element.dispatchEvent(ev)

      vi.advanceTimersByTime(550)
      await w.findAll(".lb-folder-card")[0].trigger("touchend")
      expect(w.find(".lb-cell-menu").exists()).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it("cancels long-press when the finger moves before 550ms", async () => {
    vi.useFakeTimers()
    try {
      const w = mountStrip(true)
      const card = w.findAll(".lb-folder-card")[0]
      const ev = new Event("touchstart", { bubbles: true }) as Event & {
        touches: Array<{ clientX: number; clientY: number }>
      }
      ev.touches = [{ clientX: 10, clientY: 20 }]
      card.element.dispatchEvent(ev)

      await card.trigger("touchmove")
      vi.advanceTimersByTime(800)
      expect(w.find(".lb-cell-menu").exists()).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })
})
```

- [ ] **Step 2: 运行新 spec，确认失败**

Run（在 `frontend/`）: `pnpm test -- folder-exclude-menu`
Expected: FAIL —— `.lb-folder-menu-btn` / `.lb-folder-card` 不存在，`exclude` 事件未声明。

- [ ] **Step 3: 重写 `frontend/src/components/SubfolderStrip.vue`**

整文件替换为：

```vue
<template>
  <div v-if="folders.length" class="lb-folder-grid py-2">
    <div v-for="f in folders" :key="f.relative_path"
         class="lb-folder-card group relative flex w-full flex-col overflow-hidden rounded bg-neutral-800 text-sm hover:ring-2 hover:ring-blue-500"
         @contextmenu="onContextMenu(f.relative_path, $event)"
         @touchstart="onTouchStart(f.relative_path, $event)"
         @touchend="onTouchEnd"
         @touchmove="onTouchEnd">
      <!-- 卡片整体可点进目录；省略号按钮作为链接的兄弟节点，避免 button 嵌套在 a 内 -->
      <router-link :to="linkFor(f.relative_path)"
                   class="flex w-full flex-1 flex-col">
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
        <div class="truncate p-2">
          <div class="truncate font-medium">{{ f.name }}</div>
          <div class="text-xs text-neutral-400">{{ f.descendant_count }} 张</div>
        </div>
      </router-link>
      <!-- Admin-only 省略号：hover / 键盘 focus 才显示，点击弹快捷菜单 -->
      <button v-if="canExclude"
              type="button"
              :aria-label="`排除文件夹 ${f.name}`"
              class="lb-folder-menu-btn"
              @click.stop="open(f.relative_path, $event)">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <circle cx="5" cy="12" r="2" />
          <circle cx="12" cy="12" r="2" />
          <circle cx="19" cy="12" r="2" />
        </svg>
      </button>
    </div>
    <CellContextMenu :menu="menu"
                     :items="MENU_ITEMS"
                     @action="runAction" />
  </div>
</template>

<script setup lang="ts">
import { reactive } from "vue"
import CellContextMenu from "./CellContextMenu.vue"
import { useCellMenu, type CellMenuItem } from "../composables/useCellMenu"

interface FolderItem {
  name: string
  relative_path: string
  image_count: number
  descendant_count: number
  cover_thumb_sha1: string | null
  cover_source_name?: string | null
}

const props = defineProps<{
  folders: FolderItem[]
  gid: number
  rid: number
  /** 管理员为 true：显示省略号、响应右键与长按 */
  canExclude?: boolean
}>()

const emit = defineEmits<{
  (e: "exclude", folder: FolderItem): void
}>()

const MENU_ITEMS: CellMenuItem[] = [
  { action: "exclude", label: "排除此文件夹" },
]

const { menu, open, openAt, runAction } = useCellMenu<string, "exclude">(
  (_e, key, action) => {
    if (action !== "exclude") return
    const folder = props.folders.find((f) => f.relative_path === key)
    if (folder) emit("exclude", folder)
  },
)

function onContextMenu(key: string, ev: MouseEvent) {
  // 非管理员不拦截浏览器默认右键菜单
  if (!props.canExclude) return
  ev.preventDefault()
  open(key, ev)
}

// ---------- 移动端长按（与 PhotoCell 一致：550ms，移动/抬手即取消） ----------

let pressTimer: number | null = null
let pressStart: { key: string; x: number; y: number } | null = null

function onTouchStart(key: string, _ev: TouchEvent) {
  if (!props.canExclude) return
  const t = _ev.touches[0]
  pressStart = { key, x: t.clientX, y: t.clientY }
  pressTimer = window.setTimeout(() => {
    if (!pressStart) return
    openAt(pressStart.key, pressStart.x, pressStart.y)
    pressTimer = null
  }, 550)
}

function onTouchEnd() {
  if (pressTimer !== null) {
    clearTimeout(pressTimer)
    pressTimer = null
  }
  pressStart = null
}

// 记录每张封面缩略图是否为竖版（宽 < 高）。key 为 sha1，多个文件夹复用同一封面时可共享判定。
const portrait = reactive<Record<string, boolean>>({})

function onCoverLoad(sha1: string | null, e: Event) {
  if (!sha1) return
  const img = e.target as HTMLImageElement
  portrait[sha1] = img.naturalWidth < img.naturalHeight
}

function linkFor(rel: string) {
  return `/galleries/${props.gid}/r/${props.rid}/${rel}`
}
</script>

<style scoped>
/*
 * auto-fill + 1fr：卡片等比拉伸铺满整行，左右边缘与图片网格
 * （JustifiedGrid/MasonryGrid 均为内容区满宽）严格对齐；
 * 最小列宽 128（原 w-32），间距与图片网格同为 16px。
 */
.lb-folder-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(128px, 1fr));
  gap: 16px;
}
/* 借来的封面：图底黑色渐变，托住白色来源名 */
.lb-folder-source {
  background: linear-gradient(to top, rgba(0, 0, 0, 0.75), rgba(0, 0, 0, 0));
}
/* 与 PhotoCell 的 .lb-cell-menu-btn 同款：右上角圆形半透明黑底 */
.lb-folder-menu-btn {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  display: none;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border: 0;
  z-index: 2;
}
.lb-folder-card:hover .lb-folder-menu-btn,
.lb-folder-menu-btn:focus-visible {
  display: flex;
}
.lb-folder-menu-btn:hover {
  background: rgba(0, 0, 0, 0.75);
}
</style>
```

注意：原文件第 30 行 `import { reactive } from "vue"` 在 script 中位置变动属正常；原 `<style scoped>` 中两条网格/渐变规则保留，只新增按钮规则。

- [ ] **Step 4: 跑新 spec 与既有 SubfolderStrip 测试**

Run（在 `frontend/`）: `pnpm test -- folder-exclude-menu subfolder-strip`
Expected: 两个 spec 全部 PASS（含原有 borrowed-cover 三条用例——结构调整后 `.lb-folder-source` 仍在）。

- [ ] **Step 5: 类型门**

Run（在 `frontend/`）: `npx vue-tsc --noEmit`
Expected: 无错误。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/SubfolderStrip.vue frontend/src/tests/folder-exclude-menu.spec.ts
git commit -m "feat(browse): admin hover/long-press exclude menu on folder cards"
```

---

### Task 4: BrowseView 接线——confirm、POST relative_path、局部刷新文件夹列表

**Files:**
- Modify: `frontend/src/views/BrowseView.vue`（模板第 49 行 SubfolderStrip；script 中 `loadAll` 第 251-274 行；新增 handler）
- Test: `frontend/src/tests/folder-exclude-menu.spec.ts`（在同一文件追加 BrowseView describe 块）

**Interfaces:**
- Consumes: Task 1 的 `POST /api/admin/galleries/:gid/roots/:rid/exclusions`（body `{ relative_path }`）；Task 3 的 SubfolderStrip `canExclude` prop 与 `exclude(folder)` 事件；`useAuthStore().isAdmin`；`apiPost`、`HttpError`（BrowseView 已 import）。
- Produces: 无新对外接口。行为：确认后 POST；成功只重拉 crumbs+folders（含 borrowed-cover 补查），不动图片分页与滚动；失败 `window.alert("排除失败：" + message)`。

- [ ] **Step 1: 在 `frontend/src/tests/folder-exclude-menu.spec.ts` 顶部补充 import**

在文件现有 import 之后追加：

```ts
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import BrowseView from "../views/BrowseView.vue"
import { useAuthStore } from "../stores/auth"
```

- [ ] **Step 2: 在同一测试文件末尾追加 BrowseView 级失败测试**

```ts
// ---------- BrowseView 端到端：确认 → POST relative_path → 局部刷新 ----------

const CRUMBS = [{ name: "R", relative_path: "" }]
const SERVER_FOLDERS = [
  { name: "旅行", relative_path: "trip", image_count: 0, descendant_count: 3, cover_thumb_sha1: null },
]
const IMAGES = [
  { id: 1, filename: "a.jpg", width: 400, height: 300, sha1: "sha-a", size_bytes: 1, taken_at: null, is_raw: false },
]

function jsonResponse(body: unknown, status = 200) {
  const isNull = body === null || body === undefined
  return new Response(isNull ? null : JSON.stringify(body), {
    status,
    headers: isNull ? {} : { "content-type": "application/json" },
  })
}

async function mountBrowse(role: "admin" | "viewer") {
  // 服务端状态：排除成功后 folders 重拉返回空列表（卡片应消失）
  const folders = SERVER_FOLDERS.map((x) => ({ ...x }))
  const excludeBodies: unknown[] = []
  const fetchFn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : (input as Request).url ?? String(input)
    const method = init?.method ?? "GET"
    if (method === "GET" && url.includes("/breadcrumbs")) return jsonResponse(CRUMBS)
    if (method === "GET" && url.includes("/folders")) {
      // path=trip 是 enrichBorrowedCovers 的直接子级补查，返回空即可
      return jsonResponse(url.includes("path=trip") ? [] : folders.map((x) => ({ ...x })))
    }
    if (method === "GET" && url.includes("/images")) {
      return jsonResponse({ items: IMAGES, total: IMAGES.length })
    }
    if (method === "POST" && /\/exclusions$/.test(url)) {
      excludeBodies.push(JSON.parse(init?.body as string))
      folders.splice(0, folders.length)
      return jsonResponse({ id: 99, relative_path: "trip", reason: null })
    }
    return jsonResponse({ error: { code: "not_found", message: "not mocked" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)

  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({ user: { id: 1, username: "u", role, access_scope: "lan_only" } })

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/galleries/:gid/r/:rid/:path(.*)*", component: BrowseView },
      { path: "/galleries/:gid/r/:rid/:path(.*)*/image/:iid", component: BrowseView },
    ],
  })
  await router.push("/galleries/1/r/1")
  const w = mount(BrowseView, {
    global: { plugins: [router], stubs: { ImageLightbox: true } },
  })
  await flushPromises()
  await flushPromises()  // 网格 onMounted 再等一轮
  return { w, fetchFn, excludeBodies }
}

describe("BrowseView folder quick exclude", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  it("shows the folder ellipsis for admin but not for viewer", async () => {
    const admin = await mountBrowse("admin")
    expect(admin.w.findAll('button[aria-label^="排除文件夹"]').length).toBe(1)

    const viewer = await mountBrowse("viewer")
    expect(viewer.w.findAll('button[aria-label^="排除文件夹"]').length).toBe(0)
  })

  it("POSTs relative_path after confirm and refreshes only the folder list", async () => {
    const { w, fetchFn, excludeBodies } = await mountBrowse("admin")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))

    await w.get('button[aria-label^="排除文件夹"]').trigger("click")
    await flushPromises()
    await w.get(".lb-cell-menu-item").trigger("click")
    await flushPromises()
    await flushPromises()

    expect(window.confirm).toHaveBeenCalledTimes(1)
    const confirmText = (window.confirm as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
    expect(confirmText).toContain("旅行")
    expect(confirmText).toContain("不会被删除")

    expect(excludeBodies).toEqual([{ relative_path: "trip" }])
    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const post = calls.find(
      (c) => c[1]?.method === "POST" && c[0] === "/api/admin/galleries/1/roots/1/exclusions",
    )
    expect(post).toBeDefined()

    // 文件夹卡片消失，图片分页不受影响
    expect(w.findAll('button[aria-label^="排除文件夹"]').length).toBe(0)
    expect(w.findAll("img").length).toBeGreaterThanOrEqual(1)
  })

  it("sends no POST when the confirm is cancelled", async () => {
    const { w, excludeBodies } = await mountBrowse("admin")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(false))

    await w.get('button[aria-label^="排除文件夹"]').trigger("click")
    await flushPromises()
    await w.get(".lb-cell-menu-item").trigger("click")
    await flushPromises()

    expect(excludeBodies.length).toBe(0)
    expect(w.findAll('button[aria-label^="排除文件夹"]').length).toBe(1)
  })

  it("alerts with the server message when the POST fails (e.g. 409)", async () => {
    const { w } = await mountBrowse("admin")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
    const alertSpy = vi.fn()
    vi.stubGlobal("alert", alertSpy)
    // 覆盖 fetch：仅让 exclusions POST 返回 409，其余沿用已注册行为不易重建，
    // 故直接替换全局 fetch 为精简版。
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.includes("/exclusions")) {
        return jsonResponse(
          { error: { code: "conflict", message: "this directory is already excluded" } },
          409,
        )
      }
      return jsonResponse({ error: { code: "not_found", message: "not mocked" } }, 404)
    }))

    await w.get('button[aria-label^="排除文件夹"]').trigger("click")
    await flushPromises()
    await w.get(".lb-cell-menu-item").trigger("click")
    await flushPromises()

    expect(alertSpy).toHaveBeenCalledTimes(1)
    expect(alertSpy.mock.calls[0][0]).toContain("排除失败")
    expect(alertSpy.mock.calls[0][0]).toContain("already excluded")
  })
})
```

注意 409 用例的 fetch 替换发生在 mount 之后：组件已拿到文件夹数据，POST 走替换后的 fetch；此用例不关心成功后的刷新。

- [ ] **Step 3: 运行新测试，确认失败**

Run（在 `frontend/`）: `pnpm test -- folder-exclude-menu`
Expected: 新 4 个 BrowseView 用例 FAIL（找不到 `aria-label^="排除文件夹"` 按钮 / POST 未发出）；Task 3 的组件用例仍 PASS。

- [ ] **Step 4: 模板给 SubfolderStrip 传 prop 与监听事件**

`frontend/src/views/BrowseView.vue` 模板中（当前第 49 行）：

```vue
      <SubfolderStrip v-if="folders.length" :folders="folders" :gid="gid" :rid="rid" />
```

改为：

```vue
      <SubfolderStrip v-if="folders.length" :folders="folders" :gid="gid" :rid="rid"
                      :can-exclude="auth.isAdmin"
                      @exclude="onExcludeFolder" />
```

- [ ] **Step 5: 抽出 `loadFolders()` 并新增 `onExcludeFolder`**

在 `frontend/src/views/BrowseView.vue` 的 `<script setup>` 中：

(a) 把 `loadAll` 中这段（当前约 254-264 行）：

```ts
    const key = currentKey()
    const [c, f] = await Promise.all([
      apiGet<any[]>(`/api/galleries/${gid.value}/roots/${rid.value}/breadcrumbs?path=${encodeURIComponent(path.value)}`),
      apiGet<any[]>(`/api/galleries/${gid.value}/roots/${rid.value}/folders?path=${encodeURIComponent(path.value)}`),
    ])
    crumbs.value = c
    folders.value = f
    // 空文件夹（自身无图、后代有图）借用直接子文件夹封面：fire-and-forget，
    // 不阻塞分页加载；单项失败在函数内静默处理。
    void enrichBorrowedCovers()
    page.value = 1
```

改为：

```ts
    const key = currentKey()
    await loadFolders()
    page.value = 1
```

(b) 在 `loadAll` 函数**之前**新增 `loadFolders`（与 loadAll 同级；它依赖的 gid/rid/path/crumbs/folders/enrichBorrowedCovers 均在组件作用域内）：

```ts
/**
 * 只重拉面包屑与文件夹列表（含空文件夹借封面补查）。
 * 快捷排除成功后使用：不清图片分页缓存、不滚顶、不重置页码。
 */
async function loadFolders() {
  const [c, f] = await Promise.all([
    apiGet<any[]>(`/api/galleries/${gid.value}/roots/${rid.value}/breadcrumbs?path=${encodeURIComponent(path.value)}`),
    apiGet<any[]>(`/api/galleries/${gid.value}/roots/${rid.value}/folders?path=${encodeURIComponent(path.value)}`),
  ])
  crumbs.value = c
  folders.value = f
  // 空文件夹（自身无图、后代有图）借用直接子文件夹封面：fire-and-forget，
  // 单项失败在函数内静默处理。
  await enrichBorrowedCovers()
}
```

(c) 在 `onGridMenuAction` 函数之后新增 handler：

```ts
/** 文件夹卡片快捷菜单：确认后走 P5 排除接口（仅清索引，不删磁盘文件）。 */
async function onExcludeFolder(folder: { name: string; relative_path: string }) {
  const msg =
    `确定排除文件夹「${folder.name}」？\n\n` +
    "该文件夹及其所有子文件夹、图片将从图库索引中移除，磁盘上的文件不会被删除。" +
    "之后可在「图库管理」中解除排除。"
  if (!window.confirm(msg)) return
  try {
    await apiPost(
      `/api/admin/galleries/${gid.value}/roots/${rid.value}/exclusions`,
      { relative_path: folder.relative_path },
    )
  } catch (err) {
    const m = err instanceof HttpError ? err.message : "排除失败"
    window.alert(`排除失败：${m}`)
    return
  }
  // 只刷新文件夹区域；图片分页与滚动位置保持不动
  await loadFolders()
}
```

- [ ] **Step 6: 运行该 spec**

Run（在 `frontend/`）: `pnpm test -- folder-exclude-menu`
Expected: 全部 PASS（7 个组件用例 + 4 个 BrowseView 用例）。若 409 用例报 `window.alert` 未调用，检查 `api.ts` 的 request 是否把 409 body 解析为 `HttpError`（既有删除流程依赖同一机制，应为现成行为）。

- [ ] **Step 7: 类型门**

Run（在 `frontend/`）: `npx vue-tsc --noEmit`
Expected: 无错误。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/BrowseView.vue frontend/src/tests/folder-exclude-menu.spec.ts
git commit -m "feat(browse): quick-exclude folder from thumbnail with confirm"
```

---

### Task 5: 全量回归与收尾

**Files:**
- 无代码改动；运行全部门禁。

- [ ] **Step 1: 后端全量**

Run（仓库根目录）: `python -m pytest -q`
Expected: 全绿，0 failed（基线 461 passed/6 skipped + Task 1 新增 9 个结果行：7 个函数中含 1 个三参数 parametrize）。

- [ ] **Step 2: 前端全量 + 类型门 + 生产构建**

Run（在 `frontend/`）:
```bash
npx vue-tsc --noEmit
pnpm test
pnpm build
```
Expected: vue-tsc 无错误；vitest 全绿（203 基线 + 本计划新增 11 个前端用例）；vite build 成功。

- [ ] **Step 3: 检查工作区干净并汇总**

Run: `git status && git log --oneline main..HEAD`
Expected: 工作区干净；相对 main 有 5 个提交（1 个 spec 文档 + Task 1-4 各 1 个）。

- [ ] **Step 4: 手工冒烟（可选，用户边用边验）**

起服务后以管理员登录浏览页：
1. hover 文件夹卡片 → 右上角出现三点；移开消失；Tab 键盘聚焦可见。
2. 点三点 → 「排除此文件夹」→ 取消：无请求；再走确认：卡片随列表刷新消失。
3. 进图库管理页对应 root「排除目录」面板，可见新条目；点「解除」可恢复。
4. 普通用户登录：无三点、右键是浏览器默认菜单。
5. （可选）手机视图长按 550ms 弹菜单。

## Self-Review 记录

- **Spec 覆盖**：后端字段/校验/测试（§2）→ Task 1；菜单泛化（§3.1）→ Task 2；SubfolderStrip 按钮/右键/长按/结构（§3.2）→ Task 3；BrowseView confirm 文案/POST/局部刷新/错误（§3.3）→ Task 4；测试矩阵（§4）→ Task 1/3/4 + Task 5 全量；受影响文件清单（§5）全部出现。
- **非目标守住**：未加浏览页解除入口；管理页流程零改动；菜单只一项。
- **类型一致性**：`useCellMenu<K, A>` 在 Task 2 定义、Task 3 以 `<string, "exclude">` 使用；`CellMenuItem` 在同一文件导出；事件名 `exclude`、prop `canExclude`、selector `.lb-folder-menu-btn`/`.lb-folder-card` 在 Task 3 定义并被 Task 4 测试使用；接口 URL 与 Task 1 一致。
