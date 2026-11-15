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


def preload_cuda_dlls() -> None:
    """建 ORT CUDA 会话前预加载 CUDA/cuDNN DLL（Windows/Linux）。

    显式传 providers 建会话不会触发 ORT/insightface 内部的默认预加载，
    因此 cuda 计划必须自己调一次：它会从 pip 的 nvidia-* 包目录
    （site-packages/nvidia/*/bin）、PyTorch 自带库目录及系统 PATH 查找
    CUDA 12.x / cuDNN 9.x。ORT 约定缺失的 cuDNN 库只忽略、不报错；
    老版本 ORT 没有该 API 时静默跳过。
    """
    import onnxruntime as ort

    preload = getattr(ort, "preload_dlls", None)
    if callable(preload):
        preload()


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
