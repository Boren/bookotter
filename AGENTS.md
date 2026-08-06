# AGENTS.md

## Quick Reference

- **Stack**: Python 3.14 (FastAPI + SQLAlchemy) backend, Vue 3 + TypeScript + Tailwind 4 frontend
- **Package managers**: `uv` (Python), `pnpm` (frontend)
- **Port**: 6887 (backend API + static frontend in prod)

## Commands

### Backend (from repo root)

```bash
ruff check .              # Lint
ruff format --check .     # Format check
ruff format .             # Auto-format
ruff check --fix .        # Auto-fix lint issues
```

### Frontend (from `frontend/`)

```bash
pnpm install --frozen-lockfile   # Install deps
pnpm lint                        # Biome lint (TS/JSON only, not .vue)
pnpm lint:fix                    # Biome auto-fix
pnpm build:check                 # vue-tsc type-check + vite build (CI uses this)
pnpm dev                         # Dev server (proxies /api → localhost:6887)
```

### Running locally

```bash
# Backend (needs config.yaml — copy from config.yaml.example first)
uvicorn backend.main:app --host 0.0.0.0 --port 6887 --reload

# CLI
python -m backend.cli --dry-run
```

### Tests

```bash
pytest tests/                # Run all tests
pytest tests/ -v             # Verbose output
pytest tests/ --cov          # With coverage
```

### CI checks (must pass before merge)

1. `ruff check .` + `ruff format --check .`
2. `pytest tests/`
3. `pnpm lint` + `pnpm test` + `pnpm build:check` (in `frontend/`)

## Architecture

```
backend/
  main.py              → FastAPI app, serves static frontend from ../static/
  cli.py               → Rich CLI, wraps PipelineService
  config.py            → YAML config loader (single source of truth for all config)
  database.py          → SQLAlchemy/SQLite (sync history only, NOT config)
  clients/
    hardcover_client.py    → Hardcover GraphQL API
    prowlarr_client.py     → Prowlarr REST API
    qbittorrent_client.py  → qBittorrent Web API
    kindle_client.py       → Kindle SSH/SFTP
  services/
    pipeline_service.py      → Pipeline orchestrator
    pipeline_states.py       → Book state machine
    hardcover_sync_service.py → Hardcover sync
    search_service.py        → Prowlarr search
    download_service.py      → qBittorrent download management
    import_service.py        → EPUB import with metadata
    epub_service.py          → EPUB metadata read/write
    scheduler_service.py     → Background jobs (RSS sync, automatic Kindle sync)
    websocket_manager.py     → WebSocket event broadcasting
  api/routes/          → FastAPI route modules
frontend/
  src/views/           → Vue page components
  src/stores/          → Pinia stores
```

- **Config lives in `config.yaml`**, not the database. Kindles, sync toggles, all settings — YAML.
- **Database** (SQLite) stores only sync run history and per-book results.
- `DATA_DIR` is controlled by `BOOKOTTER_DATA_DIR` env var (default: `./data/`). Config path resolution: env var → `data/config.yaml` → `./config.yaml`.
- `config.yaml` is **gitignored** (contains API keys, SSH creds). Use `config.yaml.example` as template.

## Style

- **Backend**: Ruff — 120 char lines, double quotes, spaces. isort with `known-first-party = ["backend"]`.
- **Frontend**: Biome — 100 char lines, single quotes, trailing commas (ES5). Only lints `*.ts` and `*.json` (`.vue` files excluded in biome config).
- **Commits**: Conventional commits (`feat:`, `fix:`, `docs:`, etc.) — git-cliff generates changelogs from them.

## Gotchas

- **Python version mismatch**: `pyproject.toml` says `requires-python >= 3.14`, `ruff.toml` targets `py311`, CI uses Python 3.11. Docker image uses 3.14. Locally, 3.14 is expected.
- **Frontend build output**: Vite builds to `frontend/dist/`, Docker copies it to `static/`. The `backend/static/` dir is gitignored.
- **Biome scope**: `files.includes` only covers `*.ts` and `*.json` — Vue SFC files are NOT linted by Biome.
- **Frontend path alias**: `@/*` maps to `frontend/src/*` (tsconfig paths).

## Branching & Releases

`feature` → `dev` → PR → `main` → `git tag v1.x.x` → GitHub Release

**All changes land via PR with auto-merge — never push directly to `dev` or `main`** (a repo ruleset blocks direct pushes and requires the `Backend Lint` and `Frontend Check` CI checks). Standard flow:

```bash
git checkout -b feat/my-change dev
# ...commit...
git push -u origin feat/my-change
gh pr create --base dev --fill
gh pr merge --auto --squash
```

Squash is the only allowed merge method; branches are auto-deleted after merge.

Docker images auto-built: `dev` branch → `:dev` tag, `main` → `:main`, version tags → `:latest` + semver tags.
