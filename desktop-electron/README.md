# Mustarrd Desktop (macOS + Windows)

This Electron shell launches the bundled backend server and opens the Mustarrd UI at `http://127.0.0.1:4177`.

Closing the window hides the app to the tray/menu bar while the backend keeps running.

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

## Development shell (optional)

For local shell testing, build the frontend and backend binary first:

```bash
cd frontend && npm run build
cd ../desktop-electron
npm run build:backend:mac
npm run dev
```
