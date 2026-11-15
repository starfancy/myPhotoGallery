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
        # dynamo=False：经典 TorchScript 导出器，只需 onnx 包；torch>=2.9 默认
        # 的 dynamo 导出器还要 onnxscript，对这个静态视觉模型没有额外收益。
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
            dynamo=False,
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
