# EXIF 数据分析图表（管理概览页）

日期：2026-10-31
上游数据：P3 扫描器落库的 `images.taken_at` / `images.exif_json`（白名单 20 个 EXIF tag，见 `backend/src/myphoto/scanner.py`）
落点页面：`/admin/overview`（`frontend/src/views/AdminOverview.vue`），仅 admin 可见

---

## 1. 目标与范围

利用扫描时已保存的 EXIF 信息，在管理概览页新增一组**只读统计图表**：

1. **相机厂商分布**（Make，Top 8 + 其他）
2. **相机机型分布**（Make + Model，Top 8 + 其他）
3. **焦段分布**（按 **35mm 等效焦距**：广角 / 中焦 / 长焦 / 未知）
4. **光圈分布**（FNumber：≤f/2.8、f/4、f/5.6、f/8、f/11+、未知）
5. **拍摄趋势**（按 `taken_at` 年-月，从最早月到最近月零填充）

全局统计（跨所有图库），图表纯展示（hover 显示数值），无联动、无下钻、无点击跳转。

### 关键决策（用户已确认）

- **不重扫、不加 EXIF tag**：扫描白名单不含 `FocalLengthIn35mmFilm`（0xA405），等效焦距通过「机型 → 裁切系数表」对实际焦距 `FocalLength` 换算得到。无机型 / 机型未匹配 → 焦段归「未知」，不做实际焦距兜底。
- 后端实时聚合 + 进程内短缓存（方案 A）；不新增数据表、不改扫描器。
- 前端手写 SVG/CSS 图表，**不引入图表库**。
- 图表插入现有 `/admin/overview`，不新增页面、不新增导航项。

### 明确不做（YAGNI）

- 不做图表间联动筛选、点击下钻到照片列表、EXIF 维度搜索。
- 不做按图库 / 时间范围的筛选器（一期全局口径）。
- 不做镜头（LensModel）、ISO、快门速度、GPS 分布图（数据已落库，后续可复用同一接口模式扩展）。
- 不做扫描期间的实时刷新；面板挂载时请求一次。
- 不做 viewer 可见的统计；接口仅 admin。
- 不做服务端定时预聚合 / 物化表。

---

## 2. 数据口径

### 2.1 厂商归一（normalize_make）

对 EXIF `Make` 做大小写不敏感、去空白后的名称归一：

| EXIF 原值（示例） | 归一名称 |
|---|---|
| `NIKON CORPORATION`、`NIKON` | Nikon |
| `PENTAX`、`RICOH IMAGING COMPANY, LTD.`（Model 以 `PENTAX` 开头时） | Pentax |
| `RICOH IMAGING COMPANY, LTD.`（其他） | Ricoh |
| `OLYMPUS CORPORATION`、`OLYMPUS OPTICAL CO.,LTD` | Olympus |
| `Canon`、`CANON INC.` | Canon |
| `Panasonic`、`Panasonic Corporation` | Panasonic |
| `SONY`、`SONY CORPORATION` | Sony |
| `FUJIFILM` | Fujifilm |
| `SIGMA` | Sigma |
| `vivo`、`Xiaomi` 等手机品牌 | 保留原品牌名（用于厂商图，但不进裁切表） |
| 缺失 / 空 | 未知 |

未列入的品牌原样保留（trim 后首字母大写形式不做强制，保留 EXIF 字符串 trim 结果），不影响计数。

### 2.2 机型展示名（camera_display_name）

