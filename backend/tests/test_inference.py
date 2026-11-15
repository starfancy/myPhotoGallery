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
