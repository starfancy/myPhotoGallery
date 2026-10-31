# Phase 7 设计：审计 UI + 主题令牌（浅色/深色）+ 移动端复核 + 无障碍 + 文档定稿

日期：2026-10-31
上游需求：`docs/superpowers/specs/2026-07-20-photo-gallery-design.md` §7.5（AdminAudit）、§7.8（无障碍）、§9（`[audit] retention_days`）、§11
Roadmap：`docs/superpowers/plans/2026-07-22-roadmap-p2-p7.md`（P7，最后一个 phase）

---

## 1. 目标与范围

面向发布的最后一波打磨，五个相对独立的部分：

1. **AdminAudit 页面**：表格 + 过滤 + 分页 + CSV 导出。后端 `GET /api/admin/audit` 在 P2 已就绪，本 phase 只做前端。
2. **浅色/深色主题**：当前应用为纯深色硬编码；改为语义化颜色令牌，浅色为默认、深色跟随系统 `prefers-color-scheme: dark`（spec §7.8）。不做手动切换开关。
3. **审计日志留存清理**（roadmap 外补丁）：spec §9 承诺了 `[audit] retention_days = 180` 但从未实现；本 phase 补上，是唯一的后端改动。
4. **移动端断点复核 + 无障碍闭合**：按 spec §7.2/§7.8 逐页走查定点修，不重写布局。
5. **文档定稿**：README 中英双语 + 中文部署文档。

### 与上游 spec 的偏差（需记录）

- spec §7.5 写 AdminAudit 为「无限滚动」；本设计改用全库既有的「加载更多」按钮模式（AdminTrash、SearchResults 一致），语义等价、测试与实现可直接复用既有模式。
- spec §7.8 只写「深色模式跟随 prefers-color-scheme」。当前 UI 是纯深色，本设计补出完整浅色主题；**不提供**手动主题开关（YAGNI，用户确认）。
- CSV 导出 spec 未规定形态。后端无导出接口且本 phase 不新增批量 API，导出在**前端**用既有分页接口循环拉取后本地生成。
- spec §9 的 `[audit] retention_days` 落地：默认 180 天，`0 = 永不清理`（与 trash 哨兵约定一致），AdminSettings 提供下拉。

### 明确不做（YAGNI）

- 不做手动主题切换开关、不做主题持久化、不做首屏防闪烁脚本（纯 CSS 媒体查询，无 FOUC）。
- 不做 PhotoSwipe / ImageLightbox 的浅色版本——灯箱两种主题下都保持深色。
- 不引入 a11y 自动化工具（axe 等）与对比度 CI；以组件测试覆盖焦点管理逻辑，对比度在令牌选型时人工按 WCAG AA 把关。
- 不做审计 actor（操作人）过滤 UI；过滤仅事件类型 + 时间范围两类。
- 不做后端 CSV 导出接口、不做服务端审计表分页以外的任何查询增强。
- 不做浅色截图回归。
- 不重写页面布局，移动端只定点修复。

---

## 2. 审计留存（后端，唯一后端改动）

### 2.1 配置

`[audit]` 段新增（config.toml 模板同步）：

```toml
[audit]
retention_days = 180   # 允许值: 0(永不清理) / 30 / 90 / 180 / 365
```

- loader 规则与 `[download] batch_limit` 同模式：非负整数钳制到允许集合（{0,30,90,180,365}）；越界/类型错误 → 钳到最近合法值并 `warning` 日志，不阻断启动。
- 默认 180。
- 经 `PATCH /api/admin/settings` 热生效（P5 已有 config 重载机制，只需登记新键与校验）；AdminSettings 可改。

### 2.2 清理逻辑

新增 `myphoto/audit.py::purge_expired(session, retention_days: int) -> int`：

- `retention_days == 0`：直接返回 0（哨兵，永不清理）。
- 否则删除 `AuditLog.ts < cutoff` 的行，`cutoff = now - retention_days*86400`（整数秒，与写入口径一致）；返回删除条数。
- 物理删除走 SQL `DELETE`（审计行无 FS 副作用、无外键关联，不经过回收站）。

调用时机（与 trash 完全同构）：

