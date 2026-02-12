# Mustarrd Desktop (macOS + Windows)

This Electron shell launches the bundled backend server and opens the Mustarrd UI at `http://127.0.0.1:4177`.

Closing the window hides the app to the tray/menu bar while the backend keeps running.

In desktop mode, default download and completed folders are the current user's OS Downloads directory.

## Build prerequisites

- Node.js 20+
- Python 3.10+ (for building backend sidecar binary)

## Build desktop artifacts

1. Install desktop dependencies:
   ```bash
   cd desktop-electron
   npm install
   ```
2. Build a macOS app (run on macOS):
   ```bash
   npm run dist:mac
   ```
3. Build a Windows app (run on Windows):
   ```powershell
   npm run dist:win
   ```

Output artifacts are written to `desktop-electron/release/`.

## Optional bundled post-processing tools

Desktop builds can include bundled `ffmpeg`, `ffprobe`, and `comskip` binaries under `desktop-electron/tools/`.
At runtime, the desktop shell prefers these bundled tools when present and falls back to system-installed tools when absent.

For macOS builds, `npm run dist:mac` now runs `scripts/prepare-tools-macos.sh` to vendor:
- `ffmpeg`
- `ffprobe`
- `comskip`
- non-system dynamic libraries needed by those executables

These are staged under `desktop-electron/tools/darwin-<arch>/` before packaging.
The prep step uses a manifest cache and skips rebuilding when the source tool binaries have not changed.
To force a rebuild of bundled tools:

```bash
cd desktop-electron
bash ./scripts/prepare-tools-macos.sh --force
```

This behavior is desktop-only and does not affect Linux server or Docker deployments.

## Development shell (optional)

For local shell testing, build the frontend and backend binary first:

```bash
cd frontend && npm run build
cd ../desktop-electron
npm run build:backend:mac
npm run dev
```
