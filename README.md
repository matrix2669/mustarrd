![Mustarrd Logo](https://github.com/razzamatazm/mustarrd/blob/main/frontend/src/assets/mustarrdlogo.png "Mustarrd Logo")
# Mustarrd — IPTV Catchup DVR

Mustarrd connects to your IPTV provider and lets you download past programs — think of it as a DVR for your IPTV catchup library. Browse your provider's program guide, pick anything from the last few days (or schedule shows airing in the future), and download it with a properly named file ready for Plex, Jellyfin, or just your hard drive.

## Features

- **Browse past programs** — scroll back through your provider's program guide (EPG) and see what's available to download
- **Commercial skip** — ComSkip integration removes commercials before saving
- **Remux to MKV** — TS playback sucks. MKV is a much easier container to skip through
- **Download from On Demand** — If your provider provides on demand listings, you can grab those too!
- **Scheduled recordings** — set programs to download automatically when they air
- **Smart file naming** — TV shows, movies, and sports get automatically named in the right format (`Breaking Bad - S01E01 - Pilot.ts`, `The Matrix (1999).ts`, etc.)
- **Plex Link** — Allow your plex users to request programming by logging in with their Plex creds (or don't) and push recording directly to your TV recording library
- **Multiple accounts** — connect more than one IPTV provider. Add more users to give them download access

## Why Do I Need This? I have Sonarr...

- While Sonarr grabs the majority of quality programming out there I was searching for something for those random shows that air once a year. Think sports, awards shows, dog acrobatics competitions, the olympic games, etc.
- I hate commercials
- Sure, many good iptv players have the ability to record shows, but that is a recording of a recording. If something glitches, you're out of luck.
- Link it right to Plex (allow your users to add shows to download if you want using the Plex integration)

## Requirements

- An IPTV subscription with **catchup / timeshift support** (must use the Xtream Codes protocol)
- **Docker** — recommended install method, everything is bundled

> Not sure if your provider supports catchup? Check if they give you a "catchup days" value or mention timeshift in their plan details.

## Install

### Docker (Recommended)

```bash
curl -O https://raw.githubusercontent.com/razzamatazm/mustarrd/main/docker-compose.yml
mkdir -p config downloads completed
docker compose up -d
```

Then open **http://localhost:4177** in your browser.


### Desktop App (macOS / Windows)

- An electron app builder is included in the electron folder, but Docker is by far the recommended way to use the app.


## First Run

1. Open **http://localhost:4177**
2. You'll be prompted to **set an admin password** — do this before anyone else on your network can reach the page
3. Go to **Accounts → Add Account** and enter your IPTV provider details:
   - Server URL (e.g. `https://your-provider.com`)
   - Username and password (from your provider)
   - Catchup days (how far back you can download — your provider sets this limit)
4. Mustarrd will sync your provider's channel list and program guide. This takes a minute or two on first load.
5. Go to **Browse**, pick a channel, and start downloading or search all.

## How to Use

### Browse and Download a Program

1. Go to **Browse** and select an account
2. Click a channel to open its program guide
3. Programs with a **mustard yellow border** have catchup available — click one to open the download dialog
4. Review the auto-generated filename (edit if needed) and click **Download**

### Monitor Downloads

- Go to the **Downloads** page to see active downloads with progress bars
- Failed downloads can be retried from the same page

### Schedule a Recording

- Browse to an upcoming program and use the **Schedule** option to download it automatically when it airs
- Make sure to turn on the view future programming switch

## Smart Filename Detection

Mustarrd reads the program title and automatically formats the filename for your media library:

| Type | Example Output |
|------|----------------|
| TV Show (S01E01 pattern) | `Breaking Bad - S01E01 - Pilot.ts` |
| Sports | `NFL - Dolphins vs Chargers - 2026-01-28.ts` |
| Movie | `The Matrix (1999).ts` |
| Everything else | `ESPN - SportsCenter - 2026-01-28.ts` |

Filename templates are customizable in Settings if you want a different format.

## Where Your Files Go

| Folder | Contents |
|--------|----------|
| `./downloads/` | In-progress downloads and temp files used for ComSkip |
| `./completed/` | Finished files — point this at your media library |
| `./config/` | Database, settings, and Comskip config — keep this private |

Change the `./completed/` path in `docker-compose.yml` to point directly at your Plex or Jellyfin media folder.

## Configuration

Most users never need to touch these. Set them in `docker-compose.yml` or a `backend/.env` file.

| Variable | Description | Default |
|----------|-------------|---------|
| `CATCHUP_TIMEZONE` | Timezone for the program guide display | `UTC` |
| `CATCHUP_DEFAULT_DOWNLOAD_FOLDER` | In-progress download location | `/app/downloads` |
| `CATCHUP_DEFAULT_COMPLETED_FOLDER` | Finished file location | `/app/completed` |
| `CATCHUP_MAX_CONCURRENT_DOWNLOADS` | Max simultaneous downloads | `2` |
| `CATCHUP_SESSION_SECRET` | Session signing key — auto-generated and persisted to `./config/session_secret` on first run; only set this manually to rotate or share across instances | *(auto)* |
| `CATCHUP_CORS_ORIGINS` | Comma-separated allowed frontend origins; only needed when the UI is accessed from a non-localhost address | `http://localhost:4178,...` |
| `CATCHUP_SESSION_HTTPS_ONLY` | Require HTTPS for session cookies | `true` (desktop: `false`) |
| `CATCHUP_ALLOW_REMOTE_SETUP` | Allow password setup from non-local IPs | `false` |
| `CATCHUP_FFMPEG_PATH` | Path to ffmpeg binary | *(auto-detected)* |
| `CATCHUP_COMSKIP_PATH` | Path to comskip binary | *(auto-detected)* |
| `CATCHUP_DATABASE_URL` | SQLite database URL | `sqlite+aiosqlite:////app/config/catchup_dvr.db` |
| `CATCHUP_DEBUG` | Enable debug logging | `false` |

## Development

**Backend** (FastAPI, port 4177):
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
python main.py
```

**Frontend** (React + Vite, port 4178, proxies `/api` to 4177):
```bash
cd frontend
npm install
npm run dev
```

**Docker** (full stack):
```bash
docker-compose up -d
```

See `desktop-electron/README.md` for building the macOS/Windows desktop app.

## License

MIT
