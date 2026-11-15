# 智能标签系统升级设计

> 状态：Phase 1–3 已落地（2026-11），Phase 4 调优待做；本文档已按实际实现修订
> 原型验证：`prototypes/classify_pipeline/`（YOLO + CLIP + InsightFace 三管线已跑通）
> 实测性能（i5-11320H + Iris Xe，OpenVINO GPU）：纯推理 ~270ms/张，含解码+IO 稳态
> ~350ms/张；全量 2923 张 17 分钟、0 失败；人脸 576 → 269 簇

## 1. 目标

为相册增加两个维度的自动标签：

- **场景标签**（CLIP 零样本分类，9 大类 ~45 小类）
- **人物标签**（YOLO 检测人数 + InsightFace 人脸聚类）

支持按标签筛选、按人物聚类浏览。增量打标在扫描时**同步串行**执行（仅针对
新增/变化文件，未变文件不碰模型），兼顾机械硬盘的 IO 最优；存量图库通过 CLI
`myphoto tag run` 单独批量打标。

## 2. 数据库设计

### 2.1 新增字段（`images` 表）

```sql
ALTER TABLE images ADD COLUMN scene_major TEXT;        -- 一级分类，如 "自然风光"
ALTER TABLE images ADD COLUMN scene_minor TEXT;         -- 二级分类，如 "海滩海岸"
ALTER TABLE images ADD COLUMN scene_conf REAL;          -- 置信度
ALTER TABLE images ADD COLUMN person_count INTEGER;     -- YOLO 检测人数
ALTER TABLE images ADD COLUMN tagged_at INTEGER;        -- 打标时间戳（NULL = 未打标）
ALTER TABLE images ADD COLUMN tag_model_version TEXT;   -- 模型版本，如 "clip-v2-yolo11n"
```

### 2.2 新增表

```sql
-- CLIP 图像向量（调提示词时不用重跑模型）
CREATE TABLE image_embeddings (
    image_id    INTEGER PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
    embedding   BLOB NOT NULL,          -- 512 维 float32，约 2KB
    model_version TEXT NOT NULL,        -- "clip-vit-b32-v2"
    created_at  INTEGER NOT NULL
);

-- 人脸向量（聚类增量需要）
CREATE TABLE face_embeddings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id    INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    face_index  INTEGER NOT NULL,           -- 同一张图多张脸时的序号
    bbox        TEXT,                       -- "[x1,y1,x2,y2]" 原图坐标系
    embedding   BLOB NOT NULL,              -- 512 维 float32
    confidence  REAL NOT NULL,
    cluster_id  TEXT,                       -- "P001"，未分配时 NULL
    model_version TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX idx_face_emb_cluster ON face_embeddings(cluster_id);
CREATE INDEX idx_face_emb_image ON face_embeddings(image_id);

-- 人物簇（用户可命名）
CREATE TABLE face_clusters (
    cluster_id   TEXT PRIMARY KEY,          -- "P001"
    display_name TEXT,                      -- 用户命名，NULL = 未命名
    sample_face_id INTEGER,                 -- 代表性人脸 face_embeddings.id
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
);
```

### 2.3 存量升级

新增 alembic-style 迁移脚本 `backend/src/myphoto/migrations/0002_tags.sql`：

- 检测上述字段/表是否存在，不存在则创建（幂等）
- **不回填**——存量数据由用户通过 CLI 命令按图库逐个打标（见 §3.2）
- 现有 `images` 行 `tagged_at = NULL`，代表"待打标"

## 3. 打标流程

### 3.1 增量打标（扫描时同步）

现有 scanner 流程（`scanner.py`）：

```
扫描目录 → hash → EXIF → 写 images 行（不生成缩略图）
```

升级后（**同步串行，单线程**；2026-11 落地实现）：