- 输入归一后的 Make + 原始 Model；Model 去掉首尾空白与 NUL。
- 从 Model 开头剥离去厂商名 token（不区分大小写；如 `NIKON D7000` 剥成 `D7000`、`PENTAX K-5` 剥成 `K-5`、`Canon EOS 7D` 剥成 `EOS 7D`），再统一拼成 `"{归一厂商} {剩余部分}"`（→ `Nikon D7000`、`Pentax K-5`、`Canon EOS 7D`）。Model 不含厂商名时（如 Olympus 的 `E-M1MarkIII`）直接拼接（→ `Olympus E-M1 Mark III`）。这样 Make 为 `RICOH IMAGING...` 的 PENTAX K-3 也能得到 `Pentax K-3`。
- 轻量美化（一条通用正则，不维护机型字典）：`Mark` 前缺少空格的（如 `E-M1MarkIII` → `E-M1 Mark III`）插入空格。
- 无 Model → 该照片不进机型图（计入「未知」桶），仍可进厂商图。

### 2.3 裁切系数表（crop_factor）

签名：`crop_factor(make: str | None, model: str | None) -> float | None`

匹配前对 Make/Model 统一 `upper()` 并压缩空白。**以 Model 模式匹配为主**（Make 为 `RICOH IMAGING...` 的 PENTAX K-3 也必须命中 Pentax 规则），Make 仅用于消歧。规则按品牌分组，组内**先特化后通用**，顺序即下表顺序：

**Nikon（FX = 1.0，DX = 1.5）**
- 1.0：`Z 5`/`Z5`、`Z 6`/`Z6`、`Z 7`/`Z7`、`Z 8`、`Z 9`（含 `Z6II` 等后缀）、`Z F`/`ZF`；`D3`/`D4`/`D5`/`D6`（含 x 后缀）、`D700`、`D800`/`D810`/`D850`、`Df`
- 1.5：`D1`/`D2`/`D90`、`D100`–`D500` 四位/三位机（`D3xxx`/`D5xxx`/`D7xxx` 前缀，及 `D100..D500` 枚举）、`Z 50`/`Z50`、`Z FC`/`ZFC`、`Z 30`/`Z30`
- 顺序陷阱（实现为带边界的正则，不用裸前缀）：
  - `Z 50` 以 `Z 5` 开头、`Z 5` 是 FX——DX 的 `Z 50/Z 30` 规则必须排在 FX 的 `Z 5` 之前，或用 `Z\s?5(?!0)` 这类边界写法；
  - `D500` 是 1.5（DX），`D800/D850` 是 1.0，二者都要显式规则，不靠「D 开头」猜测；
  - `Z FC` 不得被 `Z F`（Zf 全幅）前缀吞掉。
- 未匹配的 Nikon 机型（COOLPIX、E 系列小底）→ `None`。

**Canon（全画幅 = 1.0，APS-C = 1.6）**
- 1.0：初代 `EOS R`（**精确匹配**，不得作为 R 系裸前缀，否则 R3/R5/R7/R50 全被吞）、`EOS RP`、`EOS R3`、`EOS R5`（含 R5 Mark II）、`EOS R6`、`EOS R8`、`EOS 5D`、`EOS 6D`、`EOS 1D`（含 1Ds/1D X）
- 1.6：`EOS R7`、`EOS R10`、`EOS R50`、`EOS R100`；4 位数字机型（`EOS 550D`、`EOS 77D`、`EOS 400D`…，正则 `EOS \d{3,4}D`）；`REBEL`、`KISS`；`EOS M`
- 顺序陷阱：APS-C 的 R 机（R7/R10/R50/R100）必须先于 1.0 组判定；`R50` 尤其要先于 `R5`（裸前缀会误吞）。
- 未匹配（IXUS、PowerShot、DIGITAL IXUS）→ `None`。

**Pentax（Ricoh 造 Pentax 机同此组）**
- 1.0：`K-1`（含 `K-1 II`/`K-1 MARK`）
- 1.5：其余 `K-` 系（`K-3`、`K-5`、`K-r`、`K-70`、`K-S1`…，前缀 `K-`）
- 顺序陷阱：**`K-1` 规则必须先于通用 `K-` 前缀**。
- 未匹配（Q 系小底、便携机）→ `None`。

