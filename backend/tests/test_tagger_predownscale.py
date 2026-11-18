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


def test_tag_model_version_bumped_for_moon_category():
    # 提示词集合变化（新增月亮类目）必须 bump 版本戳，供库内向量来源追溯；
    # relabel 据此把旧戳图片重算到新体系
    assert TAG_MODEL_VERSION == "clip-v4-moon-category"
