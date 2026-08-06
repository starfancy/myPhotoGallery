# Scan Short Transactions + Live Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop long local scans from locking the SQLite database by doing all heavy file work outside write transactions and committing in small batches, and surface live scan progress (phase, processed/total, current file) through the existing polling endpoints.

**Architecture:** The scanner is rewritten in three phases — (1) walk the tree and load existing rows in short read sessions, (2) do all SHA1/EXIF/RAW hashing outside any transaction, (3) persist results in one folder-setup transaction plus batched upsert transactions (200 rows each) and one fast final cleanup transaction. Progress counters live in the scanner's in-memory `_RootStatus` and are exposed through the existing `scan-status`, gallery-detail, and admin-status endpoints; the Vue admin views poll every 2s while any root is running and render a progress bar.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2 async / aiosqlite (SQLite) / pytest-asyncio backend; Vue 3 + TypeScript + Vitest frontend.

## Global Constraints

- No new dependencies.
- SQLite WAL + `busy_timeout=5000` are set on every connection; in-memory databases (tests) must not error when WAL is unsupported.
- Batch size is a module constant `_SCAN_BATCH_SIZE = 200`.
- Progress state is in-memory only (never persisted); it lives and dies with the server process, matching the existing `idle|queued|running` flag.
- A scan that errors partway may leave already-committed batches visible (acceptable — the error is still recorded on the root). Previously a failure rolled everything back.
- Corrupted/unreadable files are still skipped (logged) and, if previously indexed, removed — same behavior as today.
- All timestamps are integer Unix seconds.
- Chinese UI copy exactly as given in steps.
- Backend tests run cross-platform; do not depend on real Win32 or network drives.

---

## File Structure

- Modify `backend/src/myphoto/db.py` — add `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` to the per-connection setup.
- Create `backend/tests/test_db.py` — verify WAL/busy_timeout pragmas on a file database.
- Modify `backend/src/myphoto/scanner.py` — extend `_RootStatus` with progress fields; add `_ScanRecord`; split `_scan_transaction` into discovery/processing/batched-persist phases; add `_persist_batch`; extend `get_status`.
- Modify `backend/tests/test_scanner.py` — add progress and concurrent-write tests.
- Modify `backend/src/myphoto/routes_admin.py` — include progress fields in `scan-status`, gallery detail, and admin status responses.
- Modify `backend/tests/test_routes_admin_roots.py` — assert progress fields are present.
- Modify `frontend/src/views/AdminGalleryEdit.vue` — add progress fields to `RootInfo`; silent polling while running; progress bar UI.
- Modify `frontend/src/tests/admin-gallery-edit.spec.ts` — progress rendering + polling tests.
- Modify `frontend/src/views/AdminOverview.vue` — add progress fields to `ScanStatus`; silent polling while any root runs; progress UI.
- Modify `frontend/src/tests/admin-overview.spec.ts` — progress rendering + polling tests.

---

### Task 1: Enable WAL + busy_timeout

**Files:**
- Modify: `backend/src/myphoto/db.py:58-64`
- Create: `backend/tests/test_db.py`

**Interfaces:**
- Produces: every SQLite connection runs with `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000`. In-memory connections ignore the WAL failure gracefully.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_db.py`:

```python
from pathlib import Path

from myphoto.db import make_engine


async def test_pragmas_applied_to_file_connection(tmp_path):
    db_path = tmp_path / "test.db"
    engine = await make_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    try:
        async with engine.connect() as conn:
            journal = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
            timeout = (await conn.exec_driver_sql("PRAGMA busy_timeout")).scalar_one()
        assert str(journal).lower() == "wal"
        assert timeout >= 5000
    finally:
        await engine.dispose()


async def test_in_memory_engine_does_not_fail(tmp_path):
    # :memory: does not support WAL; engine construction + connect must still work.
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
    finally:
        await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_db.py -v`

Expected: FAIL — `journal_mode` is `delete` (not `wal`) and `busy_timeout` is 0.

- [ ] **Step 3: Apply the pragmas**

In `backend/src/myphoto/db.py`, replace the existing `_set_fk_pragma` listener (currently lines 58-64):

```python
    @event.listens_for(engine.sync_engine, "connect")
    def _set_fk_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
