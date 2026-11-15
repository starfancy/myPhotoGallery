# 打标器 CUDA 执行后端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让打标器在 NVIDIA 主机上经 onnxruntime-gpu 用 CUDAExecutionProvider 跑全部四个模型，Intel 主机维持 OpenVINO 现状路径，通过 `[tagging] device` 三档配置切换。

**Architecture:** 新增无模型依赖的纯函数模块 `inference.py` 做 provider 决策；`Tagger` 构造时确定 `"cuda" | "openvino"` 两套加载计划，cuda 计划下 CLIP visual 走新导出的 `clip-onnx/visual.onnx`、YOLO/SCRFD/ArcFace 走 ORT 会话，openvino 计划与现状逐行等价。CLIP text 塔始终留 OpenVINO CPU（仅启动时一次）。

**Tech Stack:** Python 3.11+、onnxruntime 1.31（CUDA 主机换 onnxruntime-gpu）、openvino 2024.6.0、insightface 2.1、pytest（asyncio_mode=auto）、Click、torch 仅导出脚本临时需要。

## Global Constraints

- `openvino==2024.6.0` 锁版本；不安装 `optimum`；**运行时不依赖 torch**（仅 `scripts/export_clip_onnx.py` 在准备模型的机器上临时需要）。
- 模型文件不进 git：`.gitignore` 已含 `backend/models/` 与 `prototypes/`；新产物 `backend/models/clip-onnx/visual.onnx` 同样不入库。
- 真实模型不进自动化测试：单测只用 tmp 目录空文件、monkeypatch、FakeTagger；CI 无模型、无 GPU。
- `TAG_MODEL_VERSION` / `CLIP_MODEL_VERSION` / `FACE_MODEL_VERSION` 三个版本戳**不变**，不触发存量重打。
- 测试命令统一用仓库根 venv：`.venv/Scripts/python.exe -m pytest <path> -v`；提交风格 conventional commits（`feat(tagger):` 等）。
- 平台 Windows 11 + Git Bash；配置非法值按项目惯例 warning + 回退默认，绝不阻止启动。
- 设计依据：[docs/superpowers/specs/2026-11-15-tagger-cuda-execution-provider-design.md](../specs/2026-11-15-tagger-cuda-execution-provider-design.md)。

## 跨任务接口（先定死，后续任务直接引用）

```python
# backend/src/myphoto/inference.py
class BackendUnavailable(RuntimeError): ...
def select_ort_providers(device: str, available: Sequence[str] | None = None) -> list[str]: ...
def resolve_backend(device: str, available: Sequence[str] | None = None) -> str: ...  # -> "cuda" | "openvino"

# backend/src/myphoto/config.py
AppConfig.tagging_device: str          # "auto" | "cpu" | "cuda"，config 层保证合法（非法回退 "auto"）

# backend/src/myphoto/tagger.py
class Tagger:
    def __init__(self, models_dir: str | Path, device: str = "auto"): ...
    self.backend_plan: str             # "cuda" | "openvino"
    def unavailable_reason(self) -> str | None: ...   # None = 可用
    def available(self) -> bool: ...                  # 签名不变
    def expected_paths(self) -> dict[str, Path]: ...  # 按 backend_plan 分支

# backend/src/myphoto/cli.py
def _build_tagger(cfg, config_path: str | None) -> tuple["Tagger | None", str | None]: ...
# 返回 (tagger, reason)；成功时 (tagger, None)，不可用时 (None, 中文原因)
```

---

### Task 1: provider 决策纯函数模块

**Files:**
- Create: `backend/src/myphoto/inference.py`
- Test: `backend/tests/test_inference.py`

**Interfaces:**
- Consumes: `onnxruntime.get_available_providers()`（仅当入参 `available=None` 时调用）
- Produces: `BackendUnavailable`、`select_ort_providers(device, available=None) -> list[str]`、`resolve_backend(device, available=None) -> "cuda" | "openvino"`，供 Task 3/4/6 使用

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_inference.py`：

```python
"""inference 设备/provider 决策纯函数（不加载任何模型）。"""

import pytest

from myphoto.inference import BackendUnavailable, resolve_backend, select_ort_providers

CPU = ["CPUExecutionProvider"]
CUDA = ["CUDAExecutionProvider", "CPUExecutionProvider"]


def test_select_providers_auto_with_cuda():
    assert select_ort_providers("auto", ["CUDAExecutionProvider", "CPUExecutionProvider"]) == CUDA


def test_select_providers_auto_without_cuda_falls_back_to_cpu():
    assert select_ort_providers("auto", ["CPUExecutionProvider"]) == CPU


def test_select_providers_cpu_always_cpu_even_if_cuda_present():
    assert select_ort_providers("cpu", ["CUDAExecutionProvider", "CPUExecutionProvider"]) == CPU


def test_select_providers_cuda_returns_cuda_with_cpu_fallback():
    out = select_ort_providers("cuda", ["CUDAExecutionProvider", "CPUExecutionProvider"])
    assert out[0] == "CUDAExecutionProvider"
    assert "CPUExecutionProvider" in out


def test_select_providers_explicit_cuda_unavailable_raises_with_install_hint():
    with pytest.raises(BackendUnavailable) as ei:
        select_ort_providers("cuda", ["CPUExecutionProvider"])
    msg = str(ei.value)
    assert "onnxruntime-gpu" in msg
    assert "CUDAExecutionProvider" in msg


def test_select_providers_unknown_device_treated_as_auto():
    # 防御性：config 层已归一，模块层再兜一次底，不抛异常
    assert select_ort_providers("gpu", ["CPUExecutionProvider"]) == CPU


def test_resolve_backend_mappings():
    assert resolve_backend("cuda", ["CUDAExecutionProvider", "CPUExecutionProvider"]) == "cuda"
    assert resolve_backend("auto", ["CUDAExecutionProvider", "CPUExecutionProvider"]) == "cuda"
    assert resolve_backend("auto", ["CPUExecutionProvider"]) == "openvino"
    assert resolve_backend("cpu", ["CUDAExecutionProvider", "CPUExecutionProvider"]) == "openvino"


