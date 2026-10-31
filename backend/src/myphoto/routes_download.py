"""P6: 批量下载。

POST /api/download-batch        鉴权 + 数量校验 + 解析磁盘路径 → 一次性 ticket
GET  /api/download-batch/{tok}  凭 ticket 流式输出 ZIP（浏览器原生下载）

票据存内存（单进程部署）：TTL 300 秒、绑定 user_id、claim 即焚、总量上限淘汰最旧。
ZIP：ZIP_STORED（照片已压缩）、force_zip64（RAW 合集可能超 4GB）、
输出不可 seek，靠有界 queue 把写线程的字节交给 StreamingResponse。
"""
from __future__ import annotations

import logging
import queue
import re
import secrets
import shutil
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from myphoto.access import check_gallery_access
from myphoto.deps import current_user
from myphoto.errors import AppError
from myphoto.models import GalleryRoot, Image, User
from myphoto.paths import PathTraversalError, resolve_within_root

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
        self._lock = threading.Lock()
        self.ttl_sec = ttl_sec
        self.max_entries = max_entries

    def _purge(self, now: float) -> None:
        expired = [k for k, v in self._t.items() if v.expires_at <= now]
        for k in expired:
            del self._t[k]

    def issue(self, user_id: int, entries: list[DownloadEntry],
              filename: str, *, now: float | None = None,
              token: str | None = None) -> str:
        with self._lock:
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
        # 同步 GET 跑在 anyio 线程池，issue 跑在事件循环线程：
        # 加锁让 lookup/check/delete 原子，杜绝并发双 claim 与 purge 竞态。
        with self._lock:
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
            # 重抽直到不撞名（每次约 2^-32 撞已用集合），上限 8 次兜底
            for _ in range(8):
                candidate = _disambiguate(name)
                if candidate not in used:
                    name = candidate
                    break
        used.add(name)
        out.append(name)
    return out


router = APIRouter(prefix="/api", tags=["download"])


class BatchBody(BaseModel):
    image_ids: list[int] = Field(..., min_length=1, max_length=200)


@router.post("/download-batch")
async def create_download_batch(
    body: BatchBody,
    request: Request,
    user: User = Depends(current_user),
):
    limit = int(request.app.state.config.download_batch_limit)
    ids = list(dict.fromkeys(body.image_ids))  # 去重保序
    if len(ids) > limit:
        raise AppError(
            "batch_too_large", 400,
            f"batch exceeds configured limit: {limit}",
        )

    sm = request.app.state.sessionmaker
    async with sm() as s:
        rows = (
            await s.execute(
                select(Image, GalleryRoot)
                .join(GalleryRoot, Image.root_id == GalleryRoot.id)
                .where(Image.id.in_(ids))
            )
        ).all()
        by_id = {img.id: (img, root) for img, root in rows}
        if any(i not in by_id for i in ids):
            raise AppError("not_found", 404, "image not found")

        checked_galleries: set[int] = set()
        seq: list[tuple[int, str, str]] = []
        disk_paths: dict[int, Path] = {}
        for i in ids:
            img, root = by_id[i]
            if root.gallery_id not in checked_galleries:
                await check_gallery_access(s, user, root.gallery_id)
                checked_galleries.add(root.gallery_id)
            try:
                disk_paths[i] = resolve_within_root(
                    root.absolute_path, img.relative_path
                )
            except PathTraversalError:
                raise AppError("path_invalid", 400, "invalid path")
            seq.append((root.id, root.label, img.relative_path))

    arcnames = build_arcnames(seq)
    entries = [
        DownloadEntry(
            image_id=i, disk_path=str(disk_paths[i]), arcname=arc,
        )
        for i, arc in zip(ids, arcnames)
    ]
    filename = f"photos-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    store: TicketStore = request.app.state.download_tickets
    ticket = store.issue(user.id, entries, filename)
    return {"ticket": ticket, "filename": filename, "count": len(entries)}


# ---------- GET：一次性票据 → 流式 ZIP ----------

_SENTINEL = object()
_ERROR = object()
_CHUNK_MAX = 1024 * 1024
_QUEUE_DEPTH = 8
_PUT_TIMEOUT = 0.5
_REAP_JOIN_SEC = 10.0


class _ZipAborted(Exception):
    pass


class _QueueSink:
    """zipfile sink: bounded queue back-pressure; cancel-aware so an aborted
    response stops the worker within _PUT_TIMEOUT instead of finishing a
    multi-GB ZIP nobody reads."""

    def __init__(self, q: "queue.Queue[object]", cancel: threading.Event) -> None:
        self._q = q
        self._cancel = cancel
        self._pos = 0

    def write(self, b) -> int:
        data = bytes(b)
        while True:
            if self._cancel.is_set():
                raise _ZipAborted()
            try:
                self._q.put(data, timeout=_PUT_TIMEOUT)
                self._pos += len(data)
                return len(data)
            except queue.Full:
                continue

    def flush(self) -> None:
        pass

    def tell(self) -> int:
        return self._pos

    def seekable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def close(self) -> None:
        pass