```
扫描目录 → hash → EXIF → 解码原图（全分辨率，内存）
       → 同一张全尺寸图喂 CLIP + YOLO（模型内部各自降采样）
       → YOLO 检测到人脸 → 从全尺寸原图裁脸跑 InsightFace
       → 写 images 行 + 标签 + 向量
```

> **实现与初稿的差异（重要）**：初稿设想"先 resize 到 400px 再跑模型，并顺便写
> 400 缩略图缓存"。落地时去掉了 400 中间层——各模型本就会内部降采样
> （CLIP→224、YOLO→640），多一道 400 resize 是冗余；且缩略图保持纯按需生成，
> 不与扫描/打标耦合。全尺寸解码实测 ~80ms，瓶颈在推理（~270ms），去掉中间
> resize 对小脸/远处人物检测更有利。**扫描与打标全程不生成、不保存任何缩略图。**

**为什么同步而不是异步**（针对机械硬盘场景）：

- 机械硬盘单线程随机读 ~100 IOPS，并行解码 N 张会导致磁盘寻址抖动
- 异步打标 = 原图读 2 次（扫描时 hash/EXIF 一次，打标时解码一次）
- 同步打标 = 打标只处理新增/变化文件，hash 刚读过文件、OS 缓存命中，解码代价低
- 虽然 CPU 推理（实测 ~350ms/张稳态）拖慢扫描，但总 IO 最优，机械硬盘上反而更快

**配置开关**（落地为 `[tagging]` 段，见 §8.5）：

```toml
[tagging]
enabled = true            # 总开关；false 时 scanner/CLI 都不打标
scan_on_import = true     # 扫描时对新增/变化图片同步打标（未变文件不碰模型）
models_dir = "backend/models"
```

**设计要点**：

- 原图只解码 1 次，三个模型在内存中共享全尺寸图
- **不生成/不写缩略图缓存**；缩略图仍是用户预览时按需生成（与打标解耦）
- 打标失败不阻塞扫描：catch 异常，写 `tag_error`，继续下一张
- 模型懒加载、常驻内存（OpenVINO 首次调用编译一次，整个扫描过程复用）

### 3.2 存量打标（CLI 命令）

新增 CLI 命令（`cli.py`）：

```bash
# 列出所有图库及其打标状态
myphoto tag status

# 给指定图库打标（可重复执行，已打标的跳过）
myphoto tag run --gallery "我的照片"

# 给指定图库下某个文件夹打标
myphoto tag run --gallery "我的照片" --folder "旅行-OLD/成都"

# 强制重打（模型升级时用，范围内全部重打）
myphoto tag run --gallery "我的照片" --force

# 只重试历史失败项（tag_error 非空），与 --force 互斥（2026-11 新增）
myphoto tag run --gallery "我的照片" --retry-failed

# 打标完成后重新聚簇
myphoto tag cluster

# 调整提示词后，基于已有向量秒级重算标签（不跑模型）
myphoto tag relabel

# 清理无任何人脸指向的孤儿人物簇（--force 重打后的残留）
myphoto tag gc                 # 只删未命名孤儿，保留在用簇与已命名簇
myphoto tag gc --include-named # 连已命名但变孤儿的簇也删
```

**设计要点**：
- 按图库逐个跑，用户验证完一个再跑下一个（需求 2）
- 断点续跑：`tagged_at IS NULL` 或 `tagged_sha1 != sha1` 的才跑；历史失败
  （`tag_error` 非空）默认跳过，需 `--force` 才重试
- 进度输出（2026-11 落地）：首条在第 1 张即打印（小批量也有反馈），之后按
  自适应间隔（约总量 5%，夹在 10–100 之间）+ 末条；每行含
  `[done/total] 百分比 已用 剩余ETA 当前文件`。聚类/relabel 同规则。
- 已知边界：`--force` 会先清后插该范围内的 `face_embeddings`（cluster_id
  随之丢失），重新聚类可能分配**新的簇 ID**；已命名的旧簇会变孤儿
  （`face_clusters` 行保留但无 face 指向）。无命名时无实际损失；簇 ID 稳定
  回填留待 Phase 4。
