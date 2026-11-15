# 打标器 CUDA 执行后端 — 设计文档

日期：2026-11-15
状态：待实现
前置：[tags-upgrade-design.md](../../tags-upgrade-design.md)（智能标签 Phase 1–3 已落地）

## 1. 背景与动机

当前打标器（`backend/src/myphoto/tagger.py`）的执行后端：

- CLIP visual / text、YOLO11n：OpenVINO 编译运行，设备自动探测 Intel
  GPU → CPU（pip 版 openvino 只带 Intel 设备插件）
- SCRFD 人脸检测、ArcFace 人脸识别：onnxruntime 会话，**硬编码
  `CPUExecutionProvider`**；SCRFD 还通过 `prepare(ctx_id=-1)` 被
  InsightFace 2.1 内部强制 `set_providers(['CPUExecutionProvider'])`

因此在只有 NVIDIA 显卡的主机（如 RTX 3060、无 Intel 核显）上，四个模型
全部跑 CPU，显卡完全闲置。设计文档 §7.3 曾规划"3060 那台用
onnxruntime-gpu"，从未实现，本设计补齐该规划。

### 实测基线（2026-11-15，i5-11320H，512px 样本图，暖缓存，5 次均值）

| 环节 | 耗时 |
| --- | --- |
| SCRFD 检测（输入固定 640×640，与原图分辨率基本无关） | 14–17ms |
| ArcFace 对齐 + embedding（每张脸） | ~8.2ms |
| 单脸照片人脸段合计 | ~23ms，每多一张脸 +8ms |
| 完整 `tag()`（小图暖缓存） | 无脸 ~48ms / 单脸 ~74ms |

全分辨率 + 磁盘 IO 的生产稳态沿用既有数据：~350ms/张（2923 张 17 分钟）。

### 两个关键事实（已核实）

1. **三个 ONNX 模型天然可换 provider**：YOLO11n、SCRFD、ArcFace 都是
   标准 ONNX，ORT 换 `CUDAExecutionProvider` 即可，前后处理代码不变。
2. **CLIP 是格式缺口**：部署的是 OpenVINO IR（`clip-ov/*.xml`），ORT
   无法读取；OpenVINO 也没有可用的 NVIDIA 生产路线。需要把 visual 塔
   额外导出一份 ONNX。text 塔只在加载时预计算一次提示词向量，不进
   单张热路径，保持 OpenVINO CPU 不动。

## 2. 目标 / 非目标

### 目标

- `[tagging] device = "auto" | "cpu" | "cuda"` 三档配置，默认 auto
- auto：ORT 探测到 `CUDAExecutionProvider` 时四个模型全走 ORT CUDA
  （带 CPU 回退）；否则维持现有 OpenVINO 路径，Intel 主机行为零变化
- 显式 `device = "cuda"` 但环境不具备时**硬报错**（不静默回退）
- 提供入 git 的 CLIP visual ONNX 导出脚本；本机完成导出与双路径
  等价性验证
- 无 N 卡环境下可做功能级验证（ORT CPU provider 加载同一会话代码路径）

### 非目标（明确不做）

- 不引入 OpenVINO NVIDIA 插件、不做 TensorRT EP
- text 塔不上 GPU（一次性开销）、不做多卡选择
- 不把 torch 加进运行时依赖（仅导出脚本在开发机临时需要）
- 不 bump 模型版本戳、不触发存量重打（同模型换 EP 仅浮点级差异）
- 不改动打标数据模型、聚类算法与任何前端逻辑

## 3. 配置设计

`config.py`：

- `AppConfig` 增加 `tagging_device: str`
- 解析 `[tagging].device`，默认 `"auto"`；非法字符串按项目既有惯例
  （对照 `hash_workers`）打 warning 并回退 `"auto"`，不阻止启动
- 配置模板 `[tagging]` 注释段增加：
  `# device = "auto"   # auto | cpu | cuda（cuda 需 onnxruntime-gpu）`

## 4. 设备决策模块（新文件 `backend/src/myphoto/inference.py`）

纯函数、不加载模型，便于表驱动单测：

```python
class BackendUnavailable(RuntimeError):
    """显式要求的执行后端在当前环境不可用。"""

def select_ort_providers(device: str, available: Sequence[str] | None = None) -> list[str]:
    """
    device: "auto" | "cpu" | "cuda"
    - auto: 有 CUDAExecutionProvider -> ["CUDAExecutionProvider", "CPUExecutionProvider"]
            否则 -> ["CPUExecutionProvider"]
    - cpu:  恒为 ["CPUExecutionProvider"]
    - cuda: 有 CUDA -> ["CUDAExecutionProvider", "CPUExecutionProvider"]
            无 CUDA -> 抛 BackendUnavailable（消息含 onnxruntime-gpu 安装提示）
    available 为 None 时调用 onnxruntime.get_available_providers()
    """

def resolve_backend(device: str) -> str:
    """返回 "cuda" | "cpu"（openvino 计划）；cuda 不可用且显式指定时抛错。"""
```