```

with:

```python
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL allows readers while a writer is active; busy_timeout makes a
            # writer wait for the lock instead of raising "database is locked"
            # immediately. :memory: databases do not support WAL — tolerate that.
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
            except Exception:
                pass
        finally:
            cursor.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_db.py -v`

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/myphoto/db.py backend/tests/test_db.py
git commit -m "feat(backend): enable SQLite WAL and busy_timeout"
```

---

### Task 2: Add progress fields to scanner status

**Files:**
- Modify: `backend/src/myphoto/scanner.py` (`_RootStatus`, `get_status`, reset points in `scan_root_now`)
- Test: `backend/tests/test_scanner.py`

**Interfaces:**
- Produces: `_RootStatus` gains `phase: str`, `total_files: int`, `processed_files: int`, `current_path: str | None`, `started_at: int | None`.
- Produces: `Scanner.get_status(root_id)` returns those five keys in addition to the existing `status`, `last_scan_at`, `last_scan_error`.
- `phase` lifecycle: `"idle"` → `"walking"` → `"hashing"` → `"committing"` → `"idle"`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_scanner.py`:

```python
async def test_status_exposes_progress_fields(env):
    _, sm, root_id = env
    scanner = Scanner(sm)

    status = scanner.get_status(root_id)
    # Idle baseline: keys present and zeroed/neutral.
    assert status["phase"] == "idle"
    assert status["total_files"] == 0
    assert status["processed_files"] == 0
    assert status["current_path"] is None
    assert "started_at" in status
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_scanner.py::test_status_exposes_progress_fields -v`

Expected: FAIL — `KeyError: 'phase'`.

- [ ] **Step 3: Extend `_RootStatus`**

In `backend/src/myphoto/scanner.py`, replace the `_RootStatus` dataclass (lines 58-62):

```python
@dataclass
class _RootStatus:
    status: str = "idle"
    last_scan_at: int | None = None
    last_scan_error: str | None = None
```

with:

```python
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
        self.phase = "idle"
        self.total_files = 0
        self.processed_files = 0
        self.current_path = None
        self.started_at = None
```

- [ ] **Step 4: Extend `get_status`**

Replace `get_status` (lines 107-113):

```python
    def get_status(self, root_id: int) -> dict[str, str | int | None]:
        status = self._status.get(root_id, _RootStatus())
        return {
            "status": status.status,
            "last_scan_at": status.last_scan_at,
            "last_scan_error": status.last_scan_error,
        }
```

with:

```python
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
```

- [ ] **Step 5: Reset/set progress in `scan_root_now`**

In `scan_root_now`, update the three state transitions. First, the running setup (lines 128-130):

```python
        status = self._status.setdefault(root_id, _RootStatus())
        status.status = "running"
        status.last_scan_error = None
```

becomes:

```python
        status = self._status.setdefault(root_id, _RootStatus())
        status.status = "running"
        status.last_scan_error = None
        status.phase = "walking"
        status.total_files = 0
        status.processed_files = 0
        status.current_path = None
        status.started_at = int(time.time())
```

Then the CancelledError branch (lines 135-137):

```python
            except asyncio.CancelledError:
                status.status = "idle"
                raise
```

becomes:

```python
            except asyncio.CancelledError:
                status.status = "idle"
                status.reset_progress()
                raise
```

The failure branch (lines 142-143):

```python
                status.status = "idle"
                status.last_scan_error = error
```

becomes:

```python
                status.status = "idle"
                status.last_scan_error = error
                status.reset_progress()
```

And the success branch (lines 145-147):

```python
                status.status = "idle"
                status.last_scan_at = last_scan_at
                status.last_scan_error = None
```

becomes:

```python
                status.status = "idle"
                status.last_scan_at = last_scan_at
                status.last_scan_error = None
                status.reset_progress()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_scanner.py::test_status_exposes_progress_fields -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/myphoto/scanner.py backend/tests/test_scanner.py
git commit -m "feat(backend): add progress fields to scanner status"
```

---

### Task 3: Refactor scan into short transactions (A2 core)

**Files:**
- Modify: `backend/src/myphoto/scanner.py` (add `_ScanRecord`, `_SCAN_BATCH_SIZE`; rewrite `_scan_transaction`; add `_persist_batch`)
- Test: `backend/tests/test_scanner.py`

**Interfaces:**
- Consumes: existing `_walk_root`, `_process_file`, `_ensure_folders`, `_remove_unwalked_folders`, `_recompute_counts`, `_upsert_image`, `classify`.
- Produces: `Scanner._scan_transaction(root_id) -> int` with the same signature/return as before, but no write transaction is held during file hashing.
- Produces: module constant `_SCAN_BATCH_SIZE = 200`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_scanner.py`. First, a progress-during-scan test. Add these imports at the top of the file with the other imports:

```python
import threading
```

Then append:

```python
async def test_progress_advances_through_phases(env, monkeypatch):
    root_dir, sm, root_id = env
    for n in range(3):
        _jpg(root_dir / f"{n}.jpg")

    import myphoto.scanner as sc
    gate = threading.Event()
    calls = {"n": 0}
    real_process = sc._process_file

    def slow_process(path, is_raw):
        calls["n"] += 1
        if calls["n"] == 1:
            gate.wait(timeout=5)
        return real_process(path, is_raw)

    monkeypatch.setattr(sc, "_process_file", slow_process)

    scanner = Scanner(sm)
    scan_task = asyncio.create_task(scanner.scan_root_now(root_id))

    # Wait until the scan reaches the hashing phase on the first file.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        st = scanner.get_status(root_id)
        if st["status"] == "running" and st["phase"] == "hashing":
            break
        await asyncio.sleep(0.01)

    running = scanner.get_status(root_id)
    assert running["phase"] == "hashing"
    assert running["total_files"] == 3
    assert running["processed_files"] == 0
    assert running["current_path"] is not None
    assert running["started_at"] is not None

    gate.set()
    await asyncio.wait_for(scan_task, timeout=5)

    done = scanner.get_status(root_id)
    assert done["status"] == "idle"
    assert done["phase"] == "idle"
    assert done["processed_files"] == 3
    assert done["current_path"] is None
```

Also add `import asyncio` to the test file's imports if not present. Then append the locking regression test:

```python
async def test_concurrent_write_succeeds_during_hashing(env, monkeypatch):
    """A2 guarantee: no write transaction is held while hashing files, so an
    unrelated admin write must complete without 'database is locked'."""
    root_dir, sm, root_id = env
    for n in range(3):
        _jpg(root_dir / f"{n}.jpg")

    import myphoto.scanner as sc
    gate = threading.Event()
    real_process = sc._process_file

    def slow_process(path, is_raw):
        gate.wait(timeout=5)
        return real_process(path, is_raw)

    monkeypatch.setattr(sc, "_process_file", slow_process)

    scanner = Scanner(sm)
    scan_task = asyncio.create_task(scanner.scan_root_now(root_id))

    # Wait until hashing starts (no DB transaction held).
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        st = scanner.get_status(root_id)
        if st["phase"] == "hashing":
            break
        await asyncio.sleep(0.01)

    # This write must not block: the scan returned its connection before hashing.
    async def _concurrent_write():
        async with sm() as session:
            session.add(Gallery(name="Concurrent", created_at=int(time.time())))
            await session.commit()

    await asyncio.wait_for(_concurrent_write(), timeout=3)

    gate.set()
    await asyncio.wait_for(scan_task, timeout=5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_scanner.py::test_progress_advances_through_phases tests/test_scanner.py::test_concurrent_write_succeeds_during_hashing -v`

Expected: FAIL — progress stays `idle`/phase never reaches `hashing` (the current code sets no phase), and the concurrent write test times out because the old `_scan_transaction` holds the write transaction across hashing.

- [ ] **Step 3: Add `_ScanRecord` and the batch constant**

In `backend/src/myphoto/scanner.py`, add the constant near the top after the logger / `EXIF_TAGS` block (e.g. after line 22 `log = ...`):

```python
# Number of images upserted per short write transaction. Keeping this small
# bounds how long the scanner holds SQLite's single-writer lock so concurrent
# admin writes are not blocked for the whole scan.
_SCAN_BATCH_SIZE = 200
```

Then add this dataclass right after `_WalkedFile` (after line 73):

```python
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
```

- [ ] **Step 4: Rewrite `_scan_transaction`**

Replace the entire `_scan_transaction` method (lines 179-249) with the three-phase version below:

```python
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
        status.phase = "hashing"
        records: list[_ScanRecord] = []
        indexed_paths: set[str] = set()
        for relative_path, walked in walked_files.items():
            status.current_path = relative_path
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
            else:
                try:
                    sha1, width, height, taken_at, exif_json = await asyncio.to_thread(
                        _process_file,
                        walked.path,
                        classify(walked.filename) == "raw",
                    )
                except Exception as exc:
                    log.warning("skipping unreadable image %s: %s", walked.path, exc)
                    status.processed_files += 1
                    continue
                records.append(_ScanRecord(
                    walked=walked, changed=True,
                    sha1=sha1, width=width, height=height,
                    taken_at=taken_at, exif_json=exif_json,
                ))
            indexed_paths.add(relative_path)
            status.processed_files += 1
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
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_scanner.py::test_progress_advances_through_phases tests/test_scanner.py::test_concurrent_write_succeeds_during_hashing -v`

Expected: both PASS. The concurrent-write test completes well under the 3s timeout.

- [ ] **Step 6: Run the full scanner suite for regressions**

Run: `cd backend && python -m pytest tests/test_scanner.py -v`

Expected: all tests PASS, including `test_indexes_images`, `test_removes_deleted`, `test_skips_hidden`, `test_folder_counts`, `test_status_ok`, `test_skips_corrupted_file_continues`, and all EXIF tests.

- [ ] **Step 7: Commit**

```bash
git add backend/src/myphoto/scanner.py backend/tests/test_scanner.py
git commit -m "feat(backend): run scan hashing outside txn and persist in batches"
```

---

### Task 4: Expose progress through admin API endpoints (B1 backend)

**Files:**
- Modify: `backend/src/myphoto/routes_admin.py` (gallery detail ~line 124, `admin_scan_status` ~line 404, `admin_status` ~line 636)
- Test: `backend/tests/test_routes_admin_roots.py`

**Interfaces:**
- Produces: `GET /api/admin/galleries/{gid}/roots/{rid}/scan-status` returns `phase`, `total_files`, `processed_files`, `current_path`, `started_at` alongside existing fields.
- Produces: each root object in `GET /api/admin/galleries/{gid}` and each entry in `GET /api/admin/status` `scan_statuses` includes those same progress fields.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_routes_admin_roots.py`:

```python
def test_scan_status_includes_progress_fields(client_with_gallery):
    c, gid, photos, _ = client_with_gallery
    rid = c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R", "absolute_path": str(photos),
    }).json()["id"]

    r = c.get(f"/api/admin/galleries/{gid}/roots/{rid}/scan-status")
    assert r.status_code == 200
    body = r.json()
    for key in ("phase", "total_files", "processed_files", "current_path", "started_at"):
        assert key in body


def test_gallery_detail_includes_progress_fields(client_with_gallery):
    c, gid, photos, _ = client_with_gallery
    c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R", "absolute_path": str(photos),
    })
    r = c.get(f"/api/admin/galleries/{gid}")
    assert r.status_code == 200
    root = r.json()["roots"][0]
    for key in ("phase", "total_files", "processed_files", "current_path", "started_at"):
        assert key in root
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_routes_admin_roots.py -k progress -v`

Expected: FAIL — the progress keys are missing from the responses.

- [ ] **Step 3: Add progress to gallery detail**

In `admin_get_gallery`, replace the `root_out.append({...})` block (lines 124-134):

```python
            root_out.append({
                "id": r.id,
                "label": r.label,
                "absolute_path": r.absolute_path,
                "enabled": bool(r.enabled),
                "image_count": cnt,
                "status": live["status"],
                "last_scan_at": live["last_scan_at"] if live["last_scan_at"] is not None else r.last_scan_at,
                "last_scan_status": r.last_scan_status,
                "last_scan_error": live["last_scan_error"] if live["last_scan_error"] is not None else r.last_scan_error,
            })
```

with:

```python
            root_out.append({
                "id": r.id,
                "label": r.label,
                "absolute_path": r.absolute_path,
                "enabled": bool(r.enabled),
                "image_count": cnt,
                "status": live["status"],
                "last_scan_at": live["last_scan_at"] if live["last_scan_at"] is not None else r.last_scan_at,
                "last_scan_status": r.last_scan_status,
                "last_scan_error": live["last_scan_error"] if live["last_scan_error"] is not None else r.last_scan_error,
                "phase": live["phase"],
                "total_files": live["total_files"],
                "processed_files": live["processed_files"],
                "current_path": live["current_path"],
                "started_at": live["started_at"],
            })