**Panasonic / LEICA（L 口全幅 = 1.0，m4/3 = 2.0）**
- 1.0：`DC-S` 前缀（S1/S1H/S1R/S5/S9，含 Mark II）
- 2.0：`DC-G`、`DMC-G`、`DC-GH`、`DMC-GH`、`DC-GF`、`DMC-GF`、`DC-GX`、`DMC-GX`；M4/3 卡口的 L 系仅限 `DMC-L1`/`DMC-L10`（正则 `DMC-L10?$`，**不能用裸 `DMC-L` 前缀**——会误吞 `DMC-LC1`/`DMC-LC5`/`DMC-LC40` 等小底便携机）
- 顺序陷阱：**`DC-S` 判定先于任何 G 规则**；`DC-S1` 不得被 G 系规则吞掉（写注释固定顺序）。
- LEICA 机型不做覆盖（用户库无数据，YAGNI）。

**Olympus / OM DIGITAL**
- 2.0：`E-M`（E-M1/E-M5/E-M10 全系）、`E-P`、`E-PL`、`E-PM`、`PEN`、`OM-1`、`OM-3`、`OM-5`

**Sony**
- 1.0：`ILCE-7`（a7 全系）、`ILCE-9`、`ILCE-1`、`DSC-RX1`、`ZV-E1`（含 ZV-E1 II；**不含 ZV-E10**）
- 1.5：`ILCE-` 其余（a5xxx/a6xxx）、`NEX-`、`ZV-E10`
- 顺序陷阱：`ZV-E10` 以 `ZV-E1` 开头——1.5 组的 ZV-E10 必须排在 1.0 组的 `ZV-E1` 之前，或用 `ZV-E1(?!0)` 边界写法。
- 未匹配（RX100 等 1 英寸小底、手机）→ `None`。

**Fujifilm**
- 0.8（44×33 中画幅）：`GFX`
- 1.5：`X-` 前缀（X-T/X-Pro/X-E/X-H/X-S/X-A/X-M）

**Sigma**
- 1.0：`FP`
- 1.7（Foveon APS-C）：`SD14`、`SD15`、`SD9`、`SD10`、`DP` 系
- 未匹配 → `None`。

**其他品牌 / 无机型 / 手机**（vivo、Xiaomi、COOLPIX、IXUS 等）→ `None` → 焦段「未知」。

规则表以「品牌 → 有序 `(正则, 系数)` 列表」的数据结构实现，匹配按品牌分组、组内首个命中返回；新增品牌只加数据不改逻辑。

### 2.4 焦段分桶

`等效焦距 = FocalLength × crop_factor`（FocalLength 取 EXIF 数值；rational 已在扫描时序列化为 number/string，string 形态如 `"1/250"` 不会出现在焦距字段，焦距为数值，若为字符串需 `float()` 解析失败 → 未知）。

| 桶 | key | 区间（等效 mm） |
|---|---|---|
| 广角 | `wide` | `< 35` |
| 中焦 | `standard` | `35 ≤ x ≤ 70` |
| 长焦 | `tele` | `> 70` |
| 未知 | `unknown` | 无机型匹配 / 无 FocalLength / 值非法 |

`FocalLength=0`、负值、非数值 → 未知。

### 2.5 光圈分桶

直接用 `FNumber`（与画幅无关，无需换算），比较时边界带 **0.05 容差**（EXIF 常存 2.795/3.968/5.595 这类浮点近似）：

| 桶 | key | 判定 |
|---|---|---|
| ≤ f/2.8 | `f28` | `f ≤ 2.85` |
| f/4 | `f4` | `2.85 < f ≤ 4.25` |
| f/5.6 | `f56` | `4.25 < f ≤ 5.95` |
| f/8 | `f8` | `5.95 < f ≤ 9.5`（吸收 f/7.1、f/9） |
| f/11 及以上 | `f11plus` | `f > 9.5` |
| 未知 | `unknown` | 无 FNumber / 非法 |

展示名固定为 `≤ f/2.8`、`f/4`、`f/5.6`、`f/8`、`f/11+`、`未知`（桶是整档归并，不逐值显示）。

