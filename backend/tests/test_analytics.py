import json

import pytest

from myphoto.analytics import (
    aggregate_rows,
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
