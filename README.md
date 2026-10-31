# myPhotoGallery

[English](README.md) · [简体中文](README.zh-CN.md)

A self-hosted photo library web viewer for home networks. Point it at folders
of photos on disk and browse them in a fast web UI; your originals stay where
they are.

## Features

- Multiple galleries, each with any number of filesystem roots. Roots are
  scanned read-only — the only file moves are the user-initiated delete into a
  per-root `.trash/` folder and the matching restore back out of it.
- Two roles (admin and viewer) with per-gallery access grants for viewers, and
  a per-account LAN/remote access scope.
- Recycle bin with configurable retention: restore items or let them be purged
  automatically on a daily schedule.
- Grid browsing (justified / masonry layouts) with a lightbox that includes an
  EXIF side panel and an RGB histogram panel.
- Filename and folder-name search, scoped within one gallery root (with folder
  subtree anchoring).
- Batch ZIP download of multiple originals — streamed, zip64-capable, with a
  server-side per-request cap.
- Audit log of admin and security events, with configurable retention and CSV
  export from the admin audit page.
- Light/dark theme that follows the OS setting; 44px touch targets on phones
  and keyboard/screen-reader accessibility support.

## Architecture

The frontend is a Vue 3 + Pinia + vue-router single-page app, built with Vite
into `frontend/dist/`. It can be served either by FastAPI directly (a built-in
`StaticFiles` mount plus SPA fallback) or by the shipped `Caddyfile`, which
also reverse-proxies `/api/*` to the backend.

