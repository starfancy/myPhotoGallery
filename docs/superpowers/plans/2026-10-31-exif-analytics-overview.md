# EXIF 数据分析图表 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/admin/overview` 增加一组基于已保存 EXIF 的只读统计图表（厂商、机型、焦段、光圈、年-月趋势）。

**Architecture:** 后端新增 `myphoto/analytics.py`：纯函数做厂商归一/机型裁切系数换算/分桶/聚合，`GET /api/admin/analytics`（admin only）实时聚合全表，进程内以 `(COUNT, MAX(mtime), MAX(indexed_at))` 签名 + 300 秒 TTL 缓存。前端零新增依赖，手写 CSS 条形图与 SVG 环形/柱状图组件，`AnalyticsPanel` 独立请求，挂进 AdminOverview。不改数据库 schema、不改扫描器、不重扫照片。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2 (async) / pytest；Vue 3.4 `<script setup>` + TypeScript / UnoCSS 0.58（CSS 变量颜色令牌）/ vitest + @vue/test-utils。

**Spec:** `docs/superpowers/specs/2026-10-31-exif-analytics-overview-design.md`

## Global Constraints

- 不新增任何依赖（后端不加 pip 包，前端不加 npm 包）。
- 不改 DB schema、不加迁移、不改扫描器 EXIF 白名单、不触发照片重扫。
- 接口仅 admin：沿用 `Depends(admin_required)`；响应头 `Cache-Control: no-store`。
- 后端错误走现有 `AppError` 信封；前端用现有 `apiGet` / `HttpError`。
- 所有用户可见文案用中文；代码注释沿用现有风格（复杂逻辑英文注释 + 关键口径中文注释）。
- 颜色一律走 CSS 变量令牌（明暗双主题各一套）；信息性文字只用 `text-ink` / `text-ink-2`，不用 `text-ink-muted` 承载信息。
- 图表无交互（无 click/link），但必须有 `role="img"` + aria-label 和 `sr-only` 数据表。
- 频繁提交，每个任务一次 commit；**只 commit 不 push**（推送由用户手动执行）。
- 后端测试命令（仓库根目录执行）：`python -m pytest backend/tests/test_analytics.py -v`
- 前端测试命令：`pnpm -C frontend exec vitest run src/tests/<file>.spec.ts`
- 前端类型检查：`pnpm -C frontend exec vue-tsc --noEmit`

---

### Task 1: 后端纯函数 —— 厂商归一 / 机型裁切系数 / 分桶

**Files:**
- Create: `backend/src/myphoto/analytics.py`（本任务只放纯函数与规则表）
- Test: `backend/tests/test_analytics.py`（新建）

**Interfaces:**
- Consumes: 无（纯标准库）。
- Produces（后续任务依赖，签名固定勿改）:
  - `normalize_make(make: str | None, model: str | None = None) -> str | None`
  - `camera_display_name(make: str | None, model: str | None) -> str | None`
  - `crop_factor(make: str | None, model: str | None) -> float | None`
  - `focal_bucket(equiv_mm: float | None) -> str` → `wide|standard|tele|unknown`
  - `aperture_bucket(f_number: float | None) -> str` → `f28|f4|f56|f8|f11plus|unknown`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_analytics.py`：

```python
import pytest

from myphoto.analytics import (
    aperture_bucket,
    camera_display_name,
    crop_factor,
    focal_bucket,
    normalize_make,
)


# ---------- normalize_make ----------

@pytest.mark.parametrize("raw,expected", [
    ("NIKON CORPORATION", "Nikon"),
    ("NIKON", "Nikon"),
    ("Canon", "Canon"),
    ("CANON INC.", "Canon"),
    ("PENTAX", "Pentax"),
    ("OLYMPUS CORPORATION", "Olympus"),
    ("Panasonic", "Panasonic"),
    ("SONY", "Sony"),
    ("FUJIFILM", "Fujifilm"),
    ("SIGMA", "Sigma"),
    ("vivo", "vivo"),
    ("Xiaomi", "Xiaomi"),
    ("", None),
    ("   ", None),
    (None, None),
    ("\x00", None),
])
def test_normalize_make_aliases(raw, expected):
    assert normalize_make(raw) == expected


def test_normalize_make_ricoh_pentax_disambiguation():
    # 理光收购期的宾得机身：Make=RICOH IMAGING...，但 Model 以 PENTAX 开头
    assert normalize_make("RICOH IMAGING COMPANY, LTD.", "PENTAX K-3") == "Pentax"
    # 真正的理光机型仍归 Ricoh
    assert normalize_make("RICOH IMAGING COMPANY, LTD.", "GR III") == "Ricoh"


# ---------- camera_display_name ----------

@pytest.mark.parametrize("make,model,expected", [
    ("NIKON CORPORATION", "NIKON D7000", "Nikon D7000"),
    ("Canon", "Canon EOS 7D", "Canon EOS 7D"),
    ("RICOH IMAGING COMPANY, LTD.", "PENTAX K-3", "Pentax K-3"),
    ("OLYMPUS CORPORATION", "E-M1MarkIII", "Olympus E-M1 Mark III"),
    ("Panasonic", "DC-G9", "Panasonic DC-G9"),
    ("vivo", "vivo X100 Ultra", "vivo X100 Ultra"),
])
def test_camera_display_name(make, model, expected):
    assert camera_display_name(make, model) == expected


def test_camera_display_name_missing_model():
    assert camera_display_name("Canon", None) is None
    assert camera_display_name("Canon", "  ") is None
    assert camera_display_name("Canon", "\x00") is None


# ---------- crop_factor：代表机型 ----------

@pytest.mark.parametrize("make,model,factor", [
    # Nikon FX
    ("NIKON CORPORATION", "NIKON D800", 1.0),
    ("NIKON CORPORATION", "NIKON Z 7", 1.0),
    ("NIKON CORPORATION", "Z f", 1.0),
    # Nikon DX
    ("NIKON CORPORATION", "NIKON D7000", 1.5),
    ("NIKON CORPORATION", "NIKON D500", 1.5),
    ("NIKON CORPORATION", "NIKON Z 50", 1.5),
    ("NIKON CORPORATION", "Z fc", 1.5),
    # Canon FF / APS-C
    ("Canon", "Canon EOS 5D Mark III", 1.0),
    ("Canon", "Canon EOS R5", 1.0),
    ("Canon", "Canon EOS R", 1.0),
    ("Canon", "Canon EOS 7D", 1.6),
    ("Canon", "Canon EOS 550D", 1.6),
    ("Canon", "Canon EOS R7", 1.6),
    ("Canon", "Canon EOS R50", 1.6),
    ("Canon", "Canon EOS R100", 1.6),
    # Pentax
    ("PENTAX", "PENTAX K-1", 1.0),
    ("PENTAX", "PENTAX K-5", 1.5),
    ("PENTAX", "PENTAX K-r", 1.5),
    ("RICOH IMAGING COMPANY, LTD.", "PENTAX K-3", 1.5),
    # Panasonic
    ("Panasonic", "DC-S1", 1.0),
    ("Panasonic", "DC-G9", 2.0),
    ("Panasonic", "DMC-GH4", 2.0),
    ("Panasonic", "DMC-L1", 2.0),
    ("Panasonic", "DMC-LC5", None),  # 小底便携机，不得被 DMC-L 前缀吞掉
    # Olympus m43
    ("OLYMPUS CORPORATION", "E-M1MarkIII", 2.0),
    # Sony
    ("SONY", "ILCE-7M3", 1.0),
    ("SONY", "ILCE-6500", 1.5),
    ("SONY", "ZV-E10", 1.5),
    ("SONY", "ZV-E1", 1.0),
    ("SONY", "DSC-RX100M7", None),  # 1 英寸小底
    # Fuji / Sigma
    ("FUJIFILM", "X-T5", 1.5),
    ("FUJIFILM", "GFX 50S", 0.8),
    ("SIGMA", "SIGMA SD14", 1.7),
    ("SIGMA", "fp L", 1.0),
    # 手机 / 小底便携 → None
    ("vivo", "vivo X100 Ultra", None),
    ("Xiaomi", "M2011K2C", None),
    ("NIKON", "COOLPIX S3300", None),
    ("Canon", "Canon DIGITAL IXUS 750", None),
    (None, None, None),
])
def test_crop_factor(make, model, factor):
    assert crop_factor(make, model) == factor


# ---------- focal_bucket 边界 ----------

@pytest.mark.parametrize("mm,expected", [
    (34.9, "wide"),
    (0.0, "unknown"),
    (-1.0, "unknown"),
    (35.0, "standard"),
    (70.0, "standard"),
    (70.1, "tele"),
    (200.0, "tele"),
    (None, "unknown"),
])
def test_focal_bucket(mm, expected):
    assert focal_bucket(mm) == expected


# ---------- aperture_bucket 边界（含 0.05 容差） ----------

@pytest.mark.parametrize("f,expected", [
    (1.4, "f28"),
    (2.795, "f28"),
    (2.86, "f4"),
    (3.968, "f4"),
    (4.3, "f56"),
    (5.595, "f56"),
    (6.3, "f8"),
    (7.1, "f8"),
    (9.5, "f8"),
    (9.6, "f11plus"),
    (22.0, "f11plus"),
    (None, "unknown"),
    (0, "unknown"),
])
def test_aperture_bucket(f, expected):
    assert aperture_bucket(f) == expected
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest backend/tests/test_analytics.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'myphoto.analytics'`

- [ ] **Step 3: 创建 `backend/src/myphoto/analytics.py`（纯函数部分）**

```python
"""EXIF 分析聚合（管理概览页图表）。

本模块上半部分是不依赖 FastAPI/DB 的纯函数（厂商归一、机型裁切系数、
分桶），下半部分（后续任务加入）负责行聚合、取数与短缓存。

口径权威说明见
docs/superpowers/specs/2026-10-31-exif-analytics-overview-design.md §2。
"""
from __future__ import annotations

import re

# ---- 厂商归一 -------------------------------------------------------------