def test_resolve_backend_explicit_cuda_missing_raises():
    with pytest.raises(BackendUnavailable):
        resolve_backend("cuda", ["CPUExecutionProvider"])
```

- [ ] **Step 2: 验证失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_inference.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'myphoto.inference'`

- [ ] **Step 3: 实现模块**

创建 `backend/src/myphoto/inference.py`：

```python
"""打标推理后端决策（纯函数，不加载模型，可在无 GPU/无模型环境单测）。

两种加载计划：
- "cuda"：四个模型全部走 ONNX Runtime（CUDAExecutionProvider + CPU 回退）
- "openvino"：CLIP/YOLO 走 OpenVINO（内部再探 Intel GPU→CPU），人脸模型走 ORT CPU
"""

from __future__ import annotations

from collections.abc import Sequence

_CUDA_EP = "CUDAExecutionProvider"
_CPU_EP = "CPUExecutionProvider"
_VALID_DEVICES = ("auto", "cpu", "cuda")


class BackendUnavailable(RuntimeError):
    """显式要求的执行后端在当前环境不可用（如 device="cuda" 但无 CUDA EP）。"""


def _available_providers(available: Sequence[str] | None) -> list[str]:
    if available is not None:
        return list(available)
    import onnxruntime as ort

    return list(ort.get_available_providers())


def select_ort_providers(
    device: str,
    available: Sequence[str] | None = None,
) -> list[str]:
    """按 device 决策 ORT providers 列表。

    - auto：有 CUDA EP → [CUDA, CPU]，否则 [CPU]
    - cpu：恒为 [CPU]（即使环境里有 CUDA）
    - cuda：有 CUDA → [CUDA, CPU]；无 CUDA → BackendUnavailable（含安装提示）
    - 未知 device：按 auto 兜底
    """
    providers = _available_providers(available)
    has_cuda = _CUDA_EP in providers

    if device == "cpu":
        return [_CPU_EP]
    if device == "cuda":
        if not has_cuda:
            raise BackendUnavailable(
                'config [tagging].device = "cuda"，但当前 onnxruntime 未提供 '
                "CUDAExecutionProvider。请安装 GPU 版：先 "
                "`pip uninstall onnxruntime` 再 `pip install onnxruntime-gpu`，"
                "并确认 NVIDIA 驱动、CUDA 12.x 与 cuDNN 9 已就位。"
            )
        return [_CUDA_EP, _CPU_EP]
    # auto 及任何未知值：自动探测
    return [_CUDA_EP, _CPU_EP] if has_cuda else [_CPU_EP]


def resolve_backend(
    device: str,
    available: Sequence[str] | None = None,
) -> str:
    """返回 Tagger 加载计划："cuda" | "openvino"。

    显式 cuda 不可用时抛 BackendUnavailable；cpu/auto 永不抛错。
    """
    providers = _available_providers(available)
    if device == "cuda" and _CUDA_EP not in providers:
        raise BackendUnavailable(
            'config [tagging].device = "cuda"，但当前 onnxruntime 未提供 '
            "CUDAExecutionProvider。请安装 GPU 版：先 "
            "`pip uninstall onnxruntime` 再 `pip install onnxruntime-gpu`，"
            "并确认 NVIDIA 驱动、CUDA 12.x 与 cuDNN 9 已就位。"
        )
    if device in _VALID_DEVICES and _CUDA_EP in providers and device != "cpu":
        return "cuda"
    return "openvino"
```

- [ ] **Step 4: 验证通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_inference.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/inference.py backend/tests/test_inference.py
git commit -m "feat(tagger): add pure inference backend/provider selection"
```

---

### Task 2: config 增加 `[tagging] device`

**Files:**
- Modify: `backend/src/myphoto/config.py`（AppConfig 字段约 L52-55、解析约 L169-178、模板 `_DEFAULT_TEMPLATE` 约 L90-99）
- Test: `backend/tests/test_config.py`（追加，仿 `test_scanner_*` 风格）

**Interfaces:**
- Consumes: Task 1 无直接依赖（config 只做字符串归一）
- Produces: `AppConfig.tagging_device: str`，值域保证为 `auto|cpu|cuda`，供 Task 3/6 读取

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_config.py` 末尾追加：

```python
# ---------- [tagging].device ----------

_SECRET = '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'


def test_tagging_device_defaults_to_auto(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(_SECRET, encoding="utf-8")
    assert load_or_init(p).tagging_device == "auto"


def test_tagging_device_reads_three_valid_values(tmp_path):
    for value in ("auto", "cpu", "cuda"):
        p = tmp_path / "config.toml"
        p.write_text(_SECRET + f"[tagging]\ndevice = {value!r}\n", encoding="utf-8")
        assert load_or_init(p).tagging_device == value


def test_tagging_device_unknown_value_falls_back_to_auto(tmp_path, caplog):
    p = tmp_path / "config.toml"
    p.write_text(_SECRET + '[tagging]\ndevice = "tpu"\n', encoding="utf-8")
    with caplog.at_level("WARNING"):
        cfg = load_or_init(p)
    assert cfg.tagging_device == "auto"
    assert "device" in caplog.text.lower()


def test_default_template_contains_tagging_device_hint(tmp_path):
    p = tmp_path / "config.toml"
    load_or_init(p)
    text = p.read_text(encoding="utf-8")
    assert "[tagging]" in text
    assert "device" in text
```

- [ ] **Step 2: 验证失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_config.py -k tagging_device -v`
Expected: FAIL，`AttributeError: 'AppConfig' object has no attribute 'tagging_device'`

- [ ] **Step 3: 实现——AppConfig 字段**

`backend/src/myphoto/config.py` 的 dataclass 中，在 `tagging_scan_on_import` 后加一行：

```python
    tagging_scan_on_import: bool    # 扫描时对新变图片同步打标（设计 §3.1；不变文件不受影响）
    tagging_device: str             # "auto" | "cpu" | "cuda"；非法值回退 auto
