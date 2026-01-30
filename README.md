# Catchup DVR

A web application that connects to Xtream Codes IPTV servers, displays past EPG programs, and downloads catchup/timeshift content with smart file naming.

## Features

- **Account Management**: Add and manage multiple Xtream Codes IPTV accounts
- **EPG Browser**: Browse channels and view past EPG data with catchup availability
- **Smart Downloads**: Automatically generate filenames based on content type (TV shows, movies, sports, etc.)
- **Download Queue**: Manage concurrent downloads with progress tracking
- **Real-time Updates**: WebSocket-based progress updates for downloads
- **Customizable Templates**: Configure filename templates for different content types

## Technology Stack

### Backend
- FastAPI - Async web framework
- SQLAlchemy - Database ORM
- SQLite - Lightweight database
- aiohttp - Async HTTP client
- aiofiles - Async file operations

### Frontend
- React + Vite - Build tooling
- Mantine UI - Component library
- React Query - Data fetching/caching
- Day.js - Date manipulation

## Quick Start

### Development

1. **Backend**:
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # or `venv\Scripts\activate` on Windows
   pip install -r requirements.txt
   python main.py
   ```
   Backend runs on http://localhost:8000

2. **Frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   Frontend runs on http://localhost:5173

### Docker

```bash
docker-compose up -d
```

Access the app at http://localhost:3000

#### Docker volumes

For docker-compose, you only need two host folders:

```
./config      -> /app/config
./downloads   -> /app/downloads
```

The database is stored at `./config/catchup_dvr.db` and downloads at `./downloads/`.
On first run, `comskip.ini` is copied into `./config/comskip.ini` and set as the default.

#### Quick Start (Docker)

```bash
git clone https://github.com/razzamatazm/mustarrd.git
cd mustarrd
mkdir -p config downloads
docker-compose up -d
```

#### Quick Start (Docker, no clone)

```bash
curl -O https://raw.githubusercontent.com/razzamatazm/mustarrd/main/docker-compose.yml
mkdir -p config downloads
docker compose up -d
```

### Tools (ffmpeg + comskip)

Docker builds install ffmpeg via apt and compile comskip from source in the backend image.

## Configuration

Environment variables (can be set in `.env` file in backend directory):

| Variable | Description | Default |
|----------|-------------|---------|
| `CATCHUP_DATABASE_URL` | SQLite database URL | `sqlite+aiosqlite:///./data/catchup_dvr.db` |
| `CATCHUP_DEFAULT_DOWNLOAD_FOLDER` | Download location | `./data/downloads` |
| `CATCHUP_MAX_CONCURRENT_DOWNLOADS` | Max simultaneous downloads | `2` |
| `CATCHUP_DEBUG` | Enable debug mode | `false` |

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

## API Reference

### Accounts
- `GET /api/accounts` - List accounts
- `POST /api/accounts` - Create account
- `PUT /api/accounts/{id}` - Update account
- `DELETE /api/accounts/{id}` - Delete account
- `POST /api/accounts/{id}/test` - Test connection

### Channels & EPG
- `GET /api/accounts/{id}/categories` - List categories
- `GET /api/accounts/{id}/channels` - List channels
- `GET /api/accounts/{id}/channels/{channel_id}/epg` - Get EPG
- `GET /api/accounts/{id}/channels/{channel_id}/catchup` - Get catchup programs

### Downloads
- `GET /api/downloads` - List all downloads
- `POST /api/downloads` - Queue download
- `DELETE /api/downloads/{id}` - Cancel/remove download
- `POST /api/downloads/{id}/retry` - Retry failed download
- `WS /api/downloads/ws` - Real-time progress updates

### Settings
- `GET /api/settings` - Get settings
- `PUT /api/settings` - Update settings

## Timeshift URL Format

The app generates timeshift URLs in this format:
```
{server}/timeshift/{username}/{password}/{duration_minutes}/{YYYY-MM-DD:HH-MM}/{channel_id}.ts
```

## License

MIT
