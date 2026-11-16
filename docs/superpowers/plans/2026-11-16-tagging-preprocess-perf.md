# 打标预处理性能优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消灭打标热路径中全分辨率 CPU 图像处理的浪费：CLIP 改为代码侧预降采样（方式 B），大图 JPEG 启用 DCT 1/2 降分辨率解码，单张打标 CPU 耗时预期下降 35–45%，模型权重与标签体系不变。

**Architecture:** 预处理策略下沉到 `imaging` 层：新建纯函数模块 `imaging/preprocess.py`（无模型依赖、可直接单测），`imaging/decode.py` 的 `load_pil_image` 增加可选的 DCT 降分辨率参数（默认 None = 现状行为，缩略图路径零影响）；`services/tagger.py` 在喂 CLIPProcessor 前先缩到 224，`services/tagging_jobs.py` 接线解码地板。openvino / cuda 两个推理计划的代码均不改动，优化对两者同享。

**Tech Stack:** Python 3.12（要求 >=3.11）、Pillow 12（已链接 libjpeg-turbo 3.1.4）、transformers 4.57 CLIPProcessor、OpenVINO 2024.6.0、pytest 9 / pytest-asyncio。

## Global Constraints

- 不引入任何新依赖（不装 simplejpeg / torch / optimum；openvino 锁 2024.6.0）。
- 常量固定值：`CLIP_SHORTEST_EDGE = 224`、`TAG_DECODE_FLOOR = 1600`；DCT 只做 1/2 一档。
- 版本戳 bump 为 `TAG_MODEL_VERSION = "clip-v3-predownscale"`；`CLIP_MODEL_VERSION`、`FACE_MODEL_VERSION` 不动。
- 不改待打标查询语义（不自动重打存量）；不增加 config 开关。
- 验收硬门槛（任一不过，对应阶段回退）：场景一级标签一致率 ≥ 99%；图像向量 cosine 均值 ≥ 0.998；人脸数量一致率 ≥ 99% 且分歧人工抽查无真实漏检。
- `prototypes/` 被 .gitignore 忽略，其中的基准/评测脚本**不产生 git commit**；可自动化的验证必须进 `backend/tests/`。
- Python 文件统一 LF 行尾、UTF-8；注释风格与周边代码一致（中文说明）。
- 所有命令在仓库根目录 `e:/code/claude/myPhotoGallery` 执行，解释器为 `.venv/Scripts/python.exe`。

## File Structure

| 文件 | 责任 | 阶段 |
|---|---|---|
| `backend/src/myphoto/imaging/preprocess.py` | 新建。预处理常量 + `resize_shortest_edge` 纯函数 | P1 |
| `backend/tests/test_preprocess.py` | 新建。纯函数单测 | P1 |
| `backend/src/myphoto/services/tagger.py` | `_clip_scene` 预降采样；版本戳 bump | P1 |
| `backend/tests/test_tagger_predownscale.py` | 新建。fake 模型验证喂入 Processor 的尺寸 | P1 |
| `prototypes/classify_pipeline/bench_ab_full_library.py` | 新建（不进 git）。全库 A/B 一致性 + 门槛判定 | P1/P2 复用 |
| `backend/src/myphoto/imaging/decode.py` | `load_pil_image` 增加 `target_shortest_edge`，JPEG DCT | P2 |
| `backend/tests/test_imaging.py` | 追加 DCT/守卫/EXIF 交互用例 | P2 |
| `backend/src/myphoto/services/tagging_jobs.py` | `_decode_and_tag` 传入解码地板 | P2 |
| `backend/tests/test_tags.py` | 追加接线参数断言 | P2 |
| `README.zh-CN.md` | "升级"节追加可选 force 重打说明 | P2 |

---

# Phase 1：CLIP 代码侧预降采样（方式 B）

只动 CLIP 分支，人脸管线零影响。完成后收益已占大头（20MP JPG 段 365→193ms）。

### Task 1: 新建 imaging/preprocess.py 纯函数模块（TDD）

