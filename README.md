![Mustarrd Logo](https://github.com/razzamatazm/mustarrd/blob/main/frontend/src/assets/mustarrdlogo.png "Mustarrd Logo")
# Mustarrd - The IPTV Catchup DVR

A web application that connects to Xtream Codes IPTV servers, displays past EPG programs, and directly download catchup/timeshift content with smart file naming.

## Features

- **Account Management**: Add and manage multiple Xtream Codes IPTV accounts
- **EPG Browser**: Browse channels and view past EPG data with catchup availability
- **Smart Downloads**: Automatically generate filenames based on content type (TV shows, movies, sports, etc.)
- **Download Queue**: Manage concurrent downloads with progress tracking
- **Commercial Removal**: Uses Comskip to remove commercials for shows.
- **GPU and CPU Re-encoding**: Convert your program to MKV and get steadier playback and seeking.
- **Real-time Updates**: WebSocket-based progress updates for downloads
- **Customizable Templates**: Configure filename templates for different content types


## Quick Start

### Development

1. **Backend API + workers**:
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # or `venv\Scripts\activate` on Windows
   pip install -r requirements.txt
   python main.py
   ```
   Backend runs on http://localhost:4177.

2. **Frontend dev server (optional for UI development)**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   Frontend runs on http://localhost:4178 and proxies API calls to `:4177`.

3. **Single-process local app mode**:
   ```bash
   cd frontend
   npm install
   npm run build
   cd ../backend
   python main.py
   ```
   UI + API are both served from http://localhost:4177.

### Docker

```bash
docker-compose up -d
```

Access the app at http://localhost:4177

#### Docker volumes

For docker-compose, you only need three host folders:

```
./config      -> /app/config
./downloads   -> /app/downloads
./completed   -> /app/completed
```

The database is stored at `./config/catchup_dvr.db`, working downloads at `./downloads/`,
and finished files are moved to `./completed/`.
On first run, `comskip.ini` is copied into `./config/comskip.ini` and set as the default.

Timezone display can be set via environment variable:
`CATCHUP_TIMEZONE` (e.g., `America/Los_Angeles`).

#### Quick Start (Docker)

```bash
git clone https://github.com/razzamatazm/mustarrd.git
cd mustarrd
mkdir -p config downloads completed
docker-compose up -d
```

#### Quick Start (Docker, no clone)

```bash
curl -O https://raw.githubusercontent.com/razzamatazm/mustarrd/main/docker-compose.yml
mkdir -p config downloads completed
docker compose up -d
```

Note: Docker uses absolute paths inside the container:
`/app/config`, `/app/downloads`, and `/app/completed`.

### Tools (ffmpeg + comskip)

Docker builds install ffmpeg via apt, compile comskip from source, and bundle the built frontend into the same image.
If you run the backend locally (non-Docker), install ffmpeg and comskip manually.

### Desktop apps (macOS and Windows)

The `desktop-electron/` project builds native desktop shells that:

- start the bundled backend server
- load the UI from `http://127.0.0.1:4177`
- hide to tray/menu bar on close while the server keeps running

Build steps and scripts are documented in `desktop-electron/README.md`.

## Configuration

Environment variables (can be set in `.env` file in backend directory):

| Variable | Description | Default |
|----------|-------------|---------|
| `CATCHUP_DATABASE_URL` | SQLite database URL | `sqlite+aiosqlite:////app/config/catchup_dvr.db` |
| `CATCHUP_DEFAULT_DOWNLOAD_FOLDER` | Download location | `/app/downloads` |
| `CATCHUP_DEFAULT_COMPLETED_FOLDER` | Completed location | `/app/completed` |
| `CATCHUP_MAX_CONCURRENT_DOWNLOADS` | Max simultaneous downloads | `2` |
| `CATCHUP_DEBUG` | Enable debug mode | `false` |

If you run the backend locally (non-Docker), set these paths to your local folders.

## Usage

### 1. Add an Account

1. Go to the **Accounts** page
2. Click "Add Account"
3. Enter your Xtream Codes server details:
   - Server URL (e.g., `https://provider.example.com`)
   - Username
   - Password
   - Catchup days available (how many days back you can download)

### 2. Browse Channels

1. Go to the **Browse** page
2. Select an account from the dropdown
3. Optionally filter by category
4. Click a channel to view its EPG

### 3. Download a Program

1. In the EPG timeline, programs with catchup available have a blue border
2. Click on a past program to open the download modal
3. Review the auto-generated filename (edit if needed)
4. Click "Download" to add to queue

### 4. Monitor Downloads

- Go to the **Downloads** page
- View active downloads with progress bars
- Retry failed downloads or view history

## Smart Filename Detection

The app automatically detects content types and generates appropriate filenames:

| Type | Detection | Example Output |
|------|-----------|----------------|
| TV Show | Season/episode patterns (S01E01) | `Breaking Bad - S01E01 - Pilot.ts` |
| Sports | Keywords (vs, NFL, NBA, etc.) | `NFL - Dolphins vs Chargers - 2026-01-28.ts` |
| Movie | Movie category keywords | `The Matrix (1999).ts` |
| Default | Everything else | `ESPN - SportsCenter - 2026-01-28.ts` |



## License

MIT
