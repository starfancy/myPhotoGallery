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

## 备份与升级

- 备份（`<data_dir>/app.db`，默认为项目根目录下的 `app.db`，加上
  `config.toml`）与升级步骤
  （`git pull` → `pip install -e ".[dev]"` → `pnpm --dir frontend build`
  → 重启，启动时自动建表补列）见 README 的
  [Data & backups](../README.md#data--backups) 与
  [Upgrading](../README.md#upgrading) 章节。
- 中文说明见 [README.zh-CN.md](../README.zh-CN.md) 的「数据与备份」与
  「升级」章节。
