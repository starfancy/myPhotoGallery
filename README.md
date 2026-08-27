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
# run (host/port come from config.toml: 0.0.0.0:8080 by default)
myphoto serve
```

Open <http://localhost:8080>. The initial admin password is printed to
stdout on first startup — save it. Change it via the UI.

Override examples:

```bash
myphoto serve --host 127.0.0.1 --port 9000
MYPHOTO_CONFIG=/path/to/config.toml myphoto serve   # or: myphoto --config /path/to/config.toml serve
myphoto --config /path/to/config.toml list
```

## Development

```bash
# backend (auto-reload; watches backend/ only)
myphoto serve --reload

# frontend dev server (proxies /api -> 8080)
cd frontend && npx vite
```

## Production frontend

Build the frontend and serve the production bundle locally with Vite's
preview server:

```bash
cd frontend
pnpm build          # vue-tsc --noEmit && vite build -> frontend/dist/
pnpm preview        # serves frontend/dist at http://localhost:4173
```

`pnpm preview` is intended for local verification of the production build, not
as a public-facing server. For real deployments, host `frontend/dist/` behind
Nginx/Caddy and reverse-proxy `/api` to the backend.

See docs/superpowers/specs/ for design, docs/superpowers/plans/ for phase plans.