# 键为大写后的 Make，re.match 锚定字符串开头
_MAKE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"NIKON"), "Nikon"),
    (re.compile(r"CANON"), "Canon"),
    (re.compile(r"PENTAX"), "Pentax"),
    (re.compile(r"RICOH"), "Ricoh"),
    (re.compile(r"OLYMPUS"), "Olympus"),
    (re.compile(r"OM[\s-]?DIGITAL"), "OM SYSTEM"),
    (re.compile(r"PANASONIC"), "Panasonic"),
    (re.compile(r"SONY"), "Sony"),
    (re.compile(r"FUJIFILM"), "Fujifilm"),
    (re.compile(r"SIGMA"), "Sigma"),
]

# 从 Model 开头剥除的厂名 token（camera_display_name / crop_factor 共用）
_VENDOR_PREFIXES = (
    "NIKON", "CANON", "PENTAX", "OLYMPUS", "PANASONIC",
    "RICOH", "FUJIFILM", "SIGMA", "SONY",
)


def normalize_make(make: str | None, model: str | None = None) -> str | None:
    """把 EXIF Make 归一成稳定展示名；无法识别的品牌返回 trim 原值。"""
    if not isinstance(make, str):
        return None
    cleaned = make.strip().strip("\x00").strip()
    if not cleaned:
        return None
    upper = cleaned.upper()
    # 理光收购宾得影像业务后，部分宾得机身（K-3 等）写入 Make=RICOH IMAGING…
    if upper.startswith("RICOH") and (model or "").strip().upper().startswith("PENTAX"):
        return "Pentax"
    for pattern, name in _MAKE_RULES:
        if pattern.match(upper):
            return name
    return cleaned


def _strip_vendor_prefix(model: str) -> str:
    """剥掉 Model 开头自带的厂名：'NIKON D7000' -> 'D7000'。"""
    upper = model.upper()
    for token in _VENDOR_PREFIXES:
        if upper.startswith(token):
            return model[len(token):].lstrip(" -\t")
    return model


_MARK_RE = re.compile(r"(?<=[A-Za-z0-9>])(Mark)(?=[IVXLC0-9])", re.IGNORECASE)


def _prettify_model(model: str) -> str:
    """轻量美化：'E-M1MarkIII' -> 'E-M1 Mark III'。不维护机型字典。"""
    spaced = _MARK_RE.sub(r" \1 ", model)
    return re.sub(r"\s+", " ", spaced).strip()


def camera_display_name(make: str | None, model: str | None) -> str | None:
    """归一厂商 + 去重厂名前缀后的机型展示名。Model 缺失返回 None。"""
    if not isinstance(model, str):
        return None
    cleaned = model.strip().strip("\x00").strip()
    if not cleaned:
        return None
    brand = normalize_make(make, cleaned)
    rest = _strip_vendor_prefix(cleaned)
    # 未登记厂商（vivo/Xiaomi 等）不在 _VENDOR_PREFIXES 里，用原始 Make 再剥一次，
    # 否则 'vivo' + 'vivo X100 Ultra' 会拼成 'vivo vivo X100 Ultra'
    if rest == cleaned and isinstance(make, str):
        raw_make = make.strip().strip("\x00").strip()
        if raw_make and cleaned.upper().startswith(raw_make.upper()):
            tail = cleaned[len(raw_make):].lstrip(" -\t")
            if tail:
                rest = tail
    rest = _prettify_model(rest)
    if brand:
        return f"{brand} {rest}" if rest else brand
    return rest or None


# ---- 机型裁切系数表 --------------------------------------------------------
#
# 匹配键 = Model 剥厂名、去所有空白、大写（'Z 50' -> 'Z50'）。
# 规则按品牌分组，组内自上而下首个命中返回；顺序陷阱见每条注释。

_CROP_RULES: dict[str, tuple[tuple[re.Pattern[str], float], ...]] = {
    "Nikon": (
        # —— DX 微单必须排在 FX 'Z5' 前面（去空格后 Z50 不匹配 ^Z5$，双保险）——
        (re.compile(r"^Z(50|30)$"), 1.5),
        (re.compile(r"^ZFC$"), 1.5),          # Z fc；必须先于 FX 的 Zf
        # —— FX ——
        (re.compile(r"^Z[6789](II|III)?$"), 1.0),
        (re.compile(r"^Z5(II)?$"), 1.0),
        (re.compile(r"^ZF$"), 1.0),
        (re.compile(r"^D[3-6](S|X)?$"), 1.0),  # D3/D3s/D3x/D4/D4s/D5/D6
        (re.compile(r"^D700$"), 1.0),
        (re.compile(r"^D8[015]0$"), 1.0),      # D800/D810/D850
        (re.compile(r"^DF$"), 1.0),
        # —— DX 单反 ——
        (re.compile(r"^D500$"), 1.5),
        (re.compile(r"^D(100|200|300|400)$"), 1.5),
        (re.compile(r"^D90$"), 1.5),
        (re.compile(r"^D[357]\d{3}$"), 1.5),   # D3xxx/D5xxx/D7xxx
    ),
    "Canon": (
        # —— APS-C 微单先判，R50 必须先于 R5 ——
        (re.compile(r"^EOSR(7|10|50|100)$"), 1.6),
        (re.compile(r"^EOSM.*$"), 1.6),
        (re.compile(r"^.*REBEL.*$"), 1.6),
        (re.compile(r"^.*KISS.*$"), 1.6),
        # —— 全画幅 ——
        (re.compile(r"^EOSR$"), 1.0),          # 初代 EOS R，精确匹配
        (re.compile(r"^EOSRP$"), 1.0),
        (re.compile(r"^EOSR3$"), 1.0),
        (re.compile(r"^EOSR5(MARK2|MARKII)?$"), 1.0),
        (re.compile(r"^EOSR6(MARK2|MARKII)?$"), 1.0),
        (re.compile(r"^EOSR8$"), 1.0),
        (re.compile(r"^EOS5D.*$"), 1.0),
        (re.compile(r"^EOS6D.*$"), 1.0),
        (re.compile(r"^EOS1D.*$"), 1.0),       # 1Ds/1D X
        # —— APS-C 单反：3 位编号（7D/77D）与 4 位编号（550D/1000D）——
        (re.compile(r"^EOS\d{1,4}D$"), 1.6),
    ),
    "Pentax": (
        (re.compile(r"^K-1(II|MARKII|MARK2)?$"), 1.0),  # K-1 必须先于通用 K- 前缀
        (re.compile(r"^K-.*$"), 1.5),                   # K-3/K-5/K-r/K-70…
    ),
    "Panasonic": (
        (re.compile(r"^DC-S.*$"), 1.0),     # L 口全幅 S1/S5…，必须先于 G 系
        (re.compile(r"^(DC|DMC)-(G|GH|GF|GX).*$"), 2.0),
        (re.compile(r"^DMC-L10?$"), 2.0),   # m43 卡口 L1/L10；不匹配 DMC-LC5
    ),
    "Olympus": (
        (re.compile(r"^E-M.*$"), 2.0),
        (re.compile(r"^E-P(L|M)?.*$"), 2.0),  # E-P / E-PL / E-PM
        (re.compile(r"^PEN.*$"), 2.0),
        (re.compile(r"^OM-[135].*$"), 2.0),
    ),
    "OM SYSTEM": (
        (re.compile(r"^OM-[135].*$"), 2.0),
    ),
    "Sony": (
        # ZV-E10（APS-C）必须先于 ZV-E1（全幅）
        (re.compile(r"^ZV-E10.*$"), 1.5),
        (re.compile(r"^ZV-E1(MARK2|MARKII|II)?$"), 1.0),
        (re.compile(r"^ILCE-7.*$"), 1.0),
        (re.compile(r"^ILCE-9.*$"), 1.0),
        (re.compile(r"^ILCE-1$"), 1.0),
        (re.compile(r"^DSC-RX1R?$"), 1.0),   # RX1/RX1R；不吞 RX100
        (re.compile(r"^ILCE-\d"), 1.5),      # a5xxx/a6xxx 兜底
        (re.compile(r"^NEX-"), 1.5),
    ),
    "Fujifilm": (
        (re.compile(r"^GFX.*$"), 0.8),       # 44×33 中画幅
        (re.compile(r"^X-.*$"), 1.5),
    ),
    "Sigma": (
        (re.compile(r"^FP(L)?$"), 1.0),
        (re.compile(r"^SD(9|10|14|15).*$"), 1.7),
        (re.compile(r"^DP.*$"), 1.7),
    ),
}


def crop_factor(make: str | None, model: str | None) -> float | None:
    """机型 -> 裁切系数；未收录机型（手机/小底/未知）返回 None。"""
    brand = normalize_make(make, model if isinstance(model, str) else None)
    if brand is None or not isinstance(model, str):
        return None
    key = re.sub(r"\s+", "", _strip_vendor_prefix(model.strip())).upper()
    if not key:
        return None
    for pattern, factor in _CROP_RULES.get(brand, ()):
        if pattern.match(key):
            return factor
    return None


# ---- 分桶 -----------------------------------------------------------------

def focal_bucket(equiv_mm: float | None) -> str:
    """按 35mm 等效焦距分桶：<35 广角，35–70 中焦，>70 长焦。"""
    if equiv_mm is None or equiv_mm <= 0:
        return "unknown"
    if equiv_mm < 35:
        return "wide"
    if equiv_mm <= 70:
        return "standard"
    return "tele"


def aperture_bucket(f_number: float | None) -> str:
    """FNumber 整档归并，边界带 0.05 左右容差（EXIF 常存 2.795/3.968）。"""
    if f_number is None or f_number <= 0:
        return "unknown"
    if f_number <= 2.85:
        return "f28"
    if f_number <= 4.25:
        return "f4"
    if f_number <= 5.95:
        return "f56"
    if f_number <= 9.5:
        return "f8"
    return "f11plus"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest backend/tests/test_analytics.py -v`
Expected: 全部 PASS（约 60+ 参数化用例）。

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/analytics.py backend/tests/test_analytics.py
git commit -m "feat(analytics): EXIF make/model crop-factor tables and focal/aperture buckets"
```

