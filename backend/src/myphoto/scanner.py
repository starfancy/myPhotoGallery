from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from PIL import ExifTags, Image as PILImage
from PIL.TiffImagePlugin import IFDRational
from sqlalchemy import select

from myphoto.audit import write_audit
from myphoto.formats import classify, is_supported
from myphoto.models import Folder, GalleryRoot, Image

log = logging.getLogger("myphoto.scanner")

# Number of images upserted per short write transaction. Keeping this small
# bounds how long the scanner holds SQLite's single-writer lock so concurrent
# admin writes are not blocked for the whole scan.
_SCAN_BATCH_SIZE = 200

# Source-default cap on files hashed/EXIF-read concurrently during a scan.
# hashlib and the Pillow/rawpy decoders release the GIL around their heavy
# work, so wall-clock scales with cores up to this cap. Kept small to avoid
# seek thrashing on HDD/network mounts and to leave default-executor threads
# for other asyncio.to_thread callers. Config ([scanner].hash_workers in
# config.toml) overrides this; see Scanner.__init__.
_HASH_WORKERS = min(8, (os.cpu_count() or 4))

try:
    import pillow_heif  # type: ignore[import-not-found]

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - optional decoder registration
    pass


# EXIF tag ID → 输出字典中使用的名字。GPSInfo (0x8825) 单独处理：其值
# 是 sub-IFD 指针，抽取时会替换成 GPS 子字段字典。
EXIF_TAGS: dict[int, str] = {
    0x010F: "Make",
    0x0110: "Model",
    0x9003: "DateTimeOriginal",
    0x0132: "ModifyDate",
    0x829A: "ExposureTime",
    0x829D: "FNumber",
    0x8827: "ISOSpeedRatings",
    0x920A: "FocalLength",
    0xA434: "LensModel",
    0x8825: "GPSInfo",
    0x0112: "Orientation",
    0x0131: "Software",
    0x9209: "Flash",
    0xA403: "WhiteBalance",
    0xA001: "ColorSpace",
    0x8822: "ExposureProgram",
    0x9207: "MeteringMode",
    0x9204: "ExposureBiasValue",
    0xA406: "SceneCaptureType",
    0xA300: "FileSource",
}


@dataclass
class _RootStatus:
    status: str = "idle"
    last_scan_at: int | None = None
    last_scan_error: str | None = None
    # Live progress (in-memory only). phase is idle|walking|hashing|committing.
    phase: str = "idle"
    total_files: int = 0
    processed_files: int = 0
    current_path: str | None = None
    started_at: int | None = None

    def reset_progress(self) -> None:
        # Reset the transient live-progress indicators back to idle, but retain
        # total_files/processed_files as a summary of the most recent scan.
        self.phase = "idle"
        self.current_path = None
        self.started_at = None


@dataclass(frozen=True)
class _WalkedFile:
    path: Path
    filename: str
    relative_path: str
    relative_dir: str
    mtime: int
    size_bytes: int


@dataclass
class _ScanRecord:
    """One walked file prepared for persistence. Heavy work (sha1/exif) has
    already completed outside any DB transaction."""
    walked: _WalkedFile
    changed: bool
    sha1: str | None
    width: int | None
    height: int | None
    taken_at: int | None
    exif_json: str | None