The backend is FastAPI with SQLAlchemy (async) on a single SQLite database
(`<data_dir>/app.db` — by default `app.db` in the project root; see
[Data & backups](#data--backups)).
Thumbnails at fixed sizes 200 / 400 / 1600 px are generated on demand and
cached on disk under `<data_dir>/.cache/thumbnails/`; the cache is
rebuildable. A background scanner walks the gallery roots, hashing
files and reading EXIF, without touching originals.

## Quick start

Requires Python 3.11+ and [pnpm](https://pnpm.io/).

```bash
python -m venv .venv
source .venv/Scripts/activate        # Git Bash on Windows; PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

cd frontend
pnpm install
pnpm build                           # vue-tsc --noEmit && vite build -> frontend/dist/
cd ..

myphoto add-gallery Home
myphoto add-root Home Main /path/to/photos
myphoto rescan Home
myphoto serve                        # host/port from config.toml (0.0.0.0:8080 by default)
```

Open <http://localhost:8080>. On first startup a random admin password is
generated and printed to stdout once — save it, then change it in the UI.

Other CLI commands:

```bash
myphoto list                                      # galleries, roots, image counts
myphoto rescan-exif [GALLERY] [ROOT_LABEL] [--force]   # backfill EXIF / dimensions
myphoto reset-password [--username admin] [--password NEW]
```

Override examples:

```bash
myphoto serve --host 127.0.0.1 --port 9000
myphoto serve --reload                            # dev auto-restart (watches backend/)
MYPHOTO_CONFIG=/path/to/config.toml myphoto serve
myphoto --config /path/to/config.toml list
```

## Configuration

The canonical config is `config.toml` at the project root. It is created
automatically on first run (with a random `jwt_secret`); the CLI and server
use it regardless of the current working directory, unless `--config` /
`MYPHOTO_CONFIG` points elsewhere. Several runtime values can also be edited
on the admin Settings page.

### Configuration reference

| Section · key | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `[app] listen_host` | `"0.0.0.0"` | IP address | Bind address. Set `127.0.0.1` when a same-host reverse proxy serves the site. |
| `[app] listen_port` | `8080` | integer (valid TCP port) | Bind port. |
| `[app] jwt_secret` | random, generated on first run | string | HMAC secret for session JWTs. Required; changing it invalidates all existing sessions. |
| `[app] session_hours` | `8` | integer hours (admin UI: 1–720) | Session lifetime, applied to new logins. |
| `[app] data_dir` | config file's own directory (the generated template omits this key; set `data_dir = "db"` yourself to keep `app.db`/`.cache/` in a `db/` folder) | directory path | Holds `app.db` and `.cache/`. Relative paths resolve against the directory containing `config.toml`. |
| `[trash] retention_days` | `30` | integer days; `0` = never auto-purge (admin UI offers 7 / 30 / 90 / 0) | How long deleted images remain restorable. |
| `[trash] purge_hour` | `3` | `0`–`23` | Local-time hour of the daily purge. |
| `[trash] purge_minute` | `30` | `0`–`59` | Local-time minute of the daily purge. |
| `[security] trusted_proxies` | `[]` | array of IP / CIDR strings | `X-Forwarded-For` is accepted only from these peers; empty means the header is ignored (spoof-proof). |
| `[security] login_lockout_threshold` | `5` | integer (admin UI: 1–100) | Consecutive failed logins that trigger a temporary lockout. |
| `[security] login_lockout_minutes` | `15` | integer (minutes) | Lockout duration; config-file only (not on the admin settings page). |
| `[scanner] hash_workers` | commented out — source default `min(8, CPU cores)` | positive integer | Worker threads hashing files and reading EXIF during scans; lower it (e.g. `2`) on mechanical or SMB/NFS drives. |
| `[download] batch_limit` | `100` | `10`–`200` (out-of-range values are clamped) | Maximum number of images in one batch ZIP, for all users. |
| `[audit] retention_days` | `180` | `0`, `30`, `90`, `180`, `365` (`0` = keep forever; other integers are clamped to the nearest choice) | Audit log retention; expired rows are purged at startup and on the daily schedule. |

Notes:

- Thumbnail sizes (200 / 400 / 1600 px) are fixed in source code; there is no
  `[thumbnails]` config section.
- A hand-edited invalid value never prevents startup: invalid
  `[download] batch_limit` / `[audit] retention_days` values fall back or are
  clamped with a warning, and an invalid/non-positive
  `[scanner] hash_workers` falls back to the source default.

## Data & backups

Runtime data lives under `[app] data_dir`. The `config.toml` generated on
first run omits this key, so by default it is the project root (the directory
containing `config.toml`); set `data_dir = "db"` in `[app]` yourself to get a
`db/` layout (this project's own development checkout does that):

- `<data_dir>/app.db` — users, galleries, metadata, audit log (back this up).
- `<data_dir>/.cache/thumbnails/` — on-disk thumbnail cache; fully rebuildable.
- `config.toml` — includes `jwt_secret` (back this up).

To back up an installation, copy `<data_dir>/app.db` (default: `app.db` in
the project root) and `config.toml`. Stop the server first (or use
SQLite-safe backup tooling) for a consistent snapshot. Your original photos
live in the gallery roots and are only ever moved between a root and its
`.trash/` directory (delete and restore).

## Upgrading

```bash
git pull
pip install -e ".[dev]"
pnpm --dir frontend build
# restart myphoto serve
```

On startup the backend creates any missing tables and adds missing columns to
existing tables automatically (lightweight `ALTER TABLE ... ADD COLUMN`
migrations). Back up `<data_dir>/app.db` (default: `app.db` in the project
root) before upgrading anyway.

## Development

```bash
# backend with auto-reload (watches backend/ only)
myphoto serve --reload

# frontend dev server (Vite; proxies /api -> http://127.0.0.1:8080)
cd frontend && pnpm dev
```

- Backend tests: run `pytest` from the repo root (suite under
  `backend/tests/`).
- Frontend tests: `cd frontend && pnpm test` (Vitest).
- `pnpm build` runs `vue-tsc --noEmit` before bundling, so it doubles as the
  typecheck gate. `pnpm preview` serves `frontend/dist/` locally on port 4173
  for verifying production builds only — it is not a public-facing server.

## Deployment

See [docs/deployment.md](docs/deployment.md) (in Chinese) for LAN HTTP with
the shipped Caddyfile, public-domain HTTPS with automatic certificates,
process persistence, and firewall notes.

## Design documents

See `docs/superpowers/specs/` for design specs and `docs/superpowers/plans/`
for phase plans.