```

- [ ] **Step 4: Add progress to the scan-status endpoint**

In `admin_scan_status`, replace the return dict (lines 404-408):

```python
    return {
        "status": status["status"],
        "last_scan_at": status["last_scan_at"],
        "last_scan_error": status["last_scan_error"],
    }
```

with:

```python
    return {
        "status": status["status"],
        "last_scan_at": status["last_scan_at"],
        "last_scan_error": status["last_scan_error"],
        "phase": status["phase"],
        "total_files": status["total_files"],
        "processed_files": status["processed_files"],
        "current_path": status["current_path"],
        "started_at": status["started_at"],
    }
```

- [ ] **Step 5: Add progress to admin status**

In `admin_status`, replace the `scan_statuses.append({...})` block (lines 636-646):

```python
            scan_statuses.append({
                "root_id": r.id,
                "gallery_id": r.gallery_id,
                "label": r.label,
                "absolute_path": r.absolute_path,
                "enabled": bool(r.enabled),
                "status": live["status"],
                "last_scan_at": live["last_scan_at"] if live["last_scan_at"] is not None else r.last_scan_at,
                "last_scan_status": r.last_scan_status,
                "last_scan_error": live["last_scan_error"] if live["last_scan_error"] is not None else r.last_scan_error,
            })
```

with:

```python
            scan_statuses.append({
                "root_id": r.id,
                "gallery_id": r.gallery_id,
                "label": r.label,
                "absolute_path": r.absolute_path,
                "enabled": bool(r.enabled),
                "status": live["status"],
                "last_scan_at": live["last_scan_at"] if live["last_scan_at"] is not None else r.last_scan_at,
                "last_scan_status": r.last_scan_status,
                "last_scan_error": live["last_scan_error"] if live["last_scan_error"] is not None else r.last_scan_error,
                "phase": live["phase"],
                "total_files": live["total_files"],
                "processed_files": live["processed_files"],
                "current_path": live["current_path"],
                "started_at": live["started_at"],
            })
```

- [ ] **Step 6: Run the route tests**

Run: `cd backend && python -m pytest tests/test_routes_admin_roots.py -v`

Expected: all tests PASS, including the two new progress tests.

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/src/myphoto/routes_admin.py backend/tests/test_routes_admin_roots.py
git commit -m "feat(backend): expose scan progress in admin endpoints"
```

---

### Task 5: Frontend progress bar + polling in AdminGalleryEdit

**Files:**
- Modify: `frontend/src/views/AdminGalleryEdit.vue`
- Test: `frontend/src/tests/admin-gallery-edit.spec.ts`