- `tag gc`（2026-11 落地）：删除孤儿 `face_clusters` 行；默认保护已命名簇，
  `--include-named` 才一并删；人物页簇列表本身也用 inner join 过滤孤儿，
  不显示空项。每次执行写 `tag_gc` 审计事件。

### 3.3 人脸聚类时机

- **单张打标时**：只提取人脸向量，不立刻聚类（`cluster_id = NULL`）
- **打完一个图库后**：自动触发该图库的聚类（该库所有未分配的人脸向量算一遍）
- **`myphoto tag cluster`**：全库重新聚类（模型升级/调阈值时用）
- 聚类算法：贪心 cosine > 0.45（原型已验证），簇大小 < 3 的标 `low_confidence`

## 4. UI 升级

### 4.1 图库/文件夹内标签筛选（分面下钻，2026-11 落地）

**位置**：`BrowseView.vue` 顶部筛选栏的"场景"下拉。

- 一级分类下拉（9 项 + "全部"），选项来自按**当前文件夹范围**统计的
  `/api/tags/stats`；选一级后二级联动下拉
- 筛选状态写在 **URL query**（`?scene_major=...&scene_minor=...`）：刷新、
  分享链接可保留；灯箱/面包屑/文件夹卡片导航均透传 query
- 同时过滤**图片与文件夹**（分面下钻）：
  - 图片：`/api/images?scene_major=...&scene_minor=...`
  - 文件夹：`/api/folders` 同参数，后端统计每个直接子文件夹**整棵子树**
    的匹配数（`matching_count`），只返回 >0 的子文件夹
- 同 root 内下钻/上跳**不重置筛选**（子层分类是父层的真子集，父层必然包含）；
  跨 root/图库导航的链接不带 scene query，自动回到无筛选态
- 空状态区分两种：本文件夹无匹配但有子文件夹（提示可下钻）；
  图片+子文件夹都无匹配（提供"清除场景筛选"按钮，工具栏在筛选态下不隐藏）
- 文件夹卡片计数在筛选态显示 `matching_count（匹配）`

### 4.2 搜索增强（未实现）

现有搜索：关键字（文件名）。2026-11 落地场景 + 日期筛选：

```
/api/search?q=关键字&scene_major=...&scene_minor=...&date_from=...&date_to=...
```

**参数与语义（落地版，不含 person_cluster，人物浏览由 /people 页承担）：**

- `q` 改为**可选**：空关键词 + 有其它筛选条件 = 纯筛选搜索（返回全部满足
  scene/date 的图片）；空关键词且无任何筛选 = 返回空结果，不做全量倾倒
- `scene_major` / `scene_minor`：与 `/images` 列表同一套等值过滤
- `date_from` / `date_to`：Unix 秒（含边界），基于 `taken_at`；启用日期筛选时
  `taken_at IS NULL` 的图片自然被排除；`from > to` 返回 400
- 文件夹命中区块（文件夹名 LIKE）**仅在 q 非空时**返回；纯筛选只出图片
- keyset 分页（filename,id）不变，新增 WHERE 条件只缩小结果集，cursor 兼容
- 前端筛选状态全部进 URL query；日期在 URL 里存 `YYYY-MM-DD`（可读、可分享），
  调用 API 时按本地时区转当天 00:00:00 / 23:59:59 的 epoch 秒
- 搜索态复用 BrowseView 的 SceneFilter（按当前搜索范围统计可选分类），
  日期用两个原生 `<input type="date">`；搜索结果的文件夹/查看原图链接同样
  透传筛选 query，下钻后筛选不丢
- 原规划的 `person_cluster` 参数暂不实现
- 同一套 scene/date 参数在 `/images` 与 `/folders` 同样生效：无关键词的
  纯筛选走普通浏览视图（/images 过滤图片、/folders 按子树匹配数过滤文件夹），
  有关键词走 /search；两条路径的筛选状态共用同一组 URL query

