# 智能标签系统升级设计

> 状态：设计稿，待评审
> 原型验证：`prototypes/classify_pipeline/`（YOLO + CLIP + InsightFace 三管线已跑通）
> 性能基线（i5-11320H + Iris Xe，OpenVINO GPU）：合并管线 ~150ms/张，万张全量 ~25 分钟

## 1. 目标

为相册增加两个维度的自动标签：

- **场景标签**（CLIP 零样本分类，9 大类 ~45 小类）
- **人物标签**（YOLO 检测人数 + InsightFace 人脸聚类）

支持按标签筛选、按人物聚类浏览，不影响现有扫描速度（增量打标异步）。

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

升级后（**同步串行，单线程**）：

```
扫描目录 → hash → EXIF → 解码原图 → 生成 400px 缩略图（顺便存缓存）
       → 用内存中的 400px 图跑 CLIP + YOLO
       → 如果有人脸 → 从内存中的原图裁脸跑 InsightFace
       → 写 images 行 + 标签 + 向量
```

**为什么同步而不是异步**（针对机械硬盘场景）：

- 机械硬盘单线程随机读 ~100 IOPS，并行解码 N 张会导致磁盘寻址抖动
- 异步打标 = 原图读 2 次（扫描时 hash/EXIF 一次，打标时解码一次）
- 同步打标 = 原图只读 1 次，内存中同时持有原图和 400px 版本
- 虽然 CPU 推理（~150ms/张）拖慢扫描，但总 IO 最优，机械硬盘上反而更快

**配置开关**：

```toml
[scanner]
tag_during_scan = "auto"   # auto / always / never
# auto: 机械硬盘同步打标；SSD 可异步（但当前 V1 统一同步）
```

**设计要点**：

- 原图只解码 1 次，内存中复用
- 400px 缩略图顺便生成，用户预览时直接命中缓存
- 打标失败不阻塞扫描：catch 异常，写 `tag_error`，继续下一张
- 模型常驻内存（OpenVINO 编译一次，整个扫描过程复用）

### 3.2 存量打标（CLI 命令）

新增 CLI 命令（`cli.py`）：

```bash
# 列出所有图库及其打标状态
myphoto tag status

# 给指定图库打标（可重复执行，已打标的跳过）
myphoto tag run --gallery "我的照片"

# 给指定图库下某个文件夹打标
myphoto tag run --gallery "我的照片" --folder "旅行-OLD/成都"

# 强制重打（模型升级时用）
myphoto tag run --gallery "我的照片" --force

# 打标完成后重新聚簇
myphoto tag cluster

# 调整提示词后，基于已有向量秒级重算标签（不跑模型）
myphoto tag relabel --promptset v3
```

**设计要点**：
- 按图库逐个跑，用户验证完一个再跑下一个（需求 2）
- 断点续跑：`tagged_at IS NULL` 的才跑
- 进度输出：每 100 张打印一次进度 + 预计剩余时间

### 3.3 人脸聚类时机

- **单张打标时**：只提取人脸向量，不立刻聚类（`cluster_id = NULL`）
- **打完一个图库后**：自动触发该图库的聚类（该库所有未分配的人脸向量算一遍）
- **`myphoto tag cluster`**：全库重新聚类（模型升级/调阈值时用）
- 聚类算法：贪心 cosine > 0.45（原型已验证），簇大小 < 3 的标 `low_confidence`

## 4. UI 升级

### 4.1 图库/文件夹内标签筛选

**位置**：`BrowseView.vue` 顶部筛选栏，新增"场景"下拉。

- 一级分类下拉（9 项 + "全部"）
- 选一级后，二级分类联动下拉（动态加载该一级下的二级列表）
- 筛选条件传给 `/api/images?scene_major=自然风光&scene_minor=海滩海岸`

### 4.2 搜索增强

现有搜索：关键字（文件名）。

升级后：

```
/api/search?q=关键字&scene_major=...&scene_minor=...&person_cluster=P001&date_from=...&date_to=...
```

- 范围逻辑不变（仍按当前图库/文件夹）
- 日期范围基于 `taken_at`（已有 EXIF 字段）

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

### 6.1 缩略图不是现成的

项目的缩略图（200/400/1600px）是**按需生成**——只有用户预览时才会渲染并缓存。打标不能依赖"缩略图已存在"。

### 6.2 打标流程（同步，内存复用）

```
对每张图打标时（scanner 已把原图解码到内存）：
  1. 从内存中的原图 resize 到 400px → 存缩略图缓存（顺便）
  2. 用 400px 图跑 CLIP（场景分类）+ YOLO（人数检测）
  3. 如果 YOLO 检测到人脸 → 从内存中的原图裁脸区域 → 跑 InsightFace
```

**设计要点**：
- 原图只解码 1 次（scanner 读 hash/EXIF 时已解码），内存复用
- 400px 缩略图顺便生成，用户预览时直接命中缓存
- CLIP 强制 224×224 输入，400→224 resize 质量足够
- InsightFace 需要 112×112 对齐脸，从原图裁脸（不是从 400px 缩略图）
- 平均耗时：风景照（80%）~110ms CPU，有人脸的（20%）~410ms CPU，加权 **~170ms/张**
- 磁盘 IO：每张图只 1 次顺序读（原图）+ 1 次顺序写（400px 缓存）

### 6.3 为什么用 400px 而不是 224px

- 400px 是项目已有尺寸（`ALLOWED_SIZES = {200, 400, 1600}`），复用缓存路径
- 200px 太小，YOLO 检测小脸（合照）会漏
- 1600px 解码慢，没必要

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

## 7. 实施阶段

### Phase 1：DB 迁移 + 打标管线（后端）

- [ ] 写 migration SQL（§2.1–2.2）
- [ ] 实现 `Tagger` 类（封装 YOLO + CLIP + InsightFace）
- [ ] 实现 CLI `tag status / run / cluster / relabel`（§3.2）
- [ ] scanner 接入异步打标队列（§3.1）

### Phase 2：标签筛选 UI

- [ ] BrowseView 加场景筛选下拉（§4.1）
- [ ] 搜索 API 加 scene / date 参数（§4.2）
- [ ] 概览页标签统计（§4.3）

### Phase 3：人物页

- [ ] 顶栏加"人物"入口（§4.4）
- [ ] PersonClusterView 页面（簇列表 + 照片网格 + 按年月分组）
- [ ] 重命名交互

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

`config.toml` 新增：

```toml
[tagging]
enabled = true              # 总开关
backend = "auto"            # auto / openvino-gpu / openvino-cpu / onnxruntime-cpu
models_dir = "backend/models"
scan_on_import = true       # 扫描时是否异步打标
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
|---|---|
| 打标拖慢扫描 | 异步队列，不阻塞 |
| 万张全量 25 分钟 | 按图库逐个跑，用户可控 |
| CLIP 二级准确率 83% | 二级作辅助标签，前端淡化显示 |
| 人脸聚类把相似的人混了 | UI 可重命名/合并，V1 先不做自动纠错 |
| 模型文件 300MB 部署麻烦 | 不进 git，提供 `scripts/download_models.ps1` |
| 3060 机器没 OpenVINO | 运行时探测后端，fallback 到 onnxruntime-gpu |
| 照片被修改后旧标签残留 | `tagged_sha1` 联动校验，hash 变了强制重打 |
| 人脸簇重聚类丢失用户命名 | 增量聚类优先复用已有簇 ID，不自动合并 |