```

- [ ] **Step 4: 实现——解析逻辑**

在 `load_or_init` 内现有 tagging 解析处（`tagging_models_dir = ...` 一行之后）加入：

```python
    tagging_device_raw = str(tagging_section.get("device") or "auto").strip().lower()
    if tagging_device_raw not in ("auto", "cpu", "cuda"):
        log.warning(
            "[tagging].device=%r 非法（合法值 auto|cpu|cuda），回退 auto",
            tagging_device_raw,
        )
        tagging_device_raw = "auto"
```

并在 `return AppConfig(...)` 的 tagging 参数组末尾加：

```python
        tagging_device=tagging_device_raw,
```

- [ ] **Step 5: 实现——配置模板注释**

`_DEFAULT_TEMPLATE` 的 `[tagging]` 注释段（现有 `# models_dir = "backend/models"` 一行之后）追加：

```python
# device = "auto"        # auto | cpu | cuda；cuda 需安装 onnxruntime-gpu
```

- [ ] **Step 6: 验证通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_config.py -v`
Expected: 全部 PASS（含新 4 个）

- [ ] **Step 7: 提交**

```bash
git add backend/src/myphoto/config.py backend/tests/test_config.py
git commit -m "feat(config): add [tagging].device auto/cpu/cuda setting"
```

---

### Task 3: Tagger 后端计划与文件门控

**Files:**
- Modify: `backend/src/myphoto/tagger.py`（`__init__` L166-179、`expected_paths` L183-192、`available` L194-196）
- Test: `backend/tests/test_tagger_gating.py`（新建）

**Interfaces:**
- Consumes: Task 1 `resolve_backend` / `BackendUnavailable`；Task 2 `cfg.tagging_device`（本任务测试直接传字符串）
- Produces: `Tagger(models_dir, device="auto")`、`.backend_plan`、`.unavailable_reason()`、按计划分支的 `.expected_paths()` / `.available()`，供 Task 4/6 使用

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_tagger_gating.py`：

```python
"""Tagger 文件门控与后端计划：只造空文件，绝不加载真实模型。"""

from pathlib import Path

from myphoto.tagger import Tagger

_OPEN_VINO_FILES = [
    "clip-ov/visual.xml",
    "clip-ov/text.xml",
    "clip-vit-base-patch32/config.json",
    "yolo11n.onnx",
    "insightface/det_500m.onnx",
    "insightface/w600k_mbf.onnx",
]
_CUDA_FILES = [
    "clip-onnx/visual.onnx",
    "clip-ov/text.xml",          # text 塔两计划共用，cuda 主机仍需 text.xml/.bin
    "clip-vit-base-patch32/config.json",
    "yolo11n.onnx",
    "insightface/det_500m.onnx",
    "insightface/w600k_mbf.onnx",
]


def _touch(root: Path, rels: list[str]) -> None:
    for rel in rels:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")


def test_openvino_plan_uses_ir_paths(tmp_path):
    _touch(tmp_path, _OPEN_VINO_FILES)
    t = Tagger(tmp_path, device="cpu")
    assert t.backend_plan == "openvino"
    assert t.unavailable_reason() is None
    assert t.available() is True
    assert "clip_visual_xml" in t.expected_paths()
    assert "clip_visual_onnx" not in t.expected_paths()


def test_cuda_plan_requires_onnx_not_ir(tmp_path):
    _touch(tmp_path, _CUDA_FILES)
    t = Tagger(tmp_path, device="cuda", available=["CUDAExecutionProvider", "CPUExecutionProvider"])
    assert t.backend_plan == "cuda"
    assert t.available() is True
    paths = t.expected_paths()
    assert paths["clip_visual_onnx"].name == "visual.onnx"
    assert "clip_visual_xml" not in paths
    assert "clip_text_xml" in paths  # text 塔始终走 OpenVINO CPU


def test_cuda_plan_missing_visual_onnx_is_unavailable_with_reason(tmp_path):
    _touch(tmp_path, [f for f in _CUDA_FILES if f != "clip-onnx/visual.onnx"])
    t = Tagger(tmp_path, device="cuda", available=["CUDAExecutionProvider", "CPUExecutionProvider"])
    assert t.available() is False
    reason = t.unavailable_reason()
    assert reason is not None
    assert "visual.onnx" in reason


def test_explicit_cuda_without_ep_records_reason_and_keeps_server_startable(tmp_path):
    # 构造不抛异常（web 启动路径），原因经 unavailable_reason 暴露
    t = Tagger(tmp_path, device="cuda", available=["CPUExecutionProvider"])
    assert t.backend_plan == "openvino"  # 兜底，保证 expected_paths 不炸
    assert t.available() is False
    assert "CUDAExecutionProvider" in t.unavailable_reason()


def test_empty_models_dir_reports_missing(tmp_path):
    t = Tagger(tmp_path, device="auto", available=["CPUExecutionProvider"])
    assert t.available() is False
    assert "missing" in t.unavailable_reason()
```

