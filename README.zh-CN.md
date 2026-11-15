# myPhotoGallery

[English](README.md) · [简体中文](README.zh-CN.md)

面向家庭网络的自托管照片库 Web 查看器。把磁盘上存放照片的目录登记进来，
即可在流畅的网页界面中浏览；原始照片始终保留在原位。

## 功能特性

- 支持多个图库（gallery），每个图库可挂载任意数量的文件系统根目录
  （root）。扫描以只读方式进行——程序仅有的文件移动操作是：你在界面中
  删除照片时把文件移入该 root 自己的 `.trash/` 目录，以及把它从回收站
  还原。
- 两种角色（admin / viewer）：viewer 按图库授权访问；每个账号还可设置
  局域网 / 远程访问范围（access scope）。
- 回收站保留期可配置：到期前可还原，到期后由每日定时任务自动清理。
- 网格浏览（等高流水 / 瀑布流布局），灯箱内置 EXIF 侧边面板与 RGB
  直方图面板。
- 风格滤镜预览：灯箱顶栏按钮打开独立页面，用 WebGL 2 3D-LUT 套用胶片模拟
  （富士 Classic Chrome / Velvia / Acros 等），支持强度滑块、长按对比原图、
  按滤镜族分组的可折叠缩略条，并可一键导出 1600px 预览尺寸或原分辨率 JPEG。
  LUT 文件放在 `<data_dir>/luts/<分组>/` 下；admin 在 `/admin/luts` 页面
  按分组勾选启用、改名、排序，支持整组全选。
- 文件名 / 文件夹名搜索，范围限定在单个图库 root 内（可锚定某个子目录
  子树）。
- 多图批量打包 ZIP 下载：流式输出、支持 zip64 大文件，服务端限制单次
  打包数量。
- 管理与安全事件审计日志：保留期可配置，可在管理后台审计页导出 CSV。
- 智能标签：完全使用本机模型推理，不访问任何外部服务。CLIP 零样本
  场景分类采用内置两级提示词体系（9 个一级大类、43 个二级细类，带
  置信度），YOLO11n 检测照片人数，InsightFace（SCRFD + ArcFace）
  检测人脸、提取向量并按余弦相似度自动聚类。配套"人物"页
  （`/people`，人物簇可重命名）、浏览页场景分面筛选（状态写入 URL，
  同时过滤图片与子文件夹）、搜索的场景 / 日期筛选，以及管理后台的
  标签分布统计。该功能可选：缺少模型文件时服务照常运行，行为与未
  启用时完全一致。
- 浅色 / 深色主题跟随系统设置；手机端 44px 触控目标，支持键盘与屏幕
  阅读器等无障碍访问。

## 架构

前端是 Vue 3 + Pinia + vue-router 单页应用，由 Vite 构建到
`frontend/dist/`。托管方式二选一：直接由 FastAPI 托管（内置
`StaticFiles` 挂载与 SPA 回退），或使用随仓库提供的 `Caddyfile`，由
Caddy 托管静态资源并把 `/api/*` 反向代理到后端。

