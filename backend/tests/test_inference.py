"""inference 设备/provider 决策纯函数（不加载任何模型）。"""

import sys
import types

import onnxruntime as ort
import pytest

from myphoto.services.inference import (
    BackendUnavailable,
    disable_openvino_telemetry,
    preload_cuda_dlls,
    resolve_backend,
    select_ort_providers,
)
import myphoto.services.inference as inf_mod

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


# ---------- disable_openvino_telemetry ----------


def test_disable_telemetry_replaces_backend_sends_with_noop(monkeypatch):
    # 真实 openvino_telemetry 包：patch 后两个发送入口均为 no-op，且幂等。
    # 测试环境未构造过 Core()，顺带覆盖"单例未初始化"的 RuntimeError 分支。
    pytest.importorskip("openvino_telemetry")
    from openvino_telemetry.backend import backend_ga, backend_ga4

    monkeypatch.setattr(inf_mod, "_telemetry_disabled", False)
    disable_openvino_telemetry()
    assert inf_mod._telemetry_disabled is True

    # no-op：任意参数直接返回 None，不触发任何 urlopen
    assert backend_ga4._send_func(object()) is None
    assert backend_ga.GABackend.send(object(), object()) is None

    # 幂等：重复调用安全
    disable_openvino_telemetry()
    assert inf_mod._telemetry_disabled is True


def test_disable_telemetry_silent_when_package_missing(monkeypatch):
    monkeypatch.setattr(inf_mod, "_telemetry_disabled", False)
    # sys.modules 里置 None 会让 `import openvino_telemetry` 抛 ImportError
    monkeypatch.setitem(sys.modules, "openvino_telemetry", None)
    disable_openvino_telemetry()  # 不抛即通过
    assert inf_mod._telemetry_disabled is False


def test_disable_telemetry_force_shuts_down_existing_singleton(monkeypatch):
    # 单例已被更早的 Core() 初始化的分支：consent 置 False 并 force_shutdown。
    monkeypatch.setattr(inf_mod, "_telemetry_disabled", False)

    class FakeTelemetry:
        instances: list["FakeTelemetry"] = []

        def __init__(self):
            self.consent = True
            self.shutdowns: list[float] = []
            FakeTelemetry.instances.append(self)

        def force_shutdown(self, timeout):
            self.shutdowns.append(timeout)

    class FakeGABackend:
        pass

    fake_backends = types.ModuleType("openvino_telemetry.backend")
    fake_backends.backend_ga4 = types.SimpleNamespace(
        _send_func=lambda request_data: "should-be-replaced",
    )
    fake_backends.backend_ga = types.SimpleNamespace(GABackend=FakeGABackend)
    fake_pkg = types.ModuleType("openvino_telemetry")
    fake_pkg.Telemetry = FakeTelemetry
    fake_pkg.backend = fake_backends

    monkeypatch.setitem(sys.modules, "openvino_telemetry", fake_pkg)
    monkeypatch.setitem(sys.modules, "openvino_telemetry.backend", fake_backends)

    disable_openvino_telemetry()

    inst = FakeTelemetry.instances[0]
    assert inst.consent is False
    assert inst.shutdowns == [0.1]
    assert fake_backends.backend_ga4._send_func(123) is None
    assert fake_backends.backend_ga.GABackend.send(None, None) is None
    assert inf_mod._telemetry_disabled is True