- [ ] **Step 2: 验证失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_tagger_gating.py -v`
Expected: FAIL（构造参数 `device`/`available` 不存在、`backend_plan` 属性缺失）

- [ ] **Step 3: 改造 Tagger 构造与门控**

修改 `backend/src/myphoto/tagger.py`：

(a) 顶部 import 区加：

```python
from myphoto.inference import BackendUnavailable, resolve_backend
```

(b) 替换 `__init__`（现有 L166-179）为：

```python
    def __init__(self, models_dir: str | Path, device: str = "auto", available=None):
        """available 仅测试注入；生产传 None 由 inference 模块查 ORT。

        构造不加载模型、不抛 BackendUnavailable：显式 cuda 不可用时记录
        原因并兜底 openvino 计划，调用方经 unavailable_reason()/available()
        决定是否启用，保证 web 服务永远能启动。ORT providers 在构造时一次性
        算好（注入 available 时同样生效），_ensure_loaded 直接复用，不再
        重新探测——这样无 GPU 机器也能注入 provider 列表走 cuda 计划代码。
        """
        from myphoto.inference import select_ort_providers

        self.models_dir = Path(models_dir)
        self.device = device
        self._lock = threading.Lock()
        self._loaded = False
        self._init_error: str | None = None
        try:
            self.backend_plan = resolve_backend(device, available)
        except BackendUnavailable as exc:
            self._init_error = str(exc)
            self.backend_plan = "openvino"
        # 人脸两个 ORT 会话两计划都要；cuda 计划的 CLIP/YOLO ORT 会话也用它
        if self.backend_plan == "cuda":
            self._ort_providers = select_ort_providers(device, available)
        else:
            self._ort_providers = ["CPUExecutionProvider"]
        # 运行时填充（懒加载后才有）
        self._clip_proc = None
        self._clip_visual = None          # openvino 计划：编译模型
        self._clip_visual_ort = None      # cuda 计划：ORT 会话
        self._clip_text_emb = None        # (N_prompts, 512) L2 归一化
        self._flat_prompts: list[tuple[str, str, str]] = []
        self._yolo_compiled = None        # openvino 计划
        self._yolo_ort = None             # cuda 计划
        self._yolo_input = None
        self._scrfd = None
        self._recog = None
```

(c) 替换 `expected_paths` 与 `available`（现有 L183-196）为：

```python
    def expected_paths(self) -> dict[str, Path]:
        md = self.models_dir
        paths = {
            "clip_tokenizer": md / "clip-vit-base-patch32",
            "yolo_onnx": md / "yolo11n.onnx",
            "face_det_onnx": md / "insightface" / "det_500m.onnx",
            "face_rec_onnx": md / "insightface" / "w600k_mbf.onnx",
        }
        if self.backend_plan == "cuda":
            paths["clip_visual_onnx"] = md / "clip-onnx" / "visual.onnx"
        else:
            paths["clip_visual_xml"] = md / "clip-ov" / "visual.xml"
            paths["clip_text_xml"] = md / "clip-ov" / "text.xml"
        return paths

    def unavailable_reason(self) -> str | None:
        """None = 可用；否则返回中文原因（配置/缺文件），供 CLI 与启动日志。"""
        if self._init_error is not None:
            return self._init_error
        missing = [str(p) for p in self.expected_paths().values() if not p.exists()]
        if missing:
            return f"tagger models missing: {missing}"
        return None

    def available(self) -> bool:
        """配置后端可用且所有模型文件就位？不加载模型，只查文件。"""
        return self.unavailable_reason() is None
```

- [ ] **Step 4: 验证通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_tagger_gating.py backend/tests/test_tags.py -v`
Expected: 新 5 个 PASS；既有 tag 测试全绿（FakeTagger 不受影响）

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/tagger.py backend/tests/test_tagger_gating.py
git commit -m "feat(tagger): backend plan and plan-aware model file gating"
```

---

### Task 4: Tagger 双计划会话加载与推理分支

**Files:**
- Modify: `backend/src/myphoto/tagger.py`（`_ensure_loaded` L207-267、`_clip_scene` L297-306、`_count_persons` L308-350；`_resolve_device` 保留）
- Test: 无新增自动化测试（真实模型不进 CI）；以 Task 3 门控测试 + 本任务 Step 5 手动回归为准

**Interfaces:**
- Consumes: Task 1 `select_ort_providers`；Task 3 `self.backend_plan`
- Produces: 加载后 `tag()` / `classify_embedding()` 行为与现状逐值一致（同模型同权重）

- [ ] **Step 1: 重写 `_ensure_loaded` 双计划分支**

把 `backend/src/myphoto/tagger.py` 的 `_ensure_loaded` 整体替换为：

```python
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        reason = self.unavailable_reason()
        if reason is not None:
            raise RuntimeError(reason)

        from openvino.runtime import Core  # heavy import
        # 见上一提交：无 torch 时抑制 transformers advisory 警告
        os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
        from transformers import CLIPProcessor

        md = self.models_dir
        core = Core()
        is_cuda = self.backend_plan == "cuda"
        log.info(
            "tagger loading models from %s (backend_plan=%s)", md, self.backend_plan,
        )

        # ---- CLIP：processor 与 text 塔两计划共用；visual 按计划分后端 ----
        self._clip_proc = CLIPProcessor.from_pretrained(str(md / "clip-vit-base-patch32"))
        self._flat_prompts = flatten_prompts()
        import numpy as np

        text_compiled = core.compile_model(str(md / "clip-ov" / "text.xml"), "CPU")
        tok = self._clip_proc(
            text=[p[2] for p in self._flat_prompts],
            padding="max_length", max_length=77, truncation=True, return_tensors="np",
        )
        out = text_compiled({
            "input_ids": tok["input_ids"].astype(np.int32),
            "attention_mask": tok["attention_mask"].astype(np.int32),
        })
        text_emb = next(iter(out.values()))
        self._clip_text_emb = text_emb / np.linalg.norm(text_emb, axis=-1, keepdims=True)

        if is_cuda:
            import onnxruntime as ort

            self._clip_visual_ort = ort.InferenceSession(
                str(md / "clip-onnx" / "visual.onnx"), providers=list(self._ort_providers),
            )
            log.info("clip visual ORT providers=%s", self._clip_visual_ort.get_providers())
        else:
            device = self._resolve_device(core)
            self._clip_visual = core.compile_model(str(md / "clip-ov" / "visual.xml"), device)

        # ---- YOLO11n：cuda 计划走 ORT，否则 OpenVINO ----
        if is_cuda:
            import onnxruntime as ort

            self._yolo_ort = ort.InferenceSession(
                str(md / "yolo11n.onnx"), providers=list(self._ort_providers),
            )
            self._yolo_input = self._yolo_ort.get_inputs()[0].name
            log.info("yolo ORT providers=%s", self._yolo_ort.get_providers())
        else:
            yolo_model = core.read_model(str(md / "yolo11n.onnx"))
            compiled = core.compile_model(yolo_model, device)
            self._yolo_compiled = compiled
            self._yolo_input = compiled.inputs[0]

        # ---- InsightFace：SCRFD 检测 + ArcFace 识别 ----
        import onnxruntime as ort
        from insightface.model_zoo import SCRFD

        if is_cuda:
            scrfd_session = ort.InferenceSession(
                str(md / "insightface" / "det_500m.onnx"), providers=list(self._ort_providers),
            )
            self._scrfd = SCRFD(str(md / "insightface" / "det_500m.onnx"), session=scrfd_session)
            # 2.1 源码：仅 ctx_id<0 才 set_providers(CPU)；ctx_id=0 保留注入会话的 provider
            self._scrfd.prepare(ctx_id=0, input_size=(640, 640))
            self._recog = ort.InferenceSession(
                str(md / "insightface" / "w600k_mbf.onnx"), providers=list(self._ort_providers),
            )
            log.info(
                "face providers=%s; scrfd session=%s; recog=%s",
                self._ort_providers, scrfd_session.get_providers(), self._recog.get_providers(),
            )
        else:
            # 显式注入 CPU 会话：不依赖 SCRFD 内部 get_default_providers()，
            # 否则装了 onnxruntime-gpu 的机器上即使 device=cpu 也会被库选到 CUDA
            cpu_session = ort.InferenceSession(
                str(md / "insightface" / "det_500m.onnx"),
                providers=["CPUExecutionProvider"],
            )
            self._scrfd = SCRFD(str(md / "insightface" / "det_500m.onnx"), session=cpu_session)
            self._scrfd.prepare(ctx_id=-1, input_size=(640, 640))
            self._recog = ort.InferenceSession(
                str(md / "insightface" / "w600k_mbf.onnx"),
                providers=["CPUExecutionProvider"],
            )

        # ---- warmup：避免第一张图付编译/分配开销 ----
        dummy_img = np.zeros((1, 3, 224, 224), dtype=np.float32)
        if is_cuda:
            self._clip_visual_ort.run(
                None, {self._clip_visual_ort.get_inputs()[0].name: dummy_img},
            )
            self._yolo_ort.run(None, {self._yolo_input: np.zeros((1, 3, 640, 640), dtype=np.float32)})
        else:
            _ = self._clip_visual({self._clip_visual.inputs[0]: dummy_img})
            _ = self._yolo_compiled({self._yolo_input: np.zeros((1, 3, 640, 640), dtype=np.float32)})

        self._loaded = True
        log.info("tagger models loaded (%d prompts, backend_plan=%s)", len(self._flat_prompts), self.backend_plan)
