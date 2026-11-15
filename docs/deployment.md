# myPhotoGallery 部署指南

[English](../README.md) · [简体中文](../README.zh-CN.md)

本文介绍两种典型部署形态：

1. **家庭局域网 HTTP**：使用随仓库提供的 `Caddyfile`，Caddy 在 80 端口
   直接提供 HTTP 服务，适合家里 Wi-Fi / 内网使用，无需域名与证书。
2. **公网域名 + 自动 HTTPS**：把 Caddy 的监听地址换成域名，Caddy 自动
   向 Let's Encrypt 申请并续期证书，自动把 HTTP 跳转到 HTTPS。

> 提示：不使用 Caddy 也能运行。`myphoto serve` 本身会直接托管
> `frontend/dist/` 与 `/api`；全新安装默认监听 `0.0.0.0:8080`，局域网内
> 直接访问 `http://<局域网 IP>:8080` 即可。仓库不提供 `config.toml`，
> 它在首次运行时自动生成，默认即监听 `0.0.0.0:8080`；形态二会介绍如何
> 在 Caddy 后方把 `listen_host` 改为 `127.0.0.1`。Caddy 方案的好处是
> 80 端口、压缩、静态资源缓存与统一入口。

## 前置准备

两种形态都需要先准备好后端与前端产物：

```bash
# 1) 后端可运行（详见 README 快速开始）
myphoto serve
# 默认读取项目根 config.toml，监听 0.0.0.0:8080

# 2) 构建前端（在项目根执行）
pnpm --dir frontend install
pnpm --dir frontend build
# 产物在 frontend/dist/
```

