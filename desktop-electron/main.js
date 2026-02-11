const { app, BrowserWindow, Menu, Tray, dialog, ipcMain, nativeImage } = require("electron");
const http = require("http");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = process.env.CATCHUP_DESKTOP_PORT || "4177";
const BACKEND_START_TIMEOUT_MS = 30000;

let mainWindow = null;
let tray = null;
let backendProcess = null;
let isQuitting = false;
let backendReady = false;
const STARTUP_LOG_PATH = "/tmp/mustarrd-desktop.log";

function logDesktop(message) {
  const line = `${new Date().toISOString()} ${message}`;
  try {
    fs.appendFileSync(STARTUP_LOG_PATH, `${line}\n`);
  } catch {
    // Ignore logging failures.
  }
  process.stderr.write(`${line}\n`);
}

function reportFatalStartupError(error) {
  const message = error instanceof Error ? error.message : String(error);
  logDesktop(`[desktop] Fatal startup error: ${message}`);
  loadStatusPage("Startup failed", message);
  if (app.isReady()) {
    dialog.showErrorBox("Startup failed", message);
  }
}

function launchOnStartupSupported() {
  return process.platform === "darwin" || process.platform === "win32";
}

function getLaunchOnStartupStatus() {
  if (!launchOnStartupSupported()) {
    return { supported: false, enabled: false };
  }

  try {
    const settings = app.getLoginItemSettings();
    return { supported: true, enabled: Boolean(settings.openAtLogin) };
  } catch {
    return { supported: true, enabled: false };
  }
}

function setLaunchOnStartup(enabled) {
  if (!launchOnStartupSupported()) {
    return { supported: false, enabled: false };
  }

  const openAtLogin = Boolean(enabled);
  if (process.platform === "darwin") {
    app.setLoginItemSettings({ openAtLogin, openAsHidden: true });
  } else {
    app.setLoginItemSettings({ openAtLogin });
  }

  return getLaunchOnStartupStatus();
}

function isExecutable(filePath) {
  if (!filePath) return false;
  try {
    fs.accessSync(filePath, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function withPrependedPathEntries(existingPath, entries) {
  const current = existingPath ? existingPath.split(path.delimiter) : [];
  const merged = [...entries, ...current].filter(Boolean);
  return [...new Set(merged)].join(path.delimiter);
}

function resolveFirstExecutable(candidates) {
  for (const candidate of candidates) {
    if (isExecutable(candidate)) {
      return candidate;
    }
  }
  return null;
}

function backendExecutableName() {
  return process.platform === "win32" ? "catchup-backend.exe" : "catchup-backend";
}

function resolveBackendExecutablePath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "backend", backendExecutableName());
  }
  return path.join(__dirname, "backend-bin", backendExecutableName());
}

function resolveFrontendDistPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "frontend-dist");
  }
  return path.resolve(__dirname, "..", "frontend", "dist");
}

function resolveDataRootPath() {
  return path.join(app.getPath("userData"), "data");
}

function resolveTrayIconPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "mustarrd-trayTemplate.png");
  }
  return path.resolve(__dirname, "assets", "mustarrd-trayTemplate.png");
}

function resolveAppIconPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "icon.icns");
  }
  return path.resolve(__dirname, "assets", "mustarrd.icns");
}

function resolveBundledComskipIniPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "comskip.ini");
  }
  return path.resolve(__dirname, "..", "comskip.ini");
}

function toolExecutableName(toolName) {
  if (process.platform === "win32") {
    return `${toolName}.exe`;
  }
  return toolName;
}

function resolveBundledToolsRoot() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "tools");
  }
  return path.resolve(__dirname, "tools");
}

function resolveBundledToolSearchDirs() {
  const root = resolveBundledToolsRoot();
  const arch = process.arch;
  const platform = process.platform;

  return [
    path.join(root, `${platform}-${arch}`),
    path.join(root, platform),
    root
  ];
}

function resolveBundledToolPath(toolName) {
  const executable = toolExecutableName(toolName);
  const dirs = resolveBundledToolSearchDirs();
  for (const dirPath of dirs) {
    const candidate = path.join(dirPath, executable);
    if (isExecutable(candidate)) {
      return candidate;
    }
  }
  return null;
}

