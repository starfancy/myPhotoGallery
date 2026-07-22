from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage
from sqlalchemy import select

from myphoto.audit import write_audit
from myphoto.formats import classify, is_supported
from myphoto.models import Folder, GalleryRoot, Image

log = logging.getLogger("myphoto.scanner")

try:
    import pillow_heif  # type: ignore[import-not-found]

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - optional decoder registration
    pass


@dataclass
class _RootStatus:
    status: str = "idle"
    last_scan_at: int | None = None
    last_scan_error: str | None = None


@dataclass(frozen=True)
class _WalkedFile:
    path: Path
    filename: str
    relative_path: str
    relative_dir: str
    mtime: int
    size_bytes: int


class Scanner:
    def __init__(self, sessionmaker):
        self._sm = sessionmaker
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
        try:
            await self._audit(root_id, "scan_start")
            try:
                last_scan_at = await self._scan_transaction(root_id)
            except asyncio.CancelledError:
                status.status = "idle"
                raise
            except Exception as exc:
                error = str(exc)[:500]
                log.warning("scan failed for root=%s: %s", root_id, error)
                await self._record_scan_error(root_id, error)
                status.status = "idle"
                status.last_scan_error = error
            else:
                status.status = "idle"
                status.last_scan_at = last_scan_at
                status.last_scan_error = None
                await self._audit(
                    root_id, "scan_finish",
                    detail=f"last_scan_at={last_scan_at}",
                )
        except Exception:
            # A crash in _audit itself must not strand the root in "running":
            # reset defensively before re-raising to the worker loop.
            if status.status == "running":
                status.status = "idle"
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
        async with self._sm() as session:
            root = await session.get(GalleryRoot, root_id)
            if root is None:
                raise RuntimeError(f"root {root_id} not found")

            absolute_root = Path(root.absolute_path)
            walked_dirs, walked_files = await asyncio.to_thread(
                _walk_root, absolute_root
            )
            existing_images = {
                image.relative_path: image
                for image in (
                    await session.execute(
                        select(Image).where(Image.root_id == root_id)
                    )
                ).scalars()
            }
            folders = await _ensure_folders(session, root_id, walked_dirs)
            indexed_paths: set[str] = set()

            for relative_path, walked in walked_files.items():
                existing = existing_images.get(relative_path)
                folder_id = folders[walked.relative_dir].id
                if (
                    existing is not None
                    and existing.mtime == walked.mtime
                    and existing.size_bytes == walked.size_bytes
                ):
                    existing.folder_id = folder_id
                    indexed_paths.add(relative_path)
                    continue

                try:
                    sha1, width, height, taken_at = await asyncio.to_thread(
                        _process_file,
                        walked.path,
                        classify(walked.filename) == "raw",
                    )
                except Exception as exc:
                    log.warning("skipping unreadable image %s: %s", walked.path, exc)
                    continue

                _upsert_image(
                    session=session,
                    existing=existing,
                    root_id=root_id,
                    folder_id=folder_id,
                    walked=walked,
                    sha1=sha1,
                    width=width,
                    height=height,
                    taken_at=taken_at,
                )
                indexed_paths.add(relative_path)

            for relative_path, image in existing_images.items():
                if relative_path not in indexed_paths:
                    await session.delete(image)
            await session.flush()

            await _remove_unwalked_folders(session, root_id, walked_dirs)
            _recompute_counts(folders, walked_dirs, indexed_paths)

            last_scan_at = int(time.time())
            root.last_scan_at = last_scan_at
            root.last_scan_status = "ok"
            root.last_scan_error = None
            await session.commit()
            return last_scan_at

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
) -> tuple[str, int | None, int | None, int | None]:
    sha1 = _sha1_of(path)
    if is_raw:
        width, height, taken_at = _read_raw_meta(path)
    else:
        width, height, taken_at = _read_image_meta(path)
    return sha1, width, height, taken_at


def _sha1_of(path: Path, buffer_size: int = 64 * 1024) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as file:
        while chunk := file.read(buffer_size):
            digest.update(chunk)
    return digest.hexdigest()


def _read_image_meta(path: Path) -> tuple[int, int, int | None]:
    with PILImage.open(path) as image:
        image.verify()
    with PILImage.open(path) as image:
        width, height = image.size
        taken_at = _taken_at_from_exif(image.getexif())
    return width, height, taken_at


def _read_raw_meta(path: Path) -> tuple[int, int, int | None]:
    import rawpy

    with rawpy.imread(os.fspath(path)) as raw:
        sizes = raw.sizes
        width = int(sizes.width)
        height = int(sizes.height)
    return width, height, None


def _taken_at_from_exif(exif) -> int | None:
    raw_value = exif.get(0x9003) or exif.get(0x0132)
    if not raw_value:
        return None
    try:
        return int(time.mktime(time.strptime(str(raw_value), "%Y:%m:%d %H:%M:%S")))
    except (TypeError, ValueError, OverflowError):
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
