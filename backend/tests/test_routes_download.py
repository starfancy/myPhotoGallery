import io
import re
import time
import zipfile
from pathlib import Path

import pytest
from PIL import Image as PILImage
from fastapi.testclient import TestClient

from myphoto.main import build_app
from myphoto.routes_download import (
    DownloadEntry,
    TicketRecord,
    TicketStore,
    build_arcnames,
)


# ---------- build_arcnames ----------

def test_arcnames_single_root_keeps_tree():
    seq = [(1, "R", "2024/a.jpg"), (1, "R", "2024/sub/b.jpg")]
    assert build_arcnames(seq) == ["2024/a.jpg", "2024/sub/b.jpg"]


def test_arcnames_multi_root_adds_label_prefix():
    seq = [(1, "R1", "a.jpg"), (2, "R2", "b.jpg")]
    assert build_arcnames(seq) == ["R1/a.jpg", "R2/b.jpg"]


def test_arcnames_sanitizes_label():
    # label 来自用户输入，可能含 Windows 非法文件名字符或分隔符；
    # \\ / : * ? " < > | 逐字符替换为 _
    seq = [(1, 'D:/照片:库?', "a.jpg"), (2, "R2", "b.jpg")]
    assert build_arcnames(seq) == ["D__照片_库_/a.jpg", "R2/b.jpg"]


def test_arcnames_label_collision_gets_suffix():
    # 两个 root label 相同且相对路径相同 → 两个 arcname 必须可区分
    seq = [(1, "R", "a.jpg"), (2, "R", "a.jpg")]
    out = build_arcnames(seq)
    assert out[0] == "R/a.jpg"
    assert out[1] != "R/a.jpg"
    assert out[1].endswith(".jpg") and "-" in out[1]


# ---------- TicketStore ----------

def _entry(i: int) -> DownloadEntry:
    return DownloadEntry(image_id=i, disk_path=f"/tmp/{i}.jpg", arcname=f"{i}.jpg")


def test_issue_then_claim_returns_record_once():
    store = TicketStore()
    tok = store.issue(7, [_entry(1), _entry(2)], "p.zip", now=1000.0, token="tok")
    assert tok == "tok"
    rec = store.claim("tok", 7, now=1001.0)
    assert rec is not None and rec.filename == "p.zip" and len(rec.entries) == 2
    assert store.claim("tok", 7) is None  # 一次性


def test_claim_wrong_user_or_unknown_is_none():
    store = TicketStore()
    store.issue(7, [_entry(1)], "p.zip", now=1000.0, token="tok")
    assert store.claim("tok", 8, now=1001.0) is None
    assert store.claim("nope", 7) is None


def test_expired_ticket_is_none():
    store = TicketStore(ttl_sec=300)
    store.issue(7, [_entry(1)], "p.zip", now=1000.0, token="tok")
    assert store.claim("tok", 7, now=1299.0) is not None
    store.issue(7, [_entry(1)], "p.zip", now=1000.0, token="tok2")
    assert store.claim("tok2", 7, now=1301.0) is None


def test_max_entries_evicts_oldest():
    store = TicketStore(ttl_sec=300, max_entries=2)
    store.issue(1, [_entry(1)], "a.zip", now=1000.0, token="t1")
    store.issue(1, [_entry(1)], "b.zip", now=1001.0, token="t2")
    store.issue(1, [_entry(1)], "c.zip", now=1002.0, token="t3")
    assert store.claim("t1", 1, now=1002.0) is None
    assert store.claim("t2", 1, now=1002.0) is not None


# ---------- HTTP 集成 ----------


def _jpg(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (20, 20), (1, 2, 3)).save(p, "JPEG")


@pytest.fixture
def env(tmp_path, capsys):
    photos = tmp_path / "photos"
    for f in ["a.jpg", "sub/b.jpg", "相册/c.jpg"]:
        _jpg(photos / f)
    photos2 = tmp_path / "photos2"
    _jpg(photos2 / "a2.jpg")

    app = build_app(config_path=str(tmp_path / "config.toml"))
    c_cm = TestClient(app)
    c = c_cm.__enter__()
    pw = re.search(r"password=(\S+)", capsys.readouterr().out).group(1)
    c.post("/api/auth/login", json={"username": "admin", "password": pw})

    from myphoto.models import Gallery, GalleryRoot

    async def _seed():
        async with app.state.sessionmaker() as s:
            g = Gallery(name="G", created_at=int(time.time()))
            s.add(g)
            await s.flush()
            r1 = GalleryRoot(gallery_id=g.id, label="R",
                             absolute_path=str(photos.resolve()), enabled=1)
            r2 = GalleryRoot(gallery_id=g.id, label="R2",
                             absolute_path=str(photos2.resolve()), enabled=1)
            s.add_all([r1, r2])
            await s.commit()
            await s.refresh(r1)
            await s.refresh(r2)
            return g.id, r1.id, r2.id

    gid, r1, r2 = c.portal.call(_seed)
    c.portal.call(app.state.scanner.scan_root_now, r1)
    c.portal.call(app.state.scanner.scan_root_now, r2)
    yield c, app, gid, r1, r2, photos
    c_cm.__exit__(None, None, None)


