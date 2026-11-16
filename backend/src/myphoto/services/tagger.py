"""智能打标引擎：CLIP 场景分类 + YOLO 人数检测 + InsightFace 人脸向量。

纯引擎层（不碰 DB）；模型懒加载——构造 Tagger 不加载任何模型，首次
``tag()`` 时才编译/加载。web 服务在无模型环境下照常启动（``available()``
为 False，scanner 自动跳过打标）。

性能基线（i5-11320H + Iris Xe，OpenVINO GPU）：合并管线 ~150ms/张。
设计文档：docs/tags-upgrade-design.md §3、§6、§7。
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image as PILImage

from myphoto.imaging.preprocess import CLIP_SHORTEST_EDGE, resize_shortest_edge
from myphoto.services.inference import BackendUnavailable, resolve_backend

log = logging.getLogger("myphoto.tagger")

# 模型版本戳：
# - TAG_MODEL_VERSION 写入 images.tag_model_version / image_embeddings.model_version，
#   换模型/调提示词/改预处理几何时 bump，CLI 可据此决定重打；cover 路由也据此判别
#   face_embeddings.bbox 是归一化分数还是 legacy 像素坐标。
# - FACE_MODEL_VERSION 仅盖人脸模型，写入 face_embeddings.model_version；bbox 几何
#   归一化不 bump 它，所以不能靠 face 行自己的戳判别 bbox 年代（见 bbox_is_normalized）。
TAG_MODEL_VERSION = "clip-v3-predownscale"
CLIP_MODEL_VERSION = "clip-vit-b32-v2"
FACE_MODEL_VERSION = "w600k-mbf-v1"

# 归一化 [0,1] bbox 自 clip-v3 起引入；未来 bump 版本戳若仍保持归一化几何，
# 必须把新戳追加进此集合（精确相等会在 bump 后静默退回像素解释）。
NORMALIZED_BBOX_TAGS = frozenset({"clip-v3-predownscale"})

# 两级分类体系 V2（原型实测：一级 ~93%、二级 ~83%）。
# 结构：{一级: {二级: [prompt, ...]}}；prompt 级 score 取组内 max。
HIERARCHY: dict[str, dict[str, list[str]]] = {
    "自然风光": {
        "山景": ["a photo of mountains", "a photo of a mountain peak", "a photo of misty mountain forest"],
        "海滩海岸": ["a photo of a beach", "a photo of a coastline", "a photo of the sea shore"],
        "森林": ["a photo of a forest", "a photo of tall trees in woods"],
        "湖泊": ["a photo of a lake", "a photo of a calm lake with reflection"],
        "河流溪流": ["a photo of a river", "a photo of a stream in valley"],
        "瀑布": ["a photo of a waterfall", "a photo of water falling down rocks"],
        "田野草原": ["a photo of terraced fields", "a photo of rice paddy fields", "a photo of open grassland"],
        "沙漠": ["a photo of desert landscape", "a photo of sand dunes"],
        "雪景": ["a photo of snow", "a photo of snow covered mountains"],
        "天空云": ["a photo of blue sky with clouds", "a photo of dramatic sky"],
    },
    "植物花卉": {
        "花卉特写": ["a close-up of flowers", "a close-up of blooming flowers", "a photo of yellow chrysanthemums", "a photo of lotus flower"],
        "花园花坛": ["a photo of a botanical garden", "a photo of a flower bed"],
        "树木树叶": ["a photo of green leaves", "a photo of autumn foliage", "a photo of bare tree branches against sky"],
        "草地": ["a photo of a lawn", "a photo of green grass field"],
    },
    "城市建筑": {
        "城市天际线": ["a photo of a daytime city skyline", "a photo of tall modern buildings"],
        "街道街景": ["a photo of a city street", "a photo of a shopping street", "a photo of a tree-lined road"],
        "古建筑": ["a photo of a traditional Chinese building", "a photo of a cathedral church", "a photo of an ancient pagoda"],
        "现代建筑": ["a photo of modern architecture", "a photo of a shopping mall plaza"],
        "夜景": ["a photo of city skyline at night with lights", "a photo of urban night scene", "a photo of city night lights"],
        "桥梁": ["a photo of a bridge", "a photo of a bridge over river"],
        "运动场地": ["a photo of a basketball court", "a photo of a sports field"],
    },
    "人物": {
        "单人肖像": ["a close-up portrait of a person", "a photo of a person portrait", "a photo of a person looking at camera", "a photo of a person posing for photo"],
        "多人合影": ["a photo of a group of people", "a photo of friends together"],
        "人文抓拍": ["a photo of a person walking on street", "a photo of street photography of people", "a photo of a person in urban environment"],
    },
    "室内家居": {
        "客厅": ["a photo of a living room interior"],
        "厨房": ["a photo of a kitchen interior"],
        "卧室": ["a photo of a bedroom interior"],
        "办公室": ["a photo of an office interior"],
        "餐厅": ["a photo of a restaurant interior"],
    },
    "食物": {
        "正菜肴馔": ["a photo of a plated meal", "a photo of a restaurant table with dishes", "a photo of cooked food on plate"],
        "甜点": ["a photo of a dessert", "a photo of a cake"],
        "水果": ["a photo of fresh fruits", "a photo of apples and peaches"],
        "饮品": ["a photo of a cup of coffee", "a photo of drinks"],
    },
    "宠物动物": {
        "狗": ["a photo of a dog"],
        "猫": ["a photo of a cat"],
        "鸟类": ["a photo of a bird"],
        "野生动物": ["a photo of a wild animal like elephant or deer", "a photo of wildlife"],
    },
    "交通工具": {
        "汽车": ["a photo of a car on road"],
        "飞机": ["a photo of an airplane"],
        "火车": ["a photo of a train"],
    },
    "文档截图": {
        "打印文档": ["a close-up of a printed paper document"],
        "电脑屏幕": ["a screenshot of a computer screen showing text"],
        "白板": ["a photo of a whiteboard covered with writing"],
    },
}

# YOLO COCO 类别 0 = person
_YOLO_PERSON_CLS = 0
_YOLO_CONF_THRESHOLD = 0.25
_YOLO_NMS_IOU = 0.45
_FACE_DET_THRESHOLD = 0.5


@dataclass(frozen=True)
class FaceResult:
    # (x1, y1, x2, y2) 归一化分数 [0,1]：x 占宽、y 占高，相对送入打标器且已
    # EXIF 转正的图像。分数与解码分辨率无关（大 JPEG 可能按 DCT 半分辨率解码）。
    bbox: tuple[float, float, float, float]
    confidence: float
    embedding: np.ndarray  # 512 维 float32，已 L2 归一化


@dataclass(frozen=True)
class TagResult:
    scene_major: str
    scene_minor: str
    scene_conf: float
    person_count: int
    image_embedding: np.ndarray  # 512 维 float32，已 L2 归一化
    faces: list[FaceResult] = field(default_factory=list)


def flatten_prompts() -> list[tuple[str, str, str]]:
    """展开 HIERARCHY 为 (一级, 二级, prompt) 列表，顺序即文本向量矩阵行号。"""
    out: list[tuple[str, str, str]] = []
    for cat1, subs in HIERARCHY.items():
        for cat2, prompts in subs.items():
            for prompt in prompts:
                out.append((cat1, cat2, prompt))
    return out


def classify_scene(
    similarities: np.ndarray,
    flat_prompts: list[tuple[str, str, str]] | None = None,
) -> tuple[str, str, float]:
    """纯函数：prompt 级 cosine 得分 → (一级, 二级, 二级得分)。

    二级得分 = 该 (一级, 二级) 下所有 prompt 得分的 max；
    一级得分 = 其下所有二级得分的 max；最终在 top1 一级内取 top2 二级。
    与原型 eval_hierarchy.py 完全一致。
    """
    prompts = flat_prompts or flatten_prompts()
    sims = np.asarray(similarities, dtype=np.float64).reshape(-1)

    cat2_scores: dict[tuple[str, str], float] = {}
    for j, (c1, c2, _) in enumerate(prompts):
        key = (c1, c2)
        cat2_scores[key] = max(cat2_scores.get(key, -9.0), float(sims[j]))

    cat1_scores: dict[str, float] = {}
    for (c1, _c2), s in cat2_scores.items():
        cat1_scores[c1] = max(cat1_scores.get(c1, -9.0), s)

    top1 = max(cat1_scores.items(), key=lambda kv: kv[1])[0]
    top2, top2_score = max(
        ((c2, s) for (c1, c2), s in cat2_scores.items() if c1 == top1),
        key=lambda kv: kv[1],
    )
    return top1, top2, top2_score


class Tagger:
    """CLIP + YOLO + InsightFace 三合一打标器（懒加载、线程安全）。

    设计 §3.1：打标在 scanner 的 worker 线程里同步调用；多 hash_worker
    并发进来时由 ``_lock`` 串行化推理（机械硬盘场景设计上就是单线程 IO）。
    """

    def __init__(self, models_dir: str | Path, device: str = "auto", available=None):
        """available 仅测试注入；生产传 None 由 inference 模块查 ORT。

        构造不加载模型、不抛 BackendUnavailable：显式 cuda 不可用时记录
        原因并兜底 openvino 计划，调用方经 unavailable_reason()/available()
        决定是否启用，保证 web 服务永远能启动。ORT providers 在构造时一次性
        算好（注入 available 时同样生效），_ensure_loaded 直接复用，不再
        重新探测——这样无 GPU 机器也能注入 provider 列表走 cuda 计划代码。
        """
        from myphoto.services.inference import select_ort_providers

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

    # ---------- 可用性（不加载模型） ----------

    def expected_paths(self) -> dict[str, Path]:
        md = self.models_dir
        paths = {
            "clip_tokenizer": md / "clip-vit-base-patch32",
            "yolo_onnx": md / "yolo11n.onnx",
            "face_det_onnx": md / "insightface" / "det_500m.onnx",
            "face_rec_onnx": md / "insightface" / "w600k_mbf.onnx",
            # text 塔两计划共用，始终走 OpenVINO CPU
            "clip_text_xml": md / "clip-ov" / "text.xml",
        }
        if self.backend_plan == "cuda":
            paths["clip_visual_onnx"] = md / "clip-onnx" / "visual.onnx"
        else:
            paths["clip_visual_xml"] = md / "clip-ov" / "visual.xml"
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

    # ---------- 懒加载 ----------

    def _resolve_device(self, core) -> str:
        # openvino 计划内部的 Intel GPU/CPU 探测；device="cpu" 显式强制 CPU
        if self.device == "cpu":
            return "CPU"
        return "GPU" if "GPU" in core.available_devices else "CPU"

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        reason = self.unavailable_reason()
        if reason is not None:
            raise RuntimeError(reason)

        from openvino.runtime import Core  # heavy import
        # 本项目只用 CLIPProcessor 的 PIL/numpy 预处理路径，不实例化任何 HF
        # 模型类，因此运行时不需要 PyTorch。未装 torch 时 transformers 会在
        # import 期打 advisory 警告（"PyTorch was not found. Models won't be
        # available ..."），用官方环境变量抑制；setdefault 保留用户覆盖权。
        os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
        from transformers import CLIPProcessor

        md = self.models_dir
        core = Core()
        is_cuda = self.backend_plan == "cuda"
        if is_cuda:
            # 显式传 providers 建会话不会触发 ORT 内部的 DLL 预加载，必须
            # 自己先调一次：从 pip nvidia-* 包等位置加载 CUDA/cuDNN，否则
            # 会在首个 Conv 算子报 cudnn64_9.dll LoadLibrary failed (error 2)
            from myphoto.services.inference import preload_cuda_dlls

            preload_cuda_dlls()
        log.info(
            "tagger loading models from %s (backend_plan=%s)", md, self.backend_plan,
        )

        # ---- CLIP：processor 与 text 塔两计划共用；visual 按计划分后端 ----
        self._clip_proc = CLIPProcessor.from_pretrained(str(md / "clip-vit-base-patch32"))
        self._flat_prompts = flatten_prompts()

        # text 塔始终 OpenVINO CPU：只在加载时预计算一次提示词向量，不进单张热路径
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
            device = "ORT"
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

        # warmup：避免第一张图付编译/分配开销
        dummy_img = np.zeros((1, 3, 224, 224), dtype=np.float32)
        if is_cuda:
            self._clip_visual_ort.run(
                None, {self._clip_visual_ort.get_inputs()[0].name: dummy_img},
            )
            self._yolo_ort.run(
                None, {self._yolo_input: np.zeros((1, 3, 640, 640), dtype=np.float32)},
            )
        else:
            _ = self._clip_visual({self._clip_visual.inputs[0]: dummy_img})
            _ = self._yolo_compiled({self._yolo_input: np.zeros((1, 3, 640, 640), dtype=np.float32)})

        self._loaded = True
        log.info(
            "tagger models loaded (%d prompts, backend_plan=%s, device=%s)",
            len(self._flat_prompts), self.backend_plan, device,
        )

    # ---------- 推理 ----------

    def tag(self, image: PILImage.Image) -> TagResult:
        """对一张 RGB PIL 图打标；线程安全（内部锁串行化）。"""
        with self._lock:
            self._ensure_loaded()
            rgb = image.convert("RGB")
            scene_major, scene_minor, scene_conf, img_emb = self._clip_scene(rgb)
            person_count, person_boxes = self._count_persons(rgb)
            faces = self._extract_faces(rgb, person_boxes) if person_boxes else []
            return TagResult(
                scene_major=scene_major,
                scene_minor=scene_minor,
                scene_conf=scene_conf,
                person_count=person_count,
                image_embedding=img_emb,
                faces=faces,
            )

    def classify_embedding(self, img_embedding: np.ndarray) -> tuple[str, str, float]:
        """基于已存的图像向量重算场景标签（relabel 用，不跑视觉模型）。"""
        with self._lock:
            self._ensure_loaded()
            emb = np.asarray(img_embedding, dtype=np.float32).reshape(1, -1)
            emb = emb / np.linalg.norm(emb, axis=-1, keepdims=True)
            sims = (emb @ self._clip_text_emb.T).squeeze(0)
            return classify_scene(sims, self._flat_prompts)

    def _clip_scene(self, rgb: PILImage.Image) -> tuple[str, str, float, np.ndarray]:
        small = resize_shortest_edge(rgb, CLIP_SHORTEST_EDGE)
        x = self._clip_proc(images=small, return_tensors="np")
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

    def _yolo_infer(self, arr: np.ndarray) -> np.ndarray:
        """单张 letterbox 批次 (1,3,640,640) → (84,8400)，两后端输出同构。"""
        if self.backend_plan == "cuda":
            return self._yolo_ort.run(None, {self._yolo_input: arr})[0][0]
        out = self._yolo_compiled({self._yolo_input: arr})
        return next(iter(out.values()))[0]

    def _count_persons(self, rgb: PILImage.Image) -> tuple[int, list[tuple[int, int, int, int]]]:
        """YOLO person 检测 + NMS；返回 (人数, 原图坐标 person 框)。"""
        import cv2

        arr, scale, left, top = _letterbox(rgb, 640)
        preds = self._yolo_infer(arr)  # (84, 8400)
        boxes = preds[:4, :]
        scores_all = preds[4:, :]
        cls_ids = scores_all.argmax(axis=0)
        confs = scores_all.max(axis=0)

        keep = (cls_ids == _YOLO_PERSON_CLS) & (confs > _YOLO_CONF_THRESHOLD)
        if not keep.any():
            return 0, []

        # letterbox 坐标 → 原图坐标
        lb_boxes = []
        lb_confs = []
        for i in np.where(keep)[0]:
            cx, cy, w, h = boxes[:, i]
            x1 = (cx - w / 2 - left) / scale
            y1 = (cy - h / 2 - top) / scale
            x2 = (cx + w / 2 - left) / scale
            y2 = (cy + h / 2 - top) / scale
            lb_boxes.append([float(x1), float(y1), float(x2 - x1), float(y2 - y1)])
            lb_confs.append(float(confs[i]))

        idxs = cv2.dnn.NMSBoxes(lb_boxes, lb_confs, _YOLO_CONF_THRESHOLD, _YOLO_NMS_IOU)
        if idxs is None or len(idxs) == 0:
            return 0, []
        idxs = np.asarray(idxs).reshape(-1)
        w, h = rgb.size
        person_boxes: list[tuple[int, int, int, int]] = []
        for i in idxs:
            bx, by, bw, bh = lb_boxes[int(i)]
            x1 = max(0, int(bx))
            y1 = max(0, int(by))
            x2 = min(w, int(bx + bw))
            y2 = min(h, int(by + bh))
            if x2 > x1 and y2 > y1:
                person_boxes.append((x1, y1, x2, y2))
        return len(person_boxes), person_boxes

    def _extract_faces(
        self, rgb: PILImage.Image, person_boxes: list[tuple[int, int, int, int]],
    ) -> list[FaceResult]:
        """InsightFace 检测 + 对齐 + embedding。person_boxes 仅用于决定是否
        有人（V1：全图跑 SCRFD，不按 person 框裁剪）。"""
        from insightface.utils import face_align

        arr = np.asarray(rgb)[:, :, ::-1]  # RGB → BGR
        bboxes, kps = self._scrfd.detect(arr, det_thresh=_FACE_DET_THRESHOLD)
        faces: list[FaceResult] = []
        for j in range(len(bboxes)):
            box = bboxes[j][:4]
            conf = float(bboxes[j][4])
            aligned = face_align.norm_crop(arr, kps[j], image_size=112)
            blob = aligned.transpose(2, 0, 1).astype(np.float32)
            blob = (blob - 127.5) / 127.5
            blob = blob[None, ...]
            emb = self._recog.run(None, {self._recog.get_inputs()[0].name: blob})[0][0]
            emb = emb / np.linalg.norm(emb)
            # box 在 rgb（可能是 DCT 半分辨率解码图）的像素空间；归一化为分数，
            # 落库后由 cover 路由按全分辨率转正原图还原（奇数边草稿不是精确 2x）。
            box_f = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
            faces.append(FaceResult(
                bbox=normalize_bbox(box_f, rgb.size),
                confidence=conf, embedding=emb,
            ))
        return faces


def normalize_bbox(
    box: tuple[float, float, float, float],
    size: tuple[int, int],
) -> tuple[float, float, float, float]:
    """像素框 → 占图像宽/高的 [0,1] 分数（x 除宽、y 除高）。

    size 为 PIL 的 ``(w, h)``，即 box 所在像素空间的尺寸。分数坐标与解码
    分辨率无关：大 JPEG 经 DCT 半分辨率（奇数边时甚至不是精确 1/2）解码后
    检出的框，归一化后仍可映射回全分辨率原图。
    """
    w, h = size
    x1, y1, x2, y2 = box
    return x1 / w, y1 / h, x2 / w, y2 / h


def bbox_is_normalized(tag_model_version: str | None) -> bool:
    """face_embeddings.bbox 是否为归一化分数坐标，按图片的 tag_model_version 判定。

    命中显式 allow-set ``NORMALIZED_BBOX_TAGS`` 才为 True（None / legacy 戳 /
    未登记的未来戳均为 False，按像素坐标解释；无 wildcard 或前缀匹配）。
    bump TAG_MODEL_VERSION 后若 bbox 几何仍归一化，必须同步把新戳加进集合，
    否则 test_normalized_bbox_allow_set_must_cover_current_stamp 会响亮失败。

    不能看 face_embeddings.model_version：那只是人脸模型戳 FACE_MODEL_VERSION，
    bbox 几何改动前后未变，无法区分管线年代。
    """
    return tag_model_version in NORMALIZED_BBOX_TAGS


def denormalize_bbox(
    bbox: tuple[float, float, float, float],
    image_size: tuple[int, int],
    normalized: bool,
) -> tuple[float, float, float, float]:
    """cover 渲染用：归一化分数按 EXIF 转正后原图尺寸还原为像素框；
    legacy 像素框原样返回（统一转 float），image_size 不参与。"""
    x1, y1, x2, y2 = bbox
    if not normalized:
        return float(x1), float(y1), float(x2), float(y2)
    w, h = image_size
    return x1 * w, y1 * h, x2 * w, y2 * h


def _letterbox(img: PILImage.Image, size: int = 640):
    """YOLO 标准 letterbox：等比缩放 + 边缘补灰。返回 (CHW float32 batch, scale, left, top)。"""
    w, h = img.size
    scale = min(size / w, size / h)
    nw, nh = int(w * scale), int(h * scale)
    resized = img.resize((nw, nh), PILImage.BILINEAR)
    canvas = PILImage.new("RGB", (size, size), (114, 114, 114))
    left = (size - nw) // 2
    top = (size - nh) // 2
    canvas.paste(resized, (left, top))
    arr = np.asarray(canvas, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)[None, ...]
    return arr, scale, left, top
