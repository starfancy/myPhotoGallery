"""Tagger 文件门控与后端计划：只造空文件，绝不加载真实模型。"""

from pathlib import Path

from myphoto.services.tagger import Tagger

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