1. 服务启动时无条件执行一次（trash 启动清理之后，二者各自独立 try，互不影响）。
2. 现有每日定时任务（trash 的 03:17 tick）内追加调用，顺序固定为 **先 trash 后 audit**。

**清理动作自身不写审计**（自引用噪声），只 `logging.info("audit purge removed=%d cutoff=%d", ...)`。

### 2.3 测试

- `purge_expired`：空表；保留期内不动；刚好到期边界（`<` 与 `==` cutoff）；0 哨兵；返回值正确。
- config loader：缺省 180；合法值透传；非法值（负数、字符串、越界整数如 100）钳制 + warning。
- 启动钩子与每日调度联动（参考现有 trash 调度测试写法）。
- settings 接口：PATCH 合法/非法 retention_days。

---

## 3. AdminAudit 页面（前端）

### 3.1 路由与入口

- 新增路由 `/admin/audit` → `views/AdminAudit.vue`，`meta: { requiresAdmin: true }`。
- AppHeader 管理下拉菜单新增「审计日志」项（位于「设置」之前）。
- AdminOverview「最近 20 条审计」区块标题右侧加「查看全部 →」链接到 `/admin/audit`。

### 3.2 页面结构

沿用 AdminTrash 的布局与交互模式（sticky 工具条 + `overflow-x-auto` 表格 + 底部「加载更多」）：

- **过滤工具条**（sticky）：
  - 事件类型下拉：「全部事件」+ 全部已知 action 的中文标签（枚举来自共享 `utils/audit.ts`，见 3.5）。
  - 时间范围：起日期、止日期两个 `<input type="date">`。起 = 当天 00:00:00 本地 → unix 秒（`from`）；止 = 当天 23:59:59 → `to`。过滤为空时不带该参数。
  - 「导出 CSV」按钮（见 3.4）。
  - 过滤条件变化（含清空）→ 重置回第一页重新加载。
- **表格列**：

  | 列 | 内容 |
  | --- | --- |
  | 时间 | `formatDateTime(ts)`（复用现有 utils） |
  | 操作人 | `actor_user_id != NULL`：`username`（id→username 映射，映射不到显示 `#id（已删除）`）；`actor_user_id == NULL`：`login_fail` 显示「匿名」（IP 列承载来源），其余（扫描/定时清理等）显示「系统」 |
  | IP | actor_ip；登录失败行照常显示 |
  | 事件 | action 中文标签（未知 action 回退显示原始 action 名） |
  | 目标 | target 原文，等宽小字，超长省略 + title |
  | 详情 | detail 原文，等宽小字，超长省略 + title |

- **分页**：每页 limit=100，游标沿用后端 `<ts>_<id>` 不透明串；「加载更多」按钮 + loading/空态/错误态（错误显示错误条 + 重试，不吞已有数据）。竞态防护与 SearchResults/AdminTrash 相同的单调 seq 令牌。
- **操作人映射**：进入页面时调一次 `GET /api/admin/users`（P4 已有，返回精简列表），建 `Map<id, username>`；映射不到（用户已删除）显示 `#id（已删除）`。该请求失败不阻塞审计列表，操作人列回退显示 `#id`。
- 窄屏：表格套 `overflow-x-auto` + `min-w-[...]`，与 AdminTrash 一致。

### 3.3 api.ts 封装

新增 `fetchAuditEntries(params: {action?, from?, to?, limit?, cursor?})` 与 `fetchUsers()` 中已有的用户列表接口（若无独立封装则补一个）。类型定义 `AuditEntry` 对齐后端返回字段（id/ts/actor_user_id/actor_ip/action/target/detail + next_cursor 信封）。

### 3.4 CSV 导出（纯前端）

新增 `utils/csv.ts`：

