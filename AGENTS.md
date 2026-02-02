# Repository Guidelines

## Project Structure & Module Organization
- `backend/` FastAPI service, with API routers in `backend/api/`, data models in `backend/models/`, and service logic in `backend/services/`.
- `frontend/` React + Vite app, source in `frontend/src/` and build output in `frontend/dist/`.
- `data/` local runtime data for non-Docker dev; Docker stores data under `./config/` and `./downloads/`.
- `docker-compose.yml` runs the full stack; `scripts/` and `tools/` contain helper assets.

## Build, Test, and Development Commands
- Backend dev:
  - `cd backend`
  - `python -m venv venv && source venv/bin/activate`
  - `pip install -r requirements.txt`
  - `python main.py` (serves API on `http://localhost:8000`)
- Frontend dev:
  - `cd frontend`
  - `npm install`
  - `npm run dev` (serves UI on `http://localhost:5173`)
- Docker:
  - `docker-compose up -d` (full stack, UI on `http://localhost:3000`)

## Coding Style & Naming Conventions
- Python: 4-space indentation; keep async code consistent with existing FastAPI patterns.
- React: 2-space indentation and standard React component naming (PascalCase for components, camelCase for hooks and helpers).
- No repo-wide formatter or linter is configured; keep changes aligned with surrounding file style.

## Testing Guidelines
- No automated test suite is present yet. If you add tests, place them under `backend/tests/` or `frontend/src/__tests__/` and document how to run them.

## Commit & Pull Request Guidelines
- Commit messages follow short, imperative sentences (e.g., “Fix missing Path import”).
- PRs should include: a concise summary, steps to test, and screenshots for UI changes. Link related issues if applicable.

## Configuration & Local Data
- Backend supports `.env` in `backend/` for settings like `CATCHUP_DATABASE_URL` and download paths.
- Docker persists data in `./config/` and `./downloads/`; do not commit real credentials or generated media.
