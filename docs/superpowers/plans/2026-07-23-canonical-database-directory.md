# Canonical Database Directory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the live SQLite database to `<repo>/db/app.db` and make the backend and CLI use the project-root configuration by default, independent of the current working directory.

**Architecture:** Centralize default configuration resolution in `myphoto.config`, while preserving explicit `build_app(config_path=...)`, `MYPHOTO_CONFIG`, and CLI `--config` overrides. Make `data_dir` an explicit root-config setting resolved relative to the configuration file, then migrate the data-bearing root database and retain backend-local runtime files as backups.

**Tech Stack:** Python 3.11+, pathlib, TOML/tomllib, Click, FastAPI, SQLite, pytest

## Global Constraints

- The data-bearing `<repo>/app.db` is the only database migrated to `<repo>/db/app.db`.
- Do not overwrite an existing `<repo>/db/app.db`; stop and report a conflict instead.
- Stop backend/CLI processes before moving SQLite files.
- Preserve `<repo>/backend/app.db` and `<repo>/backend/config.toml` as `.bak` files; do not delete them.
- Relative `data_dir` values resolve relative to their containing `config.toml`, never the process working directory.
- Missing `data_dir` remains backward-compatible and resolves to the config file directory.
- Explicit `build_app(config_path=...)`, `MYPHOTO_CONFIG`, and CLI `--config` overrides remain supported.
- Existing temporary-config tests must continue storing their database beside the temporary config unless that config explicitly sets `data_dir`.
- No SQLite schema or gallery-image files are changed.

---

## File Structure

**Modify:**

- `backend/src/myphoto/config.py` — define project-root default config path and resolve `data_dir` relative to the config file.
- `backend/src/myphoto/main.py` — let `build_app(None)` use the shared default; retain `MYPHOTO_CONFIG` precedence for module-level startup.
- `backend/src/myphoto/cli.py` — make omitted `--config` use the shared default independently of cwd.
- `backend/tests/test_config.py` — verify relative/absolute/default `data_dir` and cwd-independent default config resolution.
- `backend/tests/test_main.py` — verify explicit temporary config remains isolated and explicit `data_dir` places the database under that directory.
- `backend/tests/test_cli.py` — verify omitted and explicit config resolution through the CLI bootstrap boundary.
- `config.toml` — add `data_dir = "db"` under `[app]`.
- `.gitignore` — ignore canonical runtime data and the two backup files.
- `README.md` — document canonical paths and cwd-independent startup commands.

**Runtime migration (untracked files):**

- Create `db/`.
- Move `app.db` (and valid SQLite sidecars, if any) to `db/`.
- Rename `backend/app.db` to `backend/app.db.bak`.
- Rename `backend/config.toml` to `backend/config.toml.bak`.

---

### Task 1: Configuration Path Contract

**Files:**
- Modify: `backend/src/myphoto/config.py`
- Modify: `backend/tests/test_config.py`

**Interfaces:**
- Produces: `PROJECT_ROOT: Path`
- Produces: `DEFAULT_CONFIG_PATH: Path`
- Produces: `resolve_config_path(path: str | Path | None = None) -> Path`
- Preserves: `load_or_init(path: str | Path) -> AppConfig`

- [ ] **Step 1: Write failing tests for canonical config and data-dir resolution**

Add these tests to `backend/tests/test_config.py`:

```python
import os

from myphoto.config import DEFAULT_CONFIG_PATH, resolve_config_path


def test_relative_data_dir_resolves_from_config_directory(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        'data_dir="db"\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.data_dir == str((tmp_path / "db").resolve())


def test_absolute_data_dir_stays_absolute(tmp_path):
    target = (tmp_path / "external-data").resolve()
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        f'data_dir="{target.as_posix()}"\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.data_dir == str(target)


def test_default_config_path_is_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_config_path() == DEFAULT_CONFIG_PATH
    assert DEFAULT_CONFIG_PATH.name == "config.toml"
    assert DEFAULT_CONFIG_PATH.parent.name == "myPhotoGallery"


def test_explicit_config_path_is_resolved_from_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_config_path("nested/config.toml") == (
        tmp_path / "nested" / "config.toml"
    ).resolve()
```

Keep the existing assertion that missing `data_dir` yields the config directory:

```python
assert cfg.data_dir == str(tmp_path)
```

- [ ] **Step 2: Run the config tests and verify they fail**