- **拉取**：按**当前过滤条件**（action/from/to，与页面一致；不带 actor）以 limit=500 循环游标翻页，直到无 next_cursor。
- **硬上限 10,000 条**：达到上限且仍有下一页 → **中止导出**（不生成半截文件），toast「最多导出 10,000 条，请收窄时间范围后重试」。
- **取消**：`AbortController`，按钮在导出中变为「导出中…（N 条）| 取消」；取消后无文件、无错误 toast。
- **格式**：
  - 列：`id,time,actor_user_id,actor_ip,action,target,detail`
  - time 为 ISO 8601 本地时区字符串，格式固定为 `YYYY-MM-DDTHH:mm:ss±HH:MM`（偏移取浏览器本地时区，如 `+08:00`）；不用 `toLocaleString`，避免随机器 locale 漂移。用现有 datetime 工具扩展或在 csv.ts 内实现。
  - `action` 输出**原始英文 action 名**（机器可读，中文标签只用于界面）。
  - 字段按 RFC 4180 转义：含逗号/引号/换行时双引号包裹，内部引号双写；行尾 CRLF。
  - 文件以 UTF-8 BOM（`﻿`）开头，Blob `type: text/csv;charset=utf-8`，文件名 `audit-YYYYMMDD-HHmmss.csv`。
- 导出按钮在过滤结果为空/加载失败时禁用。

### 3.5 共享 action 标签表

新增 `utils/audit.ts`，导出：

- `AUDIT_ACTION_LABELS: Record<string,string>`：覆盖后端**全部实际写入的 action**。以当前代码为准的完整枚举：

  ```text
  login_success, login_fail,
  user_create, user_delete, user_update, user_disable, user_enable,
  user_reset_password,
  gallery_create, gallery_update, gallery_delete,
  root_add, root_update, root_remove,
  exclusion_add, exclusion_remove,
  image_delete, image_restore, trash_purge,
  thumb_cache_purge,
  scan_start, scan_finish, scan_error, rescan_exif,
  fs_browse, settings_update
  ```

  （26 个；实现时以后端 `write_audit(...)` 调用点再次核对为准。）
- `auditActionLabel(action): string`：命中返回中文标签，未命中回退原值。

AdminOverview 内嵌的 ACTION_LABELS 删除、改为引用本模块（修复现有漂移：后台实际写 `user_reset_password`/`user_enable`/`rescan_exif`，旧表缺失或键名不符）。

### 3.6 测试

- utils/audit.ts：标签表覆盖枚举核对（测试内列出后端 action 全集清单，差集为空——防止后端新增事件后前端标签静默缺失，至少在评审时可见）。
- AdminAudit 组件：过滤参数拼装（日期边界）、过滤变化重置、游标「加载更多」、竞态 seq、空态/错误态/重试、用户名映射与已删除回退、users 请求失败降级。
- utils/csv.ts：BOM、CRLF、RFC 4180 转义（逗号/引号/CRLF/中文）、action 输出原名、时间格式固定、10,000 上限中止且不产生下载、AbortController 取消。

---

## 4. 主题令牌体系

### 4.1 令牌定义

在 `styles/base.css` 定义语义令牌，`:root` 为浅色（默认），`@media (prefers-color-scheme: dark)` 整体覆盖为深色。**深色值取当前调色板，保证深色外观零变化。**

变量以 RGB 通道形式存储，消费端为 `rgb(var(--token) / <alpha>)`，使 UnoCSS 的 `/60`、`/95` 透明度修饰符继续可用：

| 令牌 | 深色（现状） | 浅色（新增） | 语义 |
| --- | --- | --- | --- |
| `--color-base` | 9 9 11（neutral-950） | 250 250 250（neutral-50） | 页面底色 |
| `--color-surface` | 23 23 23（neutral-900） | 255 255 255 | 卡片/头部/弹层 |
| `--color-surface-2` | 38 38 38（neutral-800） | 244 244 245（neutral-100） | 输入框/嵌套面板 |
| `--color-surface-3` | 64 64 64（neutral-700） | 228 228 231（neutral-200） | hover |
| `--color-surface-4` | 82 82 82（neutral-600） | 212 212 216（neutral-300） | active/禁用强调 |
| `--color-border` | 38 38 38（neutral-800） | 228 228 231（neutral-200） | 默认边框/分隔线 |
| `--color-border-strong` | 64 64 64（neutral-700） | 212 212 216（neutral-300） | 强边框 |
| `--color-text` | 245 245 245（neutral-100） | 23 23 23（neutral-900） | 主文字 |
| `--color-text-2` | 163 163 163（neutral-400） | 64 64 64（neutral-700） | 次要文字 |
| `--color-text-muted` | 115 115 115（neutral-500） | 115 115 115（neutral-500） | 弱化文字（时间戳等非关键信息） |
| `--color-primary` | 59 130 246（blue-500） | 37 99 235（blue-600） | 主操作 |
| `--color-primary-hover` | 37 99 235（blue-600） | 29 78 216（blue-700） | 主操作 hover |
| `--color-primary-text` | 96 165 250（blue-400） | 29 78 216（blue-700） | 文字链接 |
| `--color-danger` | 220 38 38（red-600） | 220 38 38（red-600） | 危险按钮 |
| `--color-danger-text` | 248 113 113（red-400） | 185 28 28（red-700） | 危险文字 |
| `--color-danger-soft` | 127 29 29 / 0.3（red-900/30） | 254 226 226（red-100） | 危险态浅底 |
| `--color-success` | 74 222 128（green-400） | 21 128 61（green-700） | 成功状态 |
| `--color-warning` | 250 204 21（yellow-400） | 180 83 9（amber-600） | 警告状态 |
| `--color-focus-ring` | 96 165 250（blue-400） | 37 99 235（blue-600） | :focus-visible 焦点环 |