### 2.6 时间归组

- 用 `taken_at`（Unix 秒，扫描时按服务器本地时区由 `DateTimeOriginal` 经 `mktime` 得到）；月键按**服务器本地时区** `strftime('%Y-%m')`，与入库口径一致，避免 UTC 偏移导致月末照片归错月。
- 范围 = 最早有照片月 → 最近有照片月，**逐月零填充**（无照片的月份 count=0，照常出柱）。
- `taken_at IS NULL`：不进月图；接口顶层返回 `without_taken_at` 计数，前端在月图标题旁标注「无拍摄日期 N 张」。

### 2.7 计数口径与分母

- 四张分布图（厂商 / 机型 / 焦段 / 光圈）的桶集合都是**全集划分**：所有照片恰好归属一个桶（缺失值归「未知」），各桶 count 之和恒等于 `total`。因此**所有百分比统一以 `total` 为分母**，前端不需要每图单独的分母。
- 厂商 / 机型：Top 8 之外合并「其他」，缺失归「未知」（count>0 时独立追加末尾）；二者的「其他」「未知」count 同样计入 total。
- 月图不显示百分比；其柱 count 之和 = `total - without_taken_at`。
- 副标题统一展示「共 N 张，M 张含拍摄参数」（M = with_exif），让读者知道未知桶的规模背景。

---

## 3. 后端

### 3.1 新模块 `myphoto/analytics.py`

不依赖 FastAPI；SQLAlchemy 只出现在读取函数里，核心聚合吃行迭代器，便于单测。

```
crop_factor(make, model) -> float | None
normalize_make(make, model) -> str          # model 用于 RICOH→PENTAX 消歧
camera_display_name(make, model) -> str | None
focal_bucket(equiv_mm: float | None) -> str
aperture_bucket(f_number) -> str
aggregate_rows(rows: Iterable[tuple[int|None, str|None]]) -> dict
build_analytics(session) -> dict            # async：SELECT + to_thread 聚合
```

- `aggregate_rows` 逐行 `json.loads(exif_json)`：**任何异常（坏 JSON、类型不符）都吞掉并按全未知处理**，不丢照片（该照片仍计入总数与月图，taken_at 在 JSON 外）。
- 月零填充用固定顺序的月份递推（`calendar.monthrange` 或整数年月递推，禁止对稀疏键排序后猜月份）。
- 输出 payload：

```json
{
  "total": 2923,
  "with_exif": 2907,
  "without_taken_at": 16,
  "makes":        [{"name": "Pentax", "count": 1411}, ..., {"name": "其他", "count": 12}, {"name": "未知", "count": 3}],
  "cameras":      [{"name": "Pentax K-5", "count": 1059}, ..., {"name": "未知", "count": 2}],
  "focal_ranges": [{"key": "wide", "name": "广角 (<35mm)", "count": 0}, {"key": "standard", "name": "中焦 (35–70mm)", "count": 0}, {"key": "tele", "name": "长焦 (>70mm)", "count": 0}, {"key": "unknown", "name": "未知", "count": 0}],
  "apertures":    [{"key": "f28", "name": "≤ f/2.8", "count": 0}, {"key": "f4", "name": "f/4", "count": 0}, {"key": "f56", "name": "f/5.6", "count": 0}, {"key": "f8", "name": "f/8", "count": 0}, {"key": "f11plus", "name": "f/11+", "count": 0}, {"key": "unknown", "name": "未知", "count": 0}],
  "months":       [{"month": "2007-03", "count": 1}, ..., {"month": "2026-07", "count": 0}]
}
```

- `makes`/`cameras`：Top 8 +「其他」；「未知」count>0 时作为最后一个独立桶追加，不参与 Top 8 合并。count=0 的「其他」省略。
- `focal_ranges`/`apertures`：固定顺序、固定 4/6 桶，count 可为 0（前端图例置灰但仍占位）。
- 桶展示名以后端 payload 为准（前端不复制口径文案）。

