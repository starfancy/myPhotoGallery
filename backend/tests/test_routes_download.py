import time

import pytest

from myphoto.routes_download import (
    DownloadEntry,
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