---

### Task 2: 行聚合 aggregate_rows 与 payload 组装

**Files:**
- Modify: `backend/src/myphoto/analytics.py`（追加聚合部分）
- Test: `backend/tests/test_analytics.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 5 个纯函数；行输入 `Iterable[tuple[int | None, str | None]]` = `(taken_at, exif_json)`。
- Produces:
  - `aggregate_rows(rows) -> dict`（payload 形状见下，字段名前端依赖，勿改）
  - 常量 `FOCAL_SEGMENTS` / `APERTURE_SEGMENTS`（`list[(key, 展示名)]`，固定顺序）

Payload 形状：

```python
{
  "total": int, "with_exif": int, "without_taken_at": int,
  "makes": [{"name": str, "count": int}, ...],          # Top8 + 其他 + 未知
  "cameras": [{"name": str, "count": int}, ...],
  "focal_ranges": [{"key": str, "name": str, "count": int}],  # 固定 4 桶
  "apertures": [{"key": str, "name": str, "count": int}],     # 固定 6 桶
  "months": [{"month": "YYYY-MM", "count": int}, ...],        # 零填充
}
```

- [ ] **Step 1: 追加失败测试**

先在 `backend/tests/test_analytics.py` 顶部 import 区加入 `import json` 以及把 `aggregate_rows` 加入 `from myphoto.analytics import (...)` 导入列表，然后文件末尾追加：

```python
# ---------- aggregate_rows ----------


def _row(make=None, model=None, focal=None, fnumber=None, taken_at=1_700_000_000,
         blob="__use_exif__"):
    """构造 (taken_at, exif_json) 合成行。blob=None 表示无 EXIF 列。"""
    exif = {}
    if make is not None:
        exif["Make"] = make
    if model is not None:
        exif["Model"] = model
    if focal is not None:
        exif["FocalLength"] = focal
    if fnumber is not None:
        exif["FNumber"] = fnumber
    if blob == "__bad__":
        return taken_at, "{not json"
    if blob is None:
        return taken_at, None
    return taken_at, json.dumps(exif)


def test_aggregate_empty():
    out = aggregate_rows([])
    assert out["total"] == 0
    assert out["with_exif"] == 0
    assert out["without_taken_at"] == 0
    assert out["makes"] == []
    assert out["cameras"] == []
    assert out["months"] == []
    assert [s["count"] for s in out["focal_ranges"]] == [0, 0, 0, 0]
    assert [s["key"] for s in out["focal_ranges"]] == ["wide", "standard", "tele", "unknown"]
    assert [s["key"] for s in out["apertures"]] == ["f28", "f4", "f56", "f8", "f11plus", "unknown"]


def test_aggregate_basic_counts_and_equiv_focal():
    rows = [
        # DX 机身：24mm 实际 -> 36mm 等效 -> 中焦
        _row("NIKON CORPORATION", "NIKON D7000", focal=24, fnumber=5.595),
        # 全幅：24mm -> 广角
        _row("NIKON CORPORATION", "NIKON D800", focal=24, fnumber=2.8),
        # 手机无机型系数 -> 焦段未知；不给 FNumber -> 光圈也未知
        _row("vivo", "vivo X100 Ultra", focal=5.2),
    ]
    out = aggregate_rows(rows)
    assert out["total"] == 3
    assert out["with_exif"] == 3
    focal = {s["key"]: s["count"] for s in out["focal_ranges"]}
    assert focal == {"wide": 1, "standard": 1, "tele": 0, "unknown": 1}
    ap = {s["key"]: s["count"] for s in out["apertures"]}
    assert ap["f28"] == 1
    assert ap["f56"] == 1
    assert ap["f28"] + ap["f56"] == 2
    assert ap["unknown"] == 1
    makes = {m["name"]: m["count"] for m in out["makes"]}
    assert makes["Nikon"] == 2
    assert makes["vivo"] == 1
    cameras = {m["name"]: m["count"] for m in out["cameras"]}
    assert cameras["Nikon D7000"] == 1


def test_aggregate_make_and_camera_unknown_buckets():
    rows = [
        _row(None, None),                       # 无 Make/Model
        _row("Canon", "Canon EOS 5D Mark III"),
        _row(blob=None),                        # 整行无 EXIF
    ]
    out = aggregate_rows(rows)
    assert out["makes"][-1] == {"name": "未知", "count": 2}
    assert out["cameras"][-1] == {"name": "未知", "count": 2}
    # 所有照片都在四个焦段桶 / 六个光圈桶里（全集划分，合计 = total）
    assert sum(s["count"] for s in out["focal_ranges"]) == 3
    assert sum(s["count"] for s in out["apertures"]) == 3
    assert sum(m["count"] for m in out["makes"]) == 3


def test_aggregate_top8_plus_other():
    rows = [_row(f"Brand{i}", f"Model{i}") for i in range(10)]
    out = aggregate_rows(rows)
    # 10 个不同厂商：Top 8 + 其他(2)，无机型未知桶
    names = [m["name"] for m in out["makes"]]
    assert len(names) == 9
    assert names[-1] == "其他"
    assert out["makes"][-1]["count"] == 2


def test_aggregate_month_zero_fill_and_missing_taken_at():
    # 取 UTC 正午的时间戳：UTC-12 ~ UTC+14 任意时区都落在同一天，断言不依赖运行机器时区。
    # 2025-01-15 / 2025-02-15 / 2025-03-15 各一张，中间无缺月；另有 1 张无拍摄日期
    rows = [
        _row("Canon", "Canon EOS R5", taken_at=1_736_942_400),  # 2025-01-15 12:00 UTC
        _row("Canon", "Canon EOS R5", taken_at=1_739_620_800),  # 2025-02-15 12:00 UTC
        _row("Canon", "Canon EOS R5", taken_at=1_742_040_000),  # 2025-03-15 12:00 UTC
        _row("Canon", "Canon EOS R5", taken_at=None),
    ]
    out = aggregate_rows(rows)
    assert out["without_taken_at"] == 1
    months = out["months"]
    assert [m["month"] for m in months] == ["2025-01", "2025-02", "2025-03"]
    assert months[0]["count"] == 1
    assert months[2]["count"] == 1
    assert sum(m["count"] for m in months) == 3


def test_aggregate_bad_json_does_not_raise():
    out = aggregate_rows([
        (1_700_000_000, "{bad json"),
        (1_700_000_000, None),
    ])
    assert out["total"] == 2
    assert out["with_exif"] == 0
    # 坏行仍计入月图（taken_at 在 JSON 外）
    assert sum(m["count"] for m in out["months"]) == 2
    # 坏行归未知，不影响其他照片
    assert {s["key"]: s["count"] for s in out["focal_ranges"]}["unknown"] == 2


def test_aggregate_string_numeric_exif_values():
    # 扫描器对个别 rational 可能序列化成字符串；可解析为 float 的照常归类
    out = aggregate_rows([_row("Canon", "Canon EOS R5", focal="50", fnumber="2.8")])
    focal = {s["key"]: s["count"] for s in out["focal_ranges"]}
    assert focal["standard"] == 1
    assert {s["key"]: s["count"] for s in out["apertures"]}["f28"] == 1
```

注意：时间零填充测试用 UTC 时间戳，`aggregate_rows` 按**服务器本地时区**归月；在 UTC+8 机器上前两个时间戳落在同一天/月无影响（2025-01-01 00:00 UTC = 北京 08:00 同月；2025-02-28、2025-03-31 同理同月）。实现时**不要**在测试里对时区做假设以外的断言。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest backend/tests/test_analytics.py -v`
Expected: FAIL，`ImportError: cannot import name 'aggregate_rows'`

- [ ] **Step 3: 在 `analytics.py` 追加聚合实现**

在文件顶部 import 区补充：

```python
import json
import time
from collections import Counter
from typing import Iterable
```

文件末尾追加：