### 3.2 接口

`GET /api/admin/analytics`，加在 `routes_admin.py`：

- 依赖：`admin_required`（与其他 admin 接口一致，viewer → 403）；`Cache-Control: no-store`。
- 读取：`SELECT images.taken_at, images.exif_json FROM images`（无 join、无参数；全库全局口径）。
- 聚合整段放 `asyncio.to_thread`（SQLite 驱动取行 + Python 聚合都不阻塞事件循环）。
- 空库返回各桶 0、`months: []`，前端显示空态，不是错误。

### 3.3 缓存（AnalyticsCache）

新类挂 `app.state.analytics`（lifespan 中装配，位置与 scanner/thumbnails 一致）：

```
class AnalyticsCache:
    async def get(self, sessionmaker) -> dict
```

- 每次先跑签名查询（极便宜）：
  `SELECT COUNT(*), COALESCE(MAX(mtime),0), COALESCE(MAX(indexed_at),0) FROM images`
- 签名三元组与缓存一致 **且** 缓存年龄 < TTL（300 秒）→ 直接返回缓存 dict。
- 否则重新 `build_analytics` 并替换缓存（整体替换，不做原地修改）。
- TTL 是兜底（CLI 直接改库、时钟异常等）；正常路径靠签名：扫描新增/删除行改 count，更新行改 mtime/indexed_at。
- 并发请求：asyncio.Lock 防惊群，签名失效时同一时刻只跑一次聚合，其他请求等结果。
- 聚合本身异常不放行缓存逻辑外的特殊处理：异常向上抛由全局错误处理器转 500，旧缓存保留不污染。

### 3.4 后端测试（`tests/test_analytics.py`，pytest 风格对齐既有测试）

纯函数层：
- 裁切系数代表机型 + 全部顺序陷阱：K-1（1.0）vs K-5（1.5）、D500（1.5）vs D800（1.0）、Nikon Z 50（1.5）vs Z 5（1.0）、Z fc（1.5）vs Z f（1.0）、Canon R7（1.6）/R50（1.6）vs R5（1.0）/初代 R（1.0）、DC-S1（1.0）vs DC-G9（2.0）、DMC-L1（2.0）vs DMC-LC5（None）、Sony ZV-E10（1.5）vs ZV-E1（1.0）、Make 为 `RICOH IMAGING COMPANY, LTD.` 的 PENTAX K-3（1.5）、E-M1MarkIII（2.0）、vivo X100 Ultra（None）、COOLPIX S3300（None）、IXUS 750（None）。
- 焦段边界：34.9→wide，35.0→standard，70.0→standard，70.1→tele；None/0/负数→unknown。
- 光圈边界：2.795→f28，2.86→f4，3.968→f4，4.3→f56，5.595→f56，6.3→f8，7.1→f8，9.5→f8，9.6→f11plus，22→f11plus；缺失/字符串非法→unknown。
- 厂商归并：`NIKON CORPORATION` 与 `NIKON` 同名；机型展示名去重（`NIKON D7000` 不变成 `Nikon NIKON D7000`）、`E-M1MarkIII` 美化。

聚合层（合成行）：
- Top 8 + 其他 + 未知的合并与排序；
- 月零填充：跨多年、中间无照片月 count=0、无 taken_at 行计数到 without_taken_at；
- 坏 JSON 行不抛异常、全未知但仍计 total；
- 空迭代器 → 合法空 payload（months=[]）。

路由/缓存层：
- admin 200 且 payload 结构完整；viewer 403；未认证 401；
- 缓存命中：连续两次请求只产生一次全表聚合（用计数桩 / monkeypatch build_analytics 验证）；
- 签名变化（插一行）后再次请求得到新结果；TTL 不倒退时间测试（用可注入时钟或直接验证签名优先即可）。

---

## 4. 前端

### 4.1 新组件（`frontend/src/components/charts/`）

