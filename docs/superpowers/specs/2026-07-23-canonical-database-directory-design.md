# Canonical Database Directory Design

- Date: 2026-07-23
- Status: Approved for planning

## Problem

The application currently derives `AppConfig.data_dir` from the directory containing whichever `config.toml` was loaded. Both the backend entry point and CLI default to the relative path `config.toml`, so their database selection depends on the process working directory.

The repository currently contains two independent runtime sets:

- `<repo>/config.toml` + `<repo>/app.db` — this database contains the user's galleries, roots, and indexed images.
- `<repo>/backend/config.toml` + `<repo>/backend/app.db` — this is an accidental second database with no desired live data.

Running the CLI from the repository root and the backend from `backend/` therefore writes and reads different databases while both commands appear successful.

## Goal

Use one canonical live database at `<repo>/db/app.db` for both the backend and CLI, regardless of their current working directory, while retaining explicit configuration overrides for tests and alternative deployments.

## Canonical Runtime Layout

```text
<repo>/
├─ config.toml
├─ db/
│  ├─ app.db
│  └─ .cache/
│     └─ thumbnails/
├─ backend/
│  ├─ app.db.bak
│  └─ config.toml.bak
└─ ...
```

The existing data-bearing `<repo>/app.db` is moved, not recreated, to `<repo>/db/app.db`.

The accidental backend-local database and configuration are preserved as backups rather than deleted:

- `<repo>/backend/app.db` → `<repo>/backend/app.db.bak`
- `<repo>/backend/config.toml` → `<repo>/backend/config.toml.bak`

## Configuration Contract

The root `config.toml` gains an explicit application setting:

```toml
[app]
data_dir = "db"
```

Rules:

1. A relative `data_dir` is resolved relative to the containing `config.toml`, never relative to the current working directory.
2. An absolute `data_dir` is used as written after normalization.
3. If `data_dir` is absent, it defaults to the containing configuration directory. This preserves existing temporary-test behavior and backward compatibility.
4. `AppConfig.data_dir` stores the resolved absolute path.
5. `app.db` and `.cache/thumbnails/` remain children of `AppConfig.data_dir`.

## Default Configuration Resolution

A shared project-default configuration path is defined from source location rather than process working directory:

```text
backend/src/myphoto/config.py
          ↑ parents to repository root
          → <repo>/config.toml
```

Resolution precedence:

### Backend

1. `MYPHOTO_CONFIG`, if set.
2. Project-root `config.toml` derived from source location.

### CLI

1. Explicit `--config PATH`, if supplied.
2. Project-root `config.toml` derived from source location.

The CLI option must use `default=None`; the bootstrap layer resolves `None` to the shared project default. This distinguishes an omitted option from an explicitly supplied path.

### Programmatic/Test Use

`build_app(config_path=...)` continues accepting an explicit path. Existing tests that create a temporary config keep their database in the temporary config directory unless they explicitly add `data_dir`.

## Migration Safety

The migration must occur while the backend and CLI are stopped so no SQLite connection is active.

Before moving the live database:

1. Inspect the repository-root database and confirm non-zero gallery/root/image counts.
2. Inspect the backend-local database and confirm it is not the desired live database.
3. Check for SQLite sidecar files (`app.db-wal`, `app.db-shm`, `app.db-journal`) in both locations.
4. If sidecars exist, stop all processes and checkpoint/close SQLite before moving the database as a unit.
5. Create `<repo>/db/`.
6. Move `<repo>/app.db` and any valid sidecars to `<repo>/db/`.
7. Rename backend-local runtime files to `.bak`.
8. Update root `config.toml` with `data_dir = "db"`.

The migration must not overwrite an existing `<repo>/db/app.db`. If one exists, stop and surface the conflict.

## Verification

### Automated Tests

Add tests proving:

1. `data_dir = "db"` resolves relative to the config file directory.
2. Absolute `data_dir` remains absolute.
3. Missing `data_dir` preserves the config-directory default.
4. Backend default configuration resolves to project-root `config.toml` independent of current working directory.
5. CLI omitted `--config` resolves to the same project-root configuration.
6. Explicit `--config` and `MYPHOTO_CONFIG` overrides still work.

Run the complete backend test suite after changes.

### Live Verification

1. Start the backend from the repository root without setting `MYPHOTO_CONFIG`.
2. Start it from `backend/` without setting `MYPHOTO_CONFIG`.
3. In both cases, verify the effective database is `<repo>/db/app.db`.
4. Run CLI `list` from both directories and verify identical galleries, roots, and image counts.
5. Query `/api/admin/status` and `/api/galleries` and verify they match the CLI/database counts.
6. Reload the frontend admin page and verify non-zero statistics.
7. Because the canonical `jwt_secret` comes from the root config, log in again if an old cookie was signed by the backend-local configuration.

## Documentation

Update README development commands to use the project virtual environment and clarify that both backend and CLI use root `config.toml` by default. Document override examples for `MYPHOTO_CONFIG` and `--config`.

## Non-Goals

- Migrating to another database engine.
- Supporting multiple simultaneously active application databases.
- Deleting the backend-local accidental database immediately.
- Changing SQLite schema or gallery data.
- Moving gallery image files.

## Rollback

If verification fails:

1. Stop the backend and CLI.
2. Move `<repo>/db/app.db` back to `<repo>/app.db`.
3. Remove `data_dir = "db"` from root `config.toml`.
4. Revert code changes.
5. Keep `.bak` files untouched for diagnosis.