```python
# ---- 行聚合 ---------------------------------------------------------------

TOP_N = 8

FOCAL_SEGMENTS: list[tuple[str, str]] = [
    ("wide", "广角 (<35mm)"),
    ("standard", "中焦 (35–70mm)"),
    ("tele", "长焦 (>70mm)"),
    ("unknown", "未知"),
]

APERTURE_SEGMENTS: list[tuple[str, str]] = [
    ("f28", "≤ f/2.8"),
    ("f4", "f/4"),
    ("f56", "f/5.6"),
    ("f8", "f/8"),
    ("f11plus", "f/11+"),
    ("unknown", "未知"),
]

_UNKNOWN_BUCKET = "未知"
_OTHER_BUCKET = "其他"


def _as_float(value: object) -> float | None:
    """EXIF 数值容错：bool 拒绝、数字直取、可解析字符串转 float，其余 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _top_items(counter: Counter) -> list[dict[str, object]]:
    """Top N + 「其他」；「未知」始终独立放在最后（count>0 时）。"""
    unknown = counter.pop(_UNKNOWN_BUCKET, 0)
    top = counter.most_common(TOP_N)
    other_count = sum(counter.values()) - sum(cnt for _, cnt in top)
    items: list[dict[str, object]] = [
        {"name": name, "count": cnt} for name, cnt in top
    ]
    if other_count > 0:
        items.append({"name": _OTHER_BUCKET, "count": other_count})
    if unknown > 0:
        items.append({"name": _UNKNOWN_BUCKET, "count": unknown})
    return items


def _zero_fill_months(counter: Counter[str]) -> list[dict[str, object]]:
    """从最早月到最近月逐月补零。键格式 'YYYY-MM'（零填充，字符串序=时间序）。"""
    if not counter:
        return []
    start_y, start_m = (int(x) for x in min(counter).split("-"))
    end_y, end_m = (int(x) for x in max(counter).split("-"))
    out: list[dict[str, object]] = []
    year, month = start_y, start_m
    while (year, month) <= (end_y, end_m):
        key = f"{year:04d}-{month:02d}"
        out.append({"month": key, "count": counter.get(key, 0)})
        month += 1
        if month == 13:
            month, year = 1, year + 1
    return out


def aggregate_rows(
    rows: Iterable[tuple[int | None, str | None]],
) -> dict[str, object]:
    """把 (taken_at, exif_json) 行聚合成图表 payload。

    单行 JSON 损坏 / 字段类型异常一律吞掉按未知处理，绝不抛异常；
    该照片仍计入 total 与月图（taken_at 不在 JSON 内）。
    """
    makes_c: Counter[str] = Counter()
    cameras_c: Counter[str] = Counter()
    focal_c: Counter[str] = Counter()
    aperture_c: Counter[str] = Counter()
    months_c: Counter[str] = Counter()
    total = 0
    with_exif = 0
    without_taken_at = 0

    for taken_at, blob in rows:
        total += 1
        if taken_at is None:
            without_taken_at += 1
        else:
            months_c[time.strftime("%Y-%m", time.localtime(taken_at))] += 1

        exif: dict[str, object] = {}
        if blob:
            try:
                parsed = json.loads(blob)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, dict):
                exif = parsed
                with_exif += 1

        make_raw = exif.get("Make") if isinstance(exif.get("Make"), str) else None
        model_raw = exif.get("Model") if isinstance(exif.get("Model"), str) else None

        make = normalize_make(make_raw, model_raw)
        if make:
            makes_c[make] += 1
        else:
            makes_c[_UNKNOWN_BUCKET] += 1

        camera = camera_display_name(make_raw, model_raw)
        if camera:
            cameras_c[camera] += 1
        else:
            cameras_c[_UNKNOWN_BUCKET] += 1

        focal = _as_float(exif.get("FocalLength"))
        factor = crop_factor(make_raw, model_raw)
        if focal is not None and focal > 0 and factor is not None:
            focal_c[focal_bucket(focal * factor)] += 1
        else:
            focal_c["unknown"] += 1

        aperture_c[aperture_bucket(_as_float(exif.get("FNumber")))] += 1

    return {
        "total": total,
        "with_exif": with_exif,
        "without_taken_at": without_taken_at,
        "makes": _top_items(makes_c),
        "cameras": _top_items(cameras_c),
        "focal_ranges": [
            {"key": key, "name": label, "count": focal_c.get(key, 0)}
            for key, label in FOCAL_SEGMENTS
        ],
        "apertures": [
            {"key": key, "name": label, "count": aperture_c.get(key, 0)}
            for key, label in APERTURE_SEGMENTS
        ],
        "months": _zero_fill_months(months_c),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest backend/tests/test_analytics.py -v`
Expected: 全部 PASS（Task 1 + Task 2）。

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/analytics.py backend/tests/test_analytics.py
git commit -m "feat(analytics): aggregate EXIF rows into chart payload with top-N and month zero-fill"
```

---

### Task 3: 取数 / 缓存 / API 路由 / lifespan 装配

**Files:**
- Modify: `backend/src/myphoto/analytics.py`（追加 `build_analytics` 与 `AnalyticsCache`）
- Modify: `backend/src/myphoto/routes_admin.py`（新增 1 个端点）
- Modify: `backend/src/myphoto/main.py`（lifespan 装配 `app.state.analytics`）
- Test: `backend/tests/test_analytics.py`（追加路由与缓存测试）

**Interfaces:**
- Consumes: `aggregate_rows`（Task 2）；`Image.taken_at` / `Image.exif_json` / `Image.mtime` / `Image.indexed_at`。
- Produces:
  - `async build_analytics(session) -> dict`
  - `class AnalyticsCache`: `async get(sessionmaker) -> dict`，构造参数 `ttl: float = 300.0`
  - `GET /api/admin/analytics`（admin only，no-store）

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_analytics.py` 顶部 import 区追加（`json` 与 `pytest` 在 Task 1/2 已导入，不重复）：

```python
import re
import time

from fastapi.testclient import TestClient

from myphoto.main import build_app
from myphoto.models import Folder, Gallery, GalleryRoot, Image, User
from myphoto.security import hash_password
```

文件末尾追加：

```python
# ---------- 路由与缓存 ----------

@pytest.fixture
def app_client(tmp_path, capsys):
    photos = tmp_path / "photos"
    photos.mkdir()
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as client:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        yield app, client, pw, photos


def _login(client, username, password):
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def test_analytics_endpoint_empty_db_admin(app_client):
    _, client, pw, _ = app_client
    _login(client, "admin", pw)
    r = client.get("/api/admin/analytics")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["total"] == 0
    assert body["makes"] == []
    assert body["months"] == []
    assert len(body["focal_ranges"]) == 4
    assert len(body["apertures"]) == 6


def test_analytics_endpoint_requires_auth(app_client):
    _, client, _, _ = app_client
    assert client.get("/api/admin/analytics").status_code == 401


def test_analytics_endpoint_forbids_viewer(app_client):
    app, client, _, _ = app_client

    async def _make_viewer():
        async with app.state.sessionmaker() as s:
            # remote_allowed：避免 TestClient 的 "testclient" 主机名触发 lan_only 登录限制；
            # 本用例要验证的是角色 403，与访问范围无关。
            s.add(User(
                username="viewer1", password_hash=hash_password("viewerpass123"),
                role="viewer", access_scope="remote_allowed", enabled=1,
                created_at=int(time.time()),
            ))
            await s.commit()

    client.portal.call(_make_viewer)
    _login(client, "viewer1", "viewerpass123")
    assert client.get("/api/admin/analytics").status_code == 403


def test_analytics_endpoint_seeded_counts(app_client):
    app, client, pw, photos = app_client

    async def _seed():
        async with app.state.sessionmaker() as s:
            g = Gallery(name="G", created_at=1)
            s.add(g)
            await s.flush()
            r = GalleryRoot(gallery_id=g.id, label="R",
                            absolute_path=str(photos), enabled=1)
            s.add(r)
            await s.flush()
            f = Folder(root_id=r.id, relative_path="", name="",
                       image_count=0, descendant_count=0)
            s.add(f)
            await s.flush()
            for i, (make, model, focal) in enumerate([
                ("NIKON CORPORATION", "NIKON D7000", 24),
                ("NIKON CORPORATION", "NIKON D800", 24),
                ("vivo", "vivo X100 Ultra", 5.2),
            ]):
                s.add(Image(
                    root_id=r.id, folder_id=f.id, relative_path=f"a{i}.jpg",
                    filename=f"a{i}.jpg", ext="jpg", size_bytes=1, sha1=f"x{i}",
                    mtime=100 + i, width=10, height=10,
                    # 间隔 31 天 → 2025-01-15 / 02-15 / 03-18，跨 3 个月
                    taken_at=1_736_942_400 + i * 31 * 86400, is_raw=0,
                    indexed_at=1, exif_json=json.dumps(
                        {"Make": make, "Model": model, "FocalLength": focal,
                         "FNumber": 5.6}),
                ))
            await s.commit()

    client.portal.call(_seed)

    _login(client, "admin", pw)
    body = client.get("/api/admin/analytics").json()
    assert body["total"] == 3
    assert {m["name"]: m["count"] for m in body["makes"]}["Nikon"] == 2
    focal = {s["key"]: s["count"] for s in body["focal_ranges"]}
    assert focal["wide"] == 1       # D800 24mm 全幅
    assert focal["standard"] == 1   # D7000 24x1.5=36mm
    assert focal["unknown"] == 1    # 手机
    assert len(body["months"]) == 3


def test_analytics_cache_reuses_until_signature_changes(app_client, monkeypatch):
    app, client, _, _ = app_client
    sm = app.state.sessionmaker
    calls = 0

    async def fake_build(session):
        nonlocal calls
        calls += 1
        return {"total": calls}

    monkeypatch.setattr("myphoto.analytics.build_analytics", fake_build)

    async def scenario():
        await app.state.analytics.get(sm)
        await app.state.analytics.get(sm)
        assert calls == 1  # 签名未变，第二次命中缓存
        # 插入一行改变签名（COUNT 与 MAX(indexed_at) 都变）
        async with sm() as s:
            g = Gallery(name="G2", created_at=1)
            s.add(g)
            await s.flush()
            r = GalleryRoot(gallery_id=g.id, label="R2",
                            absolute_path=str(app.state.config.data_dir), enabled=1)
            s.add(r)
            await s.flush()
            f = Folder(root_id=r.id, relative_path="", name="",
                       image_count=0, descendant_count=0)
            s.add(f)
            await s.flush()
            s.add(Image(
                root_id=r.id, folder_id=f.id, relative_path="z.jpg",
                filename="z.jpg", ext="jpg", size_bytes=1, sha1="zz",
                mtime=999, width=1, height=1, taken_at=None, is_raw=0,
                indexed_at=999, exif_json=None,
            ))
            await s.commit()
        await app.state.analytics.get(sm)
        assert calls == 2  # 签名变化后重建

    client.portal.call(scenario)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest backend/tests/test_analytics.py -v`
Expected: FAIL（路由 404；`app.state.analytics` 不存在）。

- [ ] **Step 3: 在 `analytics.py` 追取数与缓存**

import 区补充：

```python
import asyncio

from sqlalchemy import func, select

from myphoto.models import Image
```

文件末尾追加：

```python
# ---- 取数与缓存 ------------------------------------------------------------

_CACHE_TTL_SECONDS = 300.0


async def build_analytics(session) -> dict[str, object]:
    """读全表 (taken_at, exif_json) 两列，在工作线程里做 CPU 聚合。"""
    rows = (
        await session.execute(select(Image.taken_at, Image.exif_json))
    ).all()
    return await asyncio.to_thread(aggregate_rows, rows)


class AnalyticsCache:
    """按 (COUNT, MAX(mtime), MAX(indexed_at)) 签名缓存聚合结果。

    签名不变且未过 TTL 直接复用；扫描增删行改 count、更新行改
    mtime/indexed_at，签名自然变化。asyncio.Lock 防并发惊群。
    """

    def __init__(self, ttl: float = _CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl
        self._lock = asyncio.Lock()
        self._signature: tuple[int, int, int] | None = None
        self._payload: dict[str, object] | None = None
        self._built_at = 0.0

    async def _signature_now(self, session) -> tuple[int, int, int]:
        row = (
            await session.execute(
                select(
                    func.count(),
                    func.coalesce(func.max(Image.mtime), 0),
                    func.coalesce(func.max(Image.indexed_at), 0),
                )
            )
        ).one()
        return int(row[0]), int(row[1]), int(row[2])

    async def get(self, sessionmaker) -> dict[str, object]:
        async with sessionmaker() as session:
            signature = await self._signature_now(session)

        async with self._lock:
            # double-check：排队等锁的请求在首个请求构建完后直接复用
            now = time.time()
            if (
                self._payload is not None
                and self._signature == signature
                and now - self._built_at < self._ttl
            ):
                return self._payload

            async with sessionmaker() as session:
                payload = await build_analytics(session)
            self._payload = payload
            self._signature = signature
            self._built_at = now
            return payload
```