function resolveBundledLibraryDirs() {
  const dirs = [];
  const searchDirs = resolveBundledToolSearchDirs();
  for (const dirPath of searchDirs) {
    if (fs.existsSync(dirPath)) {
      dirs.push(dirPath);
      const libDir = path.join(dirPath, "lib");
      if (fs.existsSync(libDir)) {
        dirs.push(libDir);
      }
    }
  }
  return [...new Set(dirs)];
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function loadStatusPage(title, message) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }

  const safeTitle = escapeHtml(title);
  const safeMessage = escapeHtml(message).replace(/\n/g, "<br/>");
  const body = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${safeTitle}</title>
    <style>
      :root {
        color-scheme: dark;
      }
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #171717;
        color: #f3f3f3;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      .card {
        width: min(760px, 92vw);
        background: #222;
        border: 1px solid #363636;
        border-radius: 12px;
        padding: 24px;
      }
      h1 {
        margin: 0 0 12px;
        font-size: 22px;
      }
      p {
        margin: 0;
        color: #ccc;
        line-height: 1.5;
        font-size: 14px;
      }
    </style>
  </head>
  <body>
    <main class="card">
      <h1>${safeTitle}</h1>
      <p>${safeMessage}</p>
    </main>
  </body>
</html>`;

  mainWindow.loadURL(`data:text/html;charset=UTF-8,${encodeURIComponent(body)}`);
}

function loadFrontend() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.loadURL(`http://${BACKEND_HOST}:${BACKEND_PORT}`);
}

function createTrayIconImage() {
  const iconPath = resolveTrayIconPath();
  if (process.platform !== "darwin") {
    return iconPath;
  }

  const image = nativeImage.createFromPath(iconPath);
  if (image.isEmpty()) {
    return iconPath;
  }

  image.setTemplateImage(true);
  return image;
}

function ensureDataFolders() {
  const dataRoot = resolveDataRootPath();
  const folders = [dataRoot, path.join(dataRoot, "downloads"), path.join(dataRoot, "completed")];
  folders.forEach((folderPath) => {
    fs.mkdirSync(folderPath, { recursive: true });
  });
}

function checkBackendHealth() {
  return new Promise((resolve) => {
    const request = http.get(
      `http://${BACKEND_HOST}:${BACKEND_PORT}/api/health`,
      { timeout: 2000 },
      (response) => {
        response.resume();
        resolve(response.statusCode === 200);
      }
    );

    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
  });
}

function fetchBackendSettings() {
  return new Promise((resolve, reject) => {
    const request = http.get(
      `http://${BACKEND_HOST}:${BACKEND_PORT}/api/settings`,
      { timeout: 5000 },
      (response) => {
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          body += chunk;
        });
        response.on("end", () => {
          if (response.statusCode !== 200) {
            reject(new Error(`Settings request failed with status ${response.statusCode}`));
            return;
          }
          try {
            resolve(JSON.parse(body));
          } catch (error) {
            reject(error);
          }
        });
      }
    );

    request.on("timeout", () => {
      request.destroy(new Error("Settings request timed out"));
    });
    request.on("error", (error) => {
      reject(error);
    });
  });
}

async function syncLaunchOnStartupFromSettings() {
  if (!launchOnStartupSupported()) {
    return;
  }

  try {
    const settings = await fetchBackendSettings();
    const desired = settings?.launch_on_startup !== false;
    const current = getLaunchOnStartupStatus().enabled;
    if (current !== desired) {
      setLaunchOnStartup(desired);
    }
  } catch (error) {
    logDesktop(`[desktop] Failed to sync startup setting: ${error.message}`);
  }
}

