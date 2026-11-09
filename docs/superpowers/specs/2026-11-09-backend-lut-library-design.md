# 后端 LUT 库 + 管理后台启用 — 设计文档

日期：2026-11-09
状态：待实现
前置：[2026-11-09-lut-filter-preview-design.md](2026-11-09-lut-filter-preview-design.md)（前端预览页已上线）

## 目标

把当前硬编码在 `frontend/public/filters/` 的静态 LUT 清单，升级为后端管理的 LUT 库：

- `.cube` 文件存放在 `backend/data/luts/<group>/<name>.cube`
- DB 存元数据（slug、label、group、enabled、sort_order、source、license）
- 启动时扫描磁盘自动发现新文件（默认 disabled）
- admin 后台按 group 分组展示，可勾选启用、改名、排序
- viewer 前端只拿已启用的 LUT 列表和对应 `.cube` 文本

## 非目标（v1 明确不做）

- 不支持 admin 通过后台上传 `.cube` 文件——加新 LUT 仍需手动放文件进 `backend/data/luts/<group>/`，重启后端
- 不支持按用户 / 按 gallery 启用（全局启用）
- 不删除前端预览页的现有 UI 逻辑——只换数据来源
- 不做 LUT 预览缩略图服务（前端已在小样条里自渲）
- 不做二级以上子文件夹分组——只扫一级 group 目录

## 数据模型

新表 `luts`：

| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| slug | TEXT UNIQUE | 内部 id，由文件名派生（小写、非字母数字→_） |
| label | TEXT | 显示名，admin 可改 |
| group | TEXT NOT NULL DEFAULT "" | 一级子文件夹名；根目录下的文件 group="" |
| file_path | TEXT UNIQUE | 相对 `backend/data/luts/` 的相对路径，如 `fujifilm/velvia.cube` |
| enabled | INTEGER NOT NULL DEFAULT 0 | 0/1 |
| sort_order | INTEGER NOT NULL DEFAULT 0 | 同组内排序 |
| source | TEXT NOT NULL DEFAULT "" | 来源 URL（许可证溯源） |
| license | TEXT NOT NULL DEFAULT "" | 许可证简写，如 "MIT (G'MIC)" |
| created_at | INTEGER NOT NULL | 首次发现时间 |

索引：`(group, sort_order)`、`enabled`。

## 文件布局

```
backend/data/luts/                    # gitignore；首次启动不存在时自动创建
  synthetic/                          # 现有 3 支合成预设迁过来
    warm.cube
    cool.cube
    mono.cube
  fujifilm/                           # 种子数据（从 YahiaAngelo/Film-Luts 挑）
    provia.cube
    velvia.cube
    astia.cube
    classic_chrome.cube
    acros.cube
  kodak/                              # 后续可手动加
  cinematic/                          # 后续可手动加
```

## 启动扫描（`lut_scanner.py`）

后端启动时（`main.py`  lifespan）：

1. 递归一层子文件夹 `backend/data/luts/`，收集所有 `.cube` 文件
2. 对每个文件：
   - 计算 `file_path`（相对路径）、派生 `slug`（从文件名，无扩展名）
   - 若 DB 里已有相同 `file_path`：跳过（不覆盖 admin 改过的 label/enabled/sort_order）
   - 若 DB 里没有：插入新行，`enabled=0` 默认、`label=slug`、`group=父目录名或""`、`created_at=now`
3. DB 里有但磁盘上已经不存在的行：**软删除**（`enabled=0` 并记日志），不真删行——保留 sort_order 历史
4. 整个扫描过程在事务内，失败不阻塞启动（只打 warning）

## API

### Viewer 可访问（authGuard 已登录即可）

- `GET /api/luts` → 已启用列表，按 group 分组：
  ```json
  [
    { "group": "fujifilm", "items": [
      { "slug": "velvia", "label": "富士 Velvia", "sort_order": 1 },
      ...
    ]},
    { "group": "synthetic", "items": [...] }
  ]
  ```
  group 按字母排序；group=""（未分组）排在最前。
- `GET /api/luts/{slug}/cube` → 返回 `.cube` 文本（`text/plain`）。只返回已启用的；未启用或不存在 → 404。

### Admin 可访问（requiresAdmin）