- [ ] **Step 4: 加路由**

在 `backend/src/myphoto/routes_admin.py` 找到 `@router.get("/status")`（约 865 行），在其**上方**插入：

```python
@router.get("/analytics")
async def admin_analytics(
    request: Request,
    response: Response,
    _admin: User = Depends(admin_required),
):
    """全局 EXIF 统计聚合（图表数据）。仅 admin；实时聚合 + 短缓存。"""
    response.headers["Cache-Control"] = "no-store"
    return await request.app.state.analytics.get(request.app.state.sessionmaker)
```

- [ ] **Step 5: lifespan 装配**

在 `backend/src/myphoto/main.py` 顶部 import 区（`from myphoto.trash import ...` 附近）加：

```python
from myphoto.analytics import AnalyticsCache
```

在 lifespan 内 `app.state.thumbnails = ThumbnailGenerator(...)` 语句之后加一行：

```python
        app.state.analytics = AnalyticsCache()
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest backend/tests/test_analytics.py -v`
Expected: 全部 PASS。

再跑后端全量测试确认无回归：

Run: `python -m pytest backend/tests -q`
Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add backend/src/myphoto/analytics.py backend/src/myphoto/routes_admin.py \
  backend/src/myphoto/main.py backend/tests/test_analytics.py
git commit -m "feat(admin): /api/admin/analytics endpoint with signature-based short cache"
```

---

### Task 4: 颜色令牌 + DonutChart 环形图组件

**Files:**
- Modify: `frontend/src/styles/base.css`（明暗两主题各加 6 个图表色）
- Modify: `frontend/uno.config.ts`（tokenNames 注册）
- Create: `frontend/src/components/charts/DonutChart.vue`
- Test: `frontend/src/tests/chart-donut.spec.ts`

**Interfaces:**
- Produces:
  - CSS 变量 `--color-chart-1..6`（明暗双主题）
  - `DonutChart.vue` props：
    - `title: string`（用于 aria-label / 表标题，如「焦段分布」）
    - `label: string`（环心小字，如「张」）
    - `total: number`
    - `segments: Array<{ key: string; name: string; count: number; color: string }>`
      （`color` 为 CSS 颜色字符串，如 `"rgb(var(--color-chart-1))"`）

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/tests/chart-donut.spec.ts`：

```ts
import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import DonutChart from "../components/charts/DonutChart.vue"

const SEGS = [
  { key: "wide", name: "广角", count: 1, color: "rgb(var(--color-chart-1))" },
  { key: "standard", name: "中焦", count: 1, color: "rgb(var(--color-chart-2))" },
  { key: "tele", name: "长焦", count: 1, color: "rgb(var(--color-chart-3))" },
  { key: "unknown", name: "未知", count: 1, color: "rgb(var(--color-ink-muted) / 0.5)" },
]

function mountChart(segments = SEGS, total = 4) {
  return mount(DonutChart, {
    props: { title: "焦段分布", label: "张", total, segments },
  })
}

describe("DonutChart", () => {
  it("draws one arc per non-zero segment with lengths summing to the circumference minus gaps", () => {
    const w = mountChart()
    const arcs = w.findAll("svg circle[stroke-dasharray]")
    expect(arcs.length).toBe(4)
    const C = 2 * Math.PI * 40
    const drawn = arcs.map((c) => Number(c.attributes("stroke-dasharray")!.split(" ")[0]))
    // 4 段各 25%，实现对每段扣 2px 间隔（首尾相邻，共 4 个间隔）→ C-8
    expect(drawn.reduce((a, b) => a + b, 0)).toBeCloseTo(C - 2 * 4, 0)
  })

  it("skips zero-count segments but keeps them in the legend (dimmed)", () => {
    const segs = [
      { key: "wide", name: "广角", count: 3, color: "c1" },
      { key: "standard", name: "中焦", count: 0, color: "c2" },
    ]
    const w = mountChart(segs, 3)
    expect(w.findAll("svg circle[stroke-dasharray]").length).toBe(1)
    const legend = w.findAll("li")
    expect(legend.length).toBe(2)
    expect(legend[1].classes().join(" ")).toContain("opacity-40")
  })

 it("renders count and rounded percentage in the legend", () => {
    const segs = [{ key: "a", name: "甲类", count: 1, color: "c1" },
                  { key: "b", name: "乙类", count: 3, color: "c2" }]
    const w = mountChart(segs, 4)
    const text = w.text()
    expect(text).toContain("25%")
    expect(text).toContain("75%")
  })

  it("exposes an img role with summarized aria-label and an sr-only data table", () => {
    const w = mountChart()
    const img = w.find('[role="img"]')
    expect(img.attributes("aria-label")).toContain("焦段分布")
    expect(img.attributes("aria-label")).toContain("广角")
    const table = w.find("table.sr-only")
    expect(table.exists()).toBe(true)
    expect(table.findAll("tbody tr").length).toBe(4)
  })

  it("shows an empty state when total is zero", () => {
    const w = mountChart([], 0)
    expect(w.text()).toContain("暂无数据")
    expect(w.find("svg").exists()).toBe(false)
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm -C frontend exec vitest run src/tests/chart-donut.spec.ts`
Expected: FAIL（找不到组件模块）。

- [ ] **Step 3: 加颜色令牌**

在 `frontend/src/styles/base.css` 的浅色 `:root { ... }` 块末尾（`--color-focus-ring` 之后）加：

```css
  /* 图表分类色（分析面板环形图）：色相固定，深色主题另有提亮版 */
  --color-chart-1: 45 108 192;   /* 蓝 */
  --color-chart-2: 52 153 102;   /* 绿 */
  --color-chart-3: 204 138 24;   /* 琥珀 */
  --color-chart-4: 133 99 198;   /* 紫 */
  --color-chart-5: 38 158 168;   /* 青 */
  --color-chart-6: 190 90 98;    /* 红灰 */
```

在 `@media (prefers-color-scheme: dark)` 的块末尾加：

```css
    --color-chart-1: 96 150 228;
    --color-chart-2: 96 190 140;
    --color-chart-3: 224 172 80;
    --color-chart-4: 170 140 222;
    --color-chart-5: 92 190 198;
    --color-chart-6: 220 140 146;
```

在 `frontend/uno.config.ts` 的 `tokenNames` 数组里 `"focus-ring"` 之后加六个 token：

```ts
  "chart-1", "chart-2", "chart-3", "chart-4", "chart-5", "chart-6",
```

- [ ] **Step 4: 创建 DonutChart 组件**

创建 `frontend/src/components/charts/DonutChart.vue`：

```vue
<template>
  <div>
    <div v-if="total > 0">
      <div class="flex items-center gap-4" role="img" :aria-label="ariaLabel">
        <div class="relative h-32 w-32 shrink-0">
          <svg viewBox="0 0 120 120" class="h-full w-full -rotate-90" aria-hidden="true">
            <circle cx="60" cy="60" :r="RADIUS" fill="none"
                    stroke="rgb(var(--color-surface-2))" :stroke-width="STROKE" />
            <circle v-for="seg in drawn" :key="seg.key"
                    cx="60" cy="60" :r="RADIUS" fill="none"
                    :stroke="seg.color" :stroke-width="STROKE"
                    :stroke-dasharray="seg.dash"
                    :stroke-dashoffset="seg.offset" />
          </svg>
          <div class="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span class="text-xl font-medium leading-none tabular-nums">{{ total.toLocaleString() }}</span>
            <span class="mt-1 text-xs text-ink-2">{{ label }}</span>
          </div>
        </div>
        <ul class="min-w-0 flex-1 space-y-1">
          <li v-for="seg in segments" :key="seg.key"
              class="flex items-center gap-2 text-xs"
              :class="seg.count === 0 ? 'opacity-40' : ''">
            <span class="h-2.5 w-2.5 shrink-0 rounded-sm" :style="{ backgroundColor: seg.color }"></span>
            <span class="min-w-0 truncate text-ink-2">{{ seg.name }}</span>
            <span class="ml-auto shrink-0 tabular-nums text-ink-2">{{ seg.count.toLocaleString() }}</span>
            <span class="w-11 shrink-0 text-right tabular-nums text-ink-2">{{ pct(seg.count) }}%</span>
          </li>
        </ul>
      </div>
      <!-- 屏幕阅读器数据表：与图形同源数据，视觉隐藏 -->
      <table class="sr-only">
        <caption>{{ title }}</caption>
        <thead>
          <tr><th scope="col">分类</th><th scope="col">张数</th><th scope="col">占比</th></tr>
        </thead>
        <tbody>
          <tr v-for="seg in segments" :key="seg.key">
            <td>{{ seg.name }}</td>
            <td>{{ seg.count }}</td>
            <td>{{ pct(seg.count) }}%</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="text-sm text-ink-2">暂无数据</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"

interface Segment {
  key: string
  name: string
  count: number
  color: string
}

const props = defineProps<{
  title: string
  label: string
  total: number
  segments: Segment[]
}>()

const RADIUS = 40
const STROKE = 14
const C = 2 * Math.PI * RADIUS
const GAP = 2 // 段间间隔 px；单段时不加间隔

interface DrawnSegment extends Segment {
  dash: string
  offset: number
}

const drawn = computed<DrawnSegment[]>(() => {
  const visible = props.segments.filter((s) => s.count > 0)
  const gap = visible.length > 1 ? GAP : 0
  let acc = 0
  return visible.map((seg) => {
    const frac = seg.count / props.total
    const len = Math.max(0, frac * C - gap)
    const out: DrawnSegment = {
      ...seg,
      dash: `${len} ${C - len}`,
      offset: -acc,
    }
    acc += frac * C
    return out
  })
})

function pct(count: number): number {
  return props.total > 0 ? Math.round((count / props.total) * 100) : 0
}

const ariaLabel = computed(() => {
  const parts = props.segments
    .filter((s) => s.count > 0)
    .map((s) => `${s.name} ${s.count.toLocaleString()} 张 ${pct(s.count)}%`)
  return `${props.title}，共 ${props.total.toLocaleString()} 张：${parts.join("，")}`
})
</script>
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pnpm -C frontend exec vitest run src/tests/chart-donut.spec.ts`
Expected: 5 个用例 PASS。

