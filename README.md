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
- Style-filter preview: a lightbox button opens a dedicated page that applies
  WebGL 2 3D-LUT film emulation (Fujifilm Classic Chrome / Velvia / Acros, etc.)
  to the current photo, with strength slider, hold-to-compare-original,
  collapsible thumbnail strip grouped by filter family, and one-click JPEG
  export at either 1600-px preview size or full original resolution. LUT files
  live in `<data_dir>/luts/<group>/`; admins enable/disable, rename, and reorder
  them on a `/admin/luts` page with per-group select-all.
- Batch ZIP download of multiple originals — streamed, zip64-capable, with a
  server-side per-request cap.
- Audit log of admin and security events, with configurable retention and CSV
  export from the admin audit page.
- Smart tagging with fully local models (no external service calls): CLIP
  zero-shot scene classification on a two-level prompt hierarchy (9 major /
  43 minor categories, each with a confidence score), YOLO11n person
  counting, and InsightFace face detection with embedding-based automatic
  clustering. Includes a People page (`/people`) with renameable person
  clusters, scene faceted filters in the grid (URL-persisted, applied to
  both images and subfolders), scene/date filters in search, and a
  tag-distribution panel on the admin overview. Tagging is optional —
  without model files the server runs exactly as before.
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
| `[tagging] enabled` | `true` | boolean | Master switch for smart tagging; when false neither the background scanner nor the `myphoto tag` CLI loads any model. |
| `[tagging] scan_on_import` | `true` | boolean | The server's background scanner synchronously tags newly added/changed photos; unchanged files never reach the models. No effect when `enabled = false` or model files are absent. |
| `[tagging] models_dir` | `"backend/models"` | directory path | Directory holding the tagger models; relative paths resolve against the directory containing `config.toml`. See [Smart tagging](#smart-tagging-optional). |
| `[tagging] device` | `"auto"` | `auto` / `cpu` / `cuda` | Inference backend selection. `auto` uses ONNX Runtime CUDA when `onnxruntime-gpu` is installed, otherwise the OpenVINO plan; an explicit `cuda` that is unavailable disables tagging with a clear error instead of silently falling back. |

Notes:

- Thumbnail sizes (200 / 400 / 1600 px) are fixed in source code; there is no
  `[thumbnails]` config section.
- A hand-edited invalid value never prevents startup: invalid
  `[download] batch_limit` / `[audit] retention_days` values fall back or are
  clamped with a warning, and an invalid/non-positive
  `[scanner] hash_workers` falls back to the source default.
- The whole `[tagging]` section is commented out in the generated template;
  the defaults in the table above apply until you override them.

## Smart tagging (optional)

Smart tagging analyzes photos entirely on the host with three local models —
nothing leaves the machine:

- **Scene tags** — CLIP ViT-B/32 zero-shot classification against a built-in
  two-level prompt hierarchy: 9 major categories (nature, plants, city,
  people, interiors, food, animals, vehicles, documents) and 43 minor
  categories, stored with a confidence score.
- **Person count** — YOLO11n detects the people in each photo.
- **Face clustering** — SCRFD detects faces and an ArcFace model
  (`w600k_mbf`) produces 512-d embeddings; a greedy cosine-similarity pass
  clusters the same person across photos. Clusters get stable IDs
  (`P001`, …), can be renamed on the People page, and are not merged
  automatically.

The results surface across the UI:

- **People page** (`/people`, top-nav entry): cluster list with face
  thumbnails; each cluster's photos are grouped by year/month and labeled
  with their gallery and folder.
- **Scene filter** in the browse toolbar: major/minor dropdowns computed from
  the current folder's statistics. The selection lives in the URL query
  (`?scene_major=…&scene_minor=…`) and filters both images and subfolders
  (folder cards show a matching-photo count).
- **Search** accepts the same scene filters plus a date range; the keyword
  becomes optional, so scene/date-only filtering is possible.
- **Admin overview** shows a tag-distribution panel with per-category counts.

### When tagging runs

Tagging and thumbnail generation share one decoder: regular images
(JPEG/PNG/HEIC, …) go through Pillow with EXIF orientation correction,
while RAW files (`.orf`, `.cr2`, `.nef`, `.arw`, …) go through rawpy —
the camera's embedded JPEG preview is used when present, with a full
demosaic fallback. Models always receive the oriented, full-resolution
RGB image and downsample internally.

- **On import** — when `enabled` and `scan_on_import` are on and the models
  are in place, the server's background scanner tags each newly added or
  changed photo synchronously in the same pass (unchanged files never reach
  the models). A per-photo failure is recorded as `tag_error` and never
  blocks the scan. Note that the standalone `myphoto rescan` CLI command
  does not run models — use `myphoto tag run` for command-line tagging.
- **Batch backfill** — tag an existing library (or retry failures) with the
  CLI below. Runs are resumable: already-tagged and unchanged photos are
  skipped; `--force` re-tags everything in the selected scope.

```bash
myphoto tag status                                              # per-gallery tagged/pending/failed + "models ready"
myphoto tag run [--gallery G] [--folder SUBPATH] [--force] [--retry-failed]  # tag pending photos, then auto-cluster;
#   --retry-failed retries only past failures (tag_error set), mutually exclusive with --force
myphoto tag cluster                                             # incremental re-cluster of unassigned faces
myphoto tag relabel                                             # re-derive scene tags from stored embeddings (no vision model runs)
myphoto tag gc [--include-named]                                # delete orphaned person clusters
```

### Model deployment requirements

The inference backend is selected by `[tagging] device`, which accepts three
values — `auto` (default, auto-detect), `cpu`, and `cuda` — mapping to two
loading plans, each for a different scenario:

- **OpenVINO plan — the default when no NVIDIA GPU is present.** It is used
  when `auto` finds no CUDA or when `device = "cpu"` is set explicitly: the
  CLIP visual tower and YOLO run on OpenVINO, which itself probes for an
  Intel integrated GPU (GPU when available, CPU otherwise; validated on an
  Intel i5-11320H with Iris Xe), while the two face models run on ONNX
  Runtime CPU. CPU-only works, just more slowly. Reference throughput on
  that hardware: about 350 ms per photo including decode and disk IO — a
  2,923-photo library tagged in 17 minutes with zero failures (576 faces →
  269 clusters), i.e. roughly an hour per 10k photos.
- **CUDA plan — the accelerated option for NVIDIA GPUs.** Once
  `onnxruntime-gpu` is installed and a CUDA environment is in place, `auto`
  selects this plan when it detects `CUDAExecutionProvider`, or set
  `device = "cuda"` explicitly. The four hot-path models — the CLIP visual
  tower, YOLO, and the two face models — all run through
  `CUDAExecutionProvider` (with CPU fallback). The CLIP text tower is
  deliberately kept on OpenVINO CPU: scene matching uses a fixed list of 85
  prompts, so the text tower runs once as a batch at model load time and its
  embedding matrix is cached; per-photo classification is then just a matrix
  multiply of the visual embedding against that matrix, never calling the
  text tower again. Since it runs only once per process, moving it to CUDA
  would not improve per-photo throughput at all, while costing an extra CUDA
  session and another model file to maintain. If `cuda` is requested but
  unavailable, startup logs explain how to fix the environment; tagging
  stays disabled while the server itself starts normally. The mutually
  exclusive ORT package swap, CUDA/cuDNN prerequisites, and verification
  steps are documented in [docs/deployment.md](docs/deployment.md).

Model requirements per plan. The weights themselves are **not tracked by
git**. Place them under `[tagging] models_dir` (default `backend/models/`,
resolved relative to `config.toml`). Before enabling tagging, the tagger
checks every path required by the selected plan and logs any missing one:

- **Shared by both plans (~730 MB):**
  - `clip-ov/text.xml` + `text.bin` — CLIP text tower, OpenVINO IR, ~121 MB
  - `clip-vit-base-patch32/` — HF tokenizer/processor configs (includes the
    `pytorch_model.bin` shipped with the snapshot; not loaded at runtime), ~580 MB
  - `yolo11n.onnx` — YOLO11n (COCO person class), ~10 MB
  - `insightface/det_500m.onnx` — SCRFD 500m face detector, ~2.5 MB
  - `insightface/w600k_mbf.onnx` — ArcFace recognition model, ~13 MB
- **Additionally required by the OpenVINO plan:** `clip-ov/visual.xml` +
  `visual.bin` (CLIP visual tower, OpenVINO IR, ~168 MB) — about **900 MB**
  in total.
- **Additionally required by the CUDA plan:** `clip-onnx/visual.onnx`
  (CLIP visual tower ONNX, ~350 MB, exported via
  [scripts/export_clip_onnx.py](scripts/export_clip_onnx.py)) — about
  **1.1 GB** in total.

The full layout looks like this (the tagger checks exactly these paths):

```text
backend/models/
├── clip-ov/
│   ├── visual.xml + visual.bin     # CLIP visual tower, OpenVINO IR (~168 MB; OpenVINO plan)
│   └── text.xml + text.bin         # CLIP text tower, OpenVINO IR (~121 MB; both plans)
├── clip-onnx/
│   └── visual.onnx                 # CLIP visual tower ONNX (~350 MB; CUDA plan only, via scripts/export_clip_onnx.py)
├── clip-vit-base-patch32/          # HF tokenizer/processor configs + pytorch_model.bin (~580 MB)
├── yolo11n.onnx                    # YOLO11n (COCO person class), ONNX (~10 MB)
└── insightface/
    ├── det_500m.onnx               # SCRFD 500m face detector (~2.5 MB)
    └── w600k_mbf.onnx              # ArcFace w600k recognition model (~13 MB)
```

Provenance: YOLO11n exported from Ultralytics;
`openai/clip-vit-base-patch32` converted to OpenVINO IR; the two InsightFace
files come from the official InsightFace model zoo (same source as the
`buffalo_l` pack). Their licenses differ — see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Notes:

- The Python dependencies install with the normal
  `pip install -e ".[dev]"` (NumPy, OpenVINO, onnxruntime, InsightFace,
  OpenCV, Transformers). **`openvino` is pinned to 2024.6.0** — newer
  2026.x releases break its API — and do not install `optimum`, which pulls
  in an incompatible OpenVINO.
- PyTorch is intentionally **not** a dependency: inference runs on
  OpenVINO/onnxruntime and Transformers is used only for `CLIPProcessor`
  (PIL/numpy preprocessing). On a torch-free host Transformers prints an
  advisory `PyTorch was not found …` warning at import — it is harmless, the
  tagger suppresses it automatically, and installing torch (a multi-GB CUDA
  wheel) just to silence it is unnecessary.
- Models **load lazily** on first use and stay resident; starting the web
  server never loads them.
- If the model files are missing, the server still starts normally: scan-time
  tagging switches off with a log line and every other feature works. After
  copying the files into place, run `myphoto tag status` to verify — it
  prints `models ready: yes` on its first line once every file required by
  the selected plan is in place.
- To disable tagging entirely (e.g. on a low-resource host), set
  `enabled = false` in the `[tagging]` section of `config.toml`. The expanded
  deployment walkthrough (mirror setup, package mirror tips, CUDA setup)
  lives in [docs/deployment.md](docs/deployment.md) (in Chinese).

### Privacy

Face embeddings are biometric data. They are stored inside
`<data_dir>/app.db` — never upload that database to a public location, and
remember its backups contain face vectors. All inference is local; the
software makes no network calls to any AI service.

## Data & backups

Runtime data lives under `[app] data_dir`. The `config.toml` generated on
first run omits this key, so by default it is the project root (the directory
containing `config.toml`); set `data_dir = "db"` in `[app]` yourself to get a
`db/` layout (this project's own development checkout does that):

- `<data_dir>/app.db` — users, galleries, metadata, audit log, LUT enable/label/sort metadata, smart tags plus image/face embeddings and person clusters (face embeddings are biometric data — keep backups private; back this up).
- `<data_dir>/.cache/thumbnails/` — on-disk thumbnail cache; fully rebuildable.
- `<data_dir>/luts/<group>/*.cube` — optional filter LUT files; metadata (enabled, label, sort_order) lives in `app.db`, add new `.cube` files here and use the admin "rescan" button.
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

Tagging preprocessing optimization (2026-11): CLIP inputs are now
pre-downscaled in code, and large JPEGs decode at DCT half resolution
(shortest-edge floor 1600px); model weights and the tag taxonomy are
unchanged. New photos automatically use the new pipeline. If you want every
stored image embedding to be byte-comparable with the new geometry, back up
first and run `myphoto tag run --force` once (skipping it is harmless —
`relabel` still works on the existing embeddings).

## Development

```bash
# backend with auto-reload (watches backend/ only)
myphoto serve --reload

# frontend dev server (Vite; proxies /api -> http://127.0.0.1:8080)
cd frontend && pnpm dev
```

- Backend tests: run `pytest` from the repo root (suite under
  `backend/tests/`); on multi-core machines pass `-n auto` to parallelize
  (pytest-xdist, ~40s vs ~135s serial for the full suite). Default stays
  serial to keep single-test debugging simple.
- Frontend tests: `cd frontend && pnpm test` (Vitest).
- `pnpm build` runs `vue-tsc --noEmit` before bundling, so it doubles as the
  typecheck gate. `pnpm preview` serves `frontend/dist/` locally on port 4173
  for verifying production builds only — it is not a public-facing server.

## Deployment

See [docs/deployment.md](docs/deployment.md) (in Chinese) for LAN HTTP with
the shipped Caddyfile, public-domain HTTPS with automatic certificates,
process persistence, firewall notes, and placing the smart-tag model files.

## License

This project's own code is released under the MIT License — see
[LICENSE](LICENSE). The smart-tag model weights are not tracked in git and
ship under their own, more restrictive licenses: notably **AGPL-3.0** for
YOLO11n and a **non-commercial research-only** term for the InsightFace
pretrained models (CLIP itself is MIT). Before redistributing the app or
using it commercially, read [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
(in Chinese) for the full component and model license list.

## Design documents

See `docs/superpowers/specs/` for design specs and `docs/superpowers/plans/`
for phase plans. The smart-tag subsystem (data model, tagging pipeline,
clustering) is documented in `docs/tags-upgrade-design.md` (in Chinese).