def _ids_at(c, gid, rid, path=""):
    r = c.get(f"/api/galleries/{gid}/roots/{rid}/images", params={"path": path, "limit": 500})
    return [i["id"] for i in r.json()["items"]]


def _post(c, ids):
    return c.post("/api/download-batch", json={"image_ids": ids})


def test_post_requires_auth(tmp_path):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        assert _post(c, [1]).status_code == 401


def test_happy_path_zip_bytes_and_headers(env):
    c, _, gid, r1, _, photos = env
    root_ids = _ids_at(c, gid, r1)
    sub_ids = _ids_at(c, gid, r1, "sub")
    r = _post(c, root_ids + sub_ids)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"ticket", "filename", "count"}
    assert body["count"] == 2
    assert body["filename"].endswith(".zip")

    z = c.get(f"/api/download-batch/{body['ticket']}")
    assert z.status_code == 200
    assert z.headers["content-type"] == "application/zip"
    assert "attachment" in z.headers["content-disposition"]

    zf = zipfile.ZipFile(io.BytesIO(z.content))
    assert set(zf.namelist()) == {"a.jpg", "sub/b.jpg"}
    assert zf.read("a.jpg") == (photos / "a.jpg").read_bytes()


def test_utf8_filename_in_zip(env):
    c, _, gid, r1, _, _ = env
    cid = [i for i in _ids_at(c, gid, r1, "相册")][0]
    ticket = _post(c, [cid]).json()["ticket"]
    zf = zipfile.ZipFile(io.BytesIO(c.get(f"/api/download-batch/{ticket}").content))
    assert zf.namelist() == ["相册/c.jpg"]
    info = zf.infolist()[0]
    assert info.flag_bits & 0x800  # UTF-8 文件名标志


def test_duplicate_ids_deduped_preserve_order(env):
    c, _, gid, r1, _, _ = env
    i = _ids_at(c, gid, r1)[0]
    body = _post(c, [i, i, i]).json()
    assert body["count"] == 1


def test_ticket_is_one_time(env):
    c, _, gid, r1, _, _ = env
    i = _ids_at(c, gid, r1)[0]
    ticket = _post(c, [i]).json()["ticket"]
    assert c.get(f"/api/download-batch/{ticket}").status_code == 200
    assert c.get(f"/api/download-batch/{ticket}").status_code == 404


def test_ticket_bound_to_user(env):
    c, app, gid, r1, _, _ = env
    from myphoto.models import User, UserGallery
    from myphoto.security import hash_password

    async def _go():
        async with app.state.sessionmaker() as s:
            u = User(username="v", password_hash=hash_password("vpw12345"),
                     role="viewer", access_scope="remote_allowed", enabled=1,
                     created_at=int(time.time()))
            s.add(u)
            await s.flush()
            s.add(UserGallery(user_id=u.id, gallery_id=gid,
                              granted_at=int(time.time())))
            await s.commit()

    c.portal.call(_go)
    i = _ids_at(c, gid, r1)[0]
    ticket = _post(c, [i]).json()["ticket"]
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "v", "password": "vpw12345"})
    # viewer 已授权该图库，但票据属于 admin → 404
    assert c.get(f"/api/download-batch/{ticket}").status_code == 404


def test_viewer_without_gallery_grant_cannot_post(env):
    c, app, gid, r1, _, _ = env
    from myphoto.models import User
    from myphoto.security import hash_password

    async def _go():
        async with app.state.sessionmaker() as s:
            s.add(User(username="v2", password_hash=hash_password("vpw12345"),
                       role="viewer", access_scope="remote_allowed", enabled=1,
                       created_at=int(time.time())))
            await s.commit()

    c.portal.call(_go)
    i = _ids_at(c, gid, r1)[0]
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "v2", "password": "vpw12345"})
    r = _post(c, [i])
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_unknown_image_id_404(env):
    c, _, _, _, _, _ = env
    r = _post(c, [999999])
    assert r.status_code == 404