Run:

```bash
.venv/Scripts/python.exe -m pytest backend/tests/test_config.py -v
```

Expected: import failure for `DEFAULT_CONFIG_PATH` / `resolve_config_path`, or relative `data_dir` assertion failure.

- [ ] **Step 3: Implement shared default config resolution**

Update `backend/src/myphoto/config.py`:

```python
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"


def resolve_config_path(path: str | Path | None = None) -> Path:
    if path is None:
        return DEFAULT_CONFIG_PATH
    return Path(path).expanduser().resolve()
```

Update `load_or_init` so it resolves the configuration path and interprets `data_dir` relative to it:

```python
def load_or_init(path: str | Path) -> AppConfig:
    p = resolve_config_path(path)
    if not p.exists():
        secret = secrets.token_urlsafe(48)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_DEFAULT_TEMPLATE.format(secret=secret), encoding="utf-8")
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    app = data.get("app", {})
    raw_data_dir = app.get("data_dir")
    if raw_data_dir is None:
        data_dir = p.parent
    else:
        configured = Path(str(raw_data_dir)).expanduser()
        data_dir = configured if configured.is_absolute() else p.parent / configured
        data_dir = data_dir.resolve()
    return AppConfig(
        listen_host=app.get("listen_host", "0.0.0.0"),
        listen_port=int(app.get("listen_port", 8080)),
        jwt_secret=app["jwt_secret"],
        session_hours=int(app.get("session_hours", 8)),
        data_dir=str(data_dir),
    )
```

Do not add `data_dir` to `_DEFAULT_TEMPLATE`; generated test/development configs without the key must remain backward-compatible.

- [ ] **Step 4: Run config tests and verify they pass**

Run:

```bash
.venv/Scripts/python.exe -m pytest backend/tests/test_config.py -v
```

Expected: all config tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/myphoto/config.py backend/tests/test_config.py
git commit -m "fix(config): resolve canonical data directory"
```

---

### Task 2: Backend and CLI Use the Shared Default

**Files:**
- Modify: `backend/src/myphoto/main.py`
- Modify: `backend/src/myphoto/cli.py`
- Modify: `backend/tests/test_main.py`
- Modify: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `DEFAULT_CONFIG_PATH`, `resolve_config_path()` from Task 1
- Produces: `build_app(config_path: str | Path | None = None) -> FastAPI`
- Produces: CLI `--config` option with `default=None`

- [ ] **Step 1: Write failing tests for backend and CLI resolution**

Add to `backend/tests/test_main.py`:

```python
from pathlib import Path


def test_build_app_honors_explicit_relative_data_dir(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        'data_dir="db"\n',
        encoding="utf-8",
    )
    app = build_app(config_path=cfg_path)
    with TestClient(app):
        assert (tmp_path / "db" / "app.db").exists()
        assert app.state.config.data_dir == str((tmp_path / "db").resolve())
```

Add to `backend/tests/test_cli.py`, testing the CLI-to-bootstrap boundary without touching the live database:

```python
from myphoto.config import DEFAULT_CONFIG_PATH


def test_cli_uses_project_config_when_option_omitted(monkeypatch):
    seen = []

    async def fake_bootstrap(config_path):
        seen.append(config_path)
        raise RuntimeError("stop after config capture")

    monkeypatch.setattr("myphoto.cli._bootstrap", fake_bootstrap)
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code != 0
    assert seen == [None]


def test_cli_passes_explicit_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    seen = []

    async def fake_bootstrap(config_path):
        seen.append(config_path)
        raise RuntimeError("stop after config capture")

    monkeypatch.setattr("myphoto.cli._bootstrap", fake_bootstrap)
    result = CliRunner().invoke(cli, ["--config", str(cfg), "list"])
    assert result.exit_code != 0
    assert seen == [str(cfg)]
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:

```bash
.venv/Scripts/python.exe -m pytest backend/tests/test_main.py backend/tests/test_cli.py -v
```

Expected: explicit `data_dir` test fails, and omitted CLI config is currently the string `"config.toml"` rather than `None`.

- [ ] **Step 3: Update backend default resolution**

Modify `backend/src/myphoto/main.py`:

```python
from pathlib import Path

from myphoto.config import AppConfig, load_or_init, resolve_config_path


def build_app(config_path: str | Path | None = None) -> FastAPI:
    cfg = load_or_init(resolve_config_path(config_path))
    db_path = Path(cfg.data_dir) / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ...


app = build_app(os.environ.get("MYPHOTO_CONFIG"))
```

