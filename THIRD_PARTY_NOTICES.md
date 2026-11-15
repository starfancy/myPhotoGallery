# 第三方组件与模型许可证声明（Third-Party Notices）

本项目自有代码以 **MIT 许可证**发布，见 [LICENSE](LICENSE)
（Copyright (c) 2026 starfancy）。本文件汇总运行、构建本项目所依赖的第三方
软件组件与模型权重的许可证。请注意：**智能标签的模型权重不纳入 git**，由
使用者自行下载部署，其许可证条款独立于本项目的 MIT 许可证，且部分条款比
MIT 更严格（见第 1 节）。

## 1. 模型权重（智能标签功能，需单独下载，约 900 MB）

| 部署路径中的文件 | 来源 | 许可证 / 使用条款 |
| --- | --- | --- |
| `yolo11n.onnx` | Ultralytics YOLO11n，<https://github.com/ultralytics/ultralytics> | **AGPL-3.0-or-later**（PyPI 包许可证字段同为 `AGPL-3.0`）；商业场景可向 Ultralytics 购买企业许可证（Enterprise License）。 |
| `clip-ov/visual.*`、`clip-ov/text.*` | OpenAI CLIP ViT-B/32 权重转换的 OpenVINO IR，上游 <https://github.com/openai/CLIP>、<https://huggingface.co/openai/clip-vit-base-patch32> | **MIT**（Copyright (c) 2021 OpenAI）。IR 仅为格式转换，权重本身不变，许可证不变。 |
| `clip-vit-base-patch32/*` | HuggingFace `openai/clip-vit-base-patch32` 的 tokenizer / processor 配置与 PyTorch 权重 | **MIT**（同上，CLIP 仓库的组成部分）。 |
| `insightface/det_500m.onnx` | InsightFace 模型库的 SCRFD 人脸检测模型（与 buffalo 系列模型包同源），<https://github.com/deepinsight/insightface> | InsightFace **代码**为 MIT；但官方模型库中的**预训练模型仅限非商业研究用途**（non-commercial research purposes only）。 |
| `insightface/w600k_mbf.onnx` | InsightFace 模型库的 ArcFace（MobileFaceNet，WebFace600K 训练）人脸识别模型 | 同上：**仅限非商业研究用途**。根据上游 2025-11-24 声明，开源人脸识别模型（如 buffalo_l 包）的商业授权可邮件联系 `recognition-oss-pack@insightface.ai`。 |

上游原文（InsightFace README，License 节）：

> The code of InsightFace is released under the MIT License. There is no
> limitation for both academic and commercial usage.
>
> The training data containing the annotation (and the models trained with
> these data) are available for non-commercial research purposes only.
>
> Both manual-downloading models from our github repo and auto-downloading
> models with our python-library follow the above license policy (which is
> for non-commercial research purposes only).

### 对部署方式的实际影响

- **个人 / 家庭自托管**：不触发上述限制。AGPL 对个人使用无源代码提供义务；
  个人、研究性质的使用属于非商业场景。
- **向他人开放网络访问（含公网部署）**：AGPL-3.0 的网络使用条款要求你向
  所有能够通过网络使用该服务的人提供完整对应源代码（含你做的修改）。
- **任何商业用途**：InsightFace 两个模型需另行取得商业授权；YOLO11n 需购买
  Ultralytics 企业许可证，或完整履行 AGPL-3.0 义务。CLIP（MIT）无此限制。
- 本仓库 git 内**不含任何模型权重**，MIT 许可证的覆盖范围仅限仓库内的
  自有源代码与文档。

## 2. 后端 Python 依赖（`pyproject.toml` 直接依赖，许可证取自各包元数据）

| 组件 | 许可证 | 用途 |
| --- | --- | --- |
| FastAPI | MIT | Web 框架 |
| Uvicorn | BSD-3-Clause | ASGI 服务器 |
| SQLAlchemy | MIT | ORM / 异步数据库层 |
| aiosqlite | MIT | SQLite 异步驱动 |
| PyJWT | MIT | 会话 JWT |
| bcrypt | Apache-2.0 | 密码哈希 |
| Pillow | MIT-CMU（MIT 变体） | 图像解码 |
| pillow-heif | BSD-3-Clause | HEIF/HEIC 支持 |
| rawpy | MIT | RAW 格式支持 |
| python-multipart | Apache-2.0 | 表单 / 文件上传解析 |
| Click | BSD-3-Clause | CLI 框架 |
| NumPy | BSD-3-Clause | 张量运算 |
| OpenVINO（锁定 2024.6.0） | Apache-2.0 | CLIP / YOLO 推理运行时 |
| onnxruntime | MIT | 人脸识别模型推理运行时 |
| InsightFace（Python 包） | MIT（仅代码；模型条款见第 1 节） | SCRFD 检测与人脸对齐 |
| opencv-python | Apache-2.0 | NMS 等图像处理 |
| Transformers | Apache-2.0 | CLIPProcessor 分词 / 预处理 |

开发依赖（pytest、pytest-asyncio、httpx、anyio）均为 MIT / BSD 系宽松许可证。
完整传递依赖清单及其许可证可在已安装环境的
`.venv/Lib/site-packages/<包>.dist-info/METADATA` 中查阅。

## 3. 前端依赖（`frontend/package.json`）

运行时依赖（均为 **MIT**）：Vue、vue-router、Pinia、PhotoSwipe、
vue-virtual-scroller、@unocss/reset。

构建与测试工具链：Vite、UnoCSS、Vitest、@vitejs/plugin-vue、
@vue/test-utils、jsdom 为 **MIT**；TypeScript 为 **Apache-2.0**。

完整传递依赖可在 `frontend/` 下用 `pnpm licenses list` 生成清单。

## 4. 其他说明

- 仓库根目录的 `Caddyfile` 只是配置片段；Caddy 本体（Apache-2.0）由使用者
  自行安装，不随本项目分发。
- 3D-LUT 滤镜文件（`<data_dir>/luts/`）由使用者自行提供，不属于本项目的
  分发内容。
- 各许可证的完整文本以对应上游仓库 / 包内的 LICENSE 文件为准；本文件如与
  上游条款不一致，以上游条款为准。