### 4.3 概览页标签统计

**位置**：`AdminOverview.vue` 或图库概览页。

新增"标签分布"区块：

```
一级分类（9 项）
  自然风光  ████████ 1234 张
  城市建筑  ██████ 980 张
  人物      ████ 560 张
  ...

二级分类（点击一级展开）
  自然风光
    海滩海岸  320
    山景      280
    湖泊      200
    ...
```

统计基于 `images.scene_major / scene_minor`，SQL 聚合秒出。

### 4.4 顶栏新增"人物"入口

**新页面**：`PersonClusterView.vue`

```
顶栏 [首页] [图库] [人物] [管理]

人物页布局：
  左侧：人物簇列表（按照片数排序）
    [P001 张三]  (156 张)
    [P002 李四]  (89 张)
    [P003 未命名] (45 张)
    ...

  右侧：选中簇的照片网格
    按年/月分组：
      2025年
        1月  [缩略图] [缩略图] ...
        3月  [缩略图] ...
      2024年
        ...
    每张图标注：
      - 所在图库（小标签）
      - 所在文件夹路径（更小的标签，如 "旅行-OLD/成都"）
```

**交互**：
- 点击簇 → 弹出重命名框
- 拖拽两张脸到一起 → 合并簇（后续做，V1 不做）
- 照片点击 → 跳转到原图浏览页（带上当前图库上下文）

## 5. 后端 API 新增

```
GET  /api/tags/stats                     # 标签分布统计（概览页用）
GET  /api/tags/clusters                  # 人物簇列表（带照片数）
GET  /api/tags/clusters/{cid}/images     # 某簇下的照片（按年/月分组）
PUT  /api/tags/clusters/{cid}            # 重命名
POST /api/tags/relabel                   # 基于新提示词重算标签（管理员）
```

## 6. 图像输入策略

### 6.1 缩略图不是现成的，打标也不依赖/不生成它

项目的缩略图（`ALLOWED_SIZES = {200, 400, 1600}`）是**按需生成**——只有用户预览
时才经 `ThumbnailGenerator.ensure()` 渲染并缓存（入口仅 `routes_media` 与
`routes_trash`）。打标**既不读缩略图缓存，也不写**：scanner、tagger、
tagging_jobs 全程不调用 ThumbnailGenerator。

### 6.2 打标流程（同步，全尺寸原图 + 内存内各模型自行降采样）

> 2026-11 落地实现，已取代初稿的"400px 中间层"方案。
>
> **2026-11 解码统一更新**：像素解码收敛到 `myphoto/imaging.py` 的
> `load_pil_image(path, is_raw)`，缩略图生成与打标共用同一入口——RAW
> （.orf/.cr2/.nef 等）走 rawpy（内嵌 JPEG 预览优先、demosaic 兜底），
> 普通图走 Pillow 并统一做 EXIF Orientation 转正与 RGB 转换，HEIF opener
> 全项目只注册一次。此前打标对 RAW 必失败（写 tag_error）且不做转正，
> 均已修复；转正对存量标签的影响需 `myphoto tag run --force` 重打才生效。

```
对每张图打标时（PIL 打开原图，全分辨率，仅在内存）：
  1. 同一张全尺寸 RGB 图喂 CLIP（CLIPProcessor 内部 resize 到 224×224）→ 场景分类
  2. 同一张全尺寸图喂 YOLO（letterbox 到 640×640）→ 人数检测
  3. YOLO 检测到人脸 → SCRFD 在全尺寸图上检测（640×640 输入）
     → 按原图坐标裁脸、5 点对齐到 112×112 → InsightFace 出 embedding
```

**设计要点（实际实现）**：
- 原图只解码 1 次，三个模型共享这张内存中的全尺寸图，各自内部降采样
- **不经过 400px 中间尺寸**，也不写缩略图缓存——避免冗余 resize，且对小脸/
  远处人物检测更有利