**Files:**
- Create: `backend/src/myphoto/imaging/preprocess.py`
- Test: `backend/tests/test_preprocess.py`

**Interfaces:**
- Produces:
  - `CLIP_SHORTEST_EDGE: int = 224`
  - `TAG_DECODE_FLOOR: int = 1600`（P2 才消费，本任务先定义）
  - `resize_shortest_edge(img: PILImage.Image, size: int, resample=PILImage.BICUBIC) -> PILImage.Image`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_preprocess.py`：

```python
"""imaging.preprocess 纯函数：无模型依赖，直接单测。"""

from PIL import Image as PILImage

from myphoto.imaging.preprocess import (
    CLIP_SHORTEST_EDGE,
    TAG_DECODE_FLOOR,
    resize_shortest_edge,
)


def test_constants():
    assert CLIP_SHORTEST_EDGE == 224
    assert TAG_DECODE_FLOOR == 1600


def test_landscape_shortest_edge_becomes_target():
    img = PILImage.new("RGB", (2000, 1000))
    out = resize_shortest_edge(img, 224)
    assert out.size == (448, 224)  # 等比：2000/1000 * 224 = 448


def test_portrait_shortest_edge_becomes_target():
    img = PILImage.new("RGB", (1000, 2000))
    out = resize_shortest_edge(img, 224)
    assert out.size == (224, 448)


def test_already_at_target_returns_same_object():
    img = PILImage.new("RGB", (300, 224))
    assert resize_shortest_edge(img, 224) is img


def test_resample_is_forwarded(monkeypatch):
    img = PILImage.new("RGB", (400, 200))
    seen = {}
    orig = PILImage.Image.resize

    def spy(self, xy, resample=PILImage.BICUBIC):
        seen["resample"] = resample
        return orig(self, xy, resample)

    monkeypatch.setattr(PILImage.Image, "resize", spy)
    resize_shortest_edge(img, 224, resample=PILImage.NEAREST)
    assert seen["resample"] == PILImage.NEAREST


def test_default_resample_is_bicubic(monkeypatch):
    img = PILImage.new("RGB", (400, 200))
    seen = {}
    orig = PILImage.Image.resize

    def spy(self, xy, resample=PILImage.BICUBIC):
        seen["resample"] = resample
        return orig(self, xy, resample)

    monkeypatch.setattr(PILImage.Image, "resize", spy)
    resize_shortest_edge(img, 224)
    assert seen["resample"] == PILImage.BICUBIC
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_preprocess.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'myphoto.imaging.preprocess'`

- [ ] **Step 3: 最小实现**

创建 `backend/src/myphoto/imaging/preprocess.py`：

```python
"""打标图像预处理纯函数：与模型运行时无关，可直接单测。"""

from __future__ import annotations

from PIL import Image as PILImage

# CLIP ViT-B/32 处理器目标 shortest_edge=224
# （见 backend/models/clip-vit-base-patch32/preprocessor_config.json）。
CLIP_SHORTEST_EDGE = 224

# 打标解码最短边地板（px）：仅当原图最短边超过该值才启用 DCT 降分辨率解码。
TAG_DECODE_FLOOR = 1600