def _put_guarded(q: "queue.Queue[object]", item, cancel: threading.Event) -> None:
    """Terminal marker put: never block forever on a full/dead queue."""
    while not cancel.is_set():
        try:
            q.put(item, timeout=_PUT_TIMEOUT)
            return
        except queue.Full:
            continue


def _zip_worker(q, cancel, record) -> None:
    try:
        with zipfile.ZipFile(
            _QueueSink(q, cancel), "w", compression=zipfile.ZIP_STORED
        ) as zf:
            missing: list[str] = []
            for e in record.entries:
                if cancel.is_set():
                    raise _ZipAborted()
                p = Path(e.disk_path)
                if not p.is_file():
                    missing.append(f"{e.image_id}  {e.arcname}")
                    continue
                try:
                    mt = time.localtime(p.stat().st_mtime)[:6]
                except OSError:
                    mt = (1980, 1, 1, 0, 0, 0)
                zi = zipfile.ZipInfo(e.arcname, date_time=mt)
                zi.compress_type = zipfile.ZIP_STORED
                zi.external_attr = (0o644 & 0xFFFF) << 16
                zi.flag_bits |= 0x800  # UTF-8 文件名
                try:
                    with zf.open(zi, "w", force_zip64=True) as out, \
                            p.open("rb") as fh:
                        shutil.copyfileobj(fh, out, length=_CHUNK_MAX)
                except OSError:
                    log.exception("zip entry read failed: %s", e.arcname)
                    missing.append(f"{e.image_id}  {e.arcname} (read error)")
            if missing and not cancel.is_set():
                mi = zipfile.ZipInfo("missing-files.txt")
                mi.compress_type = zipfile.ZIP_STORED
                mi.flag_bits |= 0x800
                # 流模式必须 force_zip64，writestr 不支持，显式 open：
                header = "以下文件在打包时缺失或读取失败（条目可能不完整）：\n"
                with zf.open(mi, "w", force_zip64=True) as out:
                    out.write(header.encode("utf-8"))
                    out.write("".join(line + "\n" for line in missing).encode("utf-8"))
    except _ZipAborted:
        log.info("zip download aborted (client disconnected): ticket entries=%d",
                 len(record.entries))
    except Exception:
        log.exception("zip streaming failed")
        _put_guarded(q, _ERROR, cancel)
    finally:
        _put_guarded(q, _SENTINEL, cancel)


def _reap_worker(thread: threading.Thread, q: "queue.Queue[object]",
                 cancel: threading.Event) -> None:
    """Run OFF the event-loop thread: tell the worker to stop and bounded-join.
    The worker is cancel-aware (its blocking put bails within _PUT_TIMEOUT);
    if it somehow stays stuck, drain briefly with timeouts, then abandon a
    daemon thread rather than block forever."""
    cancel.set()
    thread.join(timeout=_REAP_JOIN_SEC)
    while thread.is_alive():
        try:
            chunk = q.get(timeout=1.0)
        except queue.Empty:
            return  # abandon; daemon thread
        if chunk is _SENTINEL or chunk is _ERROR:
            break
    thread.join(timeout=_REAP_JOIN_SEC)


def _zip_stream(record: TicketRecord):
    q: "queue.Queue[object]" = queue.Queue(maxsize=_QUEUE_DEPTH)
    cancel = threading.Event()
    thread = threading.Thread(
        target=_zip_worker, args=(q, cancel, record), daemon=True,
    )
    thread.start()
    try:
        while True:
            chunk = q.get()
            if chunk is _SENTINEL:
                break
            if chunk is _ERROR:
                # 响应头已发出无法改状态码；提前结束流，客户端会得到损坏 ZIP
                log.error("aborting zip response after worker error")
                return
            yield chunk
    finally:
        # starlette 在事件循环线程上 finalize 被丢弃的同步 generator：
        # 这里只做廉价操作，绝不排空队列；拆除交给 daemon reaper 线程。
        threading.Thread(
            target=_reap_worker, args=(thread, q, cancel), daemon=True,
        ).start()


@router.get("/download-batch/{ticket}")
def download_batch_zip(
    ticket: str,
    request: Request,
    user: User = Depends(current_user),
):
    store: TicketStore = request.app.state.download_tickets
    record = store.claim(ticket, user.id)
    if record is None:
        raise AppError("not_found", 404, "ticket not found")
    quoted = quote(record.filename, safe="")
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{record.filename}"; '
            f"filename*=UTF-8''{quoted}"
        ),
        "Cache-Control": "no-store",
    }
    return StreamingResponse(
        _zip_stream(record),
        media_type="application/zip",
        headers=headers,
    )