| 组件 | 形态 | 说明 |
|---|---|---|
| `HBarChart.vue` | CSS div 条形行 | props: `items: {name,count}[]`、`total`；每行：名称（截断+title）、轨道（`bg-surface-2`）、填充（`bg-primary`，宽度按本图最大值等比）、张数；`title` 附百分比（count/total）。「其他」「未知」行用 `bg-ink-muted/40` 弱化。 |
| `DonutChart.vue` | SVG 环形 + 图例 | props: `segments: {key,name,count,color}[]`、`total`、`label`；环用描边圆的 `stroke-dasharray/stroke-dashoffset` 分段（viewBox 120，环半径 40，描边 14），环心透明透出卡片底色、叠放两行中心文字（total 数值 + label）；分段间留 2px 间隔。每段 `<title>` 原生提示；右侧图例：色块 + 名称 + 张数 + 占比（按 total）。count=0 的段：图例置灰、环上不画。空环（total=0）不渲染 SVG，显示「暂无数据」。 |
| `MonthChart.vue` | SVG 柱状 | props: `months: {month,count}[]`；柱宽自适应 viewBox 宽度（`preserveAspectRatio="none"` 不用于柱——改用固定柱宽 + 容器横向滚动，保证笔触不变形）：柱宽 3px、间隔 1px，SVG 宽 = 月数×4；3 条横向网格线（0/50%/100% 计数高），y 轴标最大刻度值；x 轴仅在每年 1 月标年份（旋转 -0，水平小字，间隔不足时隔年标）；每柱 `<title>{month} · {count} 张</title>`，count=0 的月不画柱但占位。容器 `overflow-x-auto`，小屏 SVG `min-width: 720px`。 |
| `AnalyticsPanel.vue` | 容器 section | 挂载时 `apiGet('/api/admin/analytics')` 一次；自带 loading / error（`role="alert"` + 「重试」按钮，点击重新请求）/ 空态；副标题展示 total / with_exif；月图标题旁展示 without_taken_at。**不接入 AdminOverview 的 2s 轮询。** |

布局（在统计卡片 section 与扫描状态 section 之间）：

```
[4 张统计卡片]
<section> 拍摄数据分析
  <p> 基于 EXIF · 共 N 张，M 张含拍摄参数
  <div grid 2 列 / 移动 1 列，gap-4>
    [卡片：厂商 Top 8]  [卡片：机型 Top 8]
    [卡片：焦段 Donut]  [卡片：光圈 Donut]
  </div>
  [卡片：年-月趋势（全宽）]  标题旁：无拍摄日期 N 张
</section>
[扫描状态] ...
```

卡片复用现有 `rounded-lg bg-surface p-4` 容器语言，标题用现有 `text-sm font-medium text-ink-2`。

### 4.2 配色

`base.css` 明暗两主题各新增 6 个令牌：`--color-chart-1..6`，同步注册进 `uno.config.ts` 的 tokenNames。

选型（浅色主题，后续实现时按 WCAG AA 在白底上人工校验文字用途的色值；图形填充本身无对比度硬要求，但图例文字用 ink/ink-2）：

- chart-1 蓝（与 primary 同族略偏青以区分链接色）
- chart-2 绿（success 同族）
- chart-3 琥珀（warning 同族）
- chart-4 紫
- chart-5 青
- chart-6 红灰（danger 降饱和）

深色主题取同色相提亮版。固定语义映射：

- 焦段：广角 chart-1、中焦 chart-2、长焦 chart-3、未知 ink-muted/40。
- 光圈：f28→chart-1、f4→chart-2、f56→chart-3、f8→chart-4、f11+→chart-5、未知 ink-muted/40。
- 条形 / 月柱：primary；其他 / 未知：ink-muted/40。

### 4.3 无障碍

