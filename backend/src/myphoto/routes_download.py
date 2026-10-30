"""P6: 批量下载。

POST /api/download-batch        鉴权 + 数量校验 + 解析磁盘路径 → 一次性 ticket
GET  /api/download-batch/{tok}  凭 ticket 流式输出 ZIP（浏览器原生下载）

票据存内存（单进程部署）：TTL 300 秒、绑定 user_id、claim 即焚、总量上限淘汰最旧。
ZIP：ZIP_STORED（照片已压缩）、force_zip64（RAW 合集可能超 4GB）、
输出不可 seek，靠有界 queue 把写线程的字节交给 StreamingResponse。
"""
from __future__ import annotations

import logging
import re
import secrets
import time
from dataclasses import dataclass

log = logging.getLogger("myphoto.routes_download")

TICKET_TTL_SEC = 300
TICKET_MAX_ENTRIES = 200


@dataclass
class DownloadEntry:
    image_id: int
    disk_path: str
    arcname: str


@dataclass
class TicketRecord:
    user_id: int
    filename: str
    entries: list[DownloadEntry]
    expires_at: float


class TicketStore:
    def __init__(self, ttl_sec: float = TICKET_TTL_SEC,
                 max_entries: int = TICKET_MAX_ENTRIES) -> None:
        self._t: dict[str, TicketRecord] = {}
        self.ttl_sec = ttl_sec
        self.max_entries = max_entries

    def _purge(self, now: float) -> None:
        expired = [k for k, v in self._t.items() if v.expires_at <= now]
        for k in expired:
            del self._t[k]

    def issue(self, user_id: int, entries: list[DownloadEntry],
              filename: str, *, now: float | None = None,
              token: str | None = None) -> str:
        now = time.time() if now is None else now
        self._purge(now)
        if len(self._t) >= self.max_entries:
            oldest = min(self._t, key=lambda k: self._t[k].expires_at)
            del self._t[oldest]
        token = token or secrets.token_urlsafe(16)
        self._t[token] = TicketRecord(
            user_id=user_id, filename=filename,
            entries=entries, expires_at=now + self.ttl_sec,
        )
        return token

    def claim(self, token: str, user_id: int,
              *, now: float | None = None) -> TicketRecord | None:
        now = time.time() if now is None else now
        rec = self._t.get(token)
        if rec is None or rec.expires_at <= now or rec.user_id != user_id:
            return None
        del self._t[token]
        return rec


_LABEL_BAD = re.compile(r'[\\/:*?"<>|]')


def _safe_label(label: str) -> str:
    """清洗 root label 用作 ZIP 内目录名（Windows 解压友好）；空结果回退 root。"""
    out = _LABEL_BAD.sub("_", label).strip().lstrip(".")
    return out or "root"


def _disambiguate(name: str) -> str:
    """同 arcname 撞名时在文件名 stem 后加 8 位 hex 后缀，保留父目录与扩展名。"""
    if "." in name.rsplit("/", 1)[-1]:
        stem, _, ext = name.rpartition(".")
        suffix = "." + ext
    else:
        stem, suffix = name, ""
    tail = f"{stem.rsplit('/', 1)[-1]}-{secrets.token_hex(4)}{suffix}"
    parent = name.rsplit("/", 1)[0] if "/" in name else ""
    return f"{parent}/{tail}" if parent else tail


def build_arcnames(seq: list[tuple[int, str, str]]) -> list[str]:
    """seq 元素 (root_id, root_label, relative_path)，已去重保序。"""
    multi = len({root_id for root_id, _, _ in seq}) > 1
    out: list[str] = []
    used: set[str] = set()
    for root_id, label, rel in seq:
        name = f"{_safe_label(label)}/{rel}" if multi else rel
        if name in used:
            name = _disambiguate(name)
        used.add(name)
        out.append(name)
    return out