`MYPHOTO_CONFIG` remains the module-level override; when absent, `None` reaches `resolve_config_path()` and selects project-root `config.toml`.

- [ ] **Step 4: Update CLI default resolution**

Modify `backend/src/myphoto/cli.py`:

```python
from myphoto.config import load_or_init, resolve_config_path


async def _bootstrap(config_path: str | None):
    cfg = load_or_init(resolve_config_path(config_path))
    db = Path(cfg.data_dir) / "app.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    ...


@click.group()
@click.option("--config", "config_path", default=None, type=click.Path(path_type=str))
@click.pass_context
def cli(ctx, config_path):
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
```

Do not change commands that already pass `ctx.obj["config_path"]` into `_bootstrap`.

- [ ] **Step 5: Run the targeted tests and verify they pass**

Run:

```bash
.venv/Scripts/python.exe -m pytest backend/tests/test_main.py backend/tests/test_cli.py -v
```

Expected: all targeted tests pass.

- [ ] **Step 6: Run the complete backend suite**

Run:

```bash
.venv/Scripts/python.exe -m pytest backend/tests -q
```

Expected: all existing tests pass; only previously known platform skips/warnings remain.

- [ ] **Step 7: Commit**

```bash
git add backend/src/myphoto/main.py backend/src/myphoto/cli.py backend/tests/test_main.py backend/tests/test_cli.py
git commit -m "fix(runtime): share backend and CLI database config"
```

---

### Task 3: Migrate the Live Runtime Database Safely

**Files:**
- Modify: `config.toml` (ignored runtime file)
- Modify: `.gitignore`
- Move: `app.db` → `db/app.db` (ignored runtime file)
- Move: `backend/app.db` → `backend/app.db.bak` (ignored backup)
- Move: `backend/config.toml` → `backend/config.toml.bak` (ignored backup)

**Interfaces:**
- Consumes: relative `data_dir` resolution from Task 1
- Produces: canonical live database at `<repo>/db/app.db`

- [ ] **Step 1: Stop application processes and inventory SQLite files**

Stop uvicorn, the frontend is optional, and any CLI process. Then run:

```bash
.venv/Scripts/python.exe - <<'PY'
from pathlib import Path
for base in (Path('.'), Path('backend')):
    for name in ('app.db', 'app.db-wal', 'app.db-shm', 'app.db-journal'):
        p = base / name
        print(f'{p}: exists={p.exists()} size={p.stat().st_size if p.exists() else 0}')
PY
```

Expected: process is stopped; inventory shows the root `app.db` and any sidecars. If `db/app.db` already exists, stop and report the conflict.

- [ ] **Step 2: Record pre-migration counts from both databases**

Run:

```bash
.venv/Scripts/python.exe - <<'PY'
import sqlite3
from pathlib import Path
for p in (Path('app.db'), Path('backend/app.db')):
    print(f'=== {p} ===')
    con = sqlite3.connect(f'file:{p.resolve().as_posix()}?mode=ro', uri=True)
    try:
        for table in ('users', 'galleries', 'gallery_roots', 'images', 'audit_log'):
            try:
                count = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            except sqlite3.DatabaseError as exc:
                count = f'ERROR: {exc}'
            print(f'{table}: {count}')
    finally:
        con.close()
PY
```

Expected: root `app.db` has the desired non-zero gallery/root/image counts; backend-local database does not contain the desired live dataset. Save the output for comparison.

- [ ] **Step 3: Update root config and ignore rules**

Add under `[app]` in root `config.toml`:

```toml
data_dir = "db"
```

Update `.gitignore`:

```gitignore
db/
backend/app.db.bak
backend/config.toml.bak
```

Keep existing `app.db`, `config.toml`, and `.cache/` entries for backward compatibility.

- [ ] **Step 4: Create the canonical directory and move runtime data**

Run only after confirming the backend is stopped and `db/app.db` does not exist:

```bash
mkdir -p db
mv app.db db/app.db
for suffix in -wal -shm -journal; do
  if [ -f "app.db${suffix}" ]; then mv "app.db${suffix}" "db/app.db${suffix}"; fi
done
mv backend/app.db backend/app.db.bak
mv backend/config.toml backend/config.toml.bak
```

Expected:

```text
db/app.db exists
app.db does not exist
backend/app.db.bak exists
backend/config.toml.bak exists
backend/app.db does not exist
backend/config.toml does not exist
```

- [ ] **Step 5: Verify post-migration database counts**

Run the same read-only count script against `db/app.db` and compare with the root database counts saved in Step 2.

Expected: every table count matches exactly.

- [ ] **Step 6: Commit tracked config-policy changes**

Because `config.toml` and databases are intentionally ignored, only `.gitignore` is committed in this task:

```bash
git add .gitignore
git commit -m "chore(runtime): ignore canonical database directory"
```

---

### Task 4: Documentation and End-to-End Verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: canonical runtime layout from Tasks 1–3
- Produces: documented startup and override commands

- [ ] **Step 1: Update README commands and runtime layout**

Replace ambiguous cwd-sensitive commands with explicit project-root commands:

```markdown
## Runtime data

The canonical configuration is `config.toml` at the project root. Its
`[app].data_dir = "db"` setting stores runtime data in:

- `db/app.db`
- `db/.cache/thumbnails/`

The backend and CLI use the root configuration by default regardless of the
current working directory.

## Quick start

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -e ".[dev]"

myphoto add-gallery Home
myphoto add-root Home Main /path/to/photos
myphoto rescan Home

python -m uvicorn myphoto.main:app --app-dir backend --host 0.0.0.0 --port 8080
```

Override examples:

```bash
MYPHOTO_CONFIG=/path/to/config.toml python -m uvicorn myphoto.main:app --app-dir backend
myphoto --config /path/to/config.toml list
```
```

Also document frontend development separately:

```bash
cd frontend
npx vite
```

- [ ] **Step 2: Verify CLI from repository root**

Run:

```bash
.venv/Scripts/python.exe -m myphoto.cli list
```

Expected: displays the migrated galleries, roots, and image counts from `db/app.db`.

- [ ] **Step 3: Verify CLI from backend directory**

Run:

```bash
cd backend
../.venv/Scripts/python.exe -m myphoto.cli list
```

Expected: identical galleries, roots, and image counts. Return to repository root afterwards.

- [ ] **Step 4: Verify backend from repository root**

Start:

```bash
.venv/Scripts/python.exe -m uvicorn myphoto.main:app --app-dir backend --host 127.0.0.1 --port 8080
```

After logging in, verify:

```text
GET /api/admin/status returns non-zero counts matching db/app.db
GET /api/galleries returns the migrated gallery list
```

Stop the backend.

- [ ] **Step 5: Verify backend from backend directory**

Start:

```bash
cd backend
../.venv/Scripts/python.exe -m uvicorn myphoto.main:app --host 127.0.0.1 --port 8080
```

Expected: same database and API counts as Step 4. Stop the backend and return to repository root.

- [ ] **Step 6: Run full regression suites**

Run:

```bash
.venv/Scripts/python.exe -m pytest backend/tests -q
cd frontend && npx vitest run && npx vue-tsc --noEmit
```

Expected: all backend and frontend tests pass with only previously documented skips/warnings.

- [ ] **Step 7: Commit documentation**

```bash
git add README.md
git commit -m "docs: document canonical database startup"
```

- [ ] **Step 8: Record migration result in progress ledger**

Update ignored `.superpowers/sdd/progress.md` with:

```text
Canonical DB migration: complete
  Design: docs/superpowers/specs/2026-07-23-canonical-database-directory-design.md
  Plan: docs/superpowers/plans/2026-07-23-canonical-database-directory.md
  Live DB: db/app.db
  Backups: backend/app.db.bak, backend/config.toml.bak
  Verification: root/backend cwd CLI + backend API counts match
```

No commit is required because `.superpowers/` is ignored.

---

## Final Verification Checklist

- [ ] `db/app.db` exists and its counts match the original root `app.db` snapshot.
- [ ] Root `app.db` no longer exists.
- [ ] `backend/app.db.bak` and `backend/config.toml.bak` exist.
- [ ] Root `config.toml` contains `data_dir = "db"`.
- [ ] Backend default resolution is independent of cwd.
- [ ] CLI default resolution is independent of cwd.
- [ ] Explicit config overrides still work.
- [ ] `/api/admin/status` and `/api/galleries` expose the migrated data.
- [ ] Full backend and frontend suites pass.
- [ ] README documents canonical runtime paths and commands.
