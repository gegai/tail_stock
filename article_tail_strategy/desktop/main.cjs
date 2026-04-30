const { app, BrowserWindow, dialog } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");

const BACKEND_PORT = Number(process.env.ARTICLE_STRATEGY_PORT || 8001);
const FRONTEND_PORT = Number(process.env.ARTICLE_STRATEGY_FRONTEND_PORT || 4175);

let backendProcess = null;
let staticServer = null;
let mainWindow = null;

function appRoot() {
  return app.isPackaged ? process.resourcesPath : path.resolve(__dirname, "..");
}

function frontendDir() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "frontend")
    : path.resolve(__dirname, "..", "frontend", "dist");
}

function backendCommand() {
  if (app.isPackaged) {
    return {
      command: path.join(process.resourcesPath, "backend", "tail-strategy-backend.exe"),
      args: [],
      cwd: path.join(process.resourcesPath, "backend")
    };
  }

  return {
    command: path.resolve(__dirname, "..", "backend", ".venv", "Scripts", "python.exe"),
    args: ["run_server.py"],
    cwd: path.resolve(__dirname, "..", "backend")
  };
}

function userStorageRoot() {
  return path.join(app.getPath("userData"), "storage");
}

function startBackend() {
  const backend = backendCommand();
  if (!fs.existsSync(backend.command)) {
    throw new Error(`后端程序不存在：${backend.command}`);
  }

  fs.mkdirSync(userStorageRoot(), { recursive: true });
  const env = {
    ...process.env,
    ARTICLE_STRATEGY_HOST: "127.0.0.1",
    ARTICLE_STRATEGY_PORT: String(BACKEND_PORT),
    STORAGE_ROOT: userStorageRoot()
  };

  backendProcess = spawn(backend.command, backend.args, {
    cwd: backend.cwd,
    env,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"]
  });

  const logPath = path.join(app.getPath("userData"), "backend.log");
  const log = fs.createWriteStream(logPath, { flags: "a" });
  backendProcess.stdout.pipe(log);
  backendProcess.stderr.pipe(log);

  backendProcess.on("exit", (code) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("backend-exit", code);
    }
  });
}

function requestOk(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume();
      resolve(res.statusCode >= 200 && res.statusCode < 500);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(1000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForBackend() {
  const healthUrl = `http://127.0.0.1:${BACKEND_PORT}/health`;
  for (let i = 0; i < 90; i += 1) {
    if (await requestOk(healthUrl)) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`后端启动超时：${healthUrl}`);
}

function contentType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".html") return "text/html; charset=utf-8";
  if (ext === ".js") return "text/javascript; charset=utf-8";
  if (ext === ".css") return "text/css; charset=utf-8";
  if (ext === ".json") return "application/json; charset=utf-8";
  if (ext === ".svg") return "image/svg+xml";
  if (ext === ".png") return "image/png";
  if (ext === ".ico") return "image/x-icon";
  return "application/octet-stream";
}

function startFrontendServer() {
  const root = frontendDir();
  if (!fs.existsSync(path.join(root, "index.html"))) {
    throw new Error(`前端构建目录不存在或缺少 index.html：${root}`);
  }

  staticServer = http.createServer((req, res) => {
    const urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
    const cleanPath = path.normalize(urlPath).replace(/^(\.\.[/\\])+/, "");
    let filePath = path.join(root, cleanPath === "/" ? "index.html" : cleanPath);
    if (!filePath.startsWith(root) || !fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      filePath = path.join(root, "index.html");
    }

    res.writeHead(200, { "Content-Type": contentType(filePath) });
    fs.createReadStream(filePath).pipe(res);
  });

  return new Promise((resolve, reject) => {
    staticServer.once("error", reject);
    staticServer.listen(FRONTEND_PORT, "127.0.0.1", resolve);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1420,
    height: 920,
    minWidth: 1100,
    minHeight: 720,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.loadURL(`http://127.0.0.1:${FRONTEND_PORT}`);
}

async function boot() {
  try {
    startBackend();
    await waitForBackend();
    await startFrontendServer();
    createWindow();
  } catch (error) {
    dialog.showErrorBox("启动失败", `${error.message}\n\n日志目录：${app.getPath("userData")}`);
    app.quit();
  }
}

app.whenReady().then(boot);

app.on("window-all-closed", () => {
  app.quit();
});

app.on("before-quit", () => {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
  if (staticServer) {
    staticServer.close();
  }
});
