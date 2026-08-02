# Windows Drive Volume Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each Windows drive in the admin directory chooser as `C:（卷标）`, falling back to the drive type (e.g. `CD/DVD 驱动器`) when no label is readable.

**Architecture:** The backend `/api/admin/browse-fs` endpoint enriches Windows drive-root entries with a `label` string, obtained via `GetVolumeInformationW` with a `GetDriveTypeW` fallback. The blocking Win32 calls run in a worker thread and are guarded against critical-error dialogs. The Vue chooser renders the optional `label` after the drive letter; all other behavior is unchanged.

**Tech Stack:** Python 3 / FastAPI backend (stdlib `ctypes`), Vue 3 + TypeScript + Vitest frontend, pytest backend.

## Global Constraints

- Display format: `盘符` first, then label/type in full-width parens: `C:（系统）`.
- `label` is always a non-empty string for Windows root entries (type fallback guarantees it).
- POSIX behavior unchanged: root lists real subdirectories, no `label` field.
- One failing drive must never break the whole drive list.
- Empty optical drives / dead network mounts must not pop a system dialog (`SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX`).
- Backend tests must run cross-platform (fake `ctypes`, never real Win32).
- Drive type display strings (exact): 可移动磁盘 / 本地磁盘 / 网络驱动器 / CD/DVD 驱动器 / RAM 磁盘 / 驱动器.

Reference spec: `docs/superpowers/specs/2026-08-02-windows-drive-volume-labels-design.md`

---

## File Structure

- Modify `backend/src/myphoto/routes_admin.py` — add `import asyncio`, `import ctypes`; add two Win32 helper functions; enrich `_list_drive_letters()`; call it via `asyncio.to_thread`.
- Modify `backend/tests/test_routes_admin_browse_fs.py` — extend root test; add cross-platform fake-ctypes test.
- Modify `frontend/src/components/DirectoryChooser.vue` — add `label?` to `DirEntry`; render it for root entries.
- Modify `frontend/src/tests/directory-chooser.spec.ts` — add a label-rendering assertion.

---

### Task 1: Backend drive label + type helpers

**Files:**
- Modify: `backend/src/myphoto/routes_admin.py` (top imports; new helpers near line 415; `_list_drive_letters`; call site near line 494)
- Test: `backend/tests/test_routes_admin_browse_fs.py`

**Interfaces:**
- Produces: `_drive_volume_label(drive: str) -> str | None` — returns the trimmed volume label for a root path like `C:\\`, or `None` if unreadable/empty.
- Produces: `_drive_type_name(drive: str) -> str` — returns the Chinese display name for the drive type, never empty.
- Produces: `_list_drive_letters() -> list[dict]` now returns dicts with keys `name`, `path`, `is_root`, `label` (label always non-empty on Windows).
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests**

Open `backend/tests/test_routes_admin_browse_fs.py`. First, extend the Windows branch of `test_browse_fs_default_returns_root` so the existing assertion block reads:

```python
    if sys.platform == "win32":
        # Windows: drive letters, path == ""
        assert data["path"] == ""
        for e in data["entries"]:
            assert e["is_root"] is True
            # e.g. "C:" as name, "C:\\" as path
            assert re.fullmatch(r"[A-Z]:", e["name"])
            assert isinstance(e["label"], str)
            assert e["label"]  # non-empty: volume label or drive-type fallback
```

Then append a new cross-platform test at the end of the file:

```python
def test_browse_fs_windows_drive_labels(monkeypatch):
    """Drive entries carry a volume label; a failed label query falls back to
    the drive-type name. Uses a fake ctypes so it runs on every platform."""
    import asyncio
    from myphoto import routes_admin

    SEM_FAILCRITICALERRORS = 0x0001
    SEM_NOOPENFILEERRORBOX = 0x8000
    expected_flags = SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX

    class FakeKernel32:
        def __init__(self):
            self.error_mode = 0
            # C: labeled, E: unreadable volume (CD-ROM type), F: removable
            self.drives = {
                "C:\\": ("系统", 3),    # DRIVE_FIXED
                "E:\\": (None, 5),      # DRIVE_CDROM, GetVolumeInformation fails
                "F:\\": ("", 2),        # DRIVE_REMOVABLE, empty label
            }

        def GetLogicalDrives(self):
            # bits for C (1<<2), E (1<<4), F (1<<5)
            return (1 << 2) | (1 << 4) | (1 << 5)

        def SetErrorMode(self, mode):
            self.error_mode = mode
            return 0

        def GetVolumeInformationW(self, root, _buf, _bsize, _a, _b, _c, _d, _e):
            label, _ = self.drives[root]
            if label is None:
                return 0  # failure -> no label
            _buf.value = label
            return 1

        def GetDriveTypeW(self, root):
            return self.drives[root][1]

    fake = FakeKernel32()

    class FakeWindll:
        kernel32 = fake

    class FakeCtypes:
        windll = FakeWindll()

        class c_wchar:
            pass

        @staticmethod
        def create_unicode_buffer(size):
            class Buf:
                def __init__(self):
                    self.value = ""
            return Buf()

        @staticmethod
        def sizeof(obj):
            # The implementation divides buf size by c_wchar size to derive a
            # character count; return 2 for both so the result is a sane int.
            return 2

    monkeypatch.setattr(routes_admin, "ctypes", FakeCtypes)
    monkeypatch.setattr(routes_admin.sys, "platform", "win32")

    entries = asyncio.run(routes_admin.asyncio.to_thread(routes_admin._list_drive_letters))
    by_letter = {e["name"]: e for e in entries}

    assert set(by_letter) == {"C:", "E:", "F:"}

    # C: has a real label
    assert by_letter["C:"]["label"] == "系统"
    assert by_letter["C:"]["is_root"] is True
    assert by_letter["C:"]["path"] == "C:\\"

    # E: GetVolumeInformation failed -> fall back to drive type
    assert by_letter["E:"]["label"] == "CD/DVD 驱动器"

    # F: empty label string -> fall back to drive type
    assert by_letter["F:"]["label"] == "可移动磁盘"

    # Critical-error dialogs were suppressed during the calls and restored.
    assert fake.error_mode == expected_flags or fake.error_mode == 0
```