- [ ] **Step 6: 类型检查并提交**

Run: `pnpm -C frontend exec vue-tsc --noEmit`
Expected: 无错误。

```bash
git add frontend/src/styles/base.css frontend/uno.config.ts \
  frontend/src/components/charts/DonutChart.vue frontend/src/tests/chart-donut.spec.ts
git commit -m "feat(overview): donut chart component with chart color tokens"
```

---

### Task 5: HBarChart 水平条形图组件

**Files:**
- Create: `frontend/src/components/charts/HBarChart.vue`
- Test: `frontend/src/tests/chart-hbar.spec.ts`

**Interfaces:**
- Produces:
  - `HBarChart.vue` props：
    - `title: string`
    - `items: Array<{ name: string; count: number; dimmed?: boolean }>`（`dimmed` 条用中性色弱化，用于「其他」「未知」）
    - `total: number`（百分比分母；条宽按本图最大 count 等比）

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/tests/chart-hbar.spec.ts`：

```ts
import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import HBarChart from "../components/charts/HBarChart.vue"

const ITEMS = [
  { name: "Pentax", count: 100 },
  { name: "Nikon", count: 50 },
  { name: "其他", count: 10, dimmed: true },
  { name: "未知", count: 5, dimmed: true },
]

function mountChart(items = ITEMS, total = 165) {
  return mount(HBarChart, { props: { title: "相机厂商", items, total } })
}

