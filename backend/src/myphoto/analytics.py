"""EXIF 分析聚合（管理概览页图表）。

本模块上半部分是不依赖 FastAPI/DB 的纯函数（厂商归一、机型裁切系数、
分桶），下半部分（后续任务加入）负责行聚合、取数与短缓存。

口径权威说明见
docs/superpowers/specs/2026-10-31-exif-analytics-overview-design.md §2。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter
from typing import Iterable

from sqlalchemy import func, select

from myphoto.models import Image

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
        # —— DX 微单必须排在 FX 'Z5' 前面（Z50/Z50II 均不匹配 ^Z5(II)?$，双保险）——
        (re.compile(r"^Z(50|30)(II)?$"), 1.5),  # Z 50/Z 30（含 II 代）
        (re.compile(r"^ZFC$"), 1.5),          # Z fc；必须先于 FX 的 Zf
        # —— FX ——
        (re.compile(r"^Z[6789](II|III)?$"), 1.0),
        (re.compile(r"^Z5(II)?$"), 1.0),
        (re.compile(r"^ZF$"), 1.0),
        (re.compile(r"^D[3-6](S|X)?$"), 1.0),  # D3/D3s/D3x/D4/D4s/D5/D6
        (re.compile(r"^D700$"), 1.0),
        (re.compile(r"^D8[015]0$"), 1.0),      # D800/D810/D850
        (re.compile(r"^D(6[01]0|7[58]0)$"), 1.0),  # D600/D610/D750/D780
        (re.compile(r"^DF$"), 1.0),
        # —— DX 单反 ——
        (re.compile(r"^D500$"), 1.5),
        (re.compile(r"^D(100|200|300S?|400)$"), 1.5),  # D100..D400，含 D300s
        # D1/D1H/D1X、D2H/D2X/D2Xs（无裸 D2）；锚定尾界，不吞 D200
        (re.compile(r"^D(1(H|X)?|2(H|X|XS))$"), 1.5),
        (re.compile(r"^D90$"), 1.5),
        # D40/D50/D60/D70/D70s/D80；锚定尾界，D700（FX）与 D500（上面的 DX）不匹配
        (re.compile(r"^D(40|50|60|70S?|80)$"), 1.5),
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
        # EOS R1 必须排在上面的 APS-C R 系规则之后：EOSR10 先被 1.6 组抓走
        (re.compile(r"^EOSR1$"), 1.0),
        (re.compile(r"^EOSR3$"), 1.0),
        (re.compile(r"^EOSR5(MARK2|MARKII)?$"), 1.0),
        (re.compile(r"^EOSR6(MARK2|MARKII)?$"), 1.0),
        (re.compile(r"^EOSR8$"), 1.0),
        (re.compile(r"^EOS5D.*$"), 1.0),
        (re.compile(r"^EOS6D.*$"), 1.0),
        (re.compile(r"^EOS1D.*$"), 1.0),       # 1Ds/1D X
        # —— APS-C 单反：编号机身（7D/77D/550D/1000D），允许 II/III/IV 代后缀（200D II）——
        (re.compile(r"^EOS\d{1,4}D(II|III|IV)?$"), 1.6),
    ),
    "Pentax": (
        (re.compile(r"^K-1(II|MARKII|MARK2)?$"), 1.0),  # K-1 必须先于通用 K- 前缀
        (re.compile(r"^K-.*$"), 1.5),                   # K-3/K-5/K-r/K-70…
        # —— 无连字符单反时代（K-1 规则仍排在最前并先赢）——
        (re.compile(r"^K[FP]$"), 1.5),                  # KF/KP
        (re.compile(r"^K[12]0D$"), 1.5),                # K10D/K20D
        (re.compile(r"^K[12]\d0D$"), 1.5),              # K100D/K110D/K200D
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
        (re.compile(r"^GFX.*$"), 0.8),       # 44×33 中画幅，必须最先
        # X- 全系 + X100 系列（X100/X100S…X100V/X100VI）；不吞小底 X10/XF1
        (re.compile(r"^(X-|X100).*$"), 1.5),
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


def _month_key(ts: int) -> str | None:
    """时间戳 -> 本地时区 'YYYY-MM'；越界/非法时间戳返回 None，绝不抛异常。

    库内 taken_at 来自历史 EXIF，个别值可能超出平台 localtime 范围
    （Linux 抛 OverflowError/OSError，Windows 抛 OSError）。
    """
    try:
        return time.strftime("%Y-%m", time.localtime(ts))
    except (OverflowError, OSError, ValueError, TypeError):
        return None


def aggregate_rows(
    rows: Iterable[tuple[int | None, str | None]],
) -> dict[str, object]:
    """把 (taken_at, exif_json) 行聚合成图表 payload。

    单行 JSON 损坏 / 字段类型异常 / taken_at 越界一律吞掉（坏时间戳视同
    无拍摄日期），绝不抛异常；JSON 损坏但 taken_at 有效的照片仍计入月图
    （taken_at 不在 JSON 内）。
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
            month = _month_key(taken_at)
            if month is None:
                # 越界时间戳不丢行：计入 without_taken_at，保持
                # sum(月计数) = total - without_taken_at 的全集划分
                without_taken_at += 1
            else:
                months_c[month] += 1

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