- 各模型固定输入：CLIP 224×224、YOLO/SCRFD 640×640、识别对齐脸 112×112
- 人脸 bbox 与裁脸都在**原图坐标系**，聚类质量不受缩略图尺寸影响
- 实测（i5-11320H + Iris Xe，OpenVINO GPU）：全尺寸解码 ~80ms；纯推理
  CLIP ~110ms + YOLO ~50ms + 人脸 ~110ms ≈ 270ms；全量 2923 张平均稳态
  **~350ms/张**（含解码与 IO），万张约 1 小时
- 磁盘 IO：每张图只顺序读原图，**无额外缩略图写盘**

### 6.3 为什么放弃 400px 中间层（相对初稿的变更）

- 初稿想用 400px（项目已有缩略图尺寸）做统一输入并顺便写缓存；落地时发现
  CLIP 本就要降到 224、YOLO 要 letterbox 到 640，400 是多余的一道缩放
- 缩略图写盘会把"按需缓存"耦合进扫描/打标流程，增加写 IO 与失败面
- 全尺寸输入对 YOLO 小脸（合照）与 SCRFD 人脸检测召回更好
- 全尺寸解码 ~80ms，相对 ~270ms 推理可忽略，没有性能动机去缩小输入

## 7. 模型与依赖

### 6.1 运行时依赖（加入 `pyproject.toml`）

```
onnxruntime>=1.31
openvino==2024.6.0          # 锁版本，2026.x API 不兼容
insightface>=2.1
opencv-python>=4.8
```

**注意**：不装 `optimum`（会升级 openvino 破坏环境）。

### 6.2 模型文件位置

```
backend/models/
  yolo11n.onnx              # 10MB
  clip-vit-base-patch32/    # PyTorch 权重 605MB（开发期）
  clip-ov/                  # OpenVINO IR（visual.xml + text.xml，280MB）
  insightface/
    det_500m.onnx           # 2.5MB
    w600k_mbf.onnx          # 13.6MB
```

模型文件**不进 git**（`.gitignore` 加 `backend/models/`），部署时手动拷贝或提供下载脚本。

### 6.3 双机适配

- 这台 i5：OpenVINO + Iris Xe GPU
- 3060 那台：onnxruntime-gpu

运行时探测：

```python
def get_inference_backend():
    if cuda_available():
        return "onnxruntime-cuda"
    if openvino_gpu_available():
        return "openvino-gpu"
    return "openvino-cpu"
```

> **2026-11 实现状态**：已落地为 `[tagging].device = auto|cpu|cuda`
> 两套加载计划——cuda 计划四个模型全走 ONNX Runtime GPU（CLIP visual
> 需额外的 `clip-onnx/visual.onnx`，由 `scripts/export_clip_onnx.py`
> 导出），openvino 计划即本节原路径；详见
> `docs/superpowers/specs/2026-11-15-tagger-cuda-execution-provider-design.md`。

## 7. 实施阶段

### Phase 1：DB 迁移 + 打标管线（后端）✅ 已完成（2026-11）

- [x] 写 migration SQL（§2.1–2.2；走 db.py `_COLUMN_MIGRATIONS` 幂等升级）
- [x] 实现 `Tagger` 类（封装 YOLO + CLIP + InsightFace，懒加载、线程安全）
- [x] 实现 CLI `tag status / run / cluster / relabel`（§3.2）
- [x] scanner 接入同步打标挂钩（仅新增/变化文件，未变文件不碰模型，§3.1）

### Phase 2：标签筛选 UI（部分完成）

- [x] BrowseView 加场景筛选下拉（§4.1；按当前文件夹范围统计）
- [ ] 搜索 API 加 scene / date 参数（§4.2；**未做**，目前 scene 筛选只接在
  `/images` 列表，未接入 `/search`，date 参数也未做）
- [x] 概览页标签统计（§4.3，TagStatsPanel）

### Phase 3：人物页 ✅ 已完成（2026-11）