（上表为选型基准；实现时以实际对比度复核为准：正文文字与所在底的对比度 ≥ 4.5:1，UI 边框/图标/大号文字 ≥ 3:1 [WCAG AA]。`text-muted` 只承载非关键信息。primary 最终取 blue-600/700 组合以同时满足深底/浅底对比度。）

### 4.2 UnoCSS 注册与写法

`uno.config.ts` 的 `theme.colors` 注册全部令牌：

```ts
function v(name: string) { return `rgb(var(--color-${name}) / <alpha-value>)` }
// colors: { base: v("base"), surface: v("surface"), "surface-2": v("surface-2"), ... }
```

注册后语义类与普通颜色类用法一致：`bg-surface-2`、`text-text-2`、`border-border`、`ring-primary`、`bg-danger-soft`、`divide-border` 等。

### 4.3 常暗作用域（灯箱）

ImageLightbox 根元素加类名 `force-dark`；在 base.css 内：

```css
.force-dark {
  --color-base: ...; /* 深色值逐令牌重绑一遍 */
  ...
}
```

灯箱（含 PhotoSwipe 二级原图查看器）内部代码一律只用语义类，不为灯箱保留任何硬编码颜色。PhotoSwipe 自身样式（`.pswp__*`）的少量覆写继续留在 base.css，按现状深色值书写，不随主题变化。

### 4.4 迁移

- 全库（约 20 个 .vue/.ts 文件，约 500 处颜色工具类）按固定映射表机械替换，映射关系即 §4.1 右三列；`neutral-300` 按语境归并到 `text-2`/`border-strong`，替换时人工判定，不做纯自动 sed。
- 替换分两批提交：① App/布局/浏览链路；② 管理页 + 弹窗 + 灯箱作用域。
- 每批后浅色模式逐页人工核对（见 §7.2 冒烟清单）。
- **回潮守卫测试**在第二批迁移完成后同批落地（迁移未完成时启用会全红）：vitest 扫描 `frontend/src/**/*.{vue,ts}` 源码文本，断言不再出现硬编码色阶类 `(bg|text|border|ring|divide|from|to|placeholder|outline)-(neutral|blue|red|green|yellow|amber|orange|purple)-[0-9]`（含 `/透明度` 形式）；白名单：`styles/base.css`、测试自身、PhotoSwipe 覆写段（集中在 base.css，天然豁免）。新增硬编码颜色即测试失败。

### 4.5 不做的事

- 不动布局尺寸/间距/圆角，只换颜色。
- 不动 index.html（不加主题脚本、不加 class）。
- 现有 base.css 里 button 背景补丁与 `.pswp--original::after` 描边保留；描边颜色改用语义/常暗变量复核。

---

## 5. 移动端复核与无障碍

### 5.1 移动端走查清单（<640 / 640–1024 / >1024 三档）

定点修复，不重写布局：