- `GET /api/admin/luts` → 全部列表（含 disabled），扁平数组：
  ```json
  [{ "slug": "...", "label": "...", "group": "...", "enabled": 0,
     "sort_order": 0, "source": "...", "license": "...",
     "file_path": "...", "created_at": 1234567890 }, ...]
  ```
- `PATCH /api/admin/luts/{slug}` → body 可选字段 `enabled`、`label`、`sort_order`。只允许改这三项。
- `POST /api/admin/luts/rescan` → 立即触发一次磁盘扫描（替代重启）。

## 前端改动

### FilterPreviewView.vue

数据来源从静态 `/filters/manifest.json` + `/filters/<file>.cube` 改为：

- 挂载后 `GET /api/luts` → 拿到分组列表
- 对每组展开，小样条按 group 分块渲染（先显示 group 中文名 label，下面是该组的小样按钮）
- 点小样 → `GET /api/luts/{slug}/cube` 拿文本 → `parseCube` → `loadLut`

**group 中文名映射表**（前端硬编码 `frontend/src/lib/lutGroups.ts`）：
```ts
export const LUT_GROUP_LABELS: Record<string, string> = {
  fujifilm: "富士胶片",
  kodak: "柯达",
  cinematic: "电影感",
  synthetic: "合成预设",
}
// 未映射的 group 直接显示原名
```

### AdminLuts.vue（新页面）

路由 `/admin/luts`，仅 admin。

布局：
- 顶部："立即重新扫描"按钮 + 提示文字"新增 .cube 文件需放到 `backend/data/luts/<group>/` 后点重新扫描"
- 按 group 分组的表格：每行一个 LUT，列 = label（可编辑 input）、enabled（toggle）、sort_order（number input）、source/license（只读灰字）、file_path（只读）
- 未启用的 LUT 整行淡化展示
- 变更即时 PATCH（失焦或 toggle 时立即保存）

### router.ts

新增：
```ts
{ path: "/admin/luts", component: () => import("./views/AdminLuts.vue"),
  meta: { requiresAdmin: true } },
```

### AppHeader 或 AdminOverview 加入口

在 `AdminOverview.vue` 或 admin 侧导航加一个"滤镜 LUT"链接——具体位置实现时再看现有导航结构。

## 种子数据（一次性脚本）

`backend/scripts/seed_luts.py`：

1. 从 YahiaAngelo/Film-Luts 仓库（MIT）下载 5 支富士 LUT（provia/velvia/astia/classic_chrome/acros）到 `backend/data/luts/fujifilm/`
2. 把现有 `frontend/public/filters/{warm,cool,mono}.cube` 复制到 `backend/data/luts/synthetic/`
3. 每张表插入对应元数据（source = 仓库 URL，license = "MIT (G'MIC)"）
4. 富士 5 支 enabled=1；合成 3 支 enabled=1（保持现状）

脚本可重复运行（幂等）。

## 迁移

- 删除 `frontend/public/filters/` 整个目录
- 删除 `frontend/scripts/gen-builtin-luts.mjs`（不再需要）
- 更新 `frontend/src/tests/filter-assets.spec.ts`（改为测 API mock 或直接删）

## 错误处理

- `backend/data/luts/` 目录不存在：启动扫描时自动 mkdir，不阻塞
- `.cube` 文件损坏（parseCube 失败）：启动扫描时记 warning，插入 DB 时 `label="<文件名> (损坏)"`，enabled=0；viewer 请求时返回 500 + 错误 message
- admin PATCH 非法字段（如改 source）：422
- 前端 `GET /api/luts` 失败：小样条空，主预览仍可显示原图（不阻塞）

## 测试策略

**后端 pytest**：
- `lut_scanner`：新文件自动发现、已有文件不覆盖 label、磁盘删除软删
- API：viewer 只能看 enabled、admin PATCH 行为、404 for disabled cube
- 启动扫描事务回滚

**前端 vitest**：
- `FilterPreviewView` 改用 mock API：`/api/luts` 返回分组数据，`/api/luts/{slug}/cube` 返回文本
- `AdminLuts`：表格渲染、toggle PATCH、group 分组
- 删除旧的 `filter-assets.spec.ts`

## 工作量估计

- 后端模型 + scanner + API：~1 天
- 种子脚本 + 5 支 LUT 下载：~2 小时
- 前端 AdminLuts 页面：~半天
- FilterPreviewView 数据迁移：~2 小时
- 测试 + 迁移旧代码：~半天

合计约 2.5-3 天。