```

注意：cuda 计划不再需要 `clip-ov/visual.xml`（Task 3 门控已排除），但 text.xml 仍是共用必需文件，两个计划的门控都保留它。

- [ ] **Step 2: `_clip_scene` 按计划分支**

替换现有 `_clip_scene` 为：

```python
    def _clip_scene(self, rgb: PILImage.Image) -> tuple[str, str, float, np.ndarray]:
        x = self._clip_proc(images=rgb, return_tensors="np")
        pixel_values = x["pixel_values"].astype(np.float32)
        if self.backend_plan == "cuda":
            img_emb = self._clip_visual_ort.run(
                None, {self._clip_visual_ort.get_inputs()[0].name: pixel_values},
            )[0]
        else:
            out = self._clip_visual({self._clip_visual.inputs[0]: pixel_values})
            img_emb = next(iter(out.values()))
        img_emb = img_emb / np.linalg.norm(img_emb, axis=-1, keepdims=True)
        sims = (img_emb @ self._clip_text_emb.T).squeeze(0)
        major, minor, conf = classify_scene(sims, self._flat_prompts)
        return major, minor, float(conf), img_emb.reshape(-1)
```

- [ ] **Step 3: 抽出 `_yolo_infer` 并改 `_count_persons`**

在 `_count_persons` 前新增辅助方法：

```python
    def _yolo_infer(self, arr: np.ndarray) -> np.ndarray:
        """单张 letterbox 批次 (1,3,640,640) → (84,8400)，两后端输出同构。"""
        if self.backend_plan == "cuda":
            return self._yolo_ort.run(None, {self._yolo_input: arr})[0][0]
        out = self._yolo_compiled({self._yolo_input: arr})
        return next(iter(out.values()))[0]
```

然后把 `_count_persons` 中这两行：

```python
        out = self._yolo_compiled({self._yolo_input: arr})
        preds = next(iter(out.values()))[0]  # (84, 8400)
```

替换为：

```python
        preds = self._yolo_infer(arr)  # (84, 8400)