def resize_shortest_edge(
    img: PILImage.Image,
    size: int,
    resample=PILImage.BICUBIC,
) -> PILImage.Image:
    """等比缩放使最短边恰好为 size，保持长宽比。

    取整规则与 CLIPProcessor 内部一致：scale = size / min(w, h)，
    新边长 round(w*scale) / round(h*scale)。已是目标尺寸时原样返回，
    避免无意义的像素拷贝。
    """
    w, h = img.size
    if min(w, h) == size:
        return img
    scale = size / min(w, h)
    return img.resize(
        (max(1, round(w * scale)), max(1, round(h * scale))),
        resample,
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_preprocess.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/imaging/preprocess.py backend/tests/test_preprocess.py
git commit -m "feat(imaging): add resize_shortest_edge preprocessing helper"
```

### Task 2: tagger 接线方式 B 并 bump 版本戳（TDD）

**Files:**
- Modify: `backend/src/myphoto/services/tagger.py`（导入区、第 28 行常量、`_clip_scene` 第 398-411 行）
- Test: `backend/tests/test_tagger_predownscale.py`

**Interfaces:**
- Consumes: `resize_shortest_edge`, `CLIP_SHORTEST_EDGE`（Task 1）
- Produces: `TAG_MODEL_VERSION = "clip-v3-predownscale"`；`_clip_scene` 保证喂给 `_clip_proc` 的图最短边为 224

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_tagger_predownscale.py`：

```python
"""_clip_scene 方式 B：进 CLIPProcessor 前先把最短边缩到 224。

不加载真实模型——用 fake processor / visual 搭最小夹具，只验证预处理接线。
"""

import numpy as np
from PIL import Image as PILImage

from myphoto.services.tagger import TAG_MODEL_VERSION, Tagger


def test_clip_scene_feeds_224_shortest_edge(tmp_path):
    # device="cpu" → openvino 计划；构造不触发模型加载（懒加载）
    t = Tagger(tmp_path, device="cpu", available=["CPUExecutionProvider"])
    captured = {}

    class FakeProc:
        def __call__(self, images, return_tensors):
            captured["size"] = images.size
            return {"pixel_values": np.zeros((1, 3, 224, 224), dtype=np.float32)}

    class _Input:
        name = "pixel_values"

    class FakeVisual:
        inputs = [_Input()]

        def __call__(self, feed):
            return {"out": np.ones((1, 512), dtype=np.float32)}

    t._clip_proc = FakeProc()
    t._clip_visual = FakeVisual()
    # 单位行向量，保证 matmul/classify_scene 可跑通
    t._clip_text_emb = np.ones((3, 512), dtype=np.float32) / np.sqrt(512)
    t._flat_prompts = [("a", "b", f"p{i}") for i in range(3)]

    t._clip_scene(PILImage.new("RGB", (2000, 1000)))

    assert captured["size"] == (448, 224)


def test_tag_model_version_bumped_for_preprocessing_change():
    # 预处理几何变化必须体现到版本戳，供库内向量来源追溯
    assert TAG_MODEL_VERSION == "clip-v3-predownscale"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_tagger_predownscale.py -v`
Expected: 2 failed（尺寸断言得到 (2000,1000)；版本戳断言失败）

- [ ] **Step 3: 改 tagger**

`backend/src/myphoto/services/tagger.py` 导入区加（放在现有 myphoto 导入旁）：

```python
from myphoto.imaging.preprocess import CLIP_SHORTEST_EDGE, resize_shortest_edge
```

第 28 行版本戳改为：

```python
TAG_MODEL_VERSION = "clip-v3-predownscale"
```

`_clip_scene` 开头两行改为（先缩再喂 Processor，其余行不动）：

```python
    def _clip_scene(self, rgb: PILImage.Image) -> tuple[str, str, float, np.ndarray]:
        small = resize_shortest_edge(rgb, CLIP_SHORTEST_EDGE)
        x = self._clip_proc(images=small, return_tensors="np")
        pixel_values = x["pixel_values"].astype(np.float32)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_tagger_predownscale.py -v`
Expected: 2 passed

- [ ] **Step 5: 跑相关回归**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_tags.py backend/tests/test_tagger_gating.py backend/tests/test_imaging.py -q`
Expected: 全过（test_tags 全部通过常量引用版本戳，无字面量依赖）

- [ ] **Step 6: 提交**

```bash
git add backend/src/myphoto/services/tagger.py backend/tests/test_tagger_predownscale.py
git commit -m "feat(tagger): pre-downscale to 224 before CLIPProcessor (mode B); bump TAG_MODEL_VERSION"
```

### Task 3: P1 全库 A/B 一致性验证（门槛 1、2）

**Files:**
- Create（gitignored，不提交）: `prototypes/classify_pipeline/bench_ab_full_library.py`

**Interfaces:**
- Consumes: 真实 `Tagger`（`backend/models/`）、`load_pil_image`、`resize_shortest_edge`、`classify_scene`
- Produces: 终端打印门槛判定；分歧 contact sheet `prototypes/classify_pipeline/ab_disagreements_p1.jpg`

- [ ] **Step 1: 修复原型目录里重组后失效的 myphoto 导入**

Run:

```bash
grep -rn "from myphoto\.\(tagger\|imaging\|config\|db\)" prototypes/ --include="*.py"
```

把命中的旧路径（如 `from myphoto.tagger import Tagger`）按新分层改写（`from myphoto.services.tagger import Tagger` 等），随后验证：

Run: `.venv/Scripts/python.exe -m compileall -q prototypes/classify_pipeline`
Expected: 无输出（编译通过）

- [ ] **Step 2: 写全库 A/B 脚本**

创建 `prototypes/classify_pipeline/bench_ab_full_library.py`（完整内容如下；`AB_PHASE=p1` 只跑 CLIP 维度，`p2` 追加 DCT/人脸维度，Task 6 复用同一脚本）：

```python
"""全库 A/B 一致性 + 验收门槛（2026-11，原型脚本不进 git）。

AB_PHASE=p1：同一份解码图，对比 CLIPProcessor 全图（旧）vs 代码预缩 224（新）。
AB_PHASE=p2：再对比完整新旧管线（DCT 解码 + 方式 B），含 SCRFD 人脸数量/IoU。
用法：AB_PHASE=p1 PYTHONIOENCODING=utf-8 python bench_ab_full_library.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image as PILImage, ImageDraw

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend" / "src"))

from myphoto.imaging.decode import load_pil_image  # noqa: E402
from myphoto.imaging.formats import classify  # noqa: E402
from myphoto.imaging.preprocess import TAG_DECODE_FLOOR, resize_shortest_edge  # noqa: E402
from myphoto.services.tagger import Tagger, classify_scene  # noqa: E402

PHASE = os.environ.get("AB_PHASE", "p1")
DB = REPO / "db" / "app.db"
OUT_SHEET = REPO / "prototypes/classify_pipeline" / f"ab_disagreements_{PHASE}.jpg"

tagger = Tagger(REPO / "backend" / "models", device="auto")
tagger._ensure_loaded()
proc = tagger._clip_proc
visual = tagger._clip_visual
visual_in = visual.inputs[0]


def visual_emb(pixel_values: np.ndarray) -> np.ndarray:
    emb = next(iter(visual({visual_in: pixel_values}).values()))
    return emb / np.linalg.norm(emb, axis=-1, keepdims=True)


def label_of(emb: np.ndarray):
    sims = (emb @ tagger._clip_text_emb.T).squeeze(0)
    major, minor, conf = classify_scene(sims, tagger._flat_prompts)
    return major, minor, float(conf)


def iou_norm(a, wa, ha, b, wb, hb) -> float:
    # 两框来自不同分辨率，先归一化到 [0,1]
    an = [a[0] / wa, a[1] / ha, a[2] / wa, a[3] / ha]
    bn = [b[0] / wb, b[1] / hb, b[2] / wb, b[3] / hb]
    x1, y1 = max(an[0], bn[0]), max(an[1], bn[1])
    x2, y2 = min(an[2], bn[2]), min(an[3], bn[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (an[2]-an[0])*(an[3]-an[1]) + (bn[2]-bn[0])*(bn[3]-bn[1]) - inter
    return inter / union if union else 0.0


con = sqlite3.connect(str(DB))
root = con.execute("select absolute_path from gallery_roots limit 1").fetchone()[0]
rows = con.execute("select relative_path from images").fetchall()

n = 0
l1_agree = l2_agree = 0
cosines: list[float] = []
face_agree = 0
face_ious: list[float] = []
disputes: list[tuple] = []
t0 = time.perf_counter()

for (rel,) in rows:
    path = Path(root) / rel
    if not path.exists():
        continue
    is_raw = classify(path.name) == "raw"
    with load_pil_image(path, is_raw=is_raw) as rgb_old:
        # ---- CLIP 维度：同一解码图，两种预处理 ----
        pv_a = proc(images=rgb_old, return_tensors="np")["pixel_values"].astype(np.float32)
        small = resize_shortest_edge(rgb_old, 224)
        pv_b = proc(images=small, return_tensors="np")["pixel_values"].astype(np.float32)
        emb_a, emb_b = visual_emb(pv_a), visual_emb(pv_b)
        cos = float(np.dot(emb_a.reshape(-1), emb_b.reshape(-1)))
        la, lb = label_of(emb_a), label_of(emb_b)

        if PHASE == "p2":
            # ---- 完整管线维度：DCT 解码 + 方式 B，含人脸 ----
            boxes_old, _ = tagger._scrfd.detect(
                np.asarray(rgb_old)[:, :, ::-1], det_thresh=0.5,
            )
            with load_pil_image(
                path, is_raw=is_raw, target_shortest_edge=TAG_DECODE_FLOOR,
            ) as rgb_new:
                pv_c = proc(
                    images=resize_shortest_edge(rgb_new, 224),
                    return_tensors="np",
                )["pixel_values"].astype(np.float32)
                boxes_new, _ = tagger._scrfd.detect(
                    np.asarray(rgb_new)[:, :, ::-1], det_thresh=0.5,
                )
            emb_c = visual_emb(pv_c)
            cos = float(np.dot(emb_a.reshape(-1), emb_c.reshape(-1)))
            lb = label_of(emb_c)
            wo, ho = rgb_old.size
            wn, hn = rgb_new.size
            if len(boxes_old) == len(boxes_new):
                face_agree += 1
            for bo in boxes_old:
                best = max(
                    (iou_norm(bo[:4], wo, ho, bn[:4], wn, hn) for bn in boxes_new),
                    default=0.0,
                )
                face_ious.append(best)

    n += 1
    cosines.append(cos)
    l1_agree += int(la[0] == lb[0])
    l2_agree += int(la[:2] == lb[:2])
    if la[0] != lb[0]:
        disputes.append((path.name, la, lb, cos))
    if n % 200 == 0:
        print(f"  ...{n} 张，耗时 {time.perf_counter()-t0:.0f}s")

cos_arr = np.array(cosines)
print("=" * 70)
print(f"PHASE={PHASE}  样本数={n}")
print(f"一级标签一致率 = {l1_agree/n:.4f} （门槛 ≥0.99：{'PASS' if l1_agree/n >= 0.99 else 'FAIL'}）")
print(f"二级标签一致率 = {l2_agree/n:.4f}（参考值）")
print(f"向量 cosine 均值 = {cos_arr.mean():.6f}（门槛 ≥0.998：{'PASS' if cos_arr.mean() >= 0.998 else 'FAIL'}）")
print(f"cosine p5 = {np.percentile(cos_arr, 5):.6f}，min = {cos_arr.min():.6f}")
if PHASE == "p2":
    print(f"人脸数量一致率 = {face_agree/n:.4f}（门槛 ≥0.99：{'PASS' if face_agree/n >= 0.99 else 'FAIL'}）")
    if face_ious:
        print(f"匹配框平均最佳 IoU = {np.mean(face_ious):.4f}（参考值）")
print(f"一级分歧 {len(disputes)} 张，明细：")
for name, la, lb, cos in disputes[:50]:
    print(f"  {name}: {la[:2]} -> {lb[:2]}  cos={cos:.4f}")

# contact sheet：最多 30 张分歧
if disputes:
    thumbs = []
    for name, *_ in disputes[:30]:
        p = Path(root) / name
        if p.exists():
            with PILImage.open(p) as im:
                im.thumbnail((200, 200))
                thumbs.append((name, im.copy()))
    if thumbs:
        sheet = PILImage.new("RGB", (6 * 210, ((len(thumbs)+5)//6) * 240), "white")
        d = ImageDraw.Draw(sheet)
        for i, (name, im) in enumerate(thumbs):
            x, y = (i % 6) * 210 + 5, (i // 6) * 240 + 30
            sheet.paste(im, (x, y))
            d.text((x, y - 25), name[:28], fill="black")
        sheet.save(OUT_SHEET, quality=85)
        print("contact sheet ->", OUT_SHEET)
```

- [ ] **Step 3: 后台跑 P1 全库对比**

Run（后台执行，2924 张约 20–40 分钟）：

```bash
cd e:/code/claude/myPhotoGallery
AB_PHASE=p1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \
  prototypes/classify_pipeline/bench_ab_full_library.py
```

Expected: 终端两个门槛均打印 `PASS`（一级标签一致率 ≥0.99、cosine 均值 ≥0.998）。

- [ ] **Step 4: 人工抽查分歧**

若存在一级分歧：打开 `ab_disagreements_p1.jpg` 逐张看新旧标签，确认无明显质量退化。任一门槛 FAIL 或抽查发现退化：停下来与用户讨论，不进入 Phase 2。

- [ ] **Step 5: 性能复测并记录**

Run:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \
  prototypes/classify_pipeline/bench_single_image_timing.py
```

把优化后数字追加到 `prototypes/classify_pipeline/single_image_timing_results.txt`（该文件 gitignored），与 P1 前基线（JPG 928.8ms / ORF 380.0ms）对照。本步骤无 commit。

---

# Phase 2：JPEG DCT 降分辨率解码

### Task 4: load_pil_image 支持 target_shortest_edge（TDD）

**Files:**
- Modify: `backend/src/myphoto/imaging/decode.py`
- Test: `backend/tests/test_imaging.py`（追加）

**Interfaces:**
- Consumes: 无
- Produces: `load_pil_image(source, is_raw, target_shortest_edge: int | None = None)`；仅 JPEG 且最短边 > 目标值时 `Image.draft` 做 DCT 1/2，其余格式/小图/RAW/默认 None 行为不变

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_imaging.py` 末尾追加：

```python
# ---------- DCT 降分辨率解码（target_shortest_edge） ----------

def test_jpeg_dct_halves_large_image(tmp_path):
    p = tmp_path / "big.jpg"
    _jpg(p, size=(2000, 1000))
    im = load_pil_image(p, is_raw=False, target_shortest_edge=1600)
    # DCT 1/2（MCU 取整后约一半）：明显缩小，最短边落在 500 附近
    assert im.mode == "RGB"
    assert 1.8 < 2000 / im.size[0] < 2.2
    assert 400 <= im.size[1] <= 600


def test_small_jpeg_below_floor_is_not_drafted(tmp_path):
    p = tmp_path / "small.jpg"
    _jpg(p, size=(800, 600))
    im = load_pil_image(p, is_raw=False, target_shortest_edge=1600)
    assert im.size == (800, 600)


def test_png_silently_ignores_target_and_keeps_full_size(tmp_path):
    p = tmp_path / "big.png"
    PILImage.new("RGB", (2000, 1000)).save(p)
    im = load_pil_image(p, is_raw=False, target_shortest_edge=1600)
    assert im.size == (2000, 1000)


def test_default_none_keeps_legacy_full_resolution(tmp_path):
    p = tmp_path / "big.jpg"
    _jpg(p, size=(2000, 1000))
    assert load_pil_image(p, is_raw=False).size == (2000, 1000)


def test_draft_combined_with_exif_orientation(tmp_path):
    # draft 在转正之前配置；Orientation=6 的横版图转正后应为降采样竖图
    p = tmp_path / "big_orient.jpg"
    _jpg(p, size=(2000, 1000), orientation=6)
    im = load_pil_image(p, is_raw=False, target_shortest_edge=1600)
    assert im.size[0] > im.size[1]          # 转正后竖版
    assert im.size[0] < 2000 and im.size[1] < 1000  # 且确实降采样
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_imaging.py -v`
Expected: 5 个新用例 FAIL（`TypeError: unexpected keyword argument` 或尺寸未降）

- [ ] **Step 3: 实现**

`backend/src/myphoto/imaging/decode.py` 中改两处。`load_pil_image` 签名与普通图分支：

```python
def load_pil_image(
    source: str | Path,
    is_raw: bool,
    target_shortest_edge: int | None = None,
) -> PILImage.Image:
    """把磁盘图片解码为已 EXIF 转正的全分辨率 RGB PIL 图像（不做缩放）。

    target_shortest_edge 仅对 JPEG 生效：原图最短边大于该值时用 libjpeg
    DCT 1/2 降分辨率解码（解码即降采样，省掉全图像素的内存搬运）；
    其他格式与 None 均走原路径。返回对象的文件句柄已关闭、像素驻留内存，
    解码失败统一抛 ImageDecodeError。
    """
    try:
        if is_raw:
            return _load_raw(str(source))
        return _load_regular(str(source), target_shortest_edge)
    except ImageDecodeError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, RuntimeError) as exc:
        raise ImageDecodeError(f"image decode failed for {source}: {exc}") from exc
```

`_load_regular` 增加参数与 draft 守卫（`_load_raw` 不动）：

```python
def _load_regular(source: str, target_shortest_edge: int | None = None) -> PILImage.Image:
    with PILImage.open(source) as im:
        # draft 必须在 load 之前配置；仅 JPEG 具备 DCT 缩放能力，
        # 非 JPEG 调用 draft 无效果，这里用格式守卫静默回退全分辨率。
        if (
            target_shortest_edge is not None
            and im.format == "JPEG"
            and min(im.size) > target_shortest_edge
        ):
            im.draft("RGB", (im.width // 2, im.height // 2))
        # 相机直出图竖拍仅靠 Orientation 标记；先转正，打标与缩略图方向才一致
        im = ImageOps.exif_transpose(im)
        if im.mode != "RGB":
            im = im.convert("RGB")
        im.load()  # 在 with 关闭句柄前把像素载入内存
        return im
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_imaging.py -v`
Expected: 全部通过（原有 9 个 + 新增 5 个 = 14 passed）

- [ ] **Step 5: 确认缩略图路径未受影响**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_thumbnails.py -q`
Expected: 全过（缩略图调用不传新参数，默认 None）

- [ ] **Step 6: 提交**

```bash
git add backend/src/myphoto/imaging/decode.py backend/tests/test_imaging.py
git commit -m "feat(imaging): optional JPEG DCT half-resolution decode via target_shortest_edge"
```

### Task 5: tagging_jobs 接线解码地板（TDD）

**Files:**
- Modify: `backend/src/myphoto/services/tagging_jobs.py`（导入区 + `_decode_and_tag` 第 132-135 行）
- Test: `backend/tests/test_tags.py`（追加）

**Interfaces:**
- Consumes: `TAG_DECODE_FLOOR`（Task 1）、`load_pil_image` 新签名（Task 4）

- [ ] **Step 1: 追加失败测试**

`backend/tests/test_tags.py` 顶部导入区加 `import contextlib`，文件末尾追加：

```python
def test_decode_and_tag_passes_dct_floor(monkeypatch, tmp_path):
    from myphoto.services import tagging_jobs as jobs

    captured = {}

    class FakeTagger:
        def tag(self, im):
            captured["image_size"] = im.size
            return "TAGGED"

    def fake_load(path, is_raw, target_shortest_edge=None):
        captured["floor"] = target_shortest_edge
        return contextlib.nullcontext(PILImage.new("RGB", (10, 10)))

    monkeypatch.setattr(jobs, "load_pil_image", fake_load)
    p = tmp_path / "x.jpg"
    p.write_bytes(b"x")

    assert jobs._decode_and_tag(FakeTagger(), p) == "TAGGED"
    assert captured["floor"] == 1600
    assert captured["image_size"] == (10, 10)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_tags.py::test_decode_and_tag_passes_dct_floor -v`
Expected: FAIL（`captured["floor"]` 为 None）

- [ ] **Step 3: 接线**

`backend/src/myphoto/services/tagging_jobs.py` 导入区：

```python
from myphoto.imaging.decode import load_pil_image
from myphoto.imaging.preprocess import TAG_DECODE_FLOOR
```

（若 `load_pil_image` 已导入则只补 preprocess 一行。）`_decode_and_tag` 改为：

```python
def _decode_and_tag(tagger, path: Path) -> TagResult:
    # 统一解码：RAW（.orf 等）走 rawpy，普通图 PIL+EXIF 转正，与缩略图同入口。
    # 大图 JPEG 在解码阶段即 DCT 1/2 降采样（最短边地板 1600px），
    # 后续 letterbox / BGR 转换全部在小图上进行。
    with load_pil_image(
        path,
        is_raw=classify(path.name) == "raw",
        target_shortest_edge=TAG_DECODE_FLOOR,
    ) as im:
        return tagger.tag(im)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_tags.py -q`
Expected: 全过

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/services/tagging_jobs.py backend/tests/test_tags.py
git commit -m "feat(tagging): decode tag inputs with 1600px DCT floor"
```

### Task 6: P2 全库验证（门槛 3）、文档与全量回归

**Files:**
- Run（gitignored）: `prototypes/classify_pipeline/bench_ab_full_library.py`（Task 3 已建）
- Modify: `README.zh-CN.md`（"升级"节，第 300-302 行段落后）

- [ ] **Step 1: 后台跑 P2 全库对比**

Run：

```bash
cd e:/code/claude/myPhotoGallery
AB_PHASE=p2 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \
  prototypes/classify_pipeline/bench_ab_full_library.py
```

Expected: 三个门槛全部 `PASS`，重点看人脸数量一致率 ≥0.99。

- [ ] **Step 2: 人工抽查人脸分歧**

打开 `ab_disagreements_p2.jpg` 并结合终端明细，确认人脸数量分歧中无真实漏检（远景小脸重点看）。FAIL 或发现漏检：P2 整体 revert（Task 4、5 两个 commit），P1 保留。

- [ ] **Step 3: 性能复测**

Run:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \
  prototypes/classify_pipeline/bench_single_image_timing.py
```

把 P2 后数字追加到 `single_image_timing_results.txt`，对照三行基线：JPG 928.8ms、ORF 380.0ms、CLIP 方式 A/B 365.4/193.4ms。无 commit。

- [ ] **Step 4: README 升级说明**

在 `README.zh-CN.md` 第 302 行（"升级前仍建议先备份……"段落）之后追加：

```markdown
打标预处理优化（2026-11）：CLIP 改为代码侧预降采样、大图 JPEG 启用 DCT
1/2 解码（最短边地板 1600px），模型权重与标签体系不变。升级后新图自动
走新管线；如需库内图像向量完全一致，可先备份再执行一次
`myphoto tag run --force`（不执行不影响任何功能，`relabel` 对存量向量
仍然有效）。
```

- [ ] **Step 5: 提交文档**

```bash
git add README.zh-CN.md
git commit -m "docs(readme): note tagging preprocessing change and optional force re-tag"
```

- [ ] **Step 6: 全量回归**

Run: `.venv/Scripts/python.exe -m pytest backend/tests -q`
Expected: 全过（基线 764 passed / 6 skipped + 本计划新增 14 个用例 = 778 passed / 6 skipped），0 failed。

- [ ] **Step 7: 收尾检查**

Run:

```bash
git log --oneline -6
grep -rn "target_shortest_edge\|resize_shortest_edge\|clip-v3-predownscale" backend/src backend/tests --include="*.py" | wc -l
```

Expected: 4 个功能 commit + 1 个文档 commit；grep 有命中（接线完整）。向用户汇报两阶段门槛结果与性能前后对照，提醒推送由用户手动执行。