1. **AppHeader**：管理菜单、用户菜单触发器 ≥44×44；窄屏标题不溢出。
2. **管理表格**：AdminUsers 补 `overflow-x-auto` 横滚容器（现状缺失）；AdminAudit 直接照 AdminTrash 模式；AdminUsers 行内操作按钮组窄屏堆叠。
3. **AdminSettings / AdminGalleryEdit / AdminUsers 表单**：窄屏边距与提交按钮全宽核对。
4. **BrowseView**：工具条 sticky 核对；子目录条 <640 为 2 列紧凑卡片；批量操作底栏按钮 ≥44px。
5. **DirectoryChooser**：窄屏弹窗贴边全宽，路径列表行高 ≥44。
6. **Lightbox**：底部信息条/关闭等控件触屏尺寸核对（PhotoSwipe 手势不动）。
7. **LoginView / ChangePasswordView / GalleryList / RootList**：窄屏边距、卡片与按钮尺寸核对。
8. **统一触控件规则**：所有可点元素最小点击区 44×44 CSS px，优先用 padding 达成，图标按钮用 `min-w-11 min-h-11`。

### 5.2 无障碍闭合（spec §7.8 五条 + 补充项）

1. **键盘导航**
   - 所有浮层（CellContextMenu、AppHeader 两个菜单、DirectoryChooser、各类确认弹窗）：打开后焦点移入；`Esc` 关闭；点击外部关闭；关闭后焦点还回触发器；浮层内 Tab 循环（focus trap，实现一个小的 `composables/useFocusTrap` 或等效工具，菜单类可只做 Esc+归还不做 trap，dialog 类做完整 trap）。
   - Lightbox 的 ←→/Esc 由 PhotoSwipe 提供，核对不被外层吞键。
   - 全局 Tab 顺序走查：头部 → 工具条 → 内容 → 分页，无错位/隐形焦点。
2. **图片 alt**：PhotoCell / SearchResults / SubfolderStrip / AdminTrash 已有；Lightbox 大图补 `alt=filename`；纯装饰图标统一 `aria-hidden="true"`。
3. **表单**：每个输入有显式 `<label>` 关联（for/id 或包裹）；错误态 `aria-invalid="true"` + `aria-describedby` 指向邻近错误文本；覆盖 Login、改密、AdminSettings、AdminUsers（新建/编辑）、AdminAudit 日期输入、GalleryEdit。
4. **ARIA 角色与标签**：
   - 模态：`role="dialog" aria-modal="true" aria-labelledby`；菜单：`role="menu"/menuitem`（AppHeader 已有，补齐其他菜单）。
   - 所有图标按钮配中文 `aria-label`。
   - 异步加载区/按钮：loading 时 `aria-busy`；「加载更多」保留可聚焦按钮形态（同时方便键盘）。
   - 批量选择状态、搜索结果数等动态信息用 `aria-live="polite"` 的礼貌播报（仅状态文本，不播报整个列表）。
5. **Skip link**：App 根放「跳到主内容」链接（默认视觉隐藏，聚焦时显现于左上角），在 App.vue 用 `<main id="main-content">` 包裹 RouterView（现有外层 div 直接改为 main，sticky 元素相对视口定位不受影响；PhotoSwipe 挂在 body 层、在 main 之外，符合预期）。链接颜色用语义令牌。
6. **焦点环**：统一 `:focus-visible` 轮廓，使用 `--color-focus-ring`；移除现有样式中对 outline 的无差别吞没，鼠标点击不显示环、键盘显示。
7. **语义地标**：核对 header/nav/main 等地标元素存在且唯一。

### 5.3 测试

- 组件测试：浮层打开焦点移入/Esc 关闭并归还焦点/点击外部关闭/dialog focus trap；skip link 存在且 href 指向 main；aria-label/role/aria-invalid 关键点在既有组件测试中断言。
- 键盘-only 与对比度不做自动化：列入 §6 人工冒烟清单，浅深两主题各走一遍。

---

## 6. 文档定稿

### 6.1 README（双语）

- `README.md`：英文版（默认，保持现有英文基调扩充）。
- `README.zh-CN.md`：中文版，与英文版内容对等。
- 两个文件首行附近互加语言切换链接（`简体中文` / `English`）。
- 内容结构：
  1. 项目一句话简介 + 特性列表（多图库多根、多用户角色 admin/viewer、LAN/远程访问域、回收站、EXIF、搜索、批量下载、审计日志、浅色/深色、移动端）
  2. 架构简述（Caddy/静态托管 + FastAPI + SQLite；一张文字版数据流说明）
  3. Quick start（沿用现有步骤并校正）
  4. **配置项参考**：config.toml 全量键表（app/trash/thumbnails/security/audit/scan/download），含默认值与合法值
  5. 数据目录与备份（db/app.db、db/.cache、config.toml；备份只需 db + config；缓存可重建）
  6. 升级流程（拉代码 → pip install -e ".[dev]" → pnpm build → 重启；迁移由 schema_init 自动处理）
  7. 开发（reload / vite / 测试命令：pytest、pnpm test、pnpm build 的 vue-tsc 门禁）
  8. 部署链接 → docs/deployment.md

