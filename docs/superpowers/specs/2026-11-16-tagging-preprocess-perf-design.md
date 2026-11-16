# 打标预处理性能优化设计（2026-11-16）

## 1. 背景与动机

单张打标计时原型（`prototypes/classify_pipeline/bench_single_image_timing.py` 等，
结果见 `single_image_timing_results.txt`）表明：i5-11320H + Iris Xe、openvino 计划下，
模型推理本身只占 13–19ms，瓶颈全部是全分辨率图上的 CPU 图像处理。20MP JPG 单张
总计约 929ms，其中 CLIPProcessor 全图预处理 296ms、SCRFD 前的全分辨率 BGR/numpy
转换约 277ms、YOLO letterbox 89ms、解码 197ms。

两个已验证的低风险优化点：

1. **CLIP 代码预降采样（方式 B）**：先用 PIL bicubic 把最短边缩到 224 再交给
   CLIPProcessor，避开慢处理器内部"全图 PIL→numpy→numpy→PIL→resize"的两次全分辨率
   数组转换。实测 JPG 段 365→193ms（−47%）、ORF 160→89ms（−44%），两路输出向量
   cosine 0.9984/0.9992，样本分类标签完全一致。
2. **JPEG DCT 降分辨率解码**：Pillow `Image.draft()` 走 libjpeg-turbo 的 DCT 缩放
   （本机 Pillow 12.3 已链接 libjpeg-turbo 3.1.4）。DCT 1/4 解码 + bicubic→224
   端到端 130ms，对比全分辨率路径 297ms。

### 非目标（本次明确不做）

- CLIP/YOLO/SCRFD 共享一份降采样中间图的 tagger 核心重构；
- OpenVINO PrePostProcessor / ONNX bake resize 等设备端预处理
  （实测 RESIZE_LINEAR 拉伸与 CLIP 等比裁剪语义不同，向量 cosine 仅 0.89/0.93）；
- GPU 解码（nvjpeg / DALI / cv2.cuda）；
- simplejpeg / PyTurboJPEG 等新依赖引入（与 Pillow 同为 libjpeg-turbo 引擎，
  边际收益仅在直出 numpy，且 JPEG-only 需维护双路径）。

## 2. 关键决策（已与用户确认）

| 决策点 | 结论 |
|---|---|
| 优化范围 | 仅方式 B + JPEG DCT 解码，不碰模型图与双计划架构 |
| 代码组织 | 预处理策略下沉 imaging 层，tagger 只调用（方案 2） |
| DCT 策略 | 保守档：仅 JPEG、最短边 >1600px 才启用、只做 1/2 一档 |
| 存量迁移 | bump `TAG_MODEL_VERSION`，不改待打标查询语义；手动 `tag run --force` 可选重打 |
| 实施节奏 | P1（方式 B）、P2（DCT 解码）分阶段，各自独立验证/回滚 |
| 配置开关 | 不加 config flag，验证通过即唯一路径；回滚靠 revert |

## 3. 组件设计

### 3.1 `imaging/preprocess.py`（新建）

纯函数策略模块，不依赖任何模型，可直接单测：

```python
CLIP_SHORTEST_EDGE = 224     # 与 clip-vit-base-patch32/preprocessor_config.json 一致
TAG_DECODE_FLOOR = 1600      # 打标解码最短边地板（px）

def resize_shortest_edge(img: PILImage.Image, size: int,
                         resample=PILImage.BICUBIC) -> PILImage.Image:
    """等比缩放使最短边 = size，长宽取整规则与 CLIPProcessor 内部一致。"""
```

### 3.2 `imaging/decode.py`：`load_pil_image` 增加可选参数

```python
def load_pil_image(source, is_raw, target_shortest_edge: int | None = None):
```

- `None`（默认）：现状行为，缩略图路径零影响；
- 传整数且为 **JPEG**、解码后最短边大于该值：`Image.draft("RGB", (w//2, h//2))`
  做单次 DCT 1/2 解码（libjpeg 仅支持 1/2、1/4、1/8 幂次档，本设计只用 1/2）；
- HEIF / PNG / 其他 web 格式：`draft` 无 DCT 能力，格式守卫静默回退全分辨率；
- RAW：rawpy 内嵌预览/demosaic 路径不变（预览通常已 ≤8MP，无需再降）；
- EXIF Orientation 转正、RGB 转换仍在解码后统一执行，位置不变。

### 3.3 `services/tagger.py`

- `_clip_scene()`：调用 `resize_shortest_edge(rgb, CLIP_SHORTEST_EDGE)` 后再传给
  `CLIPProcessor`；Processor 的 center-crop / rescale / normalize 配置全部保留，
  其内部 resize 此时对 224→224 近空操作（实测 4ms）；