Note the last assertion is intentionally loose about the *final* restored mode
(because the fake's `SetErrorMode` returns 0 and restoration sets it back); the
meaningful guarantee — that `expected_flags` was passed at least once — is
checked in Step 4. Tighten it then. For now this test fails because the helpers
and `label` field do not exist yet.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_routes_admin_browse_fs.py -v`

Expected: FAIL — `test_browse_fs_windows_drive_labels` errors with
`AttributeError: module 'myphoto.routes_admin' has no attribute 'asyncio'`
(or the new label assertion fails on the existing test).

- [ ] **Step 3: Add imports**

In `backend/src/myphoto/routes_admin.py`, add two imports in the existing
stdlib import block (alphabetically alongside the others near lines 3-8):

```python
import asyncio
import ctypes
```

- [ ] **Step 4: Implement the helpers and enrich `_list_drive_letters`**

Replace the existing `_list_drive_letters` function (currently lines 415-431)
with the block below. It adds two helpers and rewrites the drive lister to
fetch label-or-type, set the critical-error mode around each query, and always
emit a `label`:

```python
# Windows SetErrorMode flags used to suppress critical-error dialogs (e.g. an
# empty CD/DVD drive or a dead network share) while querying volume info.
_SEM_FAILCRITICALERRORS = 0x0001
_SEM_NOOPENFILEERRORBOX = 0x8000

# GetDriveTypeW return values -> Chinese display names.
_DRIVE_TYPE_NAMES = {
    2: "可移动磁盘",      # DRIVE_REMOVABLE
    3: "本地磁盘",        # DRIVE_FIXED
    4: "网络驱动器",      # DRIVE_REMOTE
    5: "CD/DVD 驱动器",  # DRIVE_CDROM
    6: "RAM 磁盘",       # DRIVE_RAMDISK
}


def _drive_volume_label(drive: str) -> str | None:
    """Return the trimmed volume label for a Windows drive root (e.g. "C:\\"),
    or None if it has no label or cannot be read.

    Sets the process error mode around the call so an empty optical drive or
    a dead network mount does not pop a system dialog.
    """
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError:
        return None
    prev = kernel32.SetErrorMode(
        _SEM_FAILCRITICALERRORS | _SEM_NOOPENFILEERRORBOX
    )
    try:
        buf = ctypes.create_unicode_buffer(256)
        ok = kernel32.GetVolumeInformationW(
            drive, buf, ctypes.sizeof(buf) // ctypes.sizeof(ctypes.c_wchar),
            None, None, None, None, 0,
        )
        if not ok:
            return None
        label = buf.value.strip()
        return label or None
    except (OSError, AttributeError):
        return None
    finally:
        kernel32.SetErrorMode(prev)


def _drive_type_name(drive: str) -> str:
    """Return a Chinese display name for a Windows drive's type. Never empty;
    unknown types map to "驱动器"."""
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        code = kernel32.GetDriveTypeW(drive)
    except (OSError, AttributeError):
        return "驱动器"
    return _DRIVE_TYPE_NAMES.get(code, "驱动器")


def _list_drive_letters() -> list[dict]:
    """Windows: return mounted drives via GetLogicalDrives bitmask.

    Uses the kernel32 bitmask rather than probing each letter with `os.path.exists`
    so we do not wake removable media or block on dead network mounts. Each entry
    carries a `label`: the volume label when available, otherwise the drive-type
    name. Per-drive errors are isolated so one bad drive never drops the others.
    """
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return []
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        if not (bitmask & (1 << i)):
            continue
        drive = f"{letter}:\\"
        try:
            label = _drive_volume_label(drive) or _drive_type_name(drive)
        except OSError:
            label = _drive_type_name(drive)
        out.append({
            "name": f"{letter}:",
            "path": drive,
            "is_root": True,
            "label": label,
        })
    return out
```

- [ ] **Step 5: Move the drive listing off the event loop**

In `admin_browse_fs`, find the Windows root branch (currently):

```python
            if sys.platform == "win32":
                entries = _list_drive_letters()
                truncated = False
                result_path = ""
```

Change the listing line to run in a worker thread (a disconnected network
mount can make the Win32 calls block):

```python
            if sys.platform == "win32":
                entries = await asyncio.to_thread(_list_drive_letters)
                truncated = False
                result_path = ""
```

- [ ] **Step 6: Tighten the test's error-mode assertion**

In `test_browse_fs_windows_drive_labels`, record every `SetErrorMode` argument
so we can prove the suppress flags were applied. Replace the `FakeKernel32`
class's `__init__` and `SetErrorMode` with:

```python
        def __init__(self):
            self.error_mode = 0
            self.error_mode_calls = []
            # C: labeled, E: unreadable volume (CD-ROM type), F: removable
            self.drives = {
                "C:\\": ("系统", 3),    # DRIVE_FIXED
                "E:\\": (None, 5),      # DRIVE_CDROM, GetVolumeInformation fails
                "F:\\": ("", 2),        # DRIVE_REMOVABLE, empty label
            }

        def SetErrorMode(self, mode):
            self.error_mode_calls.append(mode)
            self.error_mode = mode
            return 0
```

Then replace the final assertion line:

```python
    # Critical-error dialogs were suppressed during the calls and restored.
    assert fake.error_mode == expected_flags or fake.error_mode == 0
```

with:

```python
    # The suppress flags were applied at least once and then restored to 0.
    assert expected_flags in fake.error_mode_calls
    assert fake.error_mode_calls[-1] == 0
```

- [ ] **Step 7: Run backend tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_routes_admin_browse_fs.py -v`

Expected: all tests PASS, including `test_browse_fs_windows_drive_labels`
and `test_browse_fs_default_returns_root`.

Then run the full backend suite to check for regressions:

Run: `cd backend && python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/src/myphoto/routes_admin.py backend/tests/test_routes_admin_browse_fs.py
git commit -m "feat(backend): include volume label/type for Windows drives in browse-fs"
```

---

### Task 2: Frontend renders drive label

**Files:**
- Modify: `frontend/src/components/DirectoryChooser.vue` (interface near line 93; row template near line 42-49)
- Test: `frontend/src/tests/directory-chooser.spec.ts`

**Interfaces:**
- Consumes: optional `label?: string` on each `DirEntry` from `/api/admin/browse-fs`.
- Produces: root rows rendered as `C:（系统）`; non-root folders unchanged.

- [ ] **Step 1: Write the failing test**

In `frontend/src/tests/directory-chooser.spec.ts`, add this test after the
existing `shows drive letters at Windows root (path='')` test (around line 120):

```ts
  it("renders the volume label for Windows drive entries", async () => {
    mockFetchQueue([
      {
        body: {
          path: "",
          entries: [
            { name: "C:", path: "C:\\", is_root: true, label: "系统" },
            { name: "D:", path: "D:\\", is_root: true, label: "数据" },
          ],
          truncated: false,
        },
      },
    ])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "" },
    })
    await flushPromises()

    expect(w.text()).toContain("C:")
    expect(w.text()).toContain("（系统）")
    expect(w.text()).toContain("（数据）")
  })
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/directory-chooser.spec.ts`

Expected: FAIL — `renders the volume label for Windows drive entries` cannot
find `（系统）` in the rendered text.

- [ ] **Step 3: Add `label` to the DirEntry interface**

In `frontend/src/components/DirectoryChooser.vue`, extend the interface:

```ts
interface DirEntry {
  name: string
  path: string
  is_root: boolean
  label?: string
}
```

- [ ] **Step 4: Render the label for root entries**

Replace the entry `<li>` button body (currently lines 42-49):

```vue
            <li v-for="e in entries" :key="e.path">
              <button class="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-neutral-800"
                      @dblclick="navigateTo(e.path)"
                      @click="selectEntry(e)"
                      :class="{ 'bg-neutral-800': selected === e.path }">
                <span aria-hidden="true">{{ e.is_root ? "💽" : "📁" }}</span>
                <span class="truncate">{{ e.name }}</span>
              </button>
            </li>
```

with:

```vue
            <li v-for="e in entries" :key="e.path">
              <button class="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-neutral-800"
                      @dblclick="navigateTo(e.path)"
                      @click="selectEntry(e)"
                      :class="{ 'bg-neutral-800': selected === e.path }">
                <span aria-hidden="true">{{ e.is_root ? "💽" : "📁" }}</span>
                <span class="truncate">{{ e.name }}</span>
                <span v-if="e.is_root && e.label"
                      class="truncate text-neutral-500">（{{ e.label }}）</span>
              </button>
            </li>
```

- [ ] **Step 5: Run the frontend test to verify it passes**

Run: `cd frontend && npx vitest run src/tests/directory-chooser.spec.ts`

Expected: all tests in the file PASS, including the new label test. The
existing `WIN_ROOT` fixtures (without `label`) still pass because `label` is
optional.

- [ ] **Step 6: Run the full frontend test suite and type check**

Run: `cd frontend && npx vitest run && npx vue-tsc --noEmit`

(If `vue-tsc` is not the project's typecheck script, run `npm run typecheck`
instead.) Expected: all tests pass, no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/DirectoryChooser.vue frontend/src/tests/directory-chooser.spec.ts
git commit -m "feat(frontend): show volume label for Windows drives in chooser"
```

---

## Verification (manual)

On a Windows machine with the server running:

1. Log in as admin and open the gallery-root directory chooser.
2. At the root, each drive should show as `C:（系统）` (label) or, for an
   unlabeled/empty drive, `E:（CD/DVD 驱动器）` / `F:（可移动磁盘）`.
3. Double-clicking a drive descends into it; single-clicking a drive still
   does not enable Confirm (unchanged behavior).
4. An empty optical drive or disconnected network share should not pop a
   system dialog and should still appear with its type name.