Tagger 构造时调用 `resolve_backend` 记住计划（`self._backend`），
`_ensure_loaded()` 按计划分支建会话。现有构造参数 `backend: str = "auto"`
语义重定义为 device 三档（当前两个调用点 `main.py`、`cli.py` 均使用
默认值，无外部调用方受影响）；OpenVINO 分支内部的
`_resolve_device()`（Intel GPU/CPU 探测）保持原样。

## 5. Tagger 改造（`tagger.py`）

### 5.1 文件门控 `expected_paths()` / `available()`

- 新增期望文件 `clip-onnx/visual.onnx`
- cuda 计划：要求三个既有 ONNX + `clip-onnx/visual.onnx` +
  tokenizer 目录 + `clip-ov/text.xml`（text 塔两计划共用，始终走
  OpenVINO CPU）；**不要求** `clip-ov/visual.xml`
- cpu/auto(无 CUDA) 计划：与现状一致（`clip-ov` 两个 xml + tokenizer +
  三个 ONNX），不要求 visual.onnx
- ORT providers 在 Tagger 构造时一次性决策并保存（测试可注入
  `available`），加载阶段直接复用，使无 GPU 环境也能走 cuda 计划代码
  路径做功能验证（ORT 对不可用 EP 自动回退 CPU 并告警）
- 门控仍是纯文件检查、不加载模型，`myphoto tag status` 语义不变

### 5.2 各模型会话

| 模型 | cuda 计划 | cpu / auto 无 CUDA（现状保留） |
| --- | --- | --- |
| CLIP visual | 新建 ORT 会话加载 `clip-onnx/visual.onnx`，providers 取决策结果 | OpenVINO 编译 `clip-ov/visual.xml`（不动） |
| CLIP text | 始终 OpenVINO CPU（仅加载时预计算提示词向量一次） | 同左 |
| YOLO11n | ORT 会话加载既有 `yolo11n.onnx`，输入名取会话元数据 | OpenVINO read+compile（不动） |
| SCRFD | 手工建 ORT 会话（带决策 providers）注入 `SCRFD(path, session=...)`，`prepare(ctx_id=0, input_size=(640,640))` | 同构造方式但 providers=CPU，`prepare(ctx_id=-1, ...)`（现状） |
| ArcFace | ORT 会话，providers 取决策结果（替换硬编码 CPU） | CPU provider（现状） |

已核实 InsightFace 2.1 源码依据：

- `SCRFD.prepare` 仅在 `ctx_id < 0` 时调 `set_providers(['CPUExecutionProvider'])`；
  `ctx_id=0` 保留构造会话的 provider
- SCRFD 的静态形状派生会话从主会话复制 providers
  （`scrfd.py` 内 `_session_for_input_size` 路径）
- 2.1 自带 `preload_dlls()` CUDA 库发现与 `get_default_providers()`
  CUDA 优先策略，但本项目显式传 providers，不依赖其默认策略

### 5.3 推理代码分支

- `_clip_scene()`：预处理（CLIPProcessor → numpy）与后处理（L2 归一化、
  与文本向量 matmul、`classify_scene`）完全共用，仅"会话 run"一步按
  计划分 ORT / OpenVINO
- `_count_persons()`：抽出 `_yolo_infer(arr) -> preds`，两后端输出同构
  `(1,84,8400)`；letterbox、COCO person 过滤、NMS、坐标换算零改动
- `_extract_faces()`：不改（SCRFD/ArcFace 对象接口不变）
- warmup 逻辑覆盖新会话，避免首张图付编译开销
- 加载日志逐会话打印 `session.get_providers()` 实际值

### 5.4 版本戳

`TAG_MODEL_VERSION` 等三个版本常量不变。同一权重经不同 EP 推理只有
浮点级差异，无需重打存量数据，`relabel` 语义不受影响。

## 6. CLIP ONNX 导出（补格式缺口）

新脚本 `scripts/export_clip_onnx.py`（入 git；现有原型脚本在
gitignored 的 `prototypes/` 内，3060 主机拉不到）：

- 入参 `--models-dir`，默认 `backend/models`（相对 CWD）
- 从 `<models-dir>/clip-vit-base-patch32` 加载 `CLIPModel`，包装
  `vision_model → visual_projection`（与原型 `export_clip_openvino.py`
  的 VisualWrapper 同款），输入 `pixel_values (1,3,224,224)` float32，
  输出 `(1,512)`