### 6.2 docs/deployment.md（中文）

- 形态一：局域网 HTTP（现成 Caddyfile，逐段用法：build → 起后端 → `caddy run`；80 端口被占用排查记入「常见问题」）。
- 形态二：公网域名 + Caddy 自动 HTTPS（`:80` 改域名即自动证书；`trusted_proxies = ["127.0.0.1"]` 必配；viewer 的 `access_scope` LAN/远程语义与远程访问注意事项）。
- 后端进程常驻：Windows 简单后台方式说明（不绑定具体 NSSM 版本，给出思路与命令）；可选 Linux systemd unit 示例。
- Windows 防火墙放行提示。
- 不写的：Docker（YAGNI，现状无此需求）。

---

## 7. 测试与验收总览

### 7.1 自动化基线

- 后端起点 518 passed / 6 skipped；新增 audit 留存相关后全绿（无跳过项增加）。
- 前端起点 249 passed；新增 AdminAudit、csv、audit 标签、焦点管理、颜色守卫测试后全绿；`pnpm build`（含 vue-tsc --noEmit）通过。

### 7.2 人工冒烟清单（plan 末 task，沿用 P5/P6 惯例边用边验）

1. 系统切浅色：逐页核对（图库列表/浏览/搜索/Lightbox 保持深色/各管理页/弹窗/登录/改密/设置/Toast），无白底白字、无边框消失。
2. 系统切深色：外观与 P6 现状目视一致。
3. 手机视口（DevTools 375px）：§5.1 八项逐页点按；控件无小于 44px 的误触难点。
4. 键盘-only：登录 → 浏览 → 开图 → 管理菜单 → 审计过滤 → 弹窗开合，全程焦点可见、不丢失、不被困。
5. AdminAudit：过滤组合、加载更多、users 服务不可用时降级；导出 CSV 用 Excel 打开中文不乱码、各列正确；10,000 上限中止提示；取消可用。
6. 审计留存：临时把 retention_days 调成 30/0 验证清理与哨兵（直接构造旧 ts 行）；AdminSettings 保存热生效。
7. 屏幕阅读器（可选，Windows 讲述人/NVDA 任一）过一遍主要页面的朗读顺序。

### 7.3 验收标准

- spec §7.5 AdminAudit、§7.8 五条、§9 audit 留存全部闭合；roadmap P7 行可标记完成。
- 深色模式外观与 P6 无回归；浅色模式下无对比度/可读性硬伤（AA）。
- 后端除 §2 外零改动；无新表、无新 API 路径（settings 既有 PATCH 登记新键不算新 API）。
- README 双语 + deployment.md 落地，链接互通。

---

## 8. 任务拆分预告（详细排期由 plan 落地）

1. 审计留存后端（config + purge_expired + 启动/每日调度 + 测试）
2. AdminSettings 审计留存项（前端 + settings 键登记 + 测试）
3. 主题令牌基础设施（base.css 变量 + uno.config 注册；守卫测试在 Task 5 末落地）
4. 令牌迁移第一批：App/浏览链路
5. 令牌迁移第二批：管理页/弹窗/灯箱 force-dark
6. utils/audit.ts 抽取 + AdminOverview 改引用
7. AdminAudit 页面（api 封装/过滤/表格/分页/用户名映射 + 测试）
8. CSV 导出（utils/csv.ts + 按钮交互 + 测试）
9. 移动端复核定点修复
10. 无障碍闭合（焦点管理/composable、aria、label、skip link、focus-visible + 测试）
11. README 双语 + docs/deployment.md
12. 全量测试 + 人工冒烟清单 + roadmap/台账更新

依赖顺序：1→2；3→4→5；6 先行于 7；7→8；9→10 在 5 之后；11 可与 9/10 并行；12 收尾。