另外需要安装 [Caddy](https://caddyserver.com/docs/install)（Windows 上
把 `caddy.exe` 放到 PATH 或项目根即可）。

---

## 形态一：家庭局域网 HTTP（随仓库 Caddyfile）

仓库根目录的 `Caddyfile` 已配置为监听所有网卡的 80 端口（`:80`，仅
HTTP）。**在项目根目录**启动 Caddy（文件中的相对路径
`./frontend/dist` 相对于启动时的工作目录）：

```bash
caddy run          # 前台运行，日志直接输出，便于首次调试
caddy start        # 后台运行
caddy reload       # 修改 Caddyfile 后热加载
caddy validate     # 不启动，仅检查配置语法
```

启动顺序：先后端 `myphoto serve`，再启动 Caddy（顺序反了也不会报错，
但在后端就绪前打开页面 API 会失败）。

### Caddyfile 的四项职责

1. **静态托管**：把 `frontend/dist/` 作为站点根目录，并对 JS/CSS/SVG
   等文本资源启用 gzip / zstd 压缩。
2. **SPA 回退**：不存在的文件路径一律回退 `index.html`
   （`try_files`），刷新 `/browse/...` 这类前端路由不会 404。
3. **缓存策略**：`/assets/*`（Vite 产物文件名带内容哈希）强缓存一年；
   `index.html` 不缓存，保证发版后立即引用到新哈希资源。
4. **API 反向代理**：`/api/*` 原样转发到本机
   `127.0.0.1:8080`（不剥离 `/api` 前缀），并自动附带
   `X-Forwarded-For` / `X-Forwarded-Proto`。

### 访问

在同一局域网的设备上打开：

```text
http://<服务器局域网 IP>/
```

例如 `http://192.168.1.20/`。服务器本机也建议用局域网 IP 访问（见下方
常见问题）。

### 常见问题

#### 本机 80 端口被 Watt Toolkit（Steam++）占用

开发机上安装 Watt Toolkit 后，它的加速功能会占用本机回环的 80 端口，
此时在服务器本机用浏览器打开 `http://127.0.0.1/` 或
`http://localhost/` 看到的是 Watt Toolkit 而不是相册。处理办法：

- **办法一（推荐）：用局域网 IP 访问。** 在本机或其他设备上打开
  `http://<局域网 IP>/`，请求走物理网卡而非回环，即可直达 Caddy。
- **办法二：改 Caddy 监听端口。** 把 `Caddyfile` 第一行的 `:80` 改成
  其他端口（如 `:8088`），执行 `caddy reload`，然后访问
  `http://<局域网 IP>:8088/`。
- **办法三：退出 Watt Toolkit（或关闭其网络加速）后再启动 Caddy。**

若 `caddy run` 启动时直接报 80 端口 bind 失败，说明 80 端口被整体
占用，只能使用办法二或办法三。

#### 其他设备无法访问（Windows 防火墙）

首次运行 `caddy run` 时 Windows 通常会弹出防火墙授权提示，请勾选
“专用网络”。也可以用管理员 PowerShell 手动放行：

```powershell
New-NetFirewallRule -DisplayName "myPhotoGallery Caddy HTTP" `
  -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow -Profile Private
```

同时确认手机 / 其他电脑与服务器连在同一网段，且服务器使用的是专用
（家庭）网络配置文件。改用其他端口（如常见问题中的 `:8088`）时，请把
规则中的 `-LocalPort 80` 改成对应端口；不经过 Caddy、直接用
`myphoto serve` 的 8080 端口对外提供访问时，则需另行添加一条放行 TCP
8080 入站的规则。

---

## 形态二：公网域名 + 自动 HTTPS

### 1. 修改 Caddyfile

把第一行的 `:80` 改成你的域名：

```caddyfile
photos.example.com {
    # 块内其余内容保持不变
}
```

确认域名的 A / AAAA 记录已指向本机，且公网入站 80、443 端口开放。
执行 `caddy reload`（或重启 Caddy）后，Caddy 会自动向 Let's Encrypt
申请证书、续期，并把 HTTP 请求自动重定向到 HTTPS，无需其他配置。

### 2. 后端必须配置 trusted_proxies

经过反向代理后，后端看到的 TCP 对端永远是 `127.0.0.1`，真实客户端 IP
需要从 `X-Forwarded-For` 获取。请在项目根 `config.toml` 中设置：

```toml
[security]
trusted_proxies = ["127.0.0.1", "::1"]

[app]
# 与 Caddy 同机部署时建议只监听回环，8080 不对公网暴露
listen_host = "127.0.0.1"
listen_port = 8080
```

语义：只有来自可信代理（此处即本机 Caddy）的 `X-Forwarded-For` 才会
被采纳；未配置时后端忽略该请求头，所有请求都会被判定为来自
`127.0.0.1`，导致局域网 / 远程访问范围（access_scope）判定失真。该
项也可以在管理后台「设置 → 可信代理」中修改。

### 3. viewer 账号的访问范围（lan_only / remote_allowed）

每个账号都有访问范围属性：

- `lan_only`（默认）：只允许在局域网内使用。有效客户端 IP 不属于私网
  地址段时，**登录环节即被拒绝**（HTTP 403 `access_scope_violation`），
  已登录会话的后续 API 请求同样会被拒绝。被判定为“局域网”的范围是
  `10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`127.0.0.0/8`、
  `fc00::/7` 与 `::1`。
- `remote_allowed`：不限制网络位置，可经公网访问（viewer 仍需被授予
  具体图库权限；未授权图库返回 404）。

因此对公网部署：

- 初始 admin 账号默认是 `remote_allowed`，确保你首次能从公网登录；
  登录后可按需改回 `lan_only`。
- 需要远程使用的 viewer 账号，请在「用户管理」中把访问范围改为
  `remote_allowed`；其余账号保持 `lan_only`，即使站点暴露在公网也无法
  从外部登录。

---

## 进程常驻

### Windows

Caddy 本身支持后台运行：

```bash
caddy start     # 后台启动
caddy stop      # 停止
```

后端 `myphoto serve` 没有内置服务模式，推荐用「任务计划程序」在登录
时自动启动。可用管理员 PowerShell 注册：

```powershell
$repo = "E:\code\claude\myPhotoGallery"
$action = New-ScheduledTaskAction `
  -Execute "$repo\.venv\Scripts\myphoto.exe" `
  -Argument "serve" `
  -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "myPhotoGallery" `
  -Action $action -Trigger $trigger
```

日志默认只输出到控制台。需要留存日志时，不要直接调用 `myphoto.exe`，
改为把 `-Execute` 设为 `pwsh.exe`（或 `powershell.exe`）并把
`-Argument` 设为带重定向的命令字符串，例如
`-NoProfile -Command "& '$repo\.venv\Scripts\myphoto.exe' serve *>> '$repo\serve.log'"`。
Caddy 也可以用同样方式注册计划任务执行
`caddy run --config Caddyfile`，避免手工 `caddy start`。

### Linux（可选 systemd 示例）

```ini
# /etc/systemd/system/myphoto.service
[Unit]
Description=myPhotoGallery backend
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/myPhotoGallery
Environment=MYPHOTO_CONFIG=/opt/myPhotoGallery/config.toml
ExecStart=/opt/myPhotoGallery/.venv/bin/myphoto serve
Restart=on-failure
RestartSec=3
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now myphoto
```

注意：服务账号（此处为 `www-data`）必须对 `data_dir`（默认即
`config.toml` 所在目录）及其 `.cache/` 子目录拥有写权限，否则缩略图
缓存与数据库写入会失败；同时还要对每个图库 root 下的 `.trash/` 目录
拥有写权限，否则界面中的删除 / 还原操作会失败。

Caddy 在各发行版上有官方安装包，安装后通常自带 systemd service；把
仓库内的 `Caddyfile` 内容合入 `/etc/caddy/Caddyfile` 并
`sudo systemctl reload caddy` 即可。

本项目不提供 Docker 镜像或容器部署配置。

---

## 智能标签模型部署（可选）

智能标签（CLIP 场景分类 / YOLO 人数检测 / InsightFace 人脸聚类）完全
在本机推理，但模型文件**不随 git 分发**，需要单独部署。不部署也不
影响相册的其他功能：服务照常启动，后台扫描自动跳过打标并打印一条
`tagging models not available` 日志。功能与 CLI 的完整说明见
[README.zh-CN.md 的「智能标签」章节](../README.zh-CN.md#智能标签可选)。

### 1. Python 依赖

打标依赖已写入 `pyproject.toml`，随 `pip install -e ".[dev]"` 一并
安装（openvino、onnxruntime、insightface、opencv-python、
transformers、numpy）。三个注意点：

- **openvino 锁定 2024.6.0**：2026.x 版本 API 不兼容，不要手动升级。
- **不要安装 optimum**：它会连带升级 openvino，破坏运行环境。
- 国内网络拉取大 wheel 超时时，改用阿里镜像：

  ```bash
  pip install -e ".[dev]" -i https://mirrors.aliyun.com/pypi/simple/
  ```

### 2. 模型文件目录布局

模型总计约 **900 MB**，放到 `config.toml` 中 `[tagging].models_dir`
指向的目录（默认 `backend/models/`，相对路径相对配置文件所在目录
解析）。目录结构必须与下方一致——程序启用打标前会逐个检查文件是否
就位：

```text
backend/models/
├── clip-ov/
│   ├── visual.xml + visual.bin     # CLIP 视觉塔 OpenVINO IR（约 168 MB）
│   └── text.xml + text.bin         # CLIP 文本塔 OpenVINO IR（约 121 MB）
├── clip-vit-base-patch32/          # HF tokenizer/processor 配置 + pytorch_model.bin（约 580 MB）
├── yolo11n.onnx                    # YOLO11n（COCO person 类）ONNX（约 10 MB）
└── insightface/
    ├── det_500m.onnx               # SCRFD 500m 人脸检测（约 2.5 MB）
    └── w600k_mbf.onnx              # ArcFace w600k 人脸识别（约 13 MB）
```

文件来源：`yolo11n.onnx` 由 Ultralytics YOLO11n 导出 ONNX；
`clip-ov/` 由 HuggingFace `openai/clip-vit-base-patch32` 转换为
OpenVINO IR（visual / text 两个塔），`clip-vit-base-patch32/` 保留
HF tokenizer / processor 配置与原始 PyTorch 权重；两个 InsightFace
文件来自 InsightFace 官方模型库（与 buffalo 系列模型包同源）。仓库
不提供下载脚本，也不托管模型文件，请自行获取 / 转换后按上述结构
拷贝。

> **许可证提示**：模型权重的许可证独立于本项目的 MIT 许可证——
> YOLO11n 为 AGPL-3.0，InsightFace 预训练模型仅限非商业研究用途，
> CLIP 为 MIT。完整条款与商用授权方式见
> [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

### 3. 验证与开关

模型放好后，用 CLI 验证（只检查文件，不加载模型）：

```bash
myphoto tag status
# 首行输出 "models ready: yes" 即全部就位；NO 时按提示检查目录路径
```

`config.toml` 的 `[tagging]` 段在首次生成的模板里是注释状态，默认值
即如下，通常无需修改：

```toml
[tagging]
enabled = true            # 总开关；false 时扫描器与 CLI 都不打标
scan_on_import = true     # 后台扫描时对新增/变化图片同步打标
models_dir = "backend/models"
```

低性能主机想彻底关闭该功能，设 `enabled = false` 即可，其余服务
不受影响。

### 4. 硬件与性能

- 设备自动选择：OpenVINO 探测到 GPU 就用 GPU（已在 Intel
  i5-11320H + Iris Xe 核显上验证），否则回退 CPU；人脸检测与识别
  固定走 onnxruntime 的 CPU provider，**不依赖 CUDA / NVIDIA 显卡**。
- 参考性能（上述 i5 + 核显）：含解码与磁盘 IO 稳态约 350ms / 张，
  2923 张全量 17 分钟、0 失败（576 张脸聚成 269 簇），折合万张
  约 1 小时；纯 CPU 可用但更慢，请预留更宽裕的时间窗。
- 模型在首次打标时懒加载并常驻内存，web 服务启动阶段不加载模型，
  因此缺模型不会拖慢启动。

### 5. 存量图库打标

新图入库时由 `myphoto serve` 的后台扫描器自动打标；存量图片用 CLI
批量补打，支持断点续跑（已打标、未变化的自动跳过，历史失败默认
跳过、加 `--force` 才重试）：

```bash
myphoto tag run --gallery "我的照片"            # 打完自动增量聚类
myphoto tag run --gallery G --folder "旅行/成都"  # 只打某个子文件夹
myphoto tag run --gallery G --force              # 模型升级后强制重打
myphoto tag cluster                              # 仅对未分配人脸重新聚类
myphoto tag relabel                              # 用已存向量秒级重算场景标签
myphoto tag gc                                   # 清理 --force 重打后的孤儿人物簇
```

注意：命令行 `myphoto rescan` 不挂载打标器，不会触发模型；命令行
场景的打标统一走 `myphoto tag run`。

### 6. 隐私

`app.db` 中的 `face_embeddings` 表保存人脸生物特征向量，不要把数据
库上传到任何公开位置，做异地备份时同样注意保密。全部推理离线完成，
程序不会向任何 AI 云服务发起请求。

---

## 备份与升级

- 备份（`<data_dir>/app.db`，默认为项目根目录下的 `app.db`，加上
  `config.toml`）与升级步骤
  （`git pull` → `pip install -e ".[dev]"` → `pnpm --dir frontend build`
  → 重启，启动时自动建表补列）见 README 的
  [Data & backups](../README.md#data--backups) 与
  [Upgrading](../README.md#upgrading) 章节。
- 中文说明见 [README.zh-CN.md](../README.zh-CN.md) 的「数据与备份」与
  「升级」章节。
