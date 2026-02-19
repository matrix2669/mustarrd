# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mustarrd is an IPTV catchup DVR web app. It connects to Xtream Codes IPTV servers, browses past EPG programs, and downloads catchup/timeshift streams with smart filename templating, commercial skip (Comskip), and GPU/CPU re-encoding (FFmpeg).

## Development Commands

**Backend** (FastAPI, port 4177):
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```

**Frontend** (React + Vite, port 4178 in dev, proxies `/api` to 4177):
```bash
cd frontend
npm install
npm run dev
```

**Docker** (full stack):
```bash
docker-compose up -d
# backend: 4177, frontend: 4178
```

No automated test suite exists. If adding tests: `backend/tests/` or `frontend/src/__tests__/`.

## Architecture

### Download Pipeline
1. User picks a channel+EPG program → frontend calls `POST /api/downloads/`
2. `download_manager` (service) picks up the queued record and fetches the Xtream catchup URL
3. FFmpeg downloads the TS stream; `post_processor` handles Comskip and/or transcoding
4. Finished file moves to the completed folder
5. Real-time progress flows over WebSocket at `/api/downloads/ws`

### Background Managers (started in `backend/main.py` lifespan)
- `download_manager` — concurrent download queue; resumes in-progress tasks on restart
- `post_processor` — Comskip + FFmpeg re-encode/remux pipeline
- `epg_ingest_manager` — periodically refreshes EPG from Xtream for all accounts
- `scheduled_manager` — fires scheduled recordings as their time arrives

### Database & Migrations
SQLite via async SQLAlchemy. Schema is created and migrated on every startup in `backend/database.py` using lightweight `ALTER TABLE` checks — no migration framework. `app_settings` table holds global config (padding defaults, transcode flags, etc.).

Key constraint: enabling Comskip forces `transcode_enabled = true`; enabling commercial removal forces `remux_only = false`.

### Authentication (current branch: `codex/authentication`)
Session-based auth implemented in `backend/auth.py` and `backend/api/auth.py`. Optional/progressive: first run requires no password; once an admin password is set via `/auth/setup`, protected endpoints require login. Frontend uses `ProtectedRoute` in `App.jsx` and checks `/api/auth/status` on load.

### Configuration
All settings use the `CATCHUP_` env prefix (see `backend/config.py`). A `.env` file in `backend/` is supported. Key vars:
- `CATCHUP_DATABASE_URL` — defaults to SQLite in `/app/config/` (Docker) or `data/` (local)
- `CATCHUP_DEFAULT_DOWNLOAD_FOLDER` / `CATCHUP_DEFAULT_COMPLETED_FOLDER`
- `CATCHUP_MAX_CONCURRENT_DOWNLOADS` (default: 2)
- `CATCHUP_FFMPEG_PATH`, `CATCHUP_COMSKIP_PATH` — override auto-detected tool paths
- `CATCHUP_TIMEZONE`, `CATCHUP_DEBUG`

## Code Style
- Python: 4-space indentation; async throughout (FastAPI + SQLAlchemy AsyncIO)
- React: 2-space indentation; PascalCase components, camelCase hooks/helpers
- Mantine UI 7.x for all frontend components; TanStack React Query for data fetching
- No repo-wide formatter — match the style of the file you're editing

## Commits & PRs
- Short imperative commit messages (e.g., `Fix missing Path import`)
- PRs need: concise summary, steps to test, screenshots for UI changes
