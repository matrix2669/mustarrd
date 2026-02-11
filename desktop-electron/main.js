const { app, BrowserWindow, Menu, Tray, dialog } = require("electron");
const http = require("http");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");

const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = process.env.CATCHUP_DESKTOP_PORT || "4177";
const BACKEND_START_TIMEOUT_MS = 30000;

let mainWindow = null;
let tray = null;
let backendProcess = null;
let isQuitting = false;

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
    return path.join(process.resourcesPath, "frontend-dist", "favicon.png");
  }
  return path.resolve(__dirname, "..", "frontend", "public", "favicon.png");
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

  backendProcess = spawn(backendPath, [], {
    stdio: "pipe",
    env: {
      ...process.env,
      CATCHUP_DESKTOP_HOST: BACKEND_HOST,
      CATCHUP_DESKTOP_PORT: BACKEND_PORT,
      CATCHUP_DATA_ROOT: resolveDataRootPath(),
      CATCHUP_FRONTEND_DIST: frontendDistPath
    }
  });

  backendProcess.stdout.on("data", (chunk) => {
    process.stdout.write(`[backend] ${chunk}`);
  });
  backendProcess.stderr.on("data", (chunk) => {
    process.stderr.write(`[backend] ${chunk}`);
  });
  backendProcess.on("exit", (code, signal) => {
    if (!isQuitting) {
      dialog.showErrorBox(
        "Backend stopped",
        `Mustarrd backend exited unexpectedly (code=${code}, signal=${signal}).`
      );
      app.quit();
    }
  });

  await waitForBackendReady();
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
}

function hideWindowToTray() {
  if (!mainWindow) return;
  mainWindow.hide();
  if (process.platform === "darwin" && app.dock) {
    app.dock.hide();
  }
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
  tray = new Tray(resolveTrayIconPath());
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
    show: false,
    title: "Mustarrd"
  });

  mainWindow.loadURL(`http://${BACKEND_HOST}:${BACKEND_PORT}`);

  mainWindow.once("ready-to-show", () => {
    showWindowFromTray();
  });

  mainWindow.on("close", (event) => {
    if (isQuitting) {
      return;
    }
    event.preventDefault();
    hideWindowToTray();
  });
}

app.on("before-quit", () => {
  isQuitting = true;
  stopBackend();
});

app.whenReady().then(async () => {
  try {
    await startBackend();
  } catch (error) {
    dialog.showErrorBox("Startup failed", error.message);
    app.quit();
    return;
  }

  createTray();
  createMainWindow();

  app.on("activate", () => {
    showWindowFromTray();
  });
});