class Scanner:
    def __init__(self, sessionmaker, hash_workers: int | None = None):
        self._sm = sessionmaker
        # [scanner].hash_workers override from config.toml; None/non-positive
        # falls back to the source default _HASH_WORKERS.
        self._hash_workers = (
            hash_workers
            if isinstance(hash_workers, int) and hash_workers >= 1
            else _HASH_WORKERS
        )
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._enqueued: set[int] = set()
        self._worker: asyncio.Task[None] | None = None
        self._status: dict[int, _RootStatus] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        finally:
            self._worker = None

    async def enqueue(self, root_id: int) -> None:
        async with self._lock:
            if root_id in self._enqueued:
                return
            self._enqueued.add(root_id)
            self._status.setdefault(root_id, _RootStatus()).status = "queued"
        await self._queue.put(root_id)

    def get_status(self, root_id: int) -> dict[str, str | int | None]:
        status = self._status.get(root_id, _RootStatus())
        return {
            "status": status.status,
            "last_scan_at": status.last_scan_at,
            "last_scan_error": status.last_scan_error,
            "phase": status.phase,
            "total_files": status.total_files,
            "processed_files": status.processed_files,
            "current_path": status.current_path,
            "started_at": status.started_at,
        }

    async def _loop(self) -> None:
        while True:
            root_id = await self._queue.get()
            try:
                await self.scan_root_now(root_id)
            except Exception:
                log.exception("scanner worker crashed for root=%s", root_id)
            finally:
                async with self._lock:
                    self._enqueued.discard(root_id)
                self._queue.task_done()

    async def scan_root_now(self, root_id: int) -> None:
        status = self._status.setdefault(root_id, _RootStatus())
        status.status = "running"
        status.last_scan_error = None
        status.phase = "walking"
        status.total_files = 0
        status.processed_files = 0
        status.current_path = None
        status.started_at = int(time.time())
        try:
            await self._audit(root_id, "scan_start")
            try:
                last_scan_at = await self._scan_transaction(root_id)
            except asyncio.CancelledError:
                status.status = "idle"
                status.reset_progress()
                raise
            except Exception as exc:
                error = str(exc)[:500]
                log.warning("scan failed for root=%s: %s", root_id, error)
                await self._record_scan_error(root_id, error)
                status.status = "idle"
                status.last_scan_error = error
                status.reset_progress()
            else:
                status.status = "idle"
                status.last_scan_at = last_scan_at
                status.last_scan_error = None
                status.reset_progress()
                await self._audit(
                    root_id, "scan_finish",
                    detail=f"last_scan_at={last_scan_at}",
                )
        except Exception:
            # A crash in _audit itself must not strand the root in "running":
            # reset defensively before re-raising to the worker loop.
            if status.status == "running":
                status.status = "idle"
                status.reset_progress()
            raise

    async def _audit(self, root_id: int, action: str, detail: str | None = None) -> None:
        """Emit a scanner-lifecycle audit event on a dedicated session.

        Scanner runs internally (not on behalf of an HTTP request) so
        actor_user_id is None and actor_ip is fixed at 127.0.0.1 per plan.

        Failures are caught and logged: audit persistence must never break the
        scan lifecycle. `write_audit` already swallows flush errors; this
        wrapper covers the commit and connect failures too.
        """
        try:
            async with self._sm() as session:
                await write_audit(
                    session, action, None, "127.0.0.1",
                    target=f"root:{root_id}", detail=detail,
                )
                await session.commit()
        except Exception:
            log.exception("audit write failed for scanner action=%s root=%s", action, root_id)

    async def _scan_transaction(self, root_id: int) -> int:
        status = self._status.setdefault(root_id, _RootStatus())

        # --- Phase 1: resolve root, then walk the tree (no write txn held) ---
        async with self._sm() as session:
            root = await session.get(GalleryRoot, root_id)
            if root is None:
                raise RuntimeError(f"root {root_id} not found")
            absolute_root = Path(root.absolute_path)

        status.phase = "walking"
        walked_dirs, walked_files = await asyncio.to_thread(_walk_root, absolute_root)
        status.total_files = len(walked_files)
        status.processed_files = 0

        # Load existing rows in a short read session, then release the
        # connection before the CPU/IO-heavy hashing phase.
        async with self._sm() as session:
            existing_images = {
                image.relative_path: image
                for image in (
                    await session.execute(
                        select(Image).where(Image.root_id == root_id)
                    )
                ).scalars()
            }

        # --- Phase 2: hash/EXIF work OUTSIDE any transaction ---
        # Files with unchanged (mtime, size) keep their stored sha1/EXIF and
        # skip the heavy read entirely; the rest are processed concurrently on
        # a bounded worker pool (size from config [scanner].hash_workers,
        # defaulting to the source constant _HASH_WORKERS).
        status.phase = "hashing"
        records: list[_ScanRecord] = []
        indexed_paths: set[str] = set()
        pending: list[_WalkedFile] = []
        for relative_path, walked in walked_files.items():
            existing = existing_images.get(relative_path)
            unchanged = (
                existing is not None
                and existing.mtime == walked.mtime
                and existing.size_bytes == walked.size_bytes
            )
            if unchanged:
                records.append(_ScanRecord(
                    walked=walked, changed=False,
                    sha1=None, width=None, height=None,
                    taken_at=None, exif_json=None,
                ))
                indexed_paths.add(relative_path)
            else:
                pending.append(walked)

        # Unchanged files count as already processed; workers bump the counter
        # as they finish so live progress keeps advancing during the pool phase.
        status.processed_files = len(records)
        # Show the first pending file synchronously: between phase="hashing"
        # and the first worker step there is otherwise an await gap where the
        # progress UI would report hashing with no current file.
        if pending:
            status.current_path = pending[0].relative_path
        pool = asyncio.Semaphore(self._hash_workers)

        async def _hash_one(
            walked: _WalkedFile,
        ) -> _ScanRecord | tuple[_WalkedFile, BaseException]:
            """Hash + read EXIF for one file on a worker thread.

            Per-file failures are returned (not raised) so one unreadable image
            cannot abort the scan; CancelledError is not an Exception subclass
            and propagates, which lets gather cancel the whole pool.
            """
            async with pool:
                status.current_path = walked.relative_path
                try:
                    sha1, width, height, taken_at, exif_json = await asyncio.to_thread(
                        _process_file,
                        walked.path,
                        classify(walked.filename) == "raw",
                    )
                except Exception as exc:
                    return walked, exc
                finally:
                    status.processed_files += 1
            return _ScanRecord(
                walked=walked, changed=True,
                sha1=sha1, width=width, height=height,
                taken_at=taken_at, exif_json=exif_json,
            )

        # gather preserves input order, so records stay in walk order.
        results = await asyncio.gather(*(_hash_one(walked) for walked in pending))
        for outcome in results:
            if isinstance(outcome, tuple):
                walked, exc = outcome
                log.warning("skipping unreadable image %s: %s", walked.path, exc)
                continue
            records.append(outcome)
            indexed_paths.add(outcome.walked.relative_path)
        status.current_path = None

        # --- Phase 3a: create/update folders in one short write txn ---
        status.phase = "committing"
        async with self._sm() as session:
            folders = await _ensure_folders(session, root_id, walked_dirs)
            await session.commit()
        folder_ids = {relative_path: folder.id for relative_path, folder in folders.items()}

        # --- Phase 3b: upsert images in short batched transactions ---
        for start in range(0, len(records), _SCAN_BATCH_SIZE):
            batch = records[start:start + _SCAN_BATCH_SIZE]
            await self._persist_batch(root_id, batch, folder_ids)

        # --- Phase 3c: delete missing, prune folders, recompute, update root ---
        async with self._sm() as session:
            folders = {
                folder.relative_path: folder
                for folder in (
                    await session.execute(
                        select(Folder).where(Folder.root_id == root_id)
                    )
                ).scalars()
            }
            existing_now = {
                image.relative_path: image
                for image in (
                    await session.execute(
                        select(Image).where(Image.root_id == root_id)
                    )
                ).scalars()
            }
            for relative_path, image in existing_now.items():
                if relative_path not in indexed_paths:
                    await session.delete(image)
            await session.flush()

            await _remove_unwalked_folders(session, root_id, walked_dirs)
            _recompute_counts(folders, walked_dirs, indexed_paths)

            last_scan_at = int(time.time())
            root = await session.get(GalleryRoot, root_id)
            if root is not None:
                root.last_scan_at = last_scan_at
                root.last_scan_status = "ok"
                root.last_scan_error = None
            await session.commit()
        return last_scan_at

    async def _persist_batch(
        self,
        root_id: int,
        batch: list[_ScanRecord],
        folder_ids: dict[str, int],
    ) -> None:
        """Upsert one batch of records in a single short write transaction."""
        async with self._sm() as session:
            rel_paths = [record.walked.relative_path for record in batch]
            existing = {
                image.relative_path: image
                for image in (
                    await session.execute(
                        select(Image).where(
                            Image.root_id == root_id,
                            Image.relative_path.in_(rel_paths),
                        )
                    )
                ).scalars()
            }
            for record in batch:
                target_folder_id = folder_ids[record.walked.relative_dir]
                if record.changed:
                    _upsert_image(
                        session=session,
                        existing=existing.get(record.walked.relative_path),
                        root_id=root_id,
                        folder_id=target_folder_id,
                        walked=record.walked,
                        sha1=record.sha1,
                        width=record.width,
                        height=record.height,
                        taken_at=record.taken_at,
                        exif_json=record.exif_json,
                    )
                else:
                    image = existing.get(record.walked.relative_path)
                    if image is not None and image.folder_id != target_folder_id:
                        image.folder_id = target_folder_id
            await session.commit()

    async def _record_scan_error(self, root_id: int, error: str) -> None:
        try:
            async with self._sm() as session:
                root = await session.get(GalleryRoot, root_id)
                if root is not None:
                    root.last_scan_status = "error"
                    root.last_scan_error = error
                    await session.commit()
        except Exception:
            log.exception("could not persist scan error for root=%s", root_id)
        # Emit the audit AFTER the error-state commit, on a fresh session, so
        # audit failure cannot roll back the error-state persistence.
        await self._audit(root_id, "scan_error", detail=error)