describe("HBarChart", () => {
  it("renders one row per item with name and count", () => {
    const w = mountChart()
    const rows = w.findAll("li")
    expect(rows.length).toBe(4)
    expect(w.text()).toContain("Pentax")
    expect(w.text()).toContain("Nikon")
  })

  it("scales bar widths to the largest count (largest = 100%)", () => {
    const w = mountChart()
    const fills = w.findAll('[data-testid="bar-fill"]')
    expect(fills[0].attributes("style")).toContain("width: 100%")
    expect(fills[1].attributes("style")).toContain("width: 50%")
  })

  it("dims 其他/未知 rows with the muted fill class", () => {
    const w = mountChart()
    const fills = w.findAll('[data-testid="bar-fill"]')
    expect(fills[0].classes()).toContain("bg-primary")
    expect(fills[2].classes().join(" ")).toContain("bg-ink-muted/40")
    expect(fills[3].classes().join(" ")).toContain("bg-ink-muted/40")
  })

  it("shows count/total percentage in the row title tooltip", () => {
    const w = mountChart()
    const track = w.find('[data-testid="bar-track"]')
    // 100/165 ≈ 61%
    expect(track.attributes("title")).toContain("61%")
    expect(track.attributes("title")).toContain("Pentax")
  })

  it("has an img role with aria-label and an sr-only table", () => {
    const w = mountChart()
    expect(w.find('[role="img"]').attributes("aria-label")).toContain("相机厂商")
    const table = w.find("table.sr-only")
    expect(table.findAll("tbody tr").length).toBe(4)
  })

  it("shows empty state with no items", () => {
    const w = mountChart([], 0)
    expect(w.text()).toContain("暂无数据")
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm -C frontend exec vitest run src/tests/chart-hbar.spec.ts`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 创建 HBarChart 组件**

创建 `frontend/src/components/charts/HBarChart.vue`：

```vue
<template>
  <div>
    <template v-if="items.length > 0">
      <ul class="space-y-1.5" role="img" :aria-label="ariaLabel">
        <li v-for="item in items" :key="item.name">
          <div class="flex items-baseline justify-between gap-2">
            <span class="min-w-0 truncate text-xs text-ink-2">{{ item.name }}</span>
            <span class="shrink-0 text-xs tabular-nums text-ink-2">{{ item.count.toLocaleString() }}</span>
          </div>
          <div data-testid="bar-track" class="mt-0.5 h-2 rounded bg-surface-2"
               :title="`${item.name}：${item.count.toLocaleString()} 张（${pct(item.count)}%）`">
            <div data-testid="bar-fill" class="h-2 rounded"
                 :class="item.dimmed ? 'bg-ink-muted/40' : 'bg-primary'"
                 :style="{ width: widthPct(item.count) + '%' }"></div>
          </div>
        </li>
      </ul>
      <!-- sr-only 数据表：与图形为兄弟节点（不嵌在 role=img 内） -->
      <table class="sr-only">
        <caption>{{ title }}</caption>
        <thead>
          <tr><th scope="col">名称</th><th scope="col">张数</th><th scope="col">占比</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.name">
            <td>{{ item.name }}</td>
            <td>{{ item.count }}</td>
            <td>{{ pct(item.count) }}%</td>
          </tr>
        </tbody>
      </table>
    </template>
    <p v-else class="text-sm text-ink-2">暂无数据</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"

interface BarItem {
  name: string
  count: number
  dimmed?: boolean
}

const props = defineProps<{
  title: string
  items: BarItem[]
  total: number
}>()

const maxCount = computed(() =>
  props.items.reduce((m, i) => Math.max(m, i.count), 0),
)

function widthPct(count: number): number {
  if (maxCount.value <= 0) return 0
  return Math.max(count > 0 ? 2 : 0, Math.round((count / maxCount.value) * 100))
}

function pct(count: number): number {
  return props.total > 0 ? Math.round((count / props.total) * 100) : 0
}

const ariaLabel = computed(() =>
  `${props.title}，共 ${props.total.toLocaleString()} 张：` +
  props.items.map((i) => `${i.name} ${i.count.toLocaleString()} 张`).join("，"),
)
</script>
```

注意：模板里有一个空的占位 `<table v-else-if>` 是多余的——**实现时删掉第 13–14 行那个空 table**，只保留后面的完整 `sr-only` 表（本计划在 Step 4 的测试通过后顺手清理，并确认测试仍绿）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pnpm -C frontend exec vitest run src/tests/chart-hbar.spec.ts`
Expected: 6 个用例 PASS。

- [ ] **Step 5: 类型检查并提交**

Run: `pnpm -C frontend exec vue-tsc --noEmit`
Expected: 无错误。

```bash
git add frontend/src/components/charts/HBarChart.vue frontend/src/tests/chart-hbar.spec.ts
git commit -m "feat(overview): horizontal bar chart component"
```

---

### Task 6: MonthChart 年-月柱状图组件

**Files:**
- Create: `frontend/src/components/charts/MonthChart.vue`
- Test: `frontend/src/tests/chart-month-chart.spec.ts`

**Interfaces:**
- Produces:
  - `MonthChart.vue` props：`months: Array<{ month: string; count: number }>`（后端已零填充）。
  - 空数组 → 「暂无数据」。

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/tests/chart-month-chart.spec.ts`：

```ts
import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import MonthChart from "../components/charts/MonthChart.vue"

const THREE_MONTHS = [
  { month: "2025-01", count: 2 },
  { month: "2025-02", count: 0 },
  { month: "2025-03", count: 4 },
]

function mountChart(months = THREE_MONTHS) {
  return mount(MonthChart, { props: { months } })
}

describe("MonthChart", () => {
  it("renders one titled hit-area per month including zero months", () => {
    const w = mountChart()
    const titles = w.findAll("rect title").map((t) => t.text())
    expect(titles.length).toBe(3)
    expect(titles).toContain("2025-01 · 2 张")
    expect(titles).toContain("2025-02 · 0 张")
    expect(titles).toContain("2025-03 · 4 张")
  })

  it("labels years only on January columns", () => {
    const w = mountChart()
    const labels = w.findAll("text[data-testid='year-tick']").map((t) => t.text())
    expect(labels).toEqual(["2025"])
  })

  it("draws a real bar only for non-zero months", () => {
    const w = mountChart()
    const bars = w.findAll("rect[data-testid='bar']")
    expect(bars.length).toBe(2)
  })

  it("summarizes range and peak in the img aria-label; sr-only table lists non-zero months only", () => {
    const w = mountChart()
    const label = w.find('[role="img"]').attributes("aria-label")
    expect(label).toContain("2025-01")        // 起始月
    expect(label).toContain("2025-03")        // 结束月兼峰值月
    expect(label).toContain("最多的月份 2025-03")
    const rows = w.findAll("table.sr-only tbody tr")
    expect(rows.length).toBe(2) // 零值月不进表
  })

  it("shows empty state for no months", () => {
    const w = mountChart([])
    expect(w.text()).toContain("暂无数据")
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm -C frontend exec vitest run src/tests/chart-month-chart.spec.ts`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 创建 MonthChart 组件**

创建 `frontend/src/components/charts/MonthChart.vue`：

```vue
<template>
  <div v-if="months.length > 0">
    <div class="overflow-x-auto">
      <svg :width="svgWidth" :height="H" class="block" style="min-width: 720px"
           role="img" :aria-label="ariaLabel">
        <!-- 三条横向网格线：0 / 50% / 100% -->
        <line v-for="y in gridYs" :key="'g' + y"
              :x1="0" :x2="svgWidth" :y1="y" :y2="y"
              stroke="rgb(var(--color-surface-3))" stroke-width="1" />
        <text :x="2" :y="10" font-size="9"
              fill="rgb(var(--color-ink-2))">{{ maxCount }}</text>
        <text :x="2" :y="PLOT_H / 2 + 3" font-size="9"
              fill="rgb(var(--color-ink-2))">{{ halfCount }}</text>

        <!-- 零值月：透明全高命中区，只为悬停可读 -->
        <template v-for="(p, i) in months" :key="p.month">
          <rect :x="i * STEP" :y="0" :width="STEP" :height="PLOT_H"
                fill="transparent">
            <title>{{ p.month }} · {{ p.count }} 张</title>
          </rect>
          <rect v-if="p.count > 0" data-testid="bar"
                :x="i * STEP" :y="barY(p.count)" :width="BAR_W"
                :height="barHeight(p.count)"
                fill="rgb(var(--color-primary))" />
        </template>

        <text v-for="t in yearTicks" :key="t.label + t.x"
              data-testid="year-tick" :x="t.x" :y="H - 4" font-size="9"
              fill="rgb(var(--color-ink-2))">{{ t.label }}</text>
      </svg>
    </div>
    <table class="sr-only">
      <caption>拍摄趋势（按年-月）</caption>
      <thead>
        <tr><th scope="col">月份</th><th scope="col">张数</th></tr>
      </thead>
      <tbody>
        <tr v-for="p in nonZero" :key="p.month">
          <td>{{ p.month }}</td>
          <td>{{ p.count }}</td>
        </tr>
      </tbody>
    </table>
  </div>
  <p v-else class="text-sm text-ink-2">暂无数据</p>
</template>

<script setup lang="ts">
import { computed } from "vue"

interface MonthPoint {
  month: string
  count: number
}

const props = defineProps<{ months: MonthPoint[] }>()

const BAR_W = 3
const BAR_GAP = 1
const STEP = BAR_W + BAR_GAP
const PLOT_H = 120
const LABEL_H = 18
const H = PLOT_H + LABEL_H

const svgWidth = computed(() => Math.max(props.months.length * STEP, 1))
const maxCount = computed(() => props.months.reduce((m, p) => Math.max(m, p.count), 0))
const halfCount = computed(() => Math.round(maxCount.value / 2))
const totalCount = computed(() => props.months.reduce((s, p) => s + p.count, 0))
const nonZero = computed(() => props.months.filter((p) => p.count > 0))

const gridYs = [0, PLOT_H / 2, PLOT_H]

function barHeight(count: number): number {
  if (maxCount.value <= 0) return 0
  // 最小 2px，保证只占极小比例的月份也可见
  return Math.max(2, Math.round((count / maxCount.value) * PLOT_H))
}
function barY(count: number): number {
  return PLOT_H - barHeight(count)
}

const yearTicks = computed(() =>
  props.months
    .map((p, i) => ({ p, i }))
    .filter(({ p }) => p.month.endsWith("-01"))
    .map(({ p, i }) => ({ x: i * STEP, label: p.month.slice(0, 4) })),
)

const ariaLabel = computed(() => {
  if (props.months.length === 0) return "拍摄趋势：暂无数据"
  const first = props.months[0].month
  const last = props.months[props.months.length - 1].month
  const peak = props.months.reduce((a, b) => (b.count > a.count ? b : a))
  return `拍摄趋势：${first} 至 ${last}，共 ${totalCount.value.toLocaleString()} 张，` +
    `最多的月份 ${peak.month} 有 ${peak.count.toLocaleString()} 张`
})
</script>
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pnpm -C frontend exec vitest run src/tests/chart-month-chart.spec.ts`
Expected: 5 个用例 PASS。

- [ ] **Step 5: 类型检查并提交**

Run: `pnpm -C frontend exec vue-tsc --noEmit`
Expected: 无错误。

```bash
git add frontend/src/components/charts/MonthChart.vue frontend/src/tests/chart-month-chart.spec.ts
git commit -m "feat(overview): monthly bar chart component with zero-filled columns"
```

---

### Task 7: AnalyticsPanel 容器面板

**Files:**
- Create: `frontend/src/components/charts/AnalyticsPanel.vue`
- Test: `frontend/src/tests/analytics-panel.spec.ts`

**Interfaces:**
- Consumes: `GET /api/admin/analytics`（Task 3 payload）；DonutChart / HBarChart / MonthChart。
- Produces: `AnalyticsPanel.vue`（无 props，自带请求/状态/重试）。

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/tests/analytics-panel.spec.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import AnalyticsPanel from "../components/charts/AnalyticsPanel.vue"

function mockAnalytics(payload: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status,
        headers: { "content-type": "application/json" },
      }),
    ),
  )
}

const PAYLOAD = {
  total: 10,
  with_exif: 9,
  without_taken_at: 1,
  makes: [
    { name: "Pentax", count: 6 },
    { name: "Nikon", count: 3 },
    { name: "未知", count: 1 },
  ],
  cameras: [{ name: "Pentax K-5", count: 6 }, { name: "Nikon D7000", count: 3 }],
  focal_ranges: [
    { key: "wide", name: "广角 (<35mm)", count: 2 },
    { key: "standard", name: "中焦 (35–70mm)", count: 3 },
    { key: "tele", name: "长焦 (>70mm)", count: 4 },
    { key: "unknown", name: "未知", count: 1 },
  ],
  apertures: [
    { key: "f28", name: "≤ f/2.8", count: 2 },
    { key: "f4", name: "f/4", count: 2 },
    { key: "f56", name: "f/5.6", count: 2 },
    { key: "f8", name: "f/8", count: 2 },
    { key: "f11plus", name: "f/11+", count: 1 },
    { key: "unknown", name: "未知", count: 1 },
  ],
  months: [
    { month: "2025-01", count: 4 },
    { month: "2025-02", count: 0 },
    { month: "2025-03", count: 5 },
  ],
}

describe("AnalyticsPanel", () => {
  beforeEach(() => vi.unstubAllGlobals())

  it("renders five chart titles and the coverage subtitle", async () => {
    mockAnalytics(PAYLOAD)
    const w = mount(AnalyticsPanel)
    await flushPromises()
    const t = w.text()
    expect(t).toContain("相机厂商")
    expect(t).toContain("相机机型")
    expect(t).toContain("焦段分布")
    expect(t).toContain("光圈分布")
    expect(t).toContain("拍摄趋势")
    expect(t).toContain("共 10 张")
    expect(t).toContain("9 张含拍摄参数")
    expect(t).toContain("无拍摄日期 1 张")
  })

  it("passes makes/cameras rows to the two bar charts and dims 未知", async () => {
    mockAnalytics(PAYLOAD)
    const w = mount(AnalyticsPanel)
    await flushPromises()
    expect(w.text()).toContain("Pentax K-5")
    expect(w.text()).toContain("Nikon D7000")
    // makes 带「未知」桶：对应填充条使用弱化中性色（cameras 无未知桶）
    const mutedFills = w.findAll('[data-testid="bar-fill"]')
      .filter((f) => f.classes().some((c) => c.includes("ink-muted")))
    expect(mutedFills.length).toBe(1)
  })

  it("shows a loading state before the request resolves", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})))
    const w = mount(AnalyticsPanel)
    expect(w.text()).toContain("加载中")
  })

  it("shows an alert banner with retry on failure", async () => {
    mockAnalytics({ error: { code: "internal_error", message: "boom" } }, 500)
    const w = mount(AnalyticsPanel)
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(true)
    const retry = w.find("button")
    expect(retry.text()).toContain("重试")
  })

  it("shows an empty state for a fresh library", async () => {
    mockAnalytics({
      total: 0, with_exif: 0, without_taken_at: 0,
      makes: [], cameras: [],
      focal_ranges: [
        { key: "wide", name: "广角 (<35mm)", count: 0 },
        { key: "standard", name: "中焦 (35–70mm)", count: 0 },
        { key: "tele", name: "长焦 (>70mm)", count: 0 },
        { key: "unknown", name: "未知", count: 0 },
      ],
      apertures: [],
      months: [],
    })
    const w = mount(AnalyticsPanel)
    await flushPromises()
    expect(w.text()).toContain("暂无已扫描的图片")
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm -C frontend exec vitest run src/tests/analytics-panel.spec.ts`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 创建 AnalyticsPanel 组件**

创建 `frontend/src/components/charts/AnalyticsPanel.vue`：

```vue
<template>
  <section>
    <h2 class="mb-2 text-sm font-medium text-ink-2">拍摄数据分析</h2>

    <div v-if="loading" class="text-sm text-ink-2">加载中...</div>

    <div v-else-if="error" role="alert" class="flex flex-wrap items-center gap-2 text-sm">
      <span class="text-danger-text">{{ error }}</span>
      <button type="button"
              class="rounded bg-surface-3 px-2 py-1 text-xs hover:bg-surface-4"
              @click="load">重试</button>
    </div>

    <template v-else-if="data">
      <p class="mb-3 text-xs text-ink-2">
        基于 EXIF · 共 {{ data.total.toLocaleString() }} 张，
        {{ data.with_exif.toLocaleString() }} 张含拍摄参数
      </p>

      <div v-if="data.total === 0" class="rounded-lg bg-surface p-4 text-sm text-ink-2">
        暂无已扫描的图片
      </div>

      <template v-else>
        <div class="grid gap-4 sm:grid-cols-2">
          <div class="rounded-lg bg-surface p-4">
            <h3 class="mb-3 text-xs font-medium text-ink-2">相机厂商 (Top 8)</h3>
            <HBarChart title="相机厂商" :items="withDim(data.makes)" :total="data.total" />
          </div>
          <div class="rounded-lg bg-surface p-4">
            <h3 class="mb-3 text-xs font-medium text-ink-2">相机机型 (Top 8)</h3>
            <HBarChart title="相机机型" :items="withDim(data.cameras)" :total="data.total" />
          </div>
          <div class="rounded-lg bg-surface p-4">
            <h3 class="mb-3 text-xs font-medium text-ink-2">焦段分布</h3>
            <DonutChart title="焦段分布" label="张" :total="data.total"
                        :segments="focalSegments" />
          </div>
          <div class="rounded-lg bg-surface p-4">
            <h3 class="mb-3 text-xs font-medium text-ink-2">光圈分布</h3>
            <DonutChart title="光圈分布" label="张" :total="data.total"
                        :segments="apertureSegments" />
          </div>
        </div>

        <div class="mt-4 rounded-lg bg-surface p-4">
          <h3 class="mb-3 flex items-center justify-between text-xs font-medium text-ink-2">
            <span>拍摄趋势（按年-月）</span>
            <span v-if="data.without_taken_at > 0" class="font-normal text-ink-2">
              无拍摄日期 {{ data.without_taken_at.toLocaleString() }} 张
            </span>
          </h3>
          <MonthChart :months="data.months" />
        </div>
      </template>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue"
import { apiGet, errorMessage } from "../../api"
import DonutChart from "./DonutChart.vue"
import HBarChart from "./HBarChart.vue"
import MonthChart from "./MonthChart.vue"

interface NameCount { name: string; count: number }
interface Segment { key: string; name: string; count: number }

interface AnalyticsResponse {
  total: number
  with_exif: number
  without_taken_at: number
  makes: NameCount[]
  cameras: NameCount[]
  focal_ranges: Segment[]
  apertures: Segment[]
  months: { month: string; count: number }[]
}

const MUTED = "rgb(var(--color-ink-muted) / 0.5)"
const cssVar = (name: string) => `rgb(var(--color-${name}))`

const FOCAL_COLORS: Record<string, string> = {
  wide: cssVar("chart-1"),
  standard: cssVar("chart-2"),
  tele: cssVar("chart-3"),
  unknown: MUTED,
}

const APERTURE_COLORS: Record<string, string> = {
  f28: cssVar("chart-1"),
  f4: cssVar("chart-2"),
  f56: cssVar("chart-3"),
  f8: cssVar("chart-4"),
  f11plus: cssVar("chart-5"),
  unknown: MUTED,
}

const data = ref<AnalyticsResponse | null>(null)
const loading = ref(true)
const error = ref("")

async function load() {
  loading.value = true
  error.value = ""
  try {
    data.value = await apiGet<AnalyticsResponse>("/api/admin/analytics")
  } catch (err) {
    error.value = errorMessage(err, "统计数据加载失败")
  } finally {
    loading.value = false
  }
}

onMounted(load)

function withDim(items: NameCount[]): (NameCount & { dimmed: boolean })[] {
  return items.map((i) => ({
    ...i,
    dimmed: i.name === "其他" || i.name === "未知",
  }))
}

function withColor(segments: Segment[], map: Record<string, string>) {
  return segments.map((s) => ({ ...s, color: map[s.key] ?? MUTED }))
}

const focalSegments = ref<ReturnType<typeof withColor>>([])
const apertureSegments = ref<ReturnType<typeof withColor>>([])

// data 到达后给分段着色（颜色映射固定，色值本身是 CSS 变量，明暗主题自动生效）
watch(data, (d) => {
  if (!d) return
  focalSegments.value = withColor(d.focal_ranges, FOCAL_COLORS)
  apertureSegments.value = withColor(d.apertures, APERTURE_COLORS)
})
</script>
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pnpm -C frontend exec vitest run src/tests/analytics-panel.spec.ts`
Expected: 5 个用例 PASS。

- [ ] **Step 5: 类型检查并提交**

Run: `pnpm -C frontend exec vue-tsc --noEmit`
Expected: 无错误。

```bash
git add frontend/src/components/charts/AnalyticsPanel.vue frontend/src/tests/analytics-panel.spec.ts
git commit -m "feat(overview): analytics panel with five EXIF charts"
```

---

### Task 8: 挂进 AdminOverview 并修正既有测试

**Files:**
- Modify: `frontend/src/views/AdminOverview.vue`（stats 与扫描状态之间插入面板）
- Modify: `frontend/src/tests/admin-overview.spec.ts`（fetch mock 按 URL 路由，兼容新增的 /analytics 请求）
- Test: `frontend/src/tests/analytics-panel.spec.ts`（已在 Task 7）

**Interfaces:**
- Consumes: Task 7 的 `AnalyticsPanel`。

- [ ] **Step 1: 挂载组件（先改实现）**

在 `frontend/src/views/AdminOverview.vue` 模板中，统计卡片 section 的结束标签 `</section>`（当前第 41 行，`users-stat-card` 所在 section）之后、`<!-- Scan status list -->` 之前插入：

```html
        <!-- P8: EXIF 数据分析面板（独立请求 /api/admin/analytics，不参与状态轮询） -->
        <AnalyticsPanel v-if="data" />
```

在 `<script setup>` 的 import 区（`import { auditActionLabel } ...` 之后）加：

```ts
import AnalyticsPanel from "../components/charts/AnalyticsPanel.vue"
```

- [ ] **Step 2: 运行既有 AdminOverview 测试确认失败点**

Run: `pnpm -C frontend exec vitest run src/tests/admin-overview.spec.ts`
Expected: 部分用例失败——根因是现有 `mockStatus` 让**所有** fetch（含 `/api/admin/analytics`）都返回 status payload，面板数据形态不符；轮询用例的调用次数断言也会因多出的 analytics 请求而失败。

- [ ] **Step 3: 改造测试 mock，按 URL 路由**

在 `frontend/src/tests/admin-overview.spec.ts` 中，把现有 `mockStatus` 函数（第 29–39 行）整体替换为：

```ts
// 分析面板会独立请求 /api/admin/analytics；测试中给它一个空库 payload，
// 让面板安静地渲染空态，不干扰对状态页的断言。
const EMPTY_ANALYTICS = {
  total: 0, with_exif: 0, without_taken_at: 0,
  makes: [], cameras: [], focal_ranges: [], apertures: [], months: [],
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  })
}

// 签名保持与旧 mockStatus 兼容：现有错误用例以 mockStatus(payload, 403) 调用。
function mockStatus(payload: unknown, status = 200, analytics: unknown = EMPTY_ANALYTICS) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) =>
      Promise.resolve(jsonResponse(
        // 正常状态下 analytics 请求给空库 payload；错误状态下两个 URL 都回错误信封
        String(url).includes("/api/admin/analytics") && status === 200
          ? analytics
          : payload,
        status,
      )),
    ),
  )
}
```

错误用例（4xx）下 analytics 请求同样回错误信封，面板出现自己的 alert——不破坏现有断言（`w.text()` 包含 "admin only" 仍成立）。

- [ ] **Step 4: 改造轮询用例的 fetch 序列**

`it("polls status while a scan is running and stops when idle", ...)` 中的 `fetchFn` 需要区分两类 URL。把该用例里的 `const fetchFn = vi.fn()` 及其 mock 链（约 287–292 行）替换为：

```ts
    const statusSeq = [running, running, idle]
    let statusCalls = 0
    const fetchFn = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/admin/analytics")) {
        return Promise.resolve(jsonResponse(EMPTY_ANALYTICS))
      }
      return Promise.resolve(jsonResponse(statusSeq[statusCalls++]))
    })
    vi.stubGlobal("fetch", fetchFn)

    const w = mountView()
    await flushPromises()
    expect(statusCalls).toBe(1)

    vi.advanceTimersByTime(2000)
    await flushPromises()
    expect(statusCalls).toBe(2)

    vi.advanceTimersByTime(2000)
    await flushPromises()
    expect(statusCalls).toBe(3)

    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(statusCalls).toBe(3)

    w.unmount()
    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(statusCalls).toBe(3)
```

（其余断言不变；analytics 请求不计数。）

- [ ] **Step 5: 运行 AdminOverview 测试确认通过**

Run: `pnpm -C frontend exec vitest run src/tests/admin-overview.spec.ts`
Expected: 原有全部用例 PASS。

- [ ] **Step 6: 全量验证**

Run（前端全量测试 + 类型检查）:

```bash
pnpm -C frontend exec vitest run
pnpm -C frontend exec vue-tsc --noEmit
python -m pytest backend/tests -q
```

Expected: 三套全绿。

- [ ] **Step 7: 人工走查（明暗主题 / 移动端 / 真实库）**

1. `pnpm -C frontend run dev` + 后端启动，admin 登录后打开 `/admin/overview`：
   - 四张卡片 + 月图顺序正确；Pentax/Nikon/vivo 数字与库一致。
   - 手机照片（vivo/Xiaomi）与 COOLPIX/IXUS 在焦段「未知」桶。
   - K-5（×1.5）与 K-1（×1.0）若库中有，焦段归类合理。
2. 系统切深色外观：6 个分类色与柱/条仍清晰，无硬编码颜色。
3. 窄视口（DevTools 375px）：图表单列；月图可横向滑动，年份标签可读。
4. 键盘 Tab：图表不停留焦点；用屏幕阅读器（或检查 DOM）确认 `role="img"` 标签与 sr-only 表存在。

- [ ] **Step 8: 提交**

```bash
git add frontend/src/views/AdminOverview.vue frontend/src/tests/admin-overview.spec.ts
git commit -m "feat(overview): mount EXIF analytics panel between stats and scan status"
```

---

## 验收对照（spec §6）

- [ ] 5 张图数字与独立 SQL 统计一致（厂商/机型/焦段/光圈/月）。
- [ ] 陷阱机型单测覆盖：K-1/K-5、D500/D800、Z50/Z5、Z fc/Z f、R7/R50/R100 vs R5/初代 R、DC-S1/DC-G9、DMC-L1/DMC-LC5、ZV-E10/ZV-E1、RICOH Make 的 PENTAX K-3。
- [ ] 手机与便携机全部在焦段未知桶。
- [ ] viewer 命中 403、未登录 401；响应带 `Cache-Control: no-store`。
- [ ] 扫描后签名变化、5 分钟 TTL 兜底（缓存测试）。
- [ ] 移动端单列 + 月图横滑；明暗双主题无硬编码色；sr-only 数据表存在。
- [ ] `pytest backend/tests`、`vitest run`、`vue-tsc --noEmit` 全绿。
