# Windows drive volume labels in directory chooser

Date: 2026-08-02

## Problem

When an admin adds a gallery root folder, the directory chooser
([DirectoryChooser.vue](../../../frontend/src/components/DirectoryChooser.vue))
shows the Windows drive list at the virtual root as bare letters (`C:`, `D:`).
On machines with multiple partitions the user cannot tell which drive is which
because the volume label (e.g. "系统", "数据") is not shown.

## Goal

Show each Windows drive as `C:（卷标）` in the chooser. When the drive has no
label or the label cannot be read (empty optical drive, disconnected network
share, unlabeled volume), fall back to the drive type, e.g. `E:（CD/DVD 驱动器）`.

The display format is `盘符` first, then the label/type in full-width parens
with muted color.

## Non-goals

- Free/total disk space.
- Per-drive-type icons.
- Showing the label anywhere outside the directory chooser.
- Any change to POSIX behavior.

## Backend

All changes are in
[backend/src/myphoto/routes_admin.py](../../../backend/src/myphoto/routes_admin.py).

### `_drive_volume_label(drive: str) -> str | None` (new, Windows-only)

`drive` is a root path such as `C:\\`.

- Wrap `ctypes.windll.kernel32.GetVolumeInformationW` with the process error
  mode set to `SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX` for the
  duration of the call, restoring the previous mode in `finally`. This
  prevents an empty CD/DVD drive or dead network mount from popping a system
  modal dialog.
- Pass a `create_unicode_buffer(256)` for the label buffer (volume labels are
  at most 32 characters; 256 is safely above `MAX_PATH` conventions). A
  nonzero return indicates success; read the buffer value, stripping
  whitespace. An empty label string is treated as no label.
- A zero return or any `OSError`/`AttributeError` yields `None`.

### `_drive_type_name(drive: str) -> str` (new, Windows-only)

Calls `GetDriveTypeW(drive)` and maps the result:

| Constant            | Display            |
|---------------------|--------------------|
| `DRIVE_REMOVABLE`   | 可移动磁盘         |
| `DRIVE_FIXED`       | 本地磁盘           |
| `DRIVE_REMOTE`      | 网络驱动器         |
| `DRIVE_CDROM`       | CD/DVD 驱动器      |
| `DRIVE_RAMDISK`     | RAM 磁盘           |
| anything else       | 驱动器             |

All `ctypes` failures fall through to `驱动器`.

### `_list_drive_letters()` change

For each bit set in the `GetLogicalDrives()` bitmask, build `drive = "X:\\"`,
then:

```python
label = _drive_volume_label(drive) or _drive_type_name(drive)
out.append({"name": f"{letter}:", "path": drive, "is_root": True, "label": label})
```

`label` is always a non-empty string in the response (the type fallback
guarantees it). The function is now potentially blocking (a disconnected
network mount can make `GetVolumeInformationW` hang), so the call site in
`admin_browse_fs` changes from:

```python
entries = _list_drive_letters()
```

to:

```python
entries = await asyncio.to_thread(_list_drive_letters)
```

One drive failing must not drop the others; each per-drive helper call is
independently guarded so the list always contains every logical drive.

`asyncio` is already available to the module (FastAPI runs on asyncio);
`import asyncio` is added at the top if not present. The local
`import ctypes` currently inside `_list_drive_letters` is promoted to a
module-level import so the `windll` access can be substituted in tests
(`ctypes.windll` only exists on Windows, but importing the `ctypes` module
itself is safe everywhere and access remains guarded by try/except).

POSIX behavior is unchanged: the root lists real subdirectories and entries
carry no `label` field.

## Frontend

Changes in
[frontend/src/components/DirectoryChooser.vue](../../../frontend/src/components/DirectoryChooser.vue).

### `DirEntry` interface

Add an optional field:

```ts
interface DirEntry {
  name: string
  path: string
  is_root: boolean
  label?: string
}
```

### Row rendering

The entry list currently renders `e.name` only. For root entries that include a
`label`, append the label in full-width parens with muted color:

```vue
<span aria-hidden="true">{{ e.is_root ? "💽" : "📁" }}</span>
<span class="truncate">{{ e.name }}</span>
<span v-if="e.is_root && e.label"
      class="truncate pl-1 text-neutral-500">（{{ e.label }}）</span>
```

`e.name` stays `C:`, so breadcrumb reconstruction, selection, and
double-click navigation are unaffected. The `truncate` class on both text
spans keeps long labels from breaking the row. Non-root folders render
exactly as before.

## Testing

### Backend (`backend/tests/test_routes_admin_browse_fs.py`)

- Extend `test_browse_fs_default_returns_root`: on Windows, assert every
  entry has a truthy `label` string.
- Add a cross-platform test that monkeypatches `routes_admin.ctypes` with a
  fake object exposing `windll.kernel32.GetLogicalDrives`,
  `GetVolumeInformationW`, `GetDriveTypeW`, and `SetErrorMode`, and forces
  `sys.platform` to `"win32"` for the call. It covers:
  - a drive whose `GetVolumeInformationW` returns a label → response
    `label` is that label;
  - a drive whose `GetVolumeInformationW` fails (returns 0) → response
    `label` is the mapped type name (e.g. `GetDriveTypeW` → `DRIVE_FIXED`
    → "本地磁盘");
  - `SetErrorMode` is invoked with
    `SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX` and the previous mode
    is restored.
  This avoids invoking real Win32 in CI and runs on all platforms.
- The existing non-Windows assertions remain (POSIX entries have no label
  requirement).

### Frontend (`frontend/src/tests/directory-chooser.spec.ts`)

- Add a root entry with `label: "系统"` to a fixture and assert the rendered
  dialog text contains `（系统）`.
- Existing `WIN_ROOT` fixtures remain valid because `label` is optional; they
  continue to assert bare `C:`/`D:` rendering.