def _walk_root(root: Path) -> tuple[set[str], dict[str, _WalkedFile]]:
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"root path missing: {root}")

    walked_dirs: set[str] = {""}
    walked_files: dict[str, _WalkedFile] = {}
    walk_errors: list[OSError] = []

    def onerror(exc: OSError) -> None:
        walk_errors.append(exc)
        log.warning("skipping unreadable directory %s: %s", exc.filename, exc)

    for dirpath, dirnames, filenames in os.walk(
        root, topdown=True, onerror=onerror, followlinks=False
    ):
        current = Path(dirpath)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not dirname.startswith(".")
            and dirname != "__pycache__"
            and not (current / dirname).is_symlink()
        ]
        relative_dir = current.relative_to(root).as_posix()
        if relative_dir == ".":
            relative_dir = ""
        walked_dirs.add(relative_dir)

        for filename in filenames:
            if not is_supported(filename):
                continue
            path = current / filename
            try:
                if path.is_symlink():
                    continue
                stat = path.stat()
            except OSError as exc:
                log.warning("skipping unreadable file %s: %s", path, exc)
                continue
            relative_path = (
                f"{relative_dir}/{filename}" if relative_dir else filename
            )
            walked_files[relative_path] = _WalkedFile(
                path=path,
                filename=filename,
                relative_path=relative_path,
                relative_dir=relative_dir,
                mtime=int(stat.st_mtime),
                size_bytes=stat.st_size,
            )

    root_string = os.fspath(root)
    if walk_errors and any(
        Path(exc.filename or root_string) == root for exc in walk_errors
    ):
        raise RuntimeError(f"root path unreadable: {root}") from walk_errors[0]
    return walked_dirs, walked_files


