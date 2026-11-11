# 标签系统升级 Phase 1 实施计划

>  spec：[docs/tags-upgrade-design.md](../../tags-upgrade-design.md)（设计稿已定稿）
>  原型：`prototypes/classify_pipeline/`（YOLO11n + CLIP ViT-B/32 OpenVINO IR + InsightFace 已跑通）
>  日期：2026-11-11

## 范围（仅 Phase 1：后端 DB + 打标管线 + CLI + scanner 挂钩）

不含 UI（Phase 2/3）、不含 `tag relabel --promptset` 多提示词集（V1 只有一套 HIERARCHY，relabel 即按当前 HIERARCHY 重算）、不含缩略图预生成（按需缓存已足够）、不含模型下载脚本（本机已有模型，部署时手动拷贝）。

## Task 1：DB schema（models.py + db.py）

`images` 加 8 列（全部 nullable，走 `_COLUMN_MIGRATIONS` 幂等升级）：

- `scene_major TEXT` / `scene_minor TEXT` / `scene_conf REAL`
- `person_count INTEGER`
- `tagged_at INTEGER`（NULL = 未打标）
- `tag_model_version TEXT`
- `tagged_sha1 TEXT`（§8.1：hash 变了强制重打）
- `tag_error TEXT`（§8.4：NULL = 成功，非空 = 失败原因）

新表（`Base.metadata.create_all` 自动建，含索引）：

- `image_embeddings(image_id PK/FK CASCADE, embedding BLOB, model_version, created_at)`
- `face_embeddings(id PK, image_id FK CASCADE, face_index, bbox TEXT, embedding BLOB, confidence REAL, cluster_id TEXT NULL, model_version, created_at)` + `idx_face_emb_cluster` / `idx_face_emb_image`
- `face_clusters(cluster_id PK, display_name, sample_face_id, created_at, updated_at)`

**验收**：旧库（无新列）启动自动 ALTER；新库一次建全；重复启动幂等（test_schema_init）。

## Task 2：Tagger 引擎（新文件 `tagger.py`）

纯引擎层，不碰 DB；模型**懒加载**（构造不加载，首次 tag 才加载）：

- `HIERARCHY`：从 `eval_hierarchy.py` 搬入（9 一级 / ~45 二级）
- `Tagger.__init__(models_dir, backend="auto")`：探测 openvino GPU→CPU；`models_ready()` 检查文件存在性
- `tag(pil_image) -> TagResult`：
  - CLIP visual（OpenVINO IR，224×224）→ L2 归一化 512 维图像向量
  - 两级聚合求 top1 一级 + top2 二级（逻辑照搬原型 eval_hierarchy.py）
  - YOLO11n（OpenVINO 直读 ONNX，letterbox 640）→ person 检测数（conf≥0.25，NMS 原型已有）
  - 有人脸 → InsightFace SCRFD det_500m + w600k_mbf 对齐 embedding（onnxruntime CPU）
- 模型版本常量：`CLIP_MODEL_VERSION = "clip-vit-b32-v2"`、`TAG_MODEL_VERSION = "clip-v2-yolo11n-insightface"`
- 依赖可选导入：openvino / onnxruntime / insightface / cv2 / transformers 全部在函数内 import，web 服务无模型时照常启动

**验收**：无模型环境 `models_ready() == False`；提示词聚合逻辑单测（喂假向量验证二级/一级 max 聚合）不依赖模型。

## Task 3：打标作业（新文件 `tagging_jobs.py`）

DB 层异步作业：

- `iter_pending(sm, gallery_id, folder, force)`：`tagged_at IS NULL OR tagged_sha1 != sha1`（+ force）
- `tag_images(sm, tagger, gallery_id, folder, force, progress_cb)`：逐张 PIL 解码 → `tagger.tag()` → 写 images 标签字段 + `image_embeddings` + `face_embeddings`；单张失败 catch → `tag_error`，不中断；每 100 张进度回调
- `cluster_faces(sm)`（§8.3 增量）：遍历 `cluster_id IS NULL` 的人脸向量；与已分配人脸 cosine > **0.5** → 归入其簇（不建新 ID）；否则建新簇 `P{max+1}`；新建 `face_clusters` 行；簇大小 < 3 仅记录不特殊处理（V1 不标 low_confidence，留前端 later）
- `relabel(sm, tagger)`：读全部 `image_embeddings`，按当前 HIERARCHY 文本向量重算 `scene_major/minor/conf`（不跑视觉模型）

**验收**：合成人脸向量单测聚类（两个人 + 陌生人 → 2 簇、ID 复用）；fake tagger 端到端打标 + 失败写 tag_error；relabel 只动 scene 字段不动 person_count。

## Task 4：CLI（cli.py 加 `tag` 组）

- `myphoto tag status [--gallery X]`：每库 total / tagged / pending / failed 计数 + 模型就绪状态
- `myphoto tag run [--gallery X] [--folder Y] [--force]`：打标；结束后自动触发该范围增量聚类
- `myphoto tag cluster`：全库未分配人脸增量聚类
- `myphoto tag relabel`：基于 image_embeddings 重算场景标签
- 模型未就绪 → 友好报错退出（非 traceback）；审计 `tag_run` / `tag_cluster` / `tag_relabel`

**验收**：CliRunner 无模型环境下 `tag status` 正常输出、`tag run` 友好报错；tmp config 端到端 fake-tagger 测试（monkeypatch Tagger）。

## Task 5：scanner 挂钩 + config + main 接线

- `config.py` 加 `[tagging]`：`enabled=true`、`models_dir`（默认 `<project>/backend/models`）、`scan_on_import=true`
  - 安全性：测试用 tmp config → models_dir 不存在 → tagger 不可用 → 扫描行为与今天完全一致
  - 存量不变文件（mtime+size 未变）走 unchanged 分支，**根本不碰 tagger**；只有新变文件同步打标（设计 §3.1 语义）
- `Scanner.__init__(..., tagger=None)`：`_hash_one` 里 changed 文件 meta 读完后，若 tagger 可用则**同线程**（to_thread 内）跑打标，结果挂到 `_ScanRecord.tag`；异常 → `tag_error`，不中断扫描
- `_persist_batch` 把 tag 结果写入 images + embedding 表
- `main.py` lifespan：`enabled && models_ready()` 才构造 Tagger 传给 Scanner；否则 None（web 照常启动）

**验收**：现有 546 后端测试全绿（tagger=None 路径不变）；新增测试：fake tagger 下 changed 图打标落库、unchanged 图不打标、单张打标失败不中断扫描。

## Task 6：模型落地 + 依赖声明

- 拷贝 `prototypes/classify_pipeline/models/` → `backend/models/`（不进 git）
- `.gitignore` 加 `backend/models/`
- `pyproject.toml` dependencies 加：`openvino==2024.6.0`、`onnxruntime>=1.31`、`insightface>=2.1`、`opencv-python>=4.8`、`transformers>=4.40`（venv 已装好，仅声明；不装 optimum）

## 顺序

Task 1 → 2 → 3 → 4 → 5 → 6，每任务带测试；最后全量后端测试 + 真实库 `tag status` 冒烟。
