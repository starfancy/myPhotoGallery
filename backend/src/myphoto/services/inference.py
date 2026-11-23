"""打标推理后端决策（纯函数，不加载模型，可在无 GPU/无模型环境单测）。

两种加载计划：
- "cuda"：四个模型全部走 ONNX Runtime（CUDAExecutionProvider + CPU 回退）
- "openvino"：CLIP/YOLO 走 OpenVINO（内部再探 Intel GPU→CPU），人脸模型走 ORT CPU
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence

log = logging.getLogger("myphoto.inference")

_CUDA_EP = "CUDAExecutionProvider"
_CPU_EP = "CPUExecutionProvider"
_VALID_DEVICES = ("auto", "cpu", "cuda")

_telemetry_disabled = False


def disable_openvino_telemetry() -> None:
    """关闭 openvino 匿名遥测并收掉它的发送线程（幂等，任何失败静默）。

    实测挂起链路（onnxruntime 1.32 + openvino_telemetry 2025.2，Windows）：
    ``openvino.runtime.Core()`` 构造时初始化遥测单例，事件经
    ThreadPoolExecutor 工作线程 POST 到 google-analytics.com；GA4 后端在
    Windows 上直接 ``urlopen`` 且**无超时**，网络不通时 connect 长期挂起。
    解释器退出阶段 ``concurrent.futures.thread._python_exit`` 会 join 这个
    非 daemon 线程，于是 CLI 活全干完了进程却不退出（只能 Ctrl+C）。

    必须在首次 ``Core()`` 之前调用：把 ga/ga4 两个后端的发送入口替换成
    no-op，发送线程池从此收不到任务；若单例已被更早的调用初始化，再用
    ``consent=False`` + ``force_shutdown`` 兜底。遥测本身与打标无关，任何
    异常都不得影响主流程。
    """
    global _telemetry_disabled
    if _telemetry_disabled:
        return
    try:
        from openvino_telemetry import Telemetry
        from openvino_telemetry.backend import backend_ga, backend_ga4

        # GA4（Windows 路径）：模块级 _send_func 是实际的 urlopen 调用点
        backend_ga4._send_func = lambda request_data: None
        # GA（旧后端，同样无超时裸 urlopen）：堵类方法
        backend_ga.GABackend.send = lambda self, message: None
        # 单例可能已被更早的 Core()/ovc 调用初始化：掐断后续事件并收旧线程
        try:
            tm = Telemetry()
            tm.consent = False
            tm.force_shutdown(timeout=0.1)
        except RuntimeError:
            pass
        _telemetry_disabled = True
    except Exception:
        log.debug("disable_openvino_telemetry failed", exc_info=True)


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


def _find_cuda_runtime_on_path(
    names: tuple[str, ...],
    subdir_combos: tuple[tuple[str, ...], ...],
) -> str | None:
    """在 PATH 目录中查找 CUDA 运行库，返回首个命中的完整路径。

    会额外查每个 PATH 目录下的 ``subdir_combos`` 子目录（Windows CUDA 13
    Toolkit 把运行库放在 ``bin/x64``）。不能用 ``shutil.which``：Python 3.12
    的 which 只返回扩展名命中 PATHEXT（.EXE/.CMD/...）的文件，对 .dll/.so
    恒返回 None——库明明在 PATH 上也会被误判为"未安装"，进而错误触发
    preload_dlls 刷 "Failed to load cudart64_*.dll" 警告（实测全局
    CUDA 13.5 Toolkit 即如此）。
    """
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        for subdirs in subdir_combos:
            candidate_dir = os.path.join(directory, *subdirs)
            for name in names:
                path = os.path.join(candidate_dir, name)
                if os.path.isfile(path):
                    return path
    return None


def preload_cuda_dlls() -> None:
    """建 ORT CUDA 会话前预加载 CUDA/cuDNN DLL（Windows/Linux）。

    显式传 providers 建会话不会触发 ORT/insightface 内部的默认预加载，
    因此 cuda 计划必须自己调一次：它会从 pip 的 nvidia-* 包目录
    （site-packages/nvidia/*/bin）、PyTorch 自带库目录及系统 PATH 查找
    CUDA / cuDNN DLL。ORT 约定缺失的 cuDNN 库只忽略、不报错；老版本
    ORT 没有该 API 时静默跳过。

    若 PATH 已能解析 CUDA 运行库则跳过预加载——两种布局都识别：系统级
    Toolkit 的 CUDA 13 Windows 布局（``...\\CUDA\\v13.5\\bin\\x64``）与
    CUDA 12 / pip nvidia 包的扁平 ``bin`` 布局。系统级安装时 preload_dlls
    只按 pip 包位置找库，强行调用只会刷 "Failed to load ... cublas64_*.dll"
    警告，标准 DLL 搜索本就能让会话正常加载。
    """
    if sys.platform == "win32":
        runtime_names = ("cudart64_13.dll", "cudart64_12.dll")
        subdir_combos: tuple[tuple[str, ...], ...] = ((), ("x64",))
    else:
        runtime_names = ("libcudart.so.13", "libcudart.so.12")
        subdir_combos = ((),)
    if _find_cuda_runtime_on_path(runtime_names, subdir_combos):
        return

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