def _process_file(
    path: Path, is_raw: bool
) -> tuple[str, int | None, int | None, int | None, str | None]:
    sha1 = _sha1_of(path)
    if is_raw:
        width, height, taken_at, exif_json = _read_raw_meta(path)
    else:
        width, height, taken_at, exif_json = _read_image_meta(path)
    return sha1, width, height, taken_at, exif_json


def _sha1_of(path: Path) -> str:
    # hashlib.file_digest (3.11+) streams through a 256 KiB readinto buffer —
    # far fewer read syscalls and no per-chunk bytes allocation than a manual
    # 64 KiB read loop. Output is the same SHA-1 either way; like the loop it
    # runs off the event loop via asyncio.to_thread and releases the GIL
    # during hashing.
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha1").hexdigest()


def _read_image_meta(
    path: Path,
) -> tuple[int, int, int | None, str | None]:
    with PILImage.open(path) as image:
        image.verify()
    with PILImage.open(path) as image:
        width, height = _oriented_size(image)
        exif = image.getexif()
        taken_at = _taken_at_from_exif(exif)
        exif_json = _extract_exif_json(exif)
    return width, height, taken_at, exif_json


def _oriented_size(image: PILImage.Image) -> tuple[int, int]:
    """返回按 EXIF Orientation 转正后的 (width, height)。

    相机直出图片的像素按传感器方向存储（横版），竖拍仅靠 Orientation
    标签标记：5–8 表示 90°/270° 旋转，宽高需要交换。image.size 是未
    旋转的像素尺寸，直接入库会让前端网格/灯箱把竖版照片按横版排版。
    （后期软件导出时通常已把旋转烘焙进像素并置 Orientation=1。）
    """
    width, height = image.size
    try:
        orientation = image.getexif().get(0x0112)
    except Exception:  # pragma: no cover - defensive: 缺 EXIF 不阻断扫描
        orientation = None
    if orientation in (5, 6, 7, 8):
        return height, width
    return width, height