- 每张图：容器 `role="img"` + 汇总 `aria-label`（由组件根据 props 拼，如「焦段分布，共 2923 张：广角 812 张 28%，中焦……」）。
- 同卡片内附 `sr-only` `<table>`：列为 名称/张数/占比，供屏幕阅读器逐行读；视觉图表与表格二选一渲染给AT（表格 sr-only），不重复可聚焦内容。
- 月图：`role="img"` + aria-label 概括时间范围、总数、最高月；sr-only 表格只列有照片的月份（零值月不进表，避免几百行）。
- 所有文字使用 ink / ink-2，不用 ink-muted 承载信息（P7 约束：深主题 muted 不达 AA）。
- 图表无交互元素，不产生新的 tab 停；焦点环样式沿用全局。

### 4.4 前端测试（vitest，对齐 `tests/*.spec.ts` 的 mount + mock api 风格）

新增 `tests/analytics-panel.spec.ts`：
- fixture payload 下渲染 5 个标题、厂商/机型各 ≤10 行（Top 8 + 其他 + 未知）、两个 Donut 的图例段数、月柱 `<title>` 数量 = 月份数（含零填充月）；
- 空库（total=0）显示「暂无数据」且不抛错；
- apiGet reject → 错误横幅 role=alert，AdminOverview 其余区域（用例中可只挂面板）不受影响；
- sr-only 表格存在且行数正确；
- 副标题 total/with_exif、无日期 N 张文案正确。

组件小测（可并入同一文件）：
- DonutChart：各段 dash 长度占比总和 ≈ 周长、百分比文本；count=0 段不出现在环上；
- HBarChart：填充宽度按最大值等比、百分比 title；
- MonthChart：年份标签只在 1 月出现。

### 4.5 错误处理汇总

| 情况 | 行为 |
|---|---|
| 单行 exif_json 损坏 / 字段类型异常 | 后端吞异常，该照片归未知桶，仍计 total/月图 |
| 全部照片无 EXIF | 200，各桶未知/0，前端正常渲染空分布与「暂无数据」环 |
| 空库 | 200 空 payload，面板显示空态 |
| 接口 500 / 网络失败 | 面板内错误横幅 + 「重试」按钮，概览页其他 section 不受影响 |
| viewer / 未登录访问 | 403 / 401（现有 admin_required），面板走错误横幅，不泄露数据 |
| 扫描进行中打开页面 | 显示上次签名对应的聚合（可能滞后一次扫描），不提示、不轮询；5 分钟 TTL 与扫描后签名变化保证最终一致 |

---

## 5. 实施顺序建议（供 writing-plans 参考）

1. 后端纯函数（crop 表 + 归一 + 分桶）与单测 —— 风险最高、完全独立。
2. `aggregate_rows` + payload 组装与单测（合成行）。
3. AnalyticsCache + 路由 + 路由测试 + lifespan 装配。
4. 前端图表令牌（base.css / uno.config）。
5. 三个图表组件 + 组件测试。
6. AnalyticsPanel + AdminOverview 挂载 + 面板测试。
7. 真实库人工验证（当前 2923 张：核对 Pentax/Nikon/手机桶、月跨度 2007-03→2026-07）。
8. 明暗主题 + 移动端 + 屏幕阅读器走查。

## 6. 验收标准

- admin 在概览页看到 5 张图，数字与直接对 SQLite 的独立统计查询一致（厂商/机型/焦段/光圈/月）。
- K-1、R7/R50 vs R5、DC-S1 vs DC-G9、RICOH Make 的 Pentax 等陷阱机型归类正确（有单测）。
- 焦段未知桶只含无机型/无焦距照片；手机与便携机全部在未知桶。
- viewer 访问 `/api/admin/analytics` 得 403。
- 扫描完成后再次打开概览（或等 5 分钟 TTL）数字更新。
- 移动端单列可用、月图可横滑；明暗主题切换无硬编码颜色；屏幕阅读器能读到 sr-only 数据表。
- 后端 pytest 与前端 vitest 全绿；`vue-tsc --noEmit` 通过。