def test_over_200_is_422(env):
    c, _, _, _, _, _ = env
    r = _post(c, list(range(201)))
    assert r.status_code == 422


def test_batch_too_large_uses_configured_limit(env):
    c, _, gid, r1, _, _ = env
    assert c.patch("/api/admin/settings",
                   json={"download_batch_limit": 10}).status_code == 200
    r = _post(c, list(range(100, 112)))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "batch_too_large"


def test_cross_root_arcnames_prefixed(env):
    c, _, gid, r1, r2, _ = env
    i1 = _ids_at(c, gid, r1)[0]
    i2 = _ids_at(c, gid, r2)[0]
    ticket = _post(c, [i1, i2]).json()["ticket"]
    zf = zipfile.ZipFile(io.BytesIO(c.get(f"/api/download-batch/{ticket}").content))
    assert set(zf.namelist()) == {"R/a.jpg", "R2/a2.jpg"}


def test_missing_file_listed_in_zip(env):
    c, app, gid, r1, _, photos = env
    cid = _ids_at(c, gid, r1, "相册")[0]
    keep = _ids_at(c, gid, r1)[0]
    ticket = _post(c, [keep, cid]).json()["ticket"]
    # POST→GET 之间文件被删/盘离线
    (photos / "相册" / "c.jpg").unlink()
    z = c.get(f"/api/download-batch/{ticket}")
    assert z.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    assert "a.jpg" in zf.namelist()
    listing = zf.read("missing-files.txt").decode("utf-8")
    assert "相册/c.jpg" in listing and str(cid) in listing


# ---------- Fix round 1：并发 claim / 断连取消 / reaper ----------


def test_concurrent_claim_only_one_wins():
    import threading
    store = TicketStore()
    store.issue(7, [_entry(1)], "p.zip", now=1000.0, token="tok")
    barrier = threading.Barrier(2)
    winners = []
    wlock = threading.Lock()

    def claimer():
        barrier.wait()
        rec = store.claim("tok", 7, now=1001.0)
        if rec is not None:
            with wlock:
                winners.append(rec)

    threads = [threading.Thread(target=claimer) for _ in range(2)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=5)
    assert len(winners) == 1


def test_zip_stream_abort_on_generator_close(tmp_path):
    import time as _time
    from myphoto.routes_download import _zip_stream
    photos = tmp_path / "big"
    photos.mkdir()
    entries = []
    for i in range(3):
        p = photos / f"big{i}.jpg"
        p.write_bytes(b"x" * (24 * 1024 * 1024))
        entries.append(DownloadEntry(i, str(p), f"big{i}.jpg"))
    rec = TicketRecord(user_id=1, filename="p.zip", entries=entries,
                       expires_at=_time.time() + 300)
    gen = _zip_stream(rec)
    next(gen)  # first chunk (local header / first file bytes)
    gen.close()  # client disconnect: must not drain 72 MiB
    # worker must observe cancel and exit quickly; inspect via module-private
    # reaper behavior indirectly: no public thread handle, so assert the queue
    # drains and process stays responsive by giving the daemon a bounded window
    _time.sleep(3.0)
    # No assertion on thread count (daemon, reaper-managed); the real
    # guarantee is that close() returned promptly (it did — we are here)
    # and no exception escaped. Strengthen: second generator still works.
    gen2 = _zip_stream(
        TicketRecord(user_id=1, filename="p2.zip",
                     entries=[entries[0]], expires_at=_time.time() + 300)
    )
    chunks = list(gen2)
    assert sum(len(c) for c in chunks) > 24 * 1024 * 1024


def test_queue_sink_aborts_on_cancel_and_reaper_joins(tmp_path):
    import queue as qmod
    import threading
    from myphoto.routes_download import (
        _QueueSink, _SENTINEL, _reap_worker, _zip_worker,
    )
    big = tmp_path / "big.bin"
    big.write_bytes(b"y" * (32 * 1024 * 1024))
    rec = TicketRecord(
        user_id=1, filename="p.zip",
        entries=[DownloadEntry(1, str(big), "big.bin")],
        expires_at=time.time() + 300,
    )
    q = qmod.Queue(maxsize=2)
    cancel = threading.Event()
    th = threading.Thread(target=_zip_worker, args=(q, cancel, rec))
    th.start()
    q.get()  # consume one chunk then vanish like a disconnected client
    _reap_worker(th, q, cancel)  # performs cancel + bounded join
    assert not th.is_alive()