def _read_raw_meta(path: Path) -> tuple[int, int, int | None, str | None]:
    import rawpy

    exif_json: str | None = None
    taken_at: int | None = None
    with rawpy.imread(os.fspath(path)) as raw:
        sizes = raw.sizes
        width = int(sizes.width)
        height = int(sizes.height)
        # 通过 rawpy 抽取内嵌 JPEG，再用 Pillow 读它的 EXIF。RAW 库本身没提供
        # 直接的 EXIF 结构化接口；内嵌 JPEG 是相机厂商写入的原始 EXIF 副本。
        try:
            thumb = raw.extract_thumb()
        except Exception:
            thumb = None
    if thumb is not None and getattr(thumb, "format", None) == rawpy.ThumbFormat.JPEG:
        try:
            with PILImage.open(io.BytesIO(thumb.data)) as embedded:
                embedded_exif = embedded.getexif()
                taken_at = _taken_at_from_exif(embedded_exif)
                exif_json = _extract_exif_json(embedded_exif)
        except Exception:  # pragma: no cover - defensive: never break scan
            log.debug("could not read EXIF from embedded thumb of %s", path, exc_info=True)
    return width, height, taken_at, exif_json


def _taken_at_from_exif(exif) -> int | None:
    raw_value = exif.get(0x9003) or exif.get(0x0132)
    if not raw_value:
        return None
    try:
        return int(time.mktime(time.strptime(str(raw_value), "%Y:%m:%d %H:%M:%S")))
    except (TypeError, ValueError, OverflowError):
        return None


def _extract_exif_json(exif) -> str | None:
    """从 PIL exif 对象抽取 20 个白名单 tag，返回可序列化的 JSON 字符串。

    - `getexif()` 返回顶层 IFD；EXIF sub-IFD（0x8769）通过 `get_ifd(...)`
      展开合并，因为 ExposureTime、FNumber 等大部分字段实际在 sub-IFD。
    - GPSInfo 是 sub-IFD 指针（0x8825），单独通过 `get_ifd(0x8825)` 展开
      为可读字典。
    - 抽取失败绝不抛异常，返回 None。
    """
    if exif is None:
        return None
    try:
        # 顶层 tag（Make/Model/Orientation/Software/ModifyDate）
        merged: dict[int, object] = {tag: value for tag, value in exif.items()}
        # 合并 EXIF sub-IFD（大量拍摄参数在这里）
        try:
            sub = exif.get_ifd(0x8769)
            merged.update(sub)
        except Exception:  # pragma: no cover
            pass

        out: dict[str, object] = {}
        for tag_id, name in EXIF_TAGS.items():
            if tag_id not in merged:
                continue
            if tag_id == 0x8825:
                # GPSInfo 单独展开
                try:
                    gps_ifd = exif.get_ifd(0x8825)
                except Exception:  # pragma: no cover
                    gps_ifd = merged.get(0x8825)
                gps = _serialize_gps(gps_ifd)
                if gps:
                    out[name] = gps
                continue
            serialized = _serialize_exif_value(merged[tag_id])
            if serialized is not None:
                out[name] = serialized

        if not out:
            return None
        return json.dumps(out, ensure_ascii=False, sort_keys=True)
    except Exception:
        log.debug("EXIF extraction failed", exc_info=True)
        return None


def _serialize_exif_value(value):
    """转成 JSON 安全值：str/int/float/bool/list/dict。丢弃 bytes/未知对象。"""
    if isinstance(value, IFDRational):
        return _format_rational(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, str):
        # PIL 常返回带 NUL 结尾的字符串
        return value.strip("\x00").strip() or None
    if isinstance(value, bytes):
        try:
            decoded = value.decode("utf-8", errors="ignore").strip("\x00").strip()
        except Exception:
            return None
        return decoded or None
    if isinstance(value, (tuple, list)):
        items = [_serialize_exif_value(v) for v in value]
        items = [v for v in items if v is not None]
        return items or None
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = str(k)
            serialized = _serialize_exif_value(v)
            if serialized is not None:
                out[key] = serialized
        return out or None
    return None


def _format_rational(value: IFDRational) -> str | float | int:
    """有理数：分子/分母格式化。快门速度这类 <1 的用分数字符串（"1/250"），
    ≥1 的直接给 float。分母为 0 或非法时回退 float(value)。"""
    try:
        numerator = int(value.numerator)
        denominator = int(value.denominator)
    except Exception:  # pragma: no cover
        try:
            return float(value)
        except Exception:
            return None  # type: ignore[return-value]
    if denominator == 0:
        return None  # type: ignore[return-value]
    if denominator == 1:
        return numerator
    # 快门速度约定：<1 秒用 "N/M" 字符串保留可读性
    fraction = Fraction(numerator, denominator)
    if abs(fraction) < 1:
        return f"{fraction.numerator}/{fraction.denominator}"
    return round(float(fraction), 3)


