Place optional bundled desktop tool binaries here.

Layout options (auto-detected by desktop-electron/main.js):
- tools/<platform>-<arch>/ffmpeg
- tools/<platform>-<arch>/ffprobe
- tools/<platform>-<arch>/comskip
- tools/<platform>/...
- tools/... (flat fallback)

Examples:
- tools/darwin-arm64/ffmpeg
- tools/darwin-arm64/ffprobe
- tools/darwin-arm64/comskip
- tools/win32-x64/ffmpeg.exe
- tools/win32-x64/ffprobe.exe
- tools/win32-x64/comskip.exe

Any shared libraries can be colocated in the same directory or in a lib/ subdirectory.
Desktop startup prepends these directories to PATH and platform library lookup paths.

If this folder is empty, desktop falls back to system-installed tools (current behavior).