后端为 FastAPI + SQLAlchemy（异步），使用单个 SQLite 数据库
（`<data_dir>/app.db`，默认即项目根目录下的 `app.db`，详见
[数据与备份](#数据与备份)）。缩略图尺寸固定
为 200 / 400 / 1600 px，按需生成并缓存于磁盘
`<data_dir>/.cache/thumbnails/`，缓存可随时重建。后台扫描器遍历各 root，
计算文件哈希、读取 EXIF，不改动原始文件。

## 快速开始

需要 Python 3.11+ 与 [pnpm](https://pnpm.io/)。

```bash
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash；PowerShell 用 .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

cd frontend
pnpm install
pnpm build                           # vue-tsc --noEmit && vite build，产物在 frontend/dist/
cd ..

myphoto add-gallery Home
myphoto add-root Home Main /path/to/photos
myphoto rescan Home
myphoto serve                        # host/port 取自 config.toml（默认 0.0.0.0:8080）
```

打开 <http://localhost:8080>。首次启动会随机生成 admin 密码并只在标准
输出打印一次——请记下它，登录后在界面中修改。

其他 CLI 命令：

```bash
myphoto list                                      # 查看图库、root 与图片数量
myphoto rescan-exif [GALLERY] [ROOT_LABEL] [--force]   # 回填 EXIF / 宽高
myphoto reset-password [--username admin] [--password NEW]
```

覆盖配置示例：

```bash
myphoto serve --host 127.0.0.1 --port 9000
myphoto serve --reload                            # 开发模式自动重启（只监视 backend/）
MYPHOTO_CONFIG=/path/to/config.toml myphoto serve
myphoto --config /path/to/config.toml list
```

## 配置

标准配置文件是项目根目录的 `config.toml`。首次运行时自动生成（含随机
`jwt_secret`）；除非通过 `--config` / `MYPHOTO_CONFIG` 另行指定，CLI
与服务端无论在哪个工作目录下启动，都使用该文件。部分运行期取值也可以
在管理后台的设置页修改。

### 配置项参考

| 配置段 · 键 | 默认值 | 合法值 | 说明 |
| --- | --- | --- | --- |
| `[app] listen_host` | `"0.0.0.0"` | IP 地址 | 监听地址。与反向代理同机部署时建议设为 `127.0.0.1`。 |
| `[app] listen_port` | `8080` | 整数（合法 TCP 端口） | 监听端口。 |
| `[app] jwt_secret` | 首次运行随机生成 | 字符串 | 会话 JWT 的 HMAC 密钥，必填；更换后所有现有会话失效。 |
| `[app] session_hours` | `8` | 整数小时（设置页限制 1–720） | 会话有效时长，对新登录生效。 |
| `[app] data_dir` | 配置文件所在目录（自动生成的模板不含此键；可自行设置 `data_dir = "db"`，把 `app.db`/`.cache/` 收进 `db/` 目录） | 目录路径 | 存放 `app.db` 与 `.cache/`；相对路径相对于 `config.toml` 所在目录解析。 |
| `[trash] retention_days` | `30` | 整数天数；`0` = 永不自动清理（设置页提供 7 / 30 / 90 / 0） | 已删除图片可还原的保留天数。 |
| `[trash] purge_hour` | `3` | `0`–`23` | 每日定时清理的本地时间小时。 |
| `[trash] purge_minute` | `30` | `0`–`59` | 每日定时清理的本地时间分钟。 |
| `[security] trusted_proxies` | `[]` | IP / CIDR 字符串数组 | 仅信任来自这些来源的 `X-Forwarded-For`；留空表示忽略该请求头（防止伪造）。 |
| `[security] login_lockout_threshold` | `5` | 整数（设置页限制 1–100） | 连续登录失败达到该次数后临时锁定。 |
| `[security] login_lockout_minutes` | `15` | 整数（分钟） | 锁定时长；仅可在配置文件中修改（设置页未提供）。 |
| `[scanner] hash_workers` | 注释状态——源码默认 `min(8, CPU 核数)` | 正整数 | 扫描时计算哈希、读取 EXIF 的工作线程数；机械硬盘或 SMB/NFS 网络盘可调小（如 `2`）。 |
| `[download] batch_limit` | `100` | `10`–`200`（越界自动钳制） | 单次批量 ZIP 下载的图片数上限，对所有用户生效。 |
| `[audit] retention_days` | `180` | `0`、`30`、`90`、`180`、`365`（`0` = 永不清理；其他整数钳制到最近的合法值） | 审计日志保留天数；启动时与每日定时任务都会清理过期记录。 |
| `[tagging] enabled` | `true` | 布尔值 | 智能标签总开关；为 false 时后台扫描器与 `myphoto tag` CLI 都不加载任何模型。 |
| `[tagging] scan_on_import` | `true` | 布尔值 | 服务端后台扫描器对新增 / 变化图片同步打标；未变化文件不会进入模型。`enabled = false` 或模型缺失时无效。 |
| `[tagging] models_dir` | `"backend/models"` | 目录路径 | 打标模型所在目录；相对路径相对于 `config.toml` 所在目录解析。见[智能标签（可选）](#智能标签可选)。 |
| `[tagging] device` | `"auto"` | `auto` / `cpu` / `cuda` | 推理后端选择。`auto` 在安装了 onnxruntime-gpu 时走 ORT CUDA，否则走 OpenVINO 计划；显式写 `cuda` 但环境不具备时打标禁用并明确报错，不静默回退。 |

补充说明：

- 缩略图尺寸（200 / 400 / 1600 px）由源码固定，不存在 `[thumbnails]`
  配置段。
- 手改配置导致的非法值不会阻止启动：`[download] batch_limit` 与
  `[audit] retention_days` 非法时回退默认或钳制到合法值并打印警告；
  `[scanner] hash_workers` 非法或非正数时回退到源码默认值。
- 自动生成的配置模板中整个 `[tagging]` 段都是注释状态；在你显式覆盖
  之前，上表中的默认值直接生效。

## 智能标签（可选）

智能标签完全在本机用三个本地模型分析照片，数据不出本机：

- **场景标签**——CLIP ViT-B/32 零样本分类，对照内置两级提示词体系：
  9 个一级大类（自然风光、植物花卉、城市建筑、人物、室内家居、食物、
  宠物动物、交通工具、文档截图）与 43 个二级细类，结果带置信度。
- **人数检测**——YOLO11n 检测每张照片中的人物数量。
- **人脸聚类**——SCRFD 检测人脸，ArcFace（`w600k_mbf`）生成 512 维
  向量，再以贪心余弦相似度把同一个人跨照片聚成簇。簇 ID 稳定
  （`P001`、……），可在人物页重命名，系统不会自动合并簇。

结果在界面中的入口：

- **人物页**（顶栏"人物"，`/people`）：左侧人物簇列表带人脸缩略图，
  右侧选中簇的照片按年 / 月分组，并标注所在图库与文件夹。
- **场景筛选**：浏览工具栏的一级 / 二级下拉，选项按当前文件夹范围的
  统计生成；筛选状态写入 URL query（`?scene_major=…&scene_minor=…`），
  同时过滤图片与子文件夹（文件夹卡片显示匹配图片数）。
- **搜索**支持同一套场景筛选并新增日期区间；关键词变为可选，因此
  可以只按场景 / 日期做纯筛选。
- **管理后台概览页**提供标签分布统计面板，按分类展示照片数量。

### 打标时机

打标与缩略图生成共用同一套图像解码入口：普通图（JPEG/PNG/HEIC 等）
经 Pillow 解码并按 EXIF Orientation 自动转正；RAW（.orf/.cr2/.nef/.arw
等）经 rawpy 解码，优先用相机内嵌 JPEG 预览、缺失时全量 demosaic。
模型始终吃转正后的全分辨率 RGB 图，各自内部再降采样。

- **入库时**——当 `enabled`、`scan_on_import` 均开启且模型就位时，
  服务端后台扫描器在同一轮扫描中对每张新增 / 变化图片同步打标
  （未变化文件不会进入模型）。单张失败只记录 `tag_error`，不会中断
  扫描。注意命令行的 `myphoto rescan` 不挂载打标器、不会跑模型；
  命令行打标请用 `myphoto tag run`。
- **存量补打**——用下方 CLI 给已有图库批量打标（也用于失败重试）。
  支持断点续跑：已打标、未变化的图片自动跳过；`--force` 会对选定
  范围内的图片全部重打。

```bash
myphoto tag status                                              # 各图库 tagged/pending/failed 与 "models ready"
myphoto tag run [--gallery G] [--folder 子路径] [--force]       # 给待打标图片打标，结束后自动增量聚类
myphoto tag cluster                                             # 对未分配人脸做增量重新聚类
myphoto tag relabel                                             # 基于已存向量重算场景标签（不跑视觉模型）
myphoto tag gc [--include-named]                                # 清理孤儿人物簇
```

### 模型部署要求

Python 依赖随常规的 `pip install -e ".[dev]"` 一并安装（NumPy、
OpenVINO、onnxruntime、InsightFace、OpenCV、Transformers）。三个
注意点：**`openvino` 锁定 2024.6.0**——2026.x 版本 API 不兼容；
**不要安装 `optimum`**，它会连带升级 OpenVINO 破坏环境；**故意不
依赖 PyTorch**——推理全部走 OpenVINO / onnxruntime，Transformers 只
承担 `CLIPProcessor` 的 PIL/numpy 预处理。无 torch 环境下
Transformers 会在 import 时打印 `PyTorch was not found …` 的 advisory
警告，不影响运行，tagger 已自动抑制该提示，不要为消除警告去装 torch
（CUDA 版 wheel 达数 GB）。

模型权重本身**不进 git**，总计约 **900 MB**。请按下面的确切目录
结构放到 `[tagging] models_dir` 指向的位置（默认 `backend/models/`，
相对 `config.toml` 所在目录解析）——打标器启用前会逐个检查这些路径：

```text
backend/models/
├── clip-ov/
│   ├── visual.xml + visual.bin     # CLIP 视觉塔 OpenVINO IR（约 168 MB；openvino 计划需要）
│   └── text.xml + text.bin         # CLIP 文本塔 OpenVINO IR（约 121 MB；两个计划都需要）
├── clip-onnx/
│   └── visual.onnx                 # CLIP 视觉塔 ONNX（约 350 MB；仅 cuda 计划需要，scripts/ 脚本导出）
├── clip-vit-base-patch32/          # HF tokenizer/processor 配置 + pytorch_model.bin（约 580 MB）
├── yolo11n.onnx                    # YOLO11n（COCO person 类）ONNX（约 10 MB）
└── insightface/
    ├── det_500m.onnx               # SCRFD 500m 人脸检测（约 2.5 MB）
    └── w600k_mbf.onnx              # ArcFace w600k 人脸识别（约 13 MB）
```

模型来源：`yolo11n.onnx` 由 Ultralytics YOLO11n 导出 ONNX；
`clip-ov/` 由 HuggingFace `openai/clip-vit-base-patch32` 转换为
OpenVINO IR；两个 InsightFace 文件来自 InsightFace 官方模型库
（与 buffalo 系列模型包同源）。三者许可证各不相同，见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

两套加载计划由 `[tagging] device` 切换（默认 `auto` 自动探测）。无
CUDA 时走 openvino 计划：CLIP / YOLO 经 OpenVINO 探测到 Intel GPU 就
用 GPU（已在 i5-11320H + Iris Xe 上验证），否则回退 CPU，人脸两个
模型走 onnxruntime CPU。安装 onnxruntime-gpu 且具备 NVIDIA CUDA 环境
时可走 cuda 计划：四个模型全部经 `CUDAExecutionProvider` 推理（带 CPU
回退），但需要额外导出 `clip-onnx/visual.onnx`；包互斥安装、CUDA /
cuDNN 前置与验证步骤见 [docs/deployment.md](docs/deployment.md)。参考性能（上述 i5 + 核显）：含解码与磁盘
IO 稳态约 350ms / 张——2923 张图库全量 17 分钟、0 失败（576 张脸
聚成 269 簇），折合万张约 1 小时；纯 CPU 可用但更慢。模型首次使用
时才懒加载并常驻内存，启动 web 服务本身不会加载模型。

模型文件缺失时服务照常启动：入库打标随一条日志自动关闭，其他功能
不受影响。把模型拷贝到位后用下面的命令验证：

```bash
myphoto tag status     # 所有文件就位后首行输出 "models ready: yes"
```

想彻底关闭该功能（例如低性能主机），在 `config.toml` 的 `[tagging]`
段设置 `enabled = false` 即可。更完整的部署流程（镜像源、服务常驻
等）见 [docs/deployment.md](docs/deployment.md)（中文）。

### 隐私

人脸向量属于生物特征数据，保存在 `<data_dir>/app.db` 中——不要把
该数据库上传到任何公开位置，备份时同样注意其中包含人脸向量。所有
推理均在本地完成，程序不会向任何 AI 云服务发起请求。

## 数据与备份

运行期数据位于 `[app] data_dir`。首次运行生成的 `config.toml` 不含该
键，因此默认就是项目根目录（`config.toml` 所在目录）；如希望使用 `db/`
目录布局，可自行在 `[app]` 中设置 `data_dir = "db"`（本项目自己的开发
检出就是这样配置的）：

- `<data_dir>/app.db` —— 用户、图库、元数据、审计日志、LUT 启用状态与显示名、智能标签与图像 / 人脸向量、人物簇（人脸向量属生物特征数据，备份请注意保密；需要备份）。
- `<data_dir>/.cache/thumbnails/` —— 磁盘缩略图缓存，可完全重建。
- `<data_dir>/luts/<分组>/*.cube` —— 可选的滤镜 LUT 文件；启用状态与显示名存于 `app.db`，把新 `.cube` 放进对应分组目录后在 admin 页面点"重新扫描"。
- `config.toml` —— 含 `jwt_secret`（需要备份）。

备份只需复制 `<data_dir>/app.db`（默认为项目根目录下的 `app.db`）与
`config.toml`。为保证快照一致，请先停止服务，或使用 SQLite 安全备份
工具。原始照片存放在各个图库 root 中，程序只会在 root 与其 `.trash/`
目录之间移动文件（删除与还原）。

## 升级

```bash
git pull
pip install -e ".[dev]"
pnpm --dir frontend build
# 重启 myphoto serve
```

启动时后端会自动创建缺失的数据表，并为已有表补充缺失的列（轻量级
`ALTER TABLE ... ADD COLUMN` 迁移）。升级前仍建议先备份
`<data_dir>/app.db`（默认即项目根目录下的 `app.db`）。

## 开发

```bash
# 后端自动重载（只监视 backend/ 目录）
myphoto serve --reload

# 前端开发服务器（Vite；/api 代理到 http://127.0.0.1:8080）
cd frontend && pnpm dev
```

- 后端测试：在仓库根目录运行 `pytest`（测试位于 `backend/tests/`）。
- 前端测试：`cd frontend && pnpm test`（Vitest）。
- `pnpm build` 在打包前先执行 `vue-tsc --noEmit`，因此也兼作类型检查
  门禁。`pnpm preview` 可在本机 4173 端口预览 `frontend/dist/`，仅用于
  验证生产构建，不是对公网服务的服务器。

## 部署

局域网 HTTP（随仓库 Caddyfile）、公网域名 + 自动 HTTPS、进程常驻、
防火墙说明，以及智能标签模型文件的部署要求，见
[docs/deployment.md](docs/deployment.md)（中文）。

## 许可证

本项目自有代码以 MIT 许可证发布，见 [LICENSE](LICENSE)。智能标签的模型
权重不随 git 分发，且带有各自更严格的许可证：尤其注意 YOLO11n 为
**AGPL-3.0**、InsightFace 预训练模型**仅限非商业研究用途**（CLIP 本身为
MIT）。重新分发本应用或商用前，请先阅读
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 中的完整组件与模型
许可证清单。

## 设计文档

设计规格见 `docs/superpowers/specs/`，各阶段计划见
`docs/superpowers/plans/`。智能标签子系统（数据模型、打标管线、
聚类策略）的设计见 `docs/tags-upgrade-design.md`。