- [x] 顶栏加"人物"入口（§4.4）
- [x] PersonClusterView 页面（簇列表 + 人脸缩略图 + 照片网格 + 按年月分组）
- [x] 重命名交互（PUT /api/tags/clusters/{cid}）

### Phase 4：调优（可选）

- [ ] 提示词再调（基于真实使用反馈）
- [ ] 人脸簇合并/拆分 UI
- [ ] 以图搜图（基于 image_embeddings）

## 8. 边角情况处理（设计评审补充）

### 8.1 照片内容更新时标签失效

用户在 PS 里改图覆盖原文件，scanner 检测到 hash 变了。

- 存 `tagged_sha1` 字段，打标完成时记录当前 sha1
- 扫描时如果 `images.sha1 != tagged_sha1` → 强制重打标

```sql
ALTER TABLE images ADD COLUMN tagged_sha1 TEXT;
```

### 8.2 回收站/删除联动

- 软删除（进 trash）：向量和标签**保留**，恢复后不用重打
- 硬删除（purge_after 过期）：级联清 `image_embeddings` / `face_embeddings`
- 外键 `ON DELETE CASCADE` 已覆盖硬删除

### 8.3 人脸簇 ID 稳定性（关键）

用户把 P001 命名"张三"，下次全量重聚类不能把命名丢了。

- 增量聚类：新脸和已有簇相似度 > 0.5 → 归入已有簇，**不创建新 ID**
- 只有完全找不到匹配的才分配新 ID（P051、P052...）
- 合并操作必须用户显式触发（UI 拖拽），不能自动合并
- 簇大小 < 3 的标 `low_confidence`，前端可过滤

### 8.4 打标失败重试

- 新增 `tag_error TEXT` 字段：NULL = 成功，非空 = 失败原因
- 失败的图不再自动重试（避免 corrupt 图死循环）
- UI 显示"N 张打标失败"，用户可手动触发重试

### 8.5 资源配置开关

`config.toml` 新增（落地字段；`backend` 初稿设想未实现，设备由 Tagger 自动
探测 GPU→CPU）：

```toml
[tagging]
enabled = true              # 总开关；false 时 scanner/CLI 都不打标
models_dir = "backend/models"   # 相对路径相对 config.toml 所在目录解析
scan_on_import = true       # 扫描时对新增/变化图片【同步】打标（未变文件不碰）
```

### 8.6 隐私提示

- `face_embeddings` 是生物特征数据，**不要把 app.db 上传到任何地方**
- V1 不做加密（SQLite 透明加密太重），README 明确提示
- 备份策略：提醒用户 app.db 包含人脸向量

### 8.7 EXIF 无日期的照片

- 老照片/网图没有 `taken_at`
- 人物页按年/月分组时，归到"未知日期"分组，不丢图

## 9. 风险与权衡

| 风险 | 缓解 |
| --- | --- |
| 打标拖慢扫描 | 同步串行但只处理新增/变化文件；未变文件不碰模型；单张失败写 `tag_error` 不中断 |
| 全量打标耗时（实测 2923 张 17 分钟，万张约 1 小时） | 按图库/文件夹逐个跑（CLI 支持 `--gallery`/`--folder`），用户可控、断点续跑 |
| CLIP 二级准确率 83% | 二级作辅助标签，前端淡化显示 |
| 人脸聚类把相似的人混了 | UI 可重命名；合并/拆分留 Phase 4，V1 不做自动纠错 |
| 模型文件 ~900MB 部署麻烦 | 不进 git（`.gitignore` 排除 `backend/models/`、`prototypes/`），手动拷贝 |
| 无 GPU / 3060 机器没 OpenVINO | Tagger 自动探测 GPU→CPU fallback；onnxruntime 作为人脸识别后端 |
| 照片被修改后旧标签残留 | `tagged_sha1` 联动校验，hash 变了强制重打 |
| 人脸簇重聚类丢失用户命名 | 增量聚类优先复用已有簇 ID，不自动合并 |