**Interfaces:**
- Consumes: optional `phase?: string`, `total_files?: number`, `processed_files?: number`, `current_path?: string | null`, `started_at?: number | null` on each `RootInfo`.
- Produces: polls `GET /api/admin/galleries/{gid}` every 2s while any root is `queued`/`running`, stops when all are idle, and cleans up on unmount. Renders `processed / total (percent)` plus current path and a progress bar for running roots.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/tests/admin-gallery-edit.spec.ts`, add `afterEach` and two new tests inside the `describe` block (after the existing tests). First add `vi.useRealTimers()` cleanup — extend the existing `beforeEach` block (lines 75-78):

```ts
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })
```

Then append these tests before the closing `})` of the describe:

```ts
  it("renders processed/total, percent and current path for a running root", async () => {
    const running = {
      ...GALLERY,
      roots: [
        {
          ...GALLERY.roots[0],
          status: "running",
          phase: "hashing",
          total_files: 10,
          processed_files: 4,
          current_path: "vacation/001.jpg",
          started_at: 1_700_000_000,
        },
      ],
    }
    mockFetchSequence({ body: running })
    const w = await mountView()

    expect(w.text()).toContain("4 / 10")
    expect(w.text()).toContain("40%")
    expect(w.text()).toContain("vacation/001.jpg")
    // progress bar exposes its percentage for assistive tech / tests
    const bar = w.find('[role="progressbar"]')
    expect(bar.exists()).toBe(true)
    expect(bar.attributes("aria-valuenow")).toBe("40")
  })

  it("polls every 2s while a scan is running and stops when idle", async () => {
    vi.useFakeTimers()
    const running = {
      ...GALLERY,
      roots: [{ ...GALLERY.roots[0], status: "running", total_files: 10, processed_files: 1 }],
    }
    const idle = GALLERY
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(mockFetchOnce(running)) // onMounted load
      .mockResolvedValueOnce(mockFetchOnce(running)) // first poll
      .mockResolvedValueOnce(mockFetchOnce(idle))    // second poll -> idle
    vi.stubGlobal("fetch", fetchFn)

    const w = await mountView()
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(2000)
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(2)

    vi.advanceTimersByTime(2000)
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(3)

    // All roots idle -> no further polling.
    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(3)

    w.unmount()
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/tests/admin-gallery-edit.spec.ts`

Expected: FAIL — the progress text and progressbar are absent, and polling does not refetch.

- [ ] **Step 3: Extend the `RootInfo` interface**

In `frontend/src/views/AdminGalleryEdit.vue`, extend the interface (lines 101-111):

```ts
interface RootInfo {
  id: number
  label: string
  absolute_path: string
  enabled: boolean
  image_count: number
  status: string
  last_scan_at: number | null
  last_scan_status: string | null
  last_scan_error: string | null
  phase?: string
  total_files?: number
  processed_files?: number
  current_path?: string | null
  started_at?: number | null
}
```

- [ ] **Step 4: Add the progress bar to the root card template**

In the root card, after the status row (the `<div class="flex items-center gap-2 text-xs">...</div>` containing `scanStatusClass`, lines 52-56), insert the progress block. The outer track carries `role="progressbar"` and aria values; the inner fill is purely visual:

```vue
                <div v-if="isRunning(r)" class="mt-1 space-y-1">
                  <div class="h-1 w-full overflow-hidden rounded bg-neutral-800"
                       role="progressbar"
                       :aria-valuemin="0"
                       :aria-valuemax="100"
                       :aria-valuenow="scanPercent(r)">
                    <div class="h-1 rounded bg-blue-500"
                         :style="{ width: scanPercent(r) + '%' }"></div>
                  </div>
                  <div class="flex items-center justify-between gap-2 text-xs text-neutral-500">
                    <span>{{ r.processed_files ?? 0 }} / {{ r.total_files ?? 0 }} ({{ scanPercent(r) }}%)</span>
                    <span v-if="r.current_path" class="truncate" :title="r.current_path">
                      {{ r.current_path }}
                    </span>
                  </div>
                </div>
```

- [ ] **Step 5: Add silent polling logic and helpers**

Update the Vue imports (line 95):

```ts
import { onMounted, onUnmounted, ref } from "vue"
```

Change `loadGallery` to accept a silent flag (replace lines 136-150):

```ts
async function loadGallery(silent = false) {
  if (!silent) loading.value = true
  error.value = ""
  try {
    const d = await apiGet<GalleryDetail>(`/api/admin/galleries/${gid}`)
    data.value = d
    galleryName.value = d.name
    editName.value = d.name
    editDescription.value = d.description ?? ""
  } catch (err) {
    error.value = (err as HttpError).message || "加载失败"
  } finally {
    if (!silent) loading.value = false
  }
  schedulePoll()
}
```

Add the polling timer and helpers just above `onMounted(loadGallery)` (line 225):

```ts
let pollTimer: ReturnType<typeof setTimeout> | null = null

function anyRootRunning(): boolean {
  return data.value?.roots.some(
    (r) => r.status === "queued" || r.status === "running",
  ) ?? false
}

function schedulePoll() {
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
  if (anyRootRunning()) {
    pollTimer = setTimeout(() => {
      void loadGallery(true)
    }, 2000)
  }
}

function isRunning(r: RootInfo): boolean {
  return r.status === "queued" || r.status === "running"
}

function scanPercent(r: RootInfo): number {
  if (!r.total_files || r.total_files <= 0) return 0
  return Math.round(((r.processed_files ?? 0) / r.total_files) * 100)
}

onMounted(loadGallery)

onUnmounted(() => {
  if (pollTimer !== null) clearTimeout(pollTimer)
})
```

Remove the original bare `onMounted(loadGallery)` line (line 225) since the block above now includes it.

- [ ] **Step 6: Run the frontend tests**

Run: `cd frontend && npx vitest run src/tests/admin-gallery-edit.spec.ts`

Expected: all tests PASS, including the two new ones. Existing tests still pass (silent polling does not change their assertions; `rescan button sends POST and reloads` still triggers reloads).

- [ ] **Step 7: Type check**

Run: `cd frontend && npx vue-tsc --noEmit`

Expected: no type errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/AdminGalleryEdit.vue frontend/src/tests/admin-gallery-edit.spec.ts
git commit -m "feat(frontend): poll and show scan progress in gallery edit"
```

---

### Task 6: Frontend progress + polling in AdminOverview

**Files:**
- Modify: `frontend/src/views/AdminOverview.vue`
- Test: `frontend/src/tests/admin-overview.spec.ts`

**Interfaces:**
- Consumes: optional `phase`, `total_files`, `processed_files`, `current_path`, `started_at` on each `ScanStatus`.
- Produces: polls `/api/admin/status` every 2s while any root is running/queued; renders `processed / total (percent)` per running root; stops polling and cleans up on unmount.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/tests/admin-overview.spec.ts`, add timer cleanup and two tests. Extend `beforeEach` (lines 90-93):

```ts
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })
```

Append these tests inside the `describe` block before its closing `})`:

```ts
  it("renders progress for a running root", async () => {
    mockStatus({
      stats: { images: 0, galleries: 0, roots: 0, users: 1 },
      scan_statuses: [
        {
          root_id: 1, gallery_id: 1, label: "Main", absolute_path: "/photos",
          enabled: true, status: "running", last_scan_at: null,
          last_scan_status: null, last_scan_error: null,
          phase: "hashing", total_files: 20, processed_files: 5,
          current_path: "a/b.jpg", started_at: 1_700_000_000,
        },
      ],
      recent_audit: [],
    })
    const w = mountView()
    await flushPromises()

    expect(w.text()).toContain("5 / 20")
    expect(w.text()).toContain("25%")
    expect(w.find('[role="progressbar"]').attributes("aria-valuenow")).toBe("25")
  })

  it("polls status while a scan is running and stops when idle", async () => {
    vi.useFakeTimers()
    const running = {
      stats: { images: 0, galleries: 0, roots: 0, users: 1 },
      scan_statuses: [
        { root_id: 1, gallery_id: 1, label: "Main", absolute_path: "/photos",
          enabled: true, status: "running", last_scan_at: null,
          last_scan_status: null, last_scan_error: null,
          total_files: 20, processed_files: 5 },
      ],
      recent_audit: [],
    }
    const idle = {
      stats: { images: 0, galleries: 0, roots: 0, users: 1 },
      scan_statuses: [
        { root_id: 1, gallery_id: 1, label: "Main", absolute_path: "/photos",
          enabled: true, status: "idle", last_scan_at: 1_700_000_000,
          last_scan_status: "ok", last_scan_error: null },
      ],
      recent_audit: [],
    }
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(new Response(JSON.stringify(running), { headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(running), { headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(idle), { headers: { "content-type": "application/json" } }))
    vi.stubGlobal("fetch", fetchFn)

    const w = mountView()
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(2000)
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(2)

    vi.advanceTimersByTime(2000)
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(3)

    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(3)

    w.unmount()
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/tests/admin-overview.spec.ts`

Expected: FAIL — progress UI and polling are absent.

- [ ] **Step 3: Extend the `ScanStatus` interface**

In `frontend/src/views/AdminOverview.vue`, extend the interface (lines 127-137):

```ts
interface ScanStatus {
  root_id: number
  gallery_id: number
  label: string
  absolute_path: string
  enabled: boolean
  status: string
  last_scan_at: number | null
  last_scan_status: string | null
  last_scan_error: string | null
  phase?: string
  total_files?: number
  processed_files?: number
  current_path?: string | null
  started_at?: number | null
}
```

- [ ] **Step 4: Add progress UI to each scan-status row**

In the scan status list, inside the `<li>` after the status `<span>` block (after line 61, before the `last_scan_at` span), insert:

```vue
                <div v-if="isRunning(s)" class="mt-1 w-full">
                  <div class="h-1 w-full overflow-hidden rounded bg-neutral-800"
                       role="progressbar"
                       :aria-valuemin="0"
                       :aria-valuemax="100"
                       :aria-valuenow="scanPercent(s)">
                    <div class="h-1 rounded bg-blue-500"
                         :style="{ width: scanPercent(s) + '%' }"></div>
                  </div>
                  <div class="mt-1 text-xs text-neutral-500">
                    {{ s.processed_files ?? 0 }} / {{ s.total_files ?? 0 }} ({{ scanPercent(s) }}%)
                    <span v-if="s.current_path" class="ml-2 truncate" :title="s.current_path">
                      {{ s.current_path }}
                    </span>
                  </div>
                </div>
```

Because the row uses `flex flex-col ... sm:flex-row`, wrap the status column so the progress block stacks beneath it. Place the progress block immediately after the closing `</div>` of the `<div class="flex items-center gap-3 text-xs">...</div>` (which ends at line 69), still inside the `<li>`.

- [ ] **Step 5: Add silent polling and helpers**

Update the import (line 116):

```ts
import { onMounted, onUnmounted, ref } from "vue"
```

Replace the `onMounted` block (lines 159-167):

```ts
onMounted(async () => {
  try {
    data.value = await apiGet<StatusResponse>("/api/admin/status")
  } catch (err) {
    error.value = (err as HttpError).message || "加载失败"
  } finally {
    loading.value = false
  }
})
```

with:

```ts
async function loadStatus(silent = false) {
  if (!silent) loading.value = true
  try {
    data.value = await apiGet<StatusResponse>("/api/admin/status")
  } catch (err) {
    error.value = (err as HttpError).message || "加载失败"
  } finally {
    if (!silent) loading.value = false
  }
  schedulePoll()
}

let pollTimer: ReturnType<typeof setTimeout> | null = null

function anyScanRunning(): boolean {
  return data.value?.scan_statuses.some(
    (s) => s.status === "queued" || s.status === "running",
  ) ?? false
}

function schedulePoll() {
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
  if (anyScanRunning()) {
    pollTimer = setTimeout(() => {
      void loadStatus(true)
    }, 2000)
  }
}

function isRunning(s: ScanStatus): boolean {
  return s.status === "queued" || s.status === "running"
}

function scanPercent(s: ScanStatus): number {
  if (!s.total_files || s.total_files <= 0) return 0
  return Math.round(((s.processed_files ?? 0) / s.total_files) * 100)
}

onMounted(() => {
  void loadStatus()
})

onUnmounted(() => {
  if (pollTimer !== null) clearTimeout(pollTimer)
})
```

- [ ] **Step 6: Run the frontend tests**

Run: `cd frontend && npx vitest run src/tests/admin-overview.spec.ts`

Expected: all tests PASS, including the two new ones.

- [ ] **Step 7: Full frontend check**

Run: `cd frontend && npx vitest run && npx vue-tsc --noEmit`

Expected: all tests pass, no type errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/AdminOverview.vue frontend/src/tests/admin-overview.spec.ts
git commit -m "feat(frontend): poll and show scan progress on overview"
```

---

## Verification (manual)

1. Start the backend (`myphoto` or `uvicorn myphoto.main:app`) and add a root with several hundred images, including some large RAW files so the scan takes several seconds.
2. Open Admin → gallery edit page immediately after triggering "重扫". Within 2s the root card should show "扫描中" with a progress bar, `processed / total (percent)`, and the current file path; numbers advance until completion.
3. While the scan is running, open Admin → overview in another tab; it should show the same live progress.
4. While the scan is running, edit the gallery name/description and save, add/rename a user, or toggle a root's enabled flag. These writes should succeed (no spinner hang, no "database is locked") because the scanner no longer holds a write transaction during hashing.
5. Confirm `db/app.db-wal` and `db/app.db-shm` exist alongside `app.db` (WAL active).
6. Stop and restart the server mid-scan. Progress state is gone (in-memory); the root shows its previous `last_scan_status` until the startup auto-scan runs again — expected.
7. Delete a batch of images on disk and rescan: missing images are removed and folder counts recomputed (unchanged behavior).
8. Leave one corrupted/truncated image in the tree: the scan still completes with `last_scan_status = ok`, the bad file is skipped, and other images are indexed.

## Self-Review Notes

- A2: the write lock is now held only during (a) folder setup, (b) each 200-row batch commit, and (c) the final cleanup — milliseconds each. The `test_concurrent_write_succeeds_during_hashing` regression test would have deadlocked/timed out against the old single-transaction code.
- B1: progress is purely additive (new optional fields, zeroed when idle), so all existing API and frontend consumers keep working. Polling is bounded to exactly one timer per view and is torn down on unmount.
- Behavioral change recorded in Global Constraints: a mid-scan error may leave partially-committed batches visible; the root is still marked `error`.
- WAL is best-effort for `:memory:` so the existing in-memory test fixtures are unaffected.