- `TAG_MODEL_VERSION` bump 为 `"clip-v3-predownscale"`（`CLIP_MODEL_VERSION` 不动，
  权重未变）；
- YOLO letterbox、SCRFD、ArcFace 代码不动，只接受上游解码出的（可能已降采样的）图。

### 3.4 `services/tagging_jobs.py`

第 134 行附近的解码调用改为：

```python
with load_pil_image(path, is_raw=..., target_shortest_edge=TAG_DECODE_FLOOR) as im:
```

常量从 `imaging.preprocess` 导入；scanner 的元数据读取（`_process_file`）不经过
`load_pil_image`，行为不变。

## 4. 数据流

```
旧: read → 全分辨率解码
        → CLIPProcessor(全图) → 视觉塔
        → letterbox(全图) → YOLO
        → BGR contiguous(全图) → SCRFD
新: read → DCT 1/2 解码（仅 JPEG 且最短边>1600，其余照旧）
        → resize224 → CLIPProcessor(近空操作) → 视觉塔（13ms 不变）
        → letterbox(小图) → YOLO
        → BGR contiguous(小图) → SCRFD
```

两个计划（openvino / cuda）的推理代码均不改动，优化对两者同享。

## 5. 验证策略

仓库无持久化 ground-truth 标注，沿用原型期 contact sheet 方法论，分三层验证。

### 5.1 单元测试（进 git，CI 可跑）

- `resize_shortest_edge`：输出尺寸、长宽比、插值类型、最短边恰好等于目标；
- `load_pil_image` 新参数：小图不触发 DCT、非 JPEG 静默回退、RAW 路径不变、
  EXIF 转正仍生效、默认参数输出与现状逐像素一致；
- tagger 侧用 fake/小模型夹具验证喂给 Processor 的图最短边为 224、输出形状不变。

### 5.2 全库一致性脚本（prototypes/，不进 git，同既有评测工具）

刷新 `eval_hierarchy.py` 等原型脚本的重组后失效导入（`myphoto.*` 新路径、模型目录
指向 `backend/models/`），新增 A/B 对比脚本，对全库 2924 张分别跑新旧两路径，产出：

1. 场景一级 / 二级标签一致率；
2. 图像向量 cosine 分布（均值、p5、最小）；
3. 人脸数量一致率与检测框 IoU；
4. 全部分歧项的 contact sheet 供人工抽查。

### 5.3 验收硬门槛（任一不过，对应阶段回退）

- 场景一级标签一致率 ≥ 99%；
- 图像向量 cosine 均值 ≥ 0.998；
- 人脸数量一致率 ≥ 99%，且分歧项人工抽查无真实漏检。

### 5.4 性能复测

用 `bench_single_image_timing.py` 同一批样本回归，记录优化前后各阶段中位数。
预估 20MP JPG 单张 929ms → 550–600ms 量级（以实测为准），ORF 约 380→310ms。

## 6. 分阶段实施与迁移

- **P1：方式 B**。改动仅 CLIP 分支（preprocess.py + tagger `_clip_scene`），
  人脸零风险，收益已占大头。过 5.1/5.2/5.3 中与 CLIP 相关项后合入。
- **P2：DCT 解码**。decode.py 参数 + tagging_jobs 接线，必须额外通过人脸专项
  回归（门槛第 3 条）后合入。
- 版本戳在 P1 即 bump；待打标查询语义不变，升级不会触发自动重打。
- README 升级说明写明：库内向量几何会有 cosine 0.998 级别的细微差异，如需库内
  完全一致，择机执行一次 `myphoto tag run --force`（优化后本机预计 20 分钟级）；
  不重打不影响任何功能，`relabel` 对存量旧向量仍有效。

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| DCT 降分辨率导致远景小脸召回下降 | 1600px 地板 + 仅 1/2 档 + 人脸数量/IoU 全库回归 + 人工抽查；不过门槛则 P2 整体回退，P1 不受影响 |
| 预降采样的边界样本标签翻转 | 全库标签一致率门槛 + contact sheet 抽查；版本戳区分新旧向量 |
| `draft()` 与 EXIF orientation 交互异常 | 单测覆盖带 Orientation 标记的 JPEG |
| pillow-heif 等插件对 draft 行为差异 | 显式格式守卫，非 JPEG 一律回退全分辨率 |
| 原型评测脚本不进 git、他人无法复现 | 单测承载可自动化部分；全库脚本路径与用法在本 spec 与 results.txt 中留痕 |
