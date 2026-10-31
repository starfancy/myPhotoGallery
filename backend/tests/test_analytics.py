import json
import re
import time

import pytest
from fastapi.testclient import TestClient

from myphoto.main import build_app
from myphoto.models import Folder, Gallery, GalleryRoot, Image, User
from myphoto.security import hash_password

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