- `torch.onnx.export`，opset 17，batch 维动态轴
- 产物 `<models-dir>/clip-onnx/visual.onnx`（fp32，预计 250–350MB，
  以实际导出为准；不进 git）
- 内置自检：同一 pixel_values 分别走 torch 原模型与 ORT CPU 会话，
  断言 cosine > 0.999
- 脚本头注释写明：导出机需临时 `pip install torch`（CPU wheel 即可），
  运行时仍然零 torch 依赖

实施时在本机（已有 CPU 版 torch 2.15）完成导出，并用样本图做
OpenVINO 路径 vs ORT 路径的端到端比对：embedding cosine > 0.999、
场景分类标签一致。

## 7. 错误处理与调用方

- **`myphoto serve`（`main.py` lifespan）**：构造 Tagger 捕获
  `BackendUnavailable` → error 级醒目日志（含安装提示）+ tagger=None，
  服务正常启动、打标禁用，与"模型文件缺失"同模式
- **CLI `tag run` / `tag relabel`**：`_build_tagger` 失败转
  `ClickException`，区分三种原因：`enabled=false`、模型文件缺失、
  CUDA 不可用（各自独立提示文案）
- **CLI `tag status`**：不抛错，打印 backend 行，例如
  `inference backend: cuda (CUDAExecutionProvider, CPUExecutionProvider)`
  或 `inference backend: cpu (openvino)`；不可用时打印原因
- ORT 会话创建失败（如 CUDA 驱动/cuDNN 运行时缺失，provider 存在但
  会话初始化报错）：错误向上冒泡，复用上述两条调用方路径处理；
  providers 列表中保留 CPU 回退仅能处理算子级回退，不能替代驱动缺失

## 8. 测试策略

真实模型不进 CI 的原则不变，沿用 FakeTagger 体系：

1. `test_inference.py`（新）：`select_ort_providers` / `resolve_backend`
   表驱动——auto/cpu/cuda × 有无 CUDA、显式 cuda 抛错且消息含安装
   提示、返回列表中 CPU 回退位置
2. config 解析：默认 auto、合法三值、非法值回退 auto + warning
3. Tagger 门控：tmp 目录造空文件，cuda 计划缺 visual.onnx 时
   `available()` False、补齐后 True；cpu 计划不要求 onnx 文件；
   全程不触发真实加载
4. 调用方：BackendUnavailable 时 lifespan 得 tagger=None（不抛到
   启动外）；CLI status 打印原因、run/relabel 出 ClickException
5. 现有 729 后端测试 + 348 前端测试保持全绿
6. 双路径等价性验证为本机手动步骤（第 6 节），产物与比对结果写入
   实施记录，不进自动化测试

## 9. 文档与分发变更

- `docs/deployment.md`：新增"CUDA 加速（NVIDIA 显卡）"小节——
  `pip uninstall onnxruntime && pip install onnxruntime-gpu`（两包
  互斥）、CUDA 12.x / cuDNN 9 前置、insightface 2.1 `preload_dlls`
  自动发现、`device = "cuda"` 配置、visual.onnx 放置、`tag status`
  验证、基准脚本用法
- 两份 README：模型目录树增加 `clip-onnx/visual.onnx`；配置表增加
  `[tagging] device` 行；硬件段落更新为"N 卡经 onnxruntime-gpu 可用"
- `tags-upgrade-design.md` §7.3：双机适配标记为已实现并指向本设计
- `THIRD_PARTY_NOTICES.md`：补 onnxruntime-gpu（同 MIT）与
  CUDA/cuDNN 二进制遵循 NVIDIA 许可、本项目不重新分发的说明
- 基准脚本 `prototypes/classify_pipeline/bench_face_timing.py` 增加
  provider 打印，供 3060 主机同机 CPU/CUDA 对比

## 10. 风险与权衡

| 风险 | 缓解 |
| --- | --- |
| 本机无 N 卡，CUDA 路径无法本地实测 | ORT CPU provider 可加载全部新会话代码做功能验证；provider 决策纯函数单测；3060 上用基准脚本实测加速比并回报 |
| onnxruntime 与 onnxruntime-gpu 互斥，误装会冲突 | 部署文档显式 uninstall 步骤；`tag status` 直接暴露实际 provider |
| 不同 EP 浮点差异影响聚类/分类一致性 | 同权重差异在 1e-4 级，远小于聚类阈值 0.45/0.5；版本戳不变、不重打；本机 cosine>0.999 自检兜底 |
| models 目录再增数百 MB（visual.onnx） | 依旧不进 git、手工拷贝；cuda 主机才需要 visual.onnx，Intel 主机门控不要求该文件 |
| SCRFD 派生会话 provider 继承是 2.1 内部行为 | 已读源码确认；实现时在 3060 用日志打印派生会话 providers 复核 |
