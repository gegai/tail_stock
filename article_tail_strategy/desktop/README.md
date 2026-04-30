# Electron desktop shell

This folder packages the React frontend and FastAPI backend into a Windows desktop app.

Development run:

```powershell
cd article_tail_strategy/frontend
npm run build

cd ../desktop
npm install
npm start
```

Directory package with a double-clickable exe:

```powershell
cd article_tail_strategy
.\scripts\build_desktop.ps1
```

Optional installer package, which needs electron-builder to download NSIS resources:

```powershell
.\scripts\build_desktop.ps1 -Installer
```

The packaged app starts the backend on `127.0.0.1:8001` and serves the built frontend on
`127.0.0.1:4175`. Backtest records are stored under the app user data directory so the
installed app can write them without needing admin permissions.