async function waitForBackendReady() {
  const startTime = Date.now();
  while (Date.now() - startTime < BACKEND_START_TIMEOUT_MS) {
    // eslint-disable-next-line no-await-in-loop
    const healthy = await checkBackendHealth();
    if (healthy) {
      return;
    }
    // eslint-disable-next-line no-await-in-loop
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("Timed out waiting for backend health check");
}

async function startBackend() {
  const backendPath = resolveBackendExecutablePath();
  const frontendDistPath = resolveFrontendDistPath();

  if (!fs.existsSync(backendPath)) {
    throw new Error(`Backend executable not found: ${backendPath}`);
  }
  if (!fs.existsSync(path.join(frontendDistPath, "index.html"))) {
    throw new Error(`Frontend dist not found: ${frontendDistPath}`);
  }

  ensureDataFolders();

  const backendEnv = {
    ...process.env,
    CATCHUP_DESKTOP_HOST: BACKEND_HOST,
    CATCHUP_DESKTOP_PORT: BACKEND_PORT,
    CATCHUP_DESKTOP_MODE: "1",
    CATCHUP_DATA_ROOT: resolveDataRootPath(),
    CATCHUP_FRONTEND_DIST: frontendDistPath
  };

  if (!backendEnv.CATCHUP_BUNDLED_COMSKIP_INI) {
    const bundledComskipIniPath = resolveBundledComskipIniPath();
    if (fs.existsSync(bundledComskipIniPath)) {
      backendEnv.CATCHUP_BUNDLED_COMSKIP_INI = bundledComskipIniPath;
    }
  }

  const bundledFfmpegPath = resolveBundledToolPath("ffmpeg");
  const bundledFfprobePath = resolveBundledToolPath("ffprobe");
  const bundledComskipPath = resolveBundledToolPath("comskip");

  if (!backendEnv.CATCHUP_FFMPEG_PATH && bundledFfmpegPath) {
    backendEnv.CATCHUP_FFMPEG_PATH = bundledFfmpegPath;
  }
  if (!backendEnv.CATCHUP_FFPROBE_PATH && bundledFfprobePath) {
    backendEnv.CATCHUP_FFPROBE_PATH = bundledFfprobePath;
  }
  if (!backendEnv.CATCHUP_COMSKIP_PATH && bundledComskipPath) {
    backendEnv.CATCHUP_COMSKIP_PATH = bundledComskipPath;
  }

  const bundledLibraryDirs = resolveBundledLibraryDirs();
  if (bundledLibraryDirs.length > 0) {
    backendEnv.PATH = withPrependedPathEntries(backendEnv.PATH, bundledLibraryDirs);
    if (process.platform === "darwin") {
      backendEnv.DYLD_LIBRARY_PATH = withPrependedPathEntries(
        backendEnv.DYLD_LIBRARY_PATH,
        bundledLibraryDirs
      );
    } else if (process.platform === "linux") {
      backendEnv.LD_LIBRARY_PATH = withPrependedPathEntries(
        backendEnv.LD_LIBRARY_PATH,
        bundledLibraryDirs
      );
    }
  }

  if (process.platform === "darwin") {
    backendEnv.PATH = withPrependedPathEntries(backendEnv.PATH, [
      "/opt/homebrew/bin",
      "/usr/local/bin"
    ]);

    if (!backendEnv.CATCHUP_FFMPEG_PATH) {
      const ffmpegPath = resolveFirstExecutable([
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg"
      ]);
      if (ffmpegPath) {
        backendEnv.CATCHUP_FFMPEG_PATH = ffmpegPath;
      }
    }

    if (!backendEnv.CATCHUP_COMSKIP_PATH) {
      const comskipPath = resolveFirstExecutable([
        "/opt/homebrew/bin/comskip",
        "/usr/local/bin/comskip",
        "/usr/bin/comskip"
      ]);
      if (comskipPath) {
        backendEnv.CATCHUP_COMSKIP_PATH = comskipPath;
      }
    }
  }

  backendProcess = spawn(backendPath, [], {
    stdio: "pipe",
    env: backendEnv
  });

  backendProcess.stdout.on("data", (chunk) => {
    process.stdout.write(`[backend] ${chunk}`);
  });
  backendProcess.stderr.on("data", (chunk) => {
    process.stderr.write(`[backend] ${chunk}`);
  });
  backendProcess.on("error", (error) => {
    logDesktop(`[desktop] Backend spawn error: ${error.message}`);
  });
  backendProcess.on("exit", (code, signal) => {
    backendReady = false;
    logDesktop(`[desktop] Backend exited code=${code} signal=${signal}`);
    if (!isQuitting) {
      const reason = `Mustarrd backend exited unexpectedly (code=${code}, signal=${signal}).`;
      loadStatusPage("Backend stopped", `${reason}\n\nPlease relaunch Mustarrd.`);
      dialog.showErrorBox("Backend stopped", reason);
    }
  });

  await new Promise((resolve, reject) => {
    let settled = false;

    const resolveOnce = () => {
      if (settled) return;
      settled = true;
      backendProcess.off("error", onErrorDuringStart);
      backendProcess.off("exit", onExitDuringStart);
      resolve();
    };

    const rejectOnce = (error) => {
      if (settled) return;
      settled = true;
      backendProcess.off("error", onErrorDuringStart);
      backendProcess.off("exit", onExitDuringStart);
      reject(error);
    };

    const onErrorDuringStart = (error) => {
      rejectOnce(new Error(`Failed to start backend: ${error.message}`));
    };

    const onExitDuringStart = (code, signal) => {
      rejectOnce(
        new Error(`Backend exited before startup completed (code=${code}, signal=${signal}).`)
      );
    };

    backendProcess.once("error", onErrorDuringStart);
    backendProcess.once("exit", onExitDuringStart);

    waitForBackendReady()
      .then(resolveOnce)
      .catch((error) => {
        rejectOnce(error);
      });
  });

  backendReady = true;
}

function stopBackend() {
  if (!backendProcess || backendProcess.killed) {
    return;
  }

  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", `${backendProcess.pid}`, "/t", "/f"]);
  } else {
    backendProcess.kill("SIGTERM");
  }
  logDesktop("[desktop] Requested backend shutdown");
  backendProcess = null;
  backendReady = false;
}

