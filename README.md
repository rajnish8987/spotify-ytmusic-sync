# 🎵 Spotify → YouTube Music Sync

A production-grade web application that synchronizes your Spotify playlists to YouTube Music—including **Liked Songs**—with real-time progress, parallel execution, crash-resume, and a lightweight web-based management launcher.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi&logoColor=white)
![Vanilla JS](https://img.shields.io/badge/Frontend-Vanilla%20JS-F7DF1E?logo=javascript&logoColor=black)
![SQLite](https://img.shields.io/badge/Storage-SQLite-003B57?logo=sqlite&logoColor=white)
![Version](https://img.shields.io/badge/Engine-v2.2.0-blueviolet)

---

## ✨ Features

### 🔄 Core Engine
- **Smart Delta Sync**: Only processes new tracks; unchanged playlists are skipped in <1s.
- **Parallel Playlists**: Sync multiple playlists simultaneously (1–6 concurrent slots).
- **Auto-Retry Unmatched**: Automatically retries missed tracks with fallback artist/title-only queries.
- **Crash Recovery**: Saves partial progress; resumes seamlessly after a browser or server restart.

### 🖥️ Premium UI & Progress
- **🚀 Web Launcher**: A dedicated browser panel (`localhost:8081`) to start/stop the backend and view logs.
- **📊 Progress Rings**: Interactive SVG rings showing live search/upload progress per playlist.
- **⏳ Live ETA**: Real-time estimations for remaining search and upload times.
- **👁️ Preview & Reorder**: Review tracks before sync and drag playlists to prioritize execution.
- **📁 CSV Import**: Import Spotify playlists via CSV (Workaround for non-Premium accounts).

### 🏥 System Health & Management
- **🏥 Health Badge**: Live monitoring of Spotify, YT Music, and Database status.
- **🍪 Cookie Expiry Alerts**: Global banner and notifications when YT Music cookies are expiring.
- **📊 History & Analytics**: Full sync history, match rate charts, and log downloads.
- **↩️ Undo Last Sync**: Remove tracks added in the most recent run with one click.

---

## 🚀 Getting Started (Windows)

### 1. Prerequisites
- **Python 3.10+** — [python.org](https://www.python.org/downloads/) (Add to PATH).
- **Spotify Developer Account** — [developer.spotify.com](https://developer.spotify.com/dashboard).
- **EditThisCookie extension** — For exporting YouTube cookies.

### 2. Initial Setup
1.  Navigate to the `backend` folder and run `pip install -r requirements.txt`.
2.  **Connect Spotify**: Create an app in the Spotify Dashboard, add `http://127.0.0.1:8000/api/spotify/callback` to Redirect URIs, and create a `backend/.env` with your `CLIENT_ID` and `CLIENT_SECRET`.

### 3. Launching the App
1.  Double-click **`START - Spotify Sync.bat`** in the root folder.
2.  A new browser tab will open at **`http://localhost:8081`** (Web Launcher).
3.  Click **"▶ Start App"**. Wait for the status to turn green.
4.  Click **"🌐 Open App"** to begin syncing!

---

## ⚠️ Spotify Premium Restriction Workaround
If you do not have **Spotify Premium**, you may encounter an error stating: *"Your application is blocked from accessing the Web API..."*.

**Follow the CSV Workaround:**
1.  Go to **[Exportify](https://exportify.net/)** and log in with Spotify.
2.  You will see a list of your playlists (e.g., "117 playlists").
3.  Click **Export** next to the playlist you want to sync. Save the `.csv` file.
4.  In the Sync App, click **📁 Import CSV** in the sidebar.
5.  Upload the `.csv` and sync as normal—**No API or Premium required!**

---

## 🗂️ Project Structure
```
spotify-ytmusic-sync/
├── backend/                      # FastAPI Backend & Sync Engine
├── frontend/                     # Main Web UI (JS/CSS/HTML)
├── launcher-web/                 # Web Launcher UI
├── launcher_server.ps1           # Launcher Backend (Port 8081)
├── START - Spotify Sync.bat      # Main One-click Launcher
├── sync_history.db               # SQLite Database (auto-generated)
└── README.md
```

---

## 🛡️ License
MIT — Free to use, modify, and distribute.
