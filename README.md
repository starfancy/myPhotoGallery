# myPhotoGallery

Local photo library web viewer.

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

cd frontend && pnpm install && pnpm build && cd ..

myphoto add-gallery Home
myphoto add-root Home Main /path/to/photos
myphoto rescan Home
# run
python -m uvicorn myphoto.main:app --app-dir backend --host 0.0.0.0 --port 8080
```

Open <http://localhost:8080>. The initial admin password is printed to
stdout on first startup — save it. Change it via the UI.

Override examples:

```bash
MYPHOTO_CONFIG=/path/to/config.toml python -m uvicorn myphoto.main:app --app-dir backend
myphoto --config /path/to/config.toml list
```

## Development

```bash
# backend (auto-reload)
python -m uvicorn myphoto.main:app --app-dir backend --reload --host 127.0.0.1 --port 8080

# frontend dev server (proxies /api -> 8080)
cd frontend && npx vite
```

See docs/superpowers/specs/ for design, docs/superpowers/plans/ for phase plans.