# GPS sub-IFD 常见 tag id → 名字
_GPS_TAG_NAMES = {v: k for k, v in getattr(ExifTags, "GPSTAGS", {}).items()}


def _serialize_gps(ifd) -> dict | None:
    if not ifd:
        return None
    try:
        out: dict[str, object] = {}
        for tag_id, value in dict(ifd).items():
            name = ExifTags.GPSTAGS.get(tag_id, str(tag_id))
            serialized = _serialize_exif_value(value)
            if serialized is not None:
                out[name] = serialized
        return out or None
    except Exception:  # pragma: no cover
        return None


def _upsert_image(
    *,
    session,
    existing: Image | None,
    root_id: int,
    folder_id: int,
    walked: _WalkedFile,
    sha1: str,
    width: int | None,
    height: int | None,
    taken_at: int | None,
    exif_json: str | None,
) -> None:
    kind = classify(walked.filename)
    extension = walked.filename.rsplit(".", 1)[-1].lower()
    indexed_at = int(time.time())
    if existing is None:
        session.add(
            Image(
                root_id=root_id,
                folder_id=folder_id,
                relative_path=walked.relative_path,
                filename=walked.filename,
                ext=extension,
                size_bytes=walked.size_bytes,
                width=width,
                height=height,
                sha1=sha1,
                mtime=walked.mtime,
                taken_at=taken_at,
                is_raw=int(kind == "raw"),
                indexed_at=indexed_at,
                exif_json=exif_json,
            )
        )
        return

    existing.folder_id = folder_id
    existing.filename = walked.filename
    existing.ext = extension
    existing.size_bytes = walked.size_bytes
    existing.width = width
    existing.height = height
    existing.sha1 = sha1
    existing.mtime = walked.mtime
    existing.taken_at = taken_at
    existing.is_raw = int(kind == "raw")
    existing.indexed_at = indexed_at
    existing.exif_json = exif_json


async def _ensure_folders(
    session, root_id: int, walked_dirs: set[str]
) -> dict[str, Folder]:
    folders = {
        folder.relative_path: folder
        for folder in (
            await session.execute(select(Folder).where(Folder.root_id == root_id))
        ).scalars()
    }
    for relative_path in sorted(walked_dirs, key=lambda path: (path.count("/"), path)):
        folder = folders.get(relative_path)
        if folder is None:
            folder = Folder(
                root_id=root_id,
                relative_path=relative_path,
                name=relative_path.rsplit("/", 1)[-1] if relative_path else "",
                image_count=0,
                descendant_count=0,
            )
            session.add(folder)
            await session.flush()
            folders[relative_path] = folder
        else:
            folder.name = (
                relative_path.rsplit("/", 1)[-1] if relative_path else ""
            )
        if relative_path:
            parent_path = (
                relative_path.rsplit("/", 1)[0] if "/" in relative_path else ""
            )
            folder.parent_id = folders[parent_path].id
        else:
            folder.parent_id = None
    return folders


async def _remove_unwalked_folders(
    session, root_id: int, walked_dirs: set[str]
) -> None:
    stale = (
        await session.execute(select(Folder).where(Folder.root_id == root_id))
    ).scalars().all()
    for folder in sorted(
        (row for row in stale if row.relative_path not in walked_dirs),
        key=lambda row: row.relative_path.count("/"),
        reverse=True,
    ):
        await session.delete(folder)
    await session.flush()


def _recompute_counts(
    folders: dict[str, Folder], walked_dirs: set[str], indexed_paths: set[str]
) -> None:
    direct = {relative_dir: 0 for relative_dir in walked_dirs}
    for relative_path in indexed_paths:
        relative_dir = (
            relative_path.rsplit("/", 1)[0] if "/" in relative_path else ""
        )
        direct[relative_dir] += 1

    for relative_dir in walked_dirs:
        folder = folders[relative_dir]
        folder.image_count = direct[relative_dir]
        folder.descendant_count = sum(
            count
            for path, count in direct.items()
            if not relative_dir
            or path == relative_dir
            or path.startswith(relative_dir + "/")
        )
