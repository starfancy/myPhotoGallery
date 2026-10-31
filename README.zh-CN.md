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
- 文件名 / 文件夹名搜索，范围限定在单个图库 root 内（可锚定某个子目录
  子树）。
- 多图批量打包 ZIP 下载：流式输出、支持 zip64 大文件，服务端限制单次
  打包数量。
- 管理与安全事件审计日志：保留期可配置，可在管理后台审计页导出 CSV。
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

补充说明：

- 缩略图尺寸（200 / 400 / 1600 px）由源码固定，不存在 `[thumbnails]`
  配置段。
- 手改配置导致的非法值不会阻止启动：`[download] batch_limit` 与
  `[audit] retention_days` 非法时回退默认或钳制到合法值并打印警告；
  `[scanner] hash_workers` 非法或非正数时回退到源码默认值。

## 数据与备份

运行期数据位于 `[app] data_dir`。首次运行生成的 `config.toml` 不含该
键，因此默认就是项目根目录（`config.toml` 所在目录）；如希望使用 `db/`
目录布局，可自行在 `[app]` 中设置 `data_dir = "db"`（本项目自己的开发
检出就是这样配置的）：

- `<data_dir>/app.db` —— 用户、图库、元数据、审计日志（需要备份）。
- `<data_dir>/.cache/thumbnails/` —— 磁盘缩略图缓存，可完全重建。
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

局域网 HTTP（随仓库 Caddyfile）、公网域名 + 自动 HTTPS、进程常驻与
防火墙说明，见 [docs/deployment.md](docs/deployment.md)（中文）。

## 设计文档

设计规格见 `docs/superpowers/specs/`，各阶段计划见
`docs/superpowers/plans/`。
