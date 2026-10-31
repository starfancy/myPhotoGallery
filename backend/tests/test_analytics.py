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