```

其余 letterbox / NMS / 坐标换算代码不动。

- [ ] **Step 4: 全量测试确认无回归**

Run: `.venv/Scripts/python.exe -m pytest backend/tests -q`
Expected: 全绿（数量 = 既有 729 + Task1/2/3 新增 17；无模型测试被触发）

- [ ] **Step 5: 本机手动回归 OpenVINO 路径（行为必须与改造前一致）**

```bash
.venv/Scripts/python.exe -I prototypes/classify_pipeline/bench_face_timing.py
```

Expected: 正常加载、8 张样本全部出结果；数字与基线（SCRFD ~15ms、整 tag ~54ms 均值）同量级；日志含 `backend_plan=openvino`。再跑：

```bash
.venv/Scripts/python.exe -m myphoto.cli --config config.toml tag status
```

Expected: `models ready: yes`（config.toml 为开发库真实配置）。

- [ ] **Step 6: 提交**

```bash
git add backend/src/myphoto/tagger.py
git commit -m "feat(tagger): dual-plan session loading (ORT CUDA vs OpenVINO)"
```

---

### Task 5: CLIP visual ONNX 导出脚本与双路径等价验证

**Files:**
- Create: `scripts/export_clip_onnx.py`（入 git；`scripts/` 目录新建）
- Produce（不入库）: `backend/models/clip-onnx/visual.onnx`
- Test: 脚本内置自检断言；端到端比对为手动步骤

**Interfaces:**
- Consumes: `backend/models/clip-vit-base-patch32/`（已有 PyTorch 权重 + tokenizer）
- Produces: `backend/models/clip-onnx/visual.onnx`，Task 4 cuda 计划的门控文件

- [ ] **Step 1: 写导出脚本**

创建 `scripts/export_clip_onnx.py`（torch 仅在 `main()` 内导入，模块级零 torch 依赖）：

```python
"""把 CLIP visual 塔导出为 ONNX（打标器 cuda 计划经 ORT 加载）。

运行时（myphoto 打标）不依赖 torch；本脚本只在准备模型的机器上执行，
CPU 版 torch 即可，无需 GPU：

    pip install torch onnx onnxruntime transformers
    python scripts/export_clip_onnx.py [--models-dir backend/models]

产物 <models-dir>/clip-onnx/visual.onnx 不进 git，随模型手工部署到
NVIDIA 主机；OpenVINO 主机不需要该文件。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def main() -> None:
    import onnxruntime as ort
    import torch
    from transformers import CLIPModel, CLIPProcessor

    class VisualWrapper(torch.nn.Module):
        """vision_model + visual_projection，输入 pixel_values，输出 (B,512)。"""

        def __init__(self, clip):
            super().__init__()
            self.clip = clip

        def forward(self, pixel_values):
            out = self.clip.vision_model(pixel_values=pixel_values)
            return self.clip.visual_projection(out.pooler_output)

    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", default="backend/models")
    args = ap.parse_args()

    md = Path(args.models_dir)
    src = md / "clip-vit-base-patch32"
    out_dir = md / "clip-onnx"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "visual.onnx"

    clip = CLIPModel.from_pretrained(str(src))
    clip.eval()
    processor = CLIPProcessor.from_pretrained(str(src))
    wrapper = VisualWrapper(clip)

    dummy = processor(images=Image.new("RGB", (224, 224)), return_tensors="pt")["pixel_values"]
    with torch.no_grad():
        torch.onnx.export(
            wrapper,
            (dummy,),
            str(out_path),
            input_names=["pixel_values"],
            output_names=["image_embeds"],
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "image_embeds": {0: "batch"},
            },
            opset_version=17,
        )

    # 自检：同一输入 torch 原模型 vs ORT(CPU) 输出 cosine
    sess = ort.InferenceSession(str(out_path), providers=["CPUExecutionProvider"])
    with torch.no_grad():
        ref = wrapper(dummy).numpy()
    got = sess.run(None, {"pixel_values": dummy.numpy()})[0]
    cosine = float(
        np.dot(ref[0], got[0]) / (np.linalg.norm(ref[0]) * np.linalg.norm(got[0]))
    )
    size_mb = out_path.stat().st_size / 1e6
    print(f"exported {out_path} ({size_mb:.0f} MB); torch-vs-ORT cosine={cosine:.6f}")
    assert cosine > 0.999, f"cosine {cosine} below 0.999"


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 执行导出**

Run: `.venv/Scripts/python.exe scripts/export_clip_onnx.py --models-dir backend/models`
Expected: 打印 `exported ... visual.onnx (xxx MB); torch-vs-ORT cosine=1.000000`（或 ≥0.999），断言通过；`backend/models/clip-onnx/visual.onnx` 生成。若 torch.onnx 报缺失依赖，按提示 `pip install onnx`（仅导出机需要）。

- [ ] **Step 3: 双路径端到端等价验证（手动，临时脚本放 gitignored 的 prototypes）**

创建 `prototypes/classify_pipeline/verify_clip_onnx.py`（不提交），对 `samples/` 每张图分别用 OpenVINO `visual.xml` 与 ORT `visual.onnx` 算 embedding，断言：两路径 cosine > 0.999，且 `classify_scene` 输出的 (major, minor) 完全一致。脚本骨架：

```python
import sys
from pathlib import Path
import numpy as np
from PIL import Image
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend" / "src"))
from myphoto.tagger import Tagger, classify_scene, flatten_prompts  # noqa

md = REPO / "backend" / "models"
ov = Tagger(md, device="cpu")
# 注入 available 让无 GPU 机器也走 cuda 计划：ORT 收到不存在的 CUDA EP 会
# 自动 warning 并回退 CPU 会话，从而在本机验证 cuda 计划的全部代码路径
onx = Tagger(md, device="cuda", available=["CUDAExecutionProvider", "CPUExecutionProvider"])
for t in (ov, onx):
    t._ensure_loaded()
prompts = flatten_prompts()
for p in sorted((REPO / "prototypes/classify_pipeline/samples").glob("*.*")):
    img = Image.open(p).convert("RGB")
    r1 = ov._clip_scene(img)
    r2 = onx._clip_scene(img)
    cos = float(np.dot(r1[3], r2[3]) / (np.linalg.norm(r1[3]) * np.linalg.norm(r2[3])))
    assert cos > 0.999, (p.name, cos)
    assert (r1[0], r1[1]) == (r2[0], r2[1]), p.name
    print(p.name, f"cosine={cos:.6f}", r1[0], r1[1])
print("ALL MATCH")
```

Run: `.venv/Scripts/python.exe -I prototypes/classify_pipeline/verify_clip_onnx.py`
Expected: 8 行样本结果 + `ALL MATCH`。把实际 cosine 最小值记录到提交说明与最终汇报。

- [ ] **Step 4: 确认产物不入库并提交脚本**

Run: `git status --short`
Expected: `scripts/export_clip_onnx.py` 为 untracked；`backend/models/` 下无任何文件出现（.gitignore 生效）。

```bash
git add scripts/export_clip_onnx.py
git commit -m "build: add CLIP visual ONNX export script for ORT CUDA plan"
```

---

### Task 6: 调用方容错与 tag status 后端标识

**Files:**
- Modify: `backend/src/myphoto/cli.py`（`_build_tagger` L304-311、`tag_status_cmd` L355-383、`tag_run_cmd`/`tag_relabel_cmd` 的不可用提示 L397-402、L467-471）
- Modify: `backend/src/myphoto/main.py`（lifespan L50-61）
- Test: `backend/tests/test_tags.py`（扩展两个 CLI 测试）、`backend/tests/test_main.py`（扩展）

**Interfaces:**
- Consumes: Task 2 `cfg.tagging_device`；Task 3 `Tagger.unavailable_reason()` / `backend_plan`
- Produces: `_build_tagger(cfg, config_path) -> tuple[Tagger|None, str|None]`

- [ ] **Step 1: 写失败测试**

(a) `backend/tests/test_tags.py` 末尾追加：

```python
def test_cli_tag_status_reports_backend_line(tmp_path):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    runner.invoke(cli, ["--config", str(cfg), "add-gallery", "Home"])
    runner.invoke(cli, ["--config", str(cfg), "add-root", "Home", "R", str(photos.resolve())])
    runner.invoke(cli, ["--config", str(cfg), "rescan"])

    r = runner.invoke(cli, ["--config", str(cfg), "tag", "status"])
    assert r.exit_code == 0, r.output
    assert "inference backend" in r.output


def test_cli_tag_run_explicit_cuda_unavailable_has_hint(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        '[tagging]\ndevice = "cuda"\n',
        encoding="utf-8",
    )
    import onnxruntime as ort
    monkeypatch.setattr(ort, "get_available_providers", lambda: ["CPUExecutionProvider"])

    runner = CliRunner()
    runner.invoke(cli, ["--config", str(cfg), "add-gallery", "Home"])
    runner.invoke(cli, ["--config", str(cfg), "add-root", "Home", "R", str(photos.resolve())])
    runner.invoke(cli, ["--config", str(cfg), "rescan"])
    r = runner.invoke(cli, ["--config", str(cfg), "tag", "run"])
    assert r.exit_code != 0
    assert "CUDAExecutionProvider" in r.output
    assert "onnxruntime-gpu" in r.output
```

(b) `backend/tests/test_main.py` 追加：

```python
def test_lifespan_survives_explicit_cuda_unavailable(tmp_path, monkeypatch):
    import onnxruntime as ort
    monkeypatch.setattr(ort, "get_available_providers", lambda: ["CPUExecutionProvider"])
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        '[tagging]\ndevice = "cuda"\n',
        encoding="utf-8",
    )
    app = build_app(config_path=str(cfg_path))
    with TestClient(app):  # 不抛异常即通过：打标禁用、服务照常启动
        assert (tmp_path / "app.db").exists()
```

- [ ] **Step 2: 验证失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_tags.py -k "backend_line or cuda_unavailable" backend/tests/test_main.py::test_lifespan_survives_explicit_cuda_unavailable -v`
Expected: FAIL（输出无 `inference backend`、run 命令提示不含 CUDA 字样）

- [ ] **Step 3: 改 `_build_tagger` 返回原因**

替换 `backend/src/myphoto/cli.py` 的 `_build_tagger`：

```python
def _build_tagger(cfg, config_path: str | None) -> tuple:
    """返回 (tagger, reason)：成功 (tagger, None)，不可用 (None, 中文原因)。"""
    if not cfg.tagging_enabled:
        return None, "[tagging].enabled=false，智能标签已关闭"
    from myphoto.tagger import Tagger

    tagger = Tagger(
        resolve_models_dir(cfg, resolve_config_path(config_path)),
        device=cfg.tagging_device,
    )
    if tagger.available():
        return tagger, None
    return None, tagger.unavailable_reason() or "tagger models missing"
```

- [ ] **Step 4: 改 tag status 输出**

替换 `tag_status_cmd` 内的 ready 判断两行（现有 L371-372）：

```python
            tagger, reason = _build_tagger(cfg, ctx.obj["config_path"])
            if tagger is not None:
                click.echo("models ready: yes")
                if tagger.backend_plan == "cuda":
                    click.echo("inference backend: cuda (ONNX Runtime GPU)")
                else:
                    click.echo("inference backend: openvino (Intel GPU/CPU auto)")
            else:
                click.echo(f"models ready: NO（{reason}）")
```

（`providers` 局部变量若不用则删掉那一行，保持无 unused 变量。）

- [ ] **Step 5: 改 run / relabel 的错误提示**

两处现有 `tagger = _build_tagger(...)` + `if tagger is None: raise ClickException(...)` 统一改为：

```python
            tagger, reason = _build_tagger(cfg, ctx.obj["config_path"])
            if tagger is None:
                raise click.ClickException(f"tagger 不可用：{reason}")
```

- [ ] **Step 6: 改 main.py lifespan**

替换 `backend/src/myphoto/main.py` 现有 L50-61 的 tagger 构造块：

```python
        # 智能打标：enabled && scan_on_import && 模型/后端就位才传给 Scanner；
        # 显式 cuda 不可用或缺模型时 tagger=None，打标禁用但服务正常启动。
        tagger = None
        if cfg.tagging_enabled and cfg.tagging_scan_on_import:
            from myphoto.tagger import Tagger

            candidate = Tagger(
                resolve_models_dir(cfg, config_file),
                device=cfg.tagging_device,
            )
            if candidate.available():
                tagger = candidate
            else:
                log.warning(
                    "tagging disabled: %s", candidate.unavailable_reason(),
                )
```

- [ ] **Step 7: 验证通过并全量回归**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_tags.py backend/tests/test_main.py backend/tests/test_cli.py -q`
Expected: 全绿。再跑 `.venv/Scripts/python.exe -m pytest backend/tests -q` 确认全套通过。

- [ ] **Step 8: 提交**

```bash
git add backend/src/myphoto/cli.py backend/src/myphoto/main.py backend/tests/test_tags.py backend/tests/test_main.py
git commit -m "feat(cli): surface inference backend and CUDA-unavailable reasons"
```

---

### Task 7: 文档与基准脚本

**Files:**
- Modify: `docs/deployment.md`（智能标签模型部署节内新增 CUDA 小节）
- Modify: `README.md`、`README.zh-CN.md`（配置表加 device 行、模型树加 visual.onnx、硬件段更新）
- Modify: `docs/tags-upgrade-design.md`（§7.3 双机适配标记已实现）
- Modify: `THIRD_PARTY_NOTICES.md`（onnxruntime-gpu 与 CUDA/cuDNN 说明）
- Modify（本地，不提交）: `prototypes/classify_pipeline/bench_face_timing.py`

**Interfaces:** 无代码接口变化，纯文档。

- [ ] **Step 1: deployment.md 新增 "CUDA 加速（NVIDIA 显卡）" 小节**

位置：智能标签模型部署节 "1. Python 依赖" 之后、"2. 模型文件目录布局" 之前。内容要点（写成完整中文段落）：

- 互斥安装：`pip uninstall onnxruntime` 后 `pip install onnxruntime-gpu`，两包不能共存
- 系统前置：NVIDIA 驱动、CUDA 12.x、cuDNN 9；insightface 2.1 内置 `preload_dlls()` 自动发现 pip 环境中的 CUDA 库
- `config.toml` 设 `[tagging] device = "cuda"`；`auto` 会在探测到 CUDA EP 时自动启用
- cuda 计划额外需要 `backend/models/clip-onnx/visual.onnx`（由 `scripts/export_clip_onnx.py` 在任一装了 CPU torch 的机器上导出后拷贝）
- 验证：`myphoto tag status` 应打印 `inference backend: cuda (ONNX Runtime GPU)`；显式 cuda 不可用时启动日志/CLI 会给出安装提示
- 说明 CLIP text 塔仍在 CPU（仅启动时一次性预计算），不影响单张耗时

- [ ] **Step 2: 两份 README 同步**

- 配置参考表 `[tagging]` 组增加一行：`device`，默认 `"auto"`，合法值 `auto|cpu|cuda`，说明 cuda 需 onnxruntime-gpu
- 模型目录树在 `clip-ov/` 后加 `clip-onnx/visual.onnx`（注释：仅 cuda 计划需要，约数百 MB）
- 硬件段把"没有 CUDA 执行路径、N 卡闲置"改为：安装 onnxruntime-gpu 并设 `device="cuda"` 后四个模型走 ORT GPU；不装则维持 OpenVINO/CPU 现状
- 两份文档措辞各自语言，锚点与既有章节风格一致

- [ ] **Step 3: tags-upgrade-design.md §7.3 更新**

把 "### 6.3 双机适配"（原文设想 onnxruntime-cuda/openvino-gpu/openvino-cpu 三分支探测）段尾加实现状态注记：

```markdown
> **2026-11 实现状态**：已落地为 `[tagging].device = auto|cpu|cuda` 两计划
> （cuda=全模型 ORT GPU，openvino=本节原路径），详见
> `docs/superpowers/specs/2026-11-15-tagger-cuda-execution-provider-design.md`。
```

- [ ] **Step 4: THIRD_PARTY_NOTICES.md 补一行**

第 2 节后端依赖表 onnxruntime 行后补充：onnxruntime-gpu 同为 MIT；CUDA Toolkit / cuDNN 二进制遵循 NVIDIA 各自 EULA，由使用者自行安装、本项目不重新分发。

- [ ] **Step 5: bench 脚本加 provider 打印（本地文件，prototypes/ 不入库）**

在 `prototypes/classify_pipeline/bench_face_timing.py` 的 `tagger._ensure_loaded()` 后加：

```python
    print("backend_plan:", tagger.backend_plan)
    print("recog providers:", recog.get_providers())
    print("scrfd providers:", scrfd.session.get_providers())
```

- [ ] **Step 6: 提交文档**

```bash
git add docs/deployment.md README.md README.zh-CN.md docs/tags-upgrade-design.md THIRD_PARTY_NOTICES.md
git commit -m "docs: document CUDA execution provider setup and device config"
```

---

### Task 8: 最终全量验证

**Files:** 无新增改动。

- [ ] **Step 1: 后端全套测试**

Run: `.venv/Scripts/python.exe -m pytest backend/tests -q`
Expected: 全绿，总数 = 729 基线 + 20 新增（inference 8 + config 4 + gating 5 + CLI/启动 3）= 749 passed，6 skipped（若数字有出入，核对每个新测试是否真实通过而非跳过）

- [ ] **Step 2: 类型/导入健全性**

Run: `.venv/Scripts/python.exe -c "import myphoto.tagger, myphoto.inference, myphoto.config, myphoto.cli, myphoto.main; print('imports OK')"`
Expected: `imports OK`，无 transformers torch 警告刷屏

- [ ] **Step 3: 真实模型冒烟（OpenVINO 计划，本机）**

Run: `.venv/Scripts/python.exe -m myphoto.cli --config config.toml tag status`
Expected: `models ready: yes` + `inference backend: openvino (Intel GPU/CPU auto)`

- [ ] **Step 4: git 状态确认**

Run: `git status --short && git log --oneline -8`
Expected: 工作区干净（prototypes/ 与 backend/models/ 改动不出现）；7 个新提交按 Task 1-7 顺序在列。

- [ ] **Step 5: 交付汇报必须如实包含**

- 本机无 N 卡：CUDA 计划只做了 ORT-CPU 会话级功能验证（Task 5 Step 3），**GPU 加速比未实测**
- 3060 主机验证清单：装 onnxruntime-gpu → 拷 visual.onnx → 设 device="cuda" → `tag status` 确认 backend 行 → 跑 bench 脚本同机对比 CPU/CUDA 数字并回报
- visual.onnx 实际体积与双路径 cosine 最小值（Task 5 实测值）
