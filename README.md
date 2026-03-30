# 🎵 Spotify → YouTube Music Sync

A production-grade web application that synchronizes your Spotify playlists to YouTube Music—including **Liked Songs**—with real-time progress, parallel execution, crash-resume, and a lightweight web-based management launcher.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi&logoColor=white)
![Vanilla JS](https://img.shields.io/badge/Frontend-Vanilla%20JS-F7DF1E?logo=javascript&logoColor=black)
![SQLite](https://img.shields.io/badge/Storage-SQLite-003B57?logo=sqlite&logoColor=white)
![Version](https://img.shields.io/badge/Engine-v2.2.0-blueviolet)

---

## 📖 Index
1. [✨ Features](#-features)
2. [🚀 Getting Started](#-getting-started-windows)
3. [🔑 How to Get YouTube Music Cookies](#-how-to-get-youtube-music-cookies)
4. [⚠️ Spotify Premium Workaround (CSV)](#-spotify-premium-restriction-workaround)
5. [🗂️ Project Structure](#-project-structure)
6. [🛡️ License](#-license)

---

## ✨ Features

### 🔄 Core Engine
- **Smart Delta Sync**: Only processes new tracks; unchanged playlists are skipped in <1s.
- **Direct YTM API**: Uses internal internal/manual API calls (`WEB_REMIX`) for 100% library visibility, including Liked Music.
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

Follow these steps in order to set up the synchronizer:

### Step 1: Prerequisites
- **Python 3.10+** — [Download here](https://www.python.org/downloads/) (Ensure "Add to PATH" is checked).
- **Spotify Developer App** — Create one at [Spotify Dashboard](https://developer.spotify.com/dashboard).
- **Cookie Extension** — Install a "Copy Cookies" extension (e.g., [Copy Cookies](https://chrome.google.com/webstore/detail/copy-cookies/iphcomljgeghcehfbngchmfdbmhkfkbi)).

### Step 2: Initial Configuration
1.  **Configure Spotify**:
    - Add `http://127.0.0.1:8000/api/spotify/callback` to your Spotify App's **Redirect URIs**.
    - Create a file named `.env` inside the `backend` folder.
    - Add your credentials:
      ```env
      CLIENT_ID=your_spotify_client_id
      CLIENT_SECRET=your_spotify_client_secret
      ```
2.  **Install Dependencies**:
    - Open a terminal in the `backend` folder and run: `pip install -r requirements.txt`.

### Step 3: Launch & Authenticate
1.  Double-click **`START - Spotify Sync.bat`** in the root folder.
2.  Your browser will open to **`http://localhost:8081`** (Web Launcher).
3.  Click **"▶ Start App"**. Wait for the status indicator to turn green.
4.  Click **"🌐 Open App"**.
5.  **Connect Spotify**: Click the Spotify Login button in the app.
6.  **Connect YouTube Music**: Follow the [Cookie Instructions](#-how-to-get-youtube-music-cookies) below.

---

## 🔑 How to Get YouTube Music Cookies

The app requires your session cookies to interact with your YouTube Music account. Follow these steps to extract them safely:

1.  **Install an Extension**: Install a **"Copy Cookies"** extension from the Chrome Web Store.
2.  **Login**: Go to [music.youtube.com](https://music.youtube.com) and ensure you are logged in.
3.  **Export Cookies**:
    - Click the extension icon in your toolbar.
    - Click **"Copy"** or **"Export"** to copy your session cookies to the clipboard.
4.  **Paste in App**:
    - Go back to the Sync App (`localhost:8000`).
    - Select the **YouTube Music Auth** tab or click the "Fix" button on the YouTube status badge.
    - Paste the content from your clipboard into the text box and click **Save**.
5.  **Verify**: The status badge should turn green with "Authenticated".

---

## ⚠️ Spotify Premium Restriction Workaround

If you do not have **Spotify Premium**, you may encounter an error stating: *"Your application is blocked from accessing the Web API..."*.

**Follow the CSV Workaround:**
1.  Go to **[Exportify](https://exportify.net/)** and log in with Spotify.
2.  Find the playlist you want to sync and click **Export**. Save the `.csv` file.
3.  In the Sync App, click **📁 Import CSV** in the sidebar.
4.  Upload the `.csv` and sync—**No API or Premium required!**

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