function hideWindowToTray() {
  if (!mainWindow) return;
  mainWindow.hide();
}

function showWindowFromTray() {
  if (!mainWindow) return;
  if (process.platform === "darwin" && app.dock) {
    app.dock.show();
  }
  if (!mainWindow.isVisible()) {
    mainWindow.show();
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.focus();
}

function createTray() {
  try {
    tray = new Tray(createTrayIconImage());
  } catch (error) {
    tray = null;
    logDesktop(`[desktop] Tray unavailable: ${error.message}`);
    return;
  }

  tray.setToolTip("Mustarrd");
  tray.on("click", showWindowFromTray);

  const menu = Menu.buildFromTemplate([
    {
      label: "Open Mustarrd",
      click: showWindowFromTray
    },
    {
      label: "Quit Mustarrd",
      click: () => {
        isQuitting = true;
        app.quit();
      }
    }
  ]);
  tray.setContextMenu(menu);
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    show: true,
    title: "Mustarrd",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  loadStatusPage("Starting Mustarrd", "Starting backend service...");

  mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
    logDesktop(
      `[desktop] Main window failed to load (${errorCode}): ${errorDescription} (${validatedURL})`
    );
  });

  const maybeShowWindow = () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return;
    }
    mainWindow.show();
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.focus();
  };
  mainWindow.once("ready-to-show", maybeShowWindow);
  mainWindow.webContents.once("did-finish-load", maybeShowWindow);
  setTimeout(() => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      maybeShowWindow();
    }
  }, 3000);

  mainWindow.on("close", (event) => {
    if (isQuitting || !tray) {
      return;
    }
    event.preventDefault();
    hideWindowToTray();
  });
}

app.on("before-quit", () => {
  isQuitting = true;
  logDesktop("[desktop] before-quit");
  stopBackend();
});

app.whenReady().then(async () => {
  logDesktop("[desktop] app.whenReady");
  createMainWindow();

  ipcMain.handle("desktop:get-launch-on-startup", () => {
    return getLaunchOnStartupStatus();
  });

  ipcMain.handle("desktop:set-launch-on-startup", (_event, enabled) => {
    return setLaunchOnStartup(enabled);
  });

  createTray();

  try {
    logDesktop("[desktop] Starting backend");
    await startBackend();
    logDesktop("[desktop] Backend ready");
    await syncLaunchOnStartupFromSettings();
    loadFrontend();
    logDesktop("[desktop] Frontend loaded");
  } catch (error) {
    const details = `${error.message}\n\nPlease verify backend binaries are present and try again.`;
    loadStatusPage("Startup failed", details);
    logDesktop(`[desktop] Startup failed: ${error.message}`);
    dialog.showErrorBox("Startup failed", error.message);
  }

  app.on("activate", () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      createMainWindow();
      if (backendReady) {
        loadFrontend();
      }
    }
    showWindowFromTray();
  });
});

process.on("uncaughtException", (error) => {
  reportFatalStartupError(error);
});

process.on("unhandledRejection", (reason) => {
  reportFatalStartupError(reason);
});

logDesktop("[desktop] main.js loaded");
