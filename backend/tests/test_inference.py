"""inference 设备/provider 决策纯函数（不加载任何模型）。"""

import sys

import onnxruntime as ort
import pytest

from myphoto.services.inference import (
    BackendUnavailable,
    preload_cuda_dlls,
    resolve_backend,
    select_ort_providers,
)

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


def _runtime_dll_names() -> list[str]:
    if sys.platform == "win32":
        return ["cudart64_13.dll", "cudart64_12.dll"]
    return ["libcudart.so.13", "libcudart.so.12"]


def test_preload_cuda_dlls_ignores_missing_libraries(monkeypatch, tmp_path):
    # PATH 指向空目录（模拟 CI/无 GPU 机器）：真实调一次 ORT 预加载，
    # ORT 约定缺失库忽略而非报错，调用必须安全返回。
    monkeypatch.setenv("PATH", str(tmp_path))
    preload_cuda_dlls()


def test_preload_skips_ort_call_when_cuda_runtime_in_bin_root(tmp_path, monkeypatch):
    # CUDA 12 / pip nvidia-* 包布局：运行库直接在 PATH 目录（bin）内。
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in _runtime_dll_names():
        (bindir / name).write_bytes(b"")
    monkeypatch.setenv("PATH", str(bindir))
    calls = []
    monkeypatch.setattr(ort, "preload_dlls", lambda: calls.append(1))
    preload_cuda_dlls()
    assert calls == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows CUDA 13 bin/x64 布局")
def test_preload_skips_ort_call_when_cuda_runtime_in_x64_subdir(tmp_path, monkeypatch):
    # CUDA 13 Windows Toolkit 布局：PATH 条目是 bin，运行库在其 x64 子目录。
    x64dir = tmp_path / "bin" / "x64"
    x64dir.mkdir(parents=True)
    for name in _runtime_dll_names():
        (x64dir / name).write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    calls = []
    monkeypatch.setattr(ort, "preload_dlls", lambda: calls.append(1))
    preload_cuda_dlls()
    assert calls == []


def test_preload_calls_ort_when_no_cuda_runtime_on_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    calls = []
    monkeypatch.setattr(ort, "preload_dlls", lambda: calls.append(1))
    preload_cuda_dlls()
    assert calls == [1]
