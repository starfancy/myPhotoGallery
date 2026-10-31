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
