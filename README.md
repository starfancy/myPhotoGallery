# myPhotoGallery

Local photo library web viewer.

## Quick start

```bash
# backend
python -m venv .venv
source .venv/Scripts/activate       # Windows Git Bash: source .venv/Scripts/activate
pip install -e ".[dev]"

# frontend
cd frontend && pnpm install && pnpm build && cd ..

# add a gallery + root
myphoto add-gallery Home
myphoto add-root Home Main /path/to/photos
myphoto rescan Home

# run
uvicorn myphoto.main:app --host 0.0.0.0 --port 8080
```

Open <http://localhost:8080>. The initial admin password is printed to
stdout on first startup — save it. Change it via the UI (P6).

## Development

```bash
# backend (auto-reload)
uvicorn myphoto.main:app --reload --host 127.0.0.1 --port 8080

# frontend dev server (proxies /api -> 8080)
cd frontend && pnpm dev
```

See docs/superpowers/specs/ for design, docs/superpowers/plans/ for phase plans.
