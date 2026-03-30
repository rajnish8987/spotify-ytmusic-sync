const API = "http://127.0.0.1:8000/api";

// ── State ─────────────────────────────────────────────────────────────────────
let spotifyAuthed = false, ytAuthed = false;
let isSpotifySkipped = false;        // CSV Mode
let allPlaylists = [];
let csvPlaylists = [];               // Manually generated from CSV
let selectedPlaylists = new Set();
let excludedTracks = {};             // { playlistId: Set<trackId> }
let lastRunIds = [];
let currentFilter = "all";
let activeTab = "sync";
let excludedPlaylistIds = new Set(); // Feature #12
let lastSyncNotFoundList = [];       // Feature #6
let undoEntries = [];                // Feature #11

// ── Element Refs ──────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
    setupNavigation();
    setupContextMenu();
    setupLibraryHandlers();

    // Check Spotify — try playlists first, then lightweight token check, then /health
    try {
        const r = await fetch(`${API}/spotify/playlists`);
        if (r.ok) setAuth("spotify", true, false);
        else {
            // Playlists endpoint may 400 on transient Spotify API errors
            // even though OAuth token is valid — check lightweight endpoint
            const chk = await fetch(`${API}/spotify/check-auth`).then(r => r.json()).catch(() => null);
            if (chk && chk.authenticated) setAuth("spotify", true, false);
            else {
                // Final fallback: /health
                const h = await fetch(`${API}/health`).then(r => r.json()).catch(() => null);
                if (h && h.spotify && h.spotify.status === "ok") setAuth("spotify", true, false);
            }
        }
    } catch (_) {}

    // Check YT Music
    try {
        const r = await fetch(`${API}/ytmusic/check-auth`);
        const d = await r.json();
        if (d.authenticated) setAuth("yt", true, false);
        else if (await fetch(`${API}/ytmusic/playlists`).then(r => r.ok).catch(() => false))
            setAuth("yt", true, false);
    } catch (_) {}

    if (spotifyAuthed && ytAuthed) proceedToPlaylists();

    // Cookie expiry check
    fetchCookieExpiry();

    // Load excluded playlists from backend (Feature #12)
    loadExcludedPlaylists();

    // Notification permission state (Feature #9)
    updateNotifStatus();

    // Check undo state (Feature #11)
    checkUndoState();

    // Load recent unmatched tracks so panel survives page reload (Feature #3)
    loadRecentUnmatched();

    // Health badge — initial load + poll every 30s
    loadHealthBadge();
    setInterval(loadHealthBadge, 30_000);

    // Cookie expiry global banner check (Feature #3 extension)
    checkCookieExpiryBanner();

    // Load parallelism config into slider (Feature #7)
    loadConfig();

    // Periodic auth check
    setInterval(async () => {
        if (ytAuthed) {
            const r = await fetch(`${API}/ytmusic/check-auth`).then(r => r.json()).catch(() => ({}));
            if (!r.authenticated) {
                $("auth-banner").classList.remove("hidden");
                setAuth("yt", false, false);
            }
        }
    }, 5 * 60 * 1000);
}

async function fetchCookieExpiry() {
    try {
        const info = await fetch(`${API}/ytmusic/cookie-expiry`).then(r => r.json());
        renderExpiryBadge(info);
    } catch (_) {}
}

function renderExpiryBadge(info) {
    const old = document.getElementById('expiry-badge');
    if (old) old.remove();

    if (info.status === 'unknown' || info.days_remaining === null) return;

    const colors = { ok: '#22c55e', warning: '#f59e0b', critical: '#ef4444', expired: '#ef4444' };
    const icons  = { ok: '🍪', warning: '⚠️', critical: '🚨', expired: '💀' };
    const color = colors[info.status] || '#9494b0';
    const icon  = icons[info.status]  || '🍪';

    const badge = document.createElement('div');
    badge.id = 'expiry-badge';
    badge.title = info.status === 'expired' ? 'Cookies have expired — update them in Settings'
                                             : `Cookies expire in ${info.days_remaining} days`;
    badge.style.cssText = `
        background:${color}18; border:1px solid ${color}50; border-radius:8px;
        padding:0.4rem 0.75rem; font-size:0.76rem; color:${color};
        display:flex; align-items:center; gap:0.4rem; cursor:pointer;
        width: 100%; box-sizing:border-box; margin-top: auto;
    `;
    badge.innerHTML = `${icon} <span>${
        info.status === 'expired' ? 'Cookies expired!' :
        info.status === 'critical' ? `Expires in ${info.days_remaining}d!` :
        `Cookies: ${info.days_remaining}d left`
    }</span>`;
    badge.addEventListener('click', () => switchTab('settings'));
    
    // Append at the very bottom of the sidebar
    document.querySelector('.sidebar').appendChild(badge);

    if (info.status === 'critical' || info.status === 'expired') {
        const msg = info.status === 'expired'
            ? 'Your YouTube Music cookies have expired. Please update them in Settings.'
            : `Your YouTube Music cookies expire in ${info.days_remaining} day(s). Update them soon in Settings.`;
        $('settings-yt-msg').textContent = '⚠ ' + msg;
        $('settings-yt-msg').style.color = 'var(--warn)';

        // Feature #15: Browser notification for cookie expiry
        if (Notification.permission === 'granted' && info.days_remaining <= 7) {
            new Notification('🍪 Syncify: Cookie Expiring Soon', {
                body: `Your YouTube Music cookies expire in ${info.days_remaining} day(s). Update them in Settings.`,
                icon: '/favicon.ico'
            });
        }
    }
}

// ── Navigation ─────────────────────────────────────────────────────────────────
function setupNavigation() {
    document.querySelectorAll(".nav-link").forEach(link => {
        link.addEventListener("click", e => {
            e.preventDefault();
            switchTab(link.dataset.tab);
        });
    });
}

function switchTab(tab) {
    activeTab = tab;
    document.querySelectorAll(".nav-link").forEach(l => l.classList.toggle("active", l.dataset.tab === tab));
    document.querySelectorAll(".tab").forEach(t => t.classList.toggle("hidden", t.id !== `tab-${tab}`));
    if (tab === "history") loadHistory();
    if (tab === "analytics") loadAnalytics();
    if (tab === "schedules") loadSchedules();
    if (tab === "settings") loadExcludedPlaylists();
    if (tab === "library") loadYTLibrary();
}

function openSettings() { switchTab("settings"); }

// ── Auth ───────────────────────────────────────────────────────────────────────
async function setAuth(service, authed, doCheck = true) {
    if (service === "spotify") {
        spotifyAuthed = authed;
        $("sidebar-spotify").className = `status-dot ${authed ? "ok" : "error"}`;
        $("spotify-auth-status").textContent = authed ? "✅ Connected" : "Not connected";
        $("spotify-auth-status").style.color = authed ? "var(--succ)" : "var(--text-sec)";
        if (authed) { $("btn-spotify-auth").textContent = "Connected ✓"; $("btn-spotify-auth").disabled = true; }
    } else {
        ytAuthed = authed;
        $("sidebar-yt").className = `status-dot ${authed ? "ok" : "error"}`;
        $("yt-auth-status").textContent = authed ? "✅ Connected" : "Not connected";
        $("yt-auth-status").style.color = authed ? "var(--succ)" : "var(--text-sec)";
        if (authed) { 
            $("btn-yt-auth").textContent = "Connected ✓"; 
            $("btn-yt-auth").disabled = true; 
            $("yt-auth-form").classList.add("hidden"); 
            // Fetch identity
            try {
                const info = await fetch(`${API}/ytmusic/whoami`).then(r => r.json());
                if (info.authenticated) {
                    $("yt-identity-info").classList.remove("hidden");
                    $("yt-user-name").textContent = info.name;
                }
            } catch (_) {}
        } else {
            $("yt-identity-info").classList.add("hidden");
        }
        $("auth-banner").classList.toggle("hidden", authed);
    }
    if (doCheck && (spotifyAuthed || isSpotifySkipped) && ytAuthed) proceedToPlaylists();
}

// Spotify OAuth
$("btn-spotify-auth").addEventListener("click", async () => {
    try {
        const { url } = await fetch(`${API}/spotify/auth-url`).then(r => r.json());
        window.open(url, "_blank", "width=600,height=650");
        // Poll lightweight token check instead of full playlists API (which can 403)
        const poll = setInterval(async () => {
            try {
                const chk = await fetch(`${API}/spotify/check-auth`).then(r => r.json());
                if (chk && chk.authenticated) {
                    clearInterval(poll); setAuth("spotify", true);
                }
            } catch (_) {}
        }, 2000);
    } catch { alert("Could not reach backend. Is the server running?"); }
});

$("btn-skip-spotify").addEventListener("click", () => {
    isSpotifySkipped = true;
    $("spotify-auth-status").textContent = "Skipped (CSV Mode)";
    $("spotify-auth-status").style.color = "var(--warn)";
    if (ytAuthed) proceedToPlaylists();
    else alert("Please connect to YouTube Music first, then we can proceed.");
});

$("btn-yt-auth").addEventListener("click", () => $("yt-auth-form").classList.toggle("hidden"));

$("btn-yt-save").addEventListener("click", async () => {
    const raw = $("yt-headers-input").value.trim();
    const brandId = $("yt-brand-id") ? $("yt-brand-id").value.trim() : null;
    if (!raw) { alert("Paste your cookie JSON first."); return; }
    await saveYTCookies(raw, $("btn-yt-save"), $("yt-auth-form"), brandId);
});

async function saveYTCookies(raw, btn, form, brandId = null) {
    try {
        let headersRaw = raw;
        try {
            const cookies = JSON.parse(raw);
            if (Array.isArray(cookies)) headersRaw = buildCookieFromJson(cookies);
        } catch (_) {}
        if (btn) { btn.textContent = "Saving..."; btn.disabled = true; }
        const res = await fetch(`${API}/ytmusic/save-headers`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ 
                headers_raw: headersRaw,
                brand_id: brandId || null 
            })
        });
        const data = await res.json();
        if (res.ok && data.status === "success") {
            setAuth("yt", true);
            $("auth-banner").classList.add("hidden");
            fetchCookieExpiry();
            return true;
        } else { alert("Failed: " + (data.detail || "Unknown error")); }
    } catch (e) { alert("Error: " + e.message); }
    if (btn) { btn.textContent = "Save & Connect ✓"; btn.disabled = false; }
    return false;
}

function buildCookieFromJson(cookies) {
    return cookies.map(c => `${c.name}=${c.value}`).join("; ");
}

$("btn-settings-save-yt").addEventListener("click", async () => {
    const raw = $("settings-cookie-input").value.trim();
    if (!raw) { $("settings-yt-msg").textContent = "⚠ Paste your cookie JSON first."; return; }
    const ok = await saveYTCookies(raw, $("btn-settings-save-yt"), null);
    $("settings-yt-msg").textContent = ok ? "✅ Cookies updated successfully!" : "❌ Failed to save cookies.";
    $("settings-yt-msg").style.color = ok ? "var(--succ)" : "var(--err)";
});

$("btn-settings-reauth-spotify").addEventListener("click", () => {
    $("btn-spotify-auth").disabled = false;
    $("btn-spotify-auth").textContent = "Connect Spotify";
    isSpotifySkipped = false;
    setAuth("spotify", false, false);
    switchTab("sync");
    $("section-auth").classList.add("active");
});

// ── CSV Import Logic ──────────────────────────────────────────────
$("btn-import-csv").addEventListener("click", () => $("csv-modal").classList.remove("hidden"));
$("btn-csv-close").addEventListener("click", () => $("csv-modal").classList.add("hidden"));

$("csv-file-input").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) {
        $("csv-file-name").textContent = file.name;
        $("btn-csv-process").disabled = false;
        $("btn-csv-process").dataset.filename = file.name.replace('.csv', '');
    } else {
        $("csv-file-name").textContent = "No file selected";
        $("btn-csv-process").disabled = true;
    }
});

$("btn-csv-process").addEventListener("click", () => {
    const file = $("csv-file-input").files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (e) => {
        try {
            const text = e.target.result;
            const lines = text.split('\n').map(l => l.trim()).filter(l => l);
            if (lines.length < 2) throw new Error("File looks empty or invalid.");
            
            // Robust CSV parser that handles quoted fields with commas and escaped quotes
            const splitCsv = (line) => {
                const result = [];
                let current = "";
                let inQuotes = false;
                for (let i = 0; i < line.length; i++) {
                    const char = line[i];
                    if (char === '"' && line[i+1] === '"') { // Escaped quote
                        current += '"'; i++;
                    } else if (char === '"') {
                        inQuotes = !inQuotes;
                    } else if (char === ',' && !inQuotes) {
                        result.push(current.trim());
                        current = "";
                    } else {
                        current += char;
                    }
                }
                result.push(current.trim());
                return result;
            };

            const headers = splitCsv(lines[0]).map(h => h.toLowerCase().replace(/"/g, '').trim());
            const trackIdx = headers.findIndex(h => h.includes('track name') || h === 'track');
            const artistIdx = headers.findIndex(h => h.includes('artist') || h === 'artist name');
            const durationIdx = headers.findIndex(h => h.includes('duration'));
            
            if (trackIdx === -1) throw new Error("Could not find 'Track Name' (or 'Track') column in CSV.");
            
            const tracks = [];
            for (let i = 1; i < lines.length; i++) {
                const row = splitCsv(lines[i]);
                if (!row[trackIdx]) continue;
                
                let artist = artistIdx !== -1 ? row[artistIdx] || "" : "";
                let trackName = row[trackIdx];
                let durationMs = (durationIdx !== -1 && row[durationIdx]) ? parseInt(row[durationIdx]) : 0;
                
                tracks.push({
                    name: trackName,
                    artist: artist,
                    query: `${trackName} ${artist}`.trim(),
                    duration_ms: isNaN(durationMs) ? 0 : durationMs
                });
            }
            
            if (tracks.length === 0) throw new Error("No tracks found in CSV.");
            
            // Create a fake playlist object
            const baseFilename = $("btn-csv-process").dataset.filename || "Imported CSV";
            const plId = "csv_" + Date.now();
            const playlist = {
                id: plId,
                name: `[CSV] ${baseFilename}`,
                tracks: { total: tracks.length },
                is_csv: true,
                _raw_tracks: tracks // store the tracks here so we can send them to backend
            };
            
            csvPlaylists.push(playlist);
            allPlaylists.unshift(playlist); // Put it at the top
            
            $("csv-modal").classList.add("hidden");
            $("csv-file-input").value = "";
            $("csv-file-name").textContent = "No file selected";
            $("btn-csv-process").disabled = true;
            
            renderPlaylists();
            alert(`Successfully imported ${tracks.length} tracks from ${file.name}!`);
            
        } catch (err) {
            alert("Error parsing CSV: " + err.message);
        }
    };
    reader.readAsText(file);
});

// ── Feature #9: Browser Notifications ─────────────────────────────────────────
function updateNotifStatus() {
    const btn = $("btn-enable-notifications");
    const status = $("notif-status");
    if (!("Notification" in window)) {
        if (status) status.textContent = "Not supported in this browser";
        if (btn) btn.disabled = true;
        return;
    }
    const perm = Notification.permission;
    if (status) {
        status.textContent = perm === "granted" ? "✅ Enabled" : perm === "denied" ? "❌ Blocked by browser" : "Not enabled";
        status.style.color = perm === "granted" ? "var(--succ)" : perm === "denied" ? "var(--err)" : "var(--text-sec)";
    }
    if (btn) btn.textContent = perm === "granted" ? "Notifications On ✓" : "Enable Notifications";
}

$("btn-enable-notifications").addEventListener("click", async () => {
    if (!("Notification" in window)) return;
    const perm = await Notification.requestPermission();
    updateNotifStatus();
    if (perm === "granted") {
        new Notification("🎵 Syncify Notifications Enabled!", { body: "You'll be notified when a sync completes." });
    }
});

function sendSyncNotification(stats) {
    if (Notification.permission !== "granted") return;
    const total = stats.total_matched + stats.total_not_found;
    new Notification("✅ Syncify Sync Complete!", {
        body: `${stats.total_added} tracks added · ${stats.total_matched}/${total} matched · ${stats.total_not_found} not found`,
        icon: '/favicon.ico'
    });
}

// ── Feature #12: Excluded Playlists ───────────────────────────────────────────
async function loadExcludedPlaylists() {
    try {
        const { excluded } = await fetch(`${API}/excluded-playlists`).then(r => r.json());
        excludedPlaylistIds = new Set(excluded.map(e => e.id));
        renderExcludedList(excluded);
    } catch (_) {}
}

function renderExcludedList(excluded) {
    const el = $("excluded-list");
    if (!el) return;
    if (!excluded.length) {
        el.innerHTML = `<p style="font-size:0.82rem; color:var(--text-sec); font-style:italic;">No playlists excluded yet.</p>`;
        return;
    }
    el.innerHTML = excluded.map(e => `
        <div style="display:flex; align-items:center; justify-content:space-between; padding:0.5rem 0; border-bottom:1px solid var(--border);">
            <span style="font-size:0.9rem;">🚫 ${e.name}</span>
            <button onclick="unexcludePlaylist('${e.id}')" class="btn secondary small" style="color:var(--succ);">✓ Re-include</button>
        </div>
    `).join("");
}

async function excludePlaylist(id, name) {
    await fetch(`${API}/excluded-playlists`, {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ playlist_id: id, playlist_name: name })
    });
    excludedPlaylistIds.add(id);
    selectedPlaylists.delete(id);
    await loadExcludedPlaylists();
    renderPlaylists();
    updateActions();
}

async function unexcludePlaylist(id) {
    await fetch(`${API}/excluded-playlists/${id}`, { method: "DELETE" });
    excludedPlaylistIds.delete(id);
    await loadExcludedPlaylists();
    renderPlaylists();
}

window.unexcludePlaylist = unexcludePlaylist;

// ── Context Menu for playlist cards ──────────────────────────────────────────
let ctxPlaylistId = null, ctxPlaylistName = null;

function setupContextMenu() {
    document.addEventListener("contextmenu", e => {
        const card = e.target.closest(".playlist-card");
        if (!card) { $("ctx-menu").style.display = "none"; return; }
        e.preventDefault();
        ctxPlaylistId = card.dataset.id;
        ctxPlaylistName = card.dataset.name;
        const menu = $("ctx-menu");
        menu.style.display = "block";
        menu.style.left = `${Math.min(e.clientX, window.innerWidth - 180)}px`;
        menu.style.top = `${Math.min(e.clientY, window.innerHeight - 80)}px`;
    });
    document.addEventListener("click", () => { $("ctx-menu").style.display = "none"; });
    $("ctx-exclude").addEventListener("click", () => {
        if (ctxPlaylistId) excludePlaylist(ctxPlaylistId, ctxPlaylistName);
        $("ctx-menu").style.display = "none";
    });
}

// ── Feature #11: Undo Last Sync ───────────────────────────────────────────────
async function checkUndoState() {
    try {
        const state = await fetch(`${API}/sync/undo-state`).then(r => r.json());
        if (state.available && $("undo-banner")) {
            $("undo-banner").classList.remove("hidden");
        }
    } catch (_) {}
}

$("btn-undo-sync").addEventListener("click", async () => {
    if (!confirm("This will remove all tracks added in the last sync from your YouTube Music playlists. Continue?")) return;
    const btn = $("btn-undo-sync");
    btn.textContent = "Undoing..."; btn.disabled = true;
    try {
        const res = await fetch(`${API}/sync/undo`, { method: "POST" });
        const data = await res.json();
        if (res.ok) {
            alert(`✅ Undo complete. ${data.tracks_removed} tracks removed.`);
            $("undo-banner").classList.add("hidden");
        } else {
            alert("❌ Undo failed: " + (data.detail || "Unknown error"));
        }
    } catch (e) { alert("Error: " + e.message); }
    btn.textContent = "Undo Sync"; btn.disabled = false;
});

// ── Feature #3: Persist Not-Found panel across page reloads ──────────────────
async function loadRecentUnmatched() {
    try {
        const { tracks } = await fetch(`${API}/unmatched/recent`).then(r => r.json());
        if (!tracks || !tracks.length) return;
        // Pre-populate the not-found list from DB — shown in the stats section
        lastSyncNotFoundList = tracks.map(t => ({ name: t.name, artist: t.artist, playlist: t.playlist }));

        // Reveal the stats section + not-found panel if we have data
        // (without overwriting the main sync section — only show if stats are already visible)
        const panel = $("not-found-panel");
        const list  = $("not-found-list");
        if (!panel || !list) return;

        list.innerHTML = tracks.map(t => {
            const q = encodeURIComponent(t.name + (t.artist ? ` ${t.artist}` : ""));
            return `
            <div style="display:flex; align-items:center; justify-content:space-between; padding:0.5rem 0; border-bottom:1px solid var(--border);">
                <div>
                    <span style="font-weight:500; font-size:0.9rem;">${t.name}</span>
                    ${t.artist ? `<span style="font-size:0.8rem; color:var(--text-sec); margin-left:0.5rem;">${t.artist}</span>` : ""}
                    ${t.playlist ? `<span style="font-size:0.75rem; color:var(--text-sec); margin-left:0.5rem; opacity:0.6;">[${t.playlist}]</span>` : ""}
                </div>
                <a href="https://music.youtube.com/search?q=${q}" target="_blank" class="btn secondary small">🔍 Search YT Music</a>
            </div>`;
        }).join("");

        // Add a "from last sync" label if stats panel isn't open
        if ($("stats-dashboard").classList.contains("hidden")) {
            // Show a minimal persistent unmatched panel in the sync section header area
            const existingBadge = document.getElementById("persistent-unmatched-badge");
            if (!existingBadge) {
                const badge = document.createElement("div");
                badge.id = "persistent-unmatched-badge";
                badge.className = "glass-card";
                badge.style.cssText = "margin:1rem 0; border-color:var(--warn); padding:0.75rem 1rem; display:flex; align-items:center; justify-content:space-between;";
                badge.innerHTML = `
                    <span style="font-size:0.88rem; color:var(--warn);">⚠ ${tracks.length} unmatched tracks from your last sync</span>
                    <button onclick="document.getElementById('stats-dashboard').classList.remove('hidden'); document.getElementById('not-found-panel').classList.remove('hidden'); this.closest('#persistent-unmatched-badge').remove();" class="btn secondary small">View Panel</button>
                `;
                const syncSection = $("section-sync");
                if (syncSection) syncSection.insertBefore(badge, syncSection.firstChild);
            }
        } else {
            panel.classList.remove("hidden");
        }
    } catch (_) {}
}

// ── Playlists ─────────────────────────────────────────────────────────────────
let syncResumePending = false;

async function proceedToPlaylists() {
    showSection("playlists");
    await checkResumeState();
    await loadPlaylists();
}

async function checkResumeState() {
    try {
        const res = await fetch(`${API}/sync/resume-state`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.can_resume) {
            $("resume-count").textContent = data.completed;
            $("resume-banner").classList.remove("hidden");
        }
    } catch (_) {}
}

$("btn-resume-banner-discard").addEventListener("click", async () => {
    $("resume-banner").classList.add("hidden");
    await fetch(`${API}/sync/resume-state`, { method: "DELETE" });
});

$("btn-resume-banner-sync").addEventListener("click", () => {
    $("resume-banner").classList.add("hidden");
    syncResumePending = true;
    startSync();
});

function showSection(name) {
    document.querySelectorAll(".section").forEach(s => s.classList.add("hidden"));
    $(`section-${name}`).classList.remove("hidden");
}

async function loadPlaylists() {
    $("playlist-grid").innerHTML = `<div class="loading-text">Loading Spotify playlists...</div>`;

    // If we skipped spotify, just show any loaded CSVs
    if (isSpotifySkipped && !spotifyAuthed) {
        allPlaylists = [...csvPlaylists]; // only show our manual CSVs
        renderPlaylists();
        checkResumeState();
        return;
    }

    try {
        const res = await fetch(`${API}/spotify/playlists`);
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        const { playlists } = await res.json();
        allPlaylists = [...csvPlaylists, ...playlists.filter(Boolean)];
        renderPlaylists();
    } catch (e) {
        if (spotifyAuthed) {
            $("playlist-grid").innerHTML = `
                <div class="error-text" style="max-width: 500px; margin: 0 auto; text-align: center;">
                    <p><strong>Spotify API Access Error</strong></p>
                    <p style="font-size: 0.9rem; margin-top: 0.5rem; color: var(--text-sec);">
                        You are authenticated, but Spotify blocked access to your playlists. 
                        If this app is in Spotify Development Mode, your account email must be added to the 
                        <strong>"Users and Access"</strong> list in the Spotify Developer Dashboard.
                    </p>
                    <p style="font-size: 0.8rem; margin-top: 1rem; color: var(--err); opacity: 0.8;">
                        Technical detail: ${e.message}
                    </p>
                </div>`;
        } else {
            $("playlist-grid").innerHTML = `<div class="error-text">Failed to load playlists. Is Spotify connected?</div>`;
        }
    }
}

function renderPlaylists() {
    const query = $("playlist-search").value.toLowerCase();
    const sort = $("sort-select").value;

    let list = allPlaylists.filter(p => {
        if (!p) return false;
        if (excludedPlaylistIds.has(p.id)) return false; // Feature #12
        const name = (p.name || "").toLowerCase();
        if (!name.includes(query)) return false;
        if (currentFilter === "synced" && !p.last_synced) return false;
        if (currentFilter === "unsynced" && p.last_synced) return false;
        return true;
    });

    if (sort === "name") list.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    else if (sort === "size-desc") list.sort((a, b) => (b.tracks?.total || 0) - (a.tracks?.total || 0));
    else if (sort === "size-asc") list.sort((a, b) => (a.tracks?.total || 0) - (b.tracks?.total || 0));
    else if (sort === "recent") list.sort((a, b) => (b.last_synced || 0) - (a.last_synced || 0));

    const grid = $("playlist-grid");
    grid.innerHTML = "";

    if (!list.length) {
        grid.innerHTML = `<div class="empty-text">No playlists match your filter.</div>`;
        return;
    }

    list.forEach(p => {
        const isSelected = selectedPlaylists.has(p.id);
        const img = p.images?.[0]?.url || "";
        const lastSync = p.last_synced ? new Date(p.last_synced * 1000).toLocaleDateString() : null;

        const el = document.createElement("div");
        el.className = `playlist-card${isSelected ? " selected" : ""}`;
        el.dataset.id = p.id;
        el.dataset.name = p.name;
        el.innerHTML = `
            <div class="playlist-cover">
                ${img ? `<img src="${img}" alt="${p.name}" loading="lazy">` : `<div class="cover-placeholder">🎵</div>`}
                <div class="playlist-check">${isSelected ? "✓" : ""}</div>
            </div>
            <div class="playlist-info">
                <p class="playlist-name" title="${p.name}">${p.name}</p>
                <p class="playlist-meta">${p.tracks?.total || 0} tracks</p>
                ${lastSync ? `<p class="playlist-synced">Synced ${lastSync}</p>` : ""}
            </div>`;

        el.addEventListener("click", () => togglePlaylist(p.id, el));
        grid.appendChild(el);
    });
}

function togglePlaylist(id, el) {
    if (selectedPlaylists.has(id)) {
        selectedPlaylists.delete(id);
        el.classList.remove("selected");
        el.querySelector(".playlist-check").textContent = "";
    } else {
        selectedPlaylists.add(id);
        el.classList.add("selected");
        el.querySelector(".playlist-check").textContent = "✓";
    }
    updateActions();
}

function updateActions() {
    const n = selectedPlaylists.size;
    $("selected-count").textContent = `${n} selected`;
    $("btn-preview").disabled = n === 0;
    $("btn-start-sync").disabled = n === 0;
    const schedCount = $("schedule-pl-count");
    if (schedCount) {
        schedCount.textContent = `${n} playlists selected`;
        $("btn-save-schedule").disabled = n === 0;
    }
}

$("playlist-search").addEventListener("input", renderPlaylists);
$("sort-select").addEventListener("change", renderPlaylists);
document.querySelectorAll(".filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        currentFilter = btn.dataset.filter;
        renderPlaylists();
    });
});

// ── Preview Modal ──────────────────────────────────────────────────────────────
$("btn-preview").addEventListener("click", openPreview);
$("btn-modal-close").addEventListener("click", () => $("preview-modal").classList.add("hidden"));
$("btn-modal-sync").addEventListener("click", () => {
    $("preview-modal").classList.add("hidden");
    const orderedPls = Array.from(document.querySelectorAll(".preview-playlist")).map(el => el.dataset.pl);
    if (orderedPls.length > 0) selectedPlaylists = new Set(orderedPls);
    syncResumePending = false;
    startSync();
});

async function openPreview() {
    $("preview-modal").classList.remove("hidden");
    $("preview-content").innerHTML = `<div class="loading-text">Loading track lists...</div>`;
    
    const spotifyIds = [];
    const localCsvs = [];
    for (const pid of selectedPlaylists) {
        if (pid.startsWith("csv_")) {
            const match = csvPlaylists.find(c => c.id === pid);
            if (match) localCsvs.push(match);
        } else {
            spotifyIds.push(pid);
        }
    }

    try {
        let fetchedPlaylists = [];
        if (spotifyIds.length > 0) {
            const res = await fetch(`${API}/preview`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ spotify_playlist_ids: spotifyIds })
            });
            const data = await res.json();
            fetchedPlaylists = data.playlists || [];
        }

        // Add our local CSV playlists into the preview format
        localCsvs.forEach(c => {
            fetchedPlaylists.push({
                id: c.id,
                name: c.name,
                image: "", // CSVs don't have cover images
                tracks: c._raw_tracks.map((t, i) => ({
                    id: `csv_track_${i}`,
                    name: t.name,
                    artist: t.artist,
                    duration_ms: t.duration_ms
                }))
            });
        });

        excludedTracks = {};
        $("preview-content").innerHTML = "";

        if (fetchedPlaylists.length === 0) {
            $("preview-content").innerHTML = `<div class="muted">No tracks to preview.</div>`;
            return;
        }

        fetchedPlaylists.forEach(pl => {
            excludedTracks[pl.id] = new Set();
            const section = document.createElement("div");
            section.className = "preview-playlist";
            section.dataset.pl = pl.id;
            section.innerHTML = `<h4 class="preview-pl-name" style="cursor:grab;">
                <span class="muted" style="margin-right:0.5rem">☰</span>
                ${pl.image ? `<img src="${pl.image}" class="preview-pl-img">` : "🎵"}
                ${pl.name} <span class="muted">(${pl.tracks.length} tracks)</span>
            </h4>`;
            const table = document.createElement("div");
            table.className = "preview-tracks";
            pl.tracks.forEach(t => {
                const row = document.createElement("label");
                row.className = "preview-track-row";
                row.innerHTML = `
                    <input type="checkbox" class="track-cb" data-pl="${pl.id}" data-id="${t.id}" checked>
                    <span class="track-name">${t.name}</span>
                    <span class="track-artist muted">${t.artist}</span>
                    <span class="track-dur muted">${formatMs(t.duration_ms)}</span>`;
                row.querySelector("input").addEventListener("change", e => {
                    if (!e.target.checked) excludedTracks[pl.id].add(t.id);
                    else excludedTracks[pl.id].delete(t.id);
                });
                table.appendChild(row);
            });
            section.appendChild(table);
            $("preview-content").appendChild(section);
        });
        if (typeof Sortable !== "undefined") {
            new Sortable($("preview-content"), { animation: 150, handle: ".preview-pl-name", ghostClass: "sortable-ghost" });
        }
    } catch (e) {
        $("preview-content").innerHTML = `<div class="error-text">Failed to load preview: ${e.message}</div>`;
    }
}

function formatMs(ms) {
    if (!ms) return "";
    const s = Math.floor(ms / 1000);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// ── Sync ───────────────────────────────────────────────────────────────────────
$("btn-start-sync").addEventListener("click", () => { syncResumePending = false; startSync(); });

async function startSync() {
    showSection("sync");
    $("sync-log").innerHTML = "";
    $("stats-dashboard").classList.add("hidden");
    $("not-found-panel").classList.add("hidden");
    $("undo-banner").classList.add("hidden");
    $("sync-progress").style.width = "5%";
    $("progress-pct").textContent = "5%";
    lastRunIds = [];
    undoEntries = [];
    lastSyncNotFoundList = [];

    const excludedMap = {};
    for (const [plId, idSet] of Object.entries(excludedTracks)) {
        excludedMap[plId] = Array.from(idSet);
    }

    // Separate normal spotify IDs from CSV playlists so we can send the raw tracks
    const spotifyIds = [];
    const csvPayloads = [];
    
    for (const pid of selectedPlaylists) {
        if (pid.startsWith("csv_")) {
            const match = csvPlaylists.find(c => c.id === pid);
            if (match) {
                csvPayloads.push({
                    id: match.id,
                    name: match.name,
                    tracks: match._raw_tracks
                });
            }
        } else {
            spotifyIds.push(pid);
        }
    }

    try {
        const isDryRun = $("chk-dry-run")?.checked || false;
        const res = await fetch(`${API}/sync`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                spotify_playlist_ids: spotifyIds,
                excluded_track_ids: excludedMap,
                dry_run: isDryRun,
                resume: syncResumePending,
                force_resync: $("chk-force-resync")?.checked || false,
                csv_playlists: csvPayloads.length > 0 ? csvPayloads : null
            })
        });

        if (!res.ok) { logMsg("Fatal: Could not start sync.", "error"); return; }

        // Wire up control buttons fresh for this sync session
        const btnPause  = $("btn-pause-sync");
        const btnResume = $("btn-resume-sync");
        const btnCancel = $("btn-cancel-sync");

        if (btnPause) {
            btnPause.classList.remove("hidden");
            btnPause.onclick = async () => {
                const r = await fetch(`${API}/sync/pause`, { method: "POST" });
                if (r.ok) { btnPause.classList.add("hidden"); btnResume.classList.remove("hidden"); }
            };
        }
        if (btnResume) {
            btnResume.classList.add("hidden");
            btnResume.onclick = async () => {
                const r = await fetch(`${API}/sync/resume`, { method: "POST" });
                if (r.ok) { btnResume.classList.add("hidden"); btnPause.classList.remove("hidden"); }
            };
        }
        if (btnCancel) {
            btnCancel.classList.remove("hidden");
            btnCancel.disabled = false;
            btnCancel.textContent = "🛑 Cancel";
            btnCancel.onclick = async () => {
                if (confirm("Are you sure you want to cancel the active sync?")) {
                    const r = await fetch(`${API}/sync/cancel`, { method: "POST" });
                    if (r.ok) { btnCancel.disabled = true; btnCancel.textContent = "Cancelling..."; }
                }
            };
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const chunks = buffer.split("\n\n");
            buffer = chunks.pop();

            for (const chunk of chunks) {
                if (!chunk.startsWith("data: ")) continue;
                try {
                    const ev = JSON.parse(chunk.slice(6));
                    if (ev.type === "log") {
                        logMsg(ev.msg, ev.level);
                    } else if (ev.type === "progress") {
                        const pct = Math.max(5, ev.value);
                        $("sync-progress").style.width = pct + "%";
                        $("progress-pct").textContent = pct + "%";
                    } else if (ev.type === "eta") {
                        // Update ETA chip next to the progress bar
                        let etaEl = $("eta-display");
                        if (!etaEl) {
                            etaEl = document.createElement("span");
                            etaEl.id = "eta-display";
                            etaEl.style.cssText = "font-size:0.78rem; color:var(--text-sec); margin-left:0.75rem; font-variant-numeric:tabular-nums;";
                            const pctEl = $("progress-pct");
                            if (pctEl && pctEl.parentNode) pctEl.parentNode.appendChild(etaEl);
                        }
                        const phase = ev.phase === "upload" ? "📤" : "🔍";
                        etaEl.textContent = `${phase} ${ev.label}${ev.playlist ? ` · ${ev.playlist}` : ""}`;
                    } else if (ev.type === "playlist_ring_init") {
                        createPlaylistRing(ev.playlist, ev.total_batches);
                    } else if (ev.type === "playlist_progress") {
                        updatePlaylistRing(ev.playlist, ev.batch, ev.total_batches);
                    } else if (ev.type === "stats") {
                        showStatsDashboard(ev);
                        // Collect all not-found tracks across playlists (with yt_playlist_id)
                        const allNotFound = (ev.playlists || []).flatMap(p => p.not_found_tracks || []);
                        if (allNotFound.length) renderNotFoundPanel(allNotFound);
                    } else if (ev.type === "done") {
                        $("sync-progress").style.width = "100%";
                        $("progress-pct").textContent = "100%";
                        $("stats-dashboard").classList.remove("hidden");
                        $("stats-dashboard").scrollIntoView({ behavior: "smooth" });
                        const ctrls = document.querySelector(".sync-controls");
                        if (ctrls) ctrls.classList.add("hidden");

                        // Feature #9: OS notification
                        if (ev.allow_notification) {
                            const lastStats = {
                                total_matched: parseInt($("stats-cards")?.querySelector(".stat-val")?.textContent || "0"),
                                total_not_found: 0, total_added: 0
                            };
                            sendSyncNotification(lastStats);
                        }
                        // Feature #11: Save undo state if tracks were added
                        if (undoEntries.length > 0) {
                            await fetch(`${API}/sync/save-undo`, {
                                method: "POST", headers: {"Content-Type":"application/json"},
                                body: JSON.stringify({ available: true, entries: undoEntries })
                            });
                            $("undo-banner").classList.remove("hidden");
                        }
                    }
                } catch (_) {}
            }
        }
    } catch (e) {
        logMsg(`Connection error: ${e.message}`, "error");
    }
    // Clear ETA chip and playlist rings on sync end
    const etaEl = $("eta-display");
    if (etaEl) etaEl.remove();
    clearPlaylistRings();
}

function logMsg(msg, level = "info") {
    const el = document.createElement("div");
    el.className = `log-entry ${level}`;
    el.textContent = msg;
    const log = $("sync-log");
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
}

// ── Stats Dashboard ────────────────────────────────────────────────────────────
function showStatsDashboard(stats) {
    const totalTracks = stats.playlists.reduce((s, p) => s + (p.total || 0), 0);
    const overallPct = totalTracks > 0 ? Math.round(stats.total_matched / totalTracks * 100) : 0;
    const totalExisted = stats.total_matched - stats.total_added;

    $("stats-cards").innerHTML = `
        <div class="stat-card"><div class="stat-val">${stats.total_matched}</div><div class="stat-lbl">Matched</div></div>
        <div class="stat-card warn"><div class="stat-val">${stats.total_not_found}</div><div class="stat-lbl">Not Found</div></div>
        <div class="stat-card info" style="border-color:#3b82f6;"><div class="stat-val" style="color:#3b82f6;">${totalExisted < 0 ? 0 : totalExisted}</div><div class="stat-lbl">Already Existed</div></div>
        <div class="stat-card ok"><div class="stat-val">${stats.total_added}</div><div class="stat-lbl">Added</div></div>
        <div class="stat-card"><div class="stat-val">${overallPct}%</div><div class="stat-lbl">Match Rate</div></div>`;

    const tbody = $("stats-tbody");
    tbody.innerHTML = "";
    stats.playlists.forEach(p => {
        const statusBadge = { created: "🆕", updated: "✏️", "renamed+updated": "✏️🔄", skipped: "❌" };
        const existed = p.matched - p.added;
        tbody.innerHTML += `<tr>
            <td title="${p.name}">${p.yt_name}</td>
            <td>${statusBadge[p.status] || p.status}</td>
            <td>${p.matched}</td>
            <td>${existed < 0 ? 0 : existed}</td>
            <td>${p.added}</td>
            <td>${p.match_pct}%</td>
            <td>${p.low_conf || 0}</td>
        </tr>`;
    });

    // Feature #6: Not Found Review Panel
    if (lastSyncNotFoundList.length > 0) {
        renderNotFoundPanel(lastSyncNotFoundList);
    }
}

function renderNotFoundPanel(tracks) {
    const panel = $("not-found-panel");
    const list = $("not-found-list");
    if (!panel || !list || !tracks.length) return;

    list.innerHTML = tracks.map((t, i) => {
        const q = encodeURIComponent(t.name + (t.artist ? ` ${t.artist}` : ""));
        const ytPid = t.yt_playlist_id || "";
        const rowId  = `nf-row-${i}`;
        const inpId  = `nf-inp-${i}`;
        const btnId  = `nf-btn-${i}`;
        const quickAdd = ytPid
            ? `<div style="display:flex;gap:0.4rem;margin-top:0.35rem;">
                <input id="${inpId}" type="text" placeholder="Paste YT Music URL or video ID"
                    style="flex:1;font-size:0.75rem;padding:0.25rem 0.5rem;border-radius:6px;
                           border:1px solid var(--border);background:var(--bg-card);color:var(--text);">
                <button id="${btnId}" class="btn secondary small"
                    onclick="quickAddTrack('${ytPid}','${t.name.replace(/'/g,"\\'").replace(/"/g,'&quot;')}','${(t.artist||'').replace(/'/g,"\\'").replace(/"/g,'&quot;')}','${inpId}','${btnId}','${rowId}')">
                    ➕ Add
                </button>
               </div>`
            : "";
        return `
        <div id="${rowId}" style="padding:0.5rem 0;border-bottom:1px solid var(--border);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
                <div>
                    <span style="font-weight:500;font-size:0.9rem;">${t.name}</span>
                    ${t.artist ? `<span style="font-size:0.8rem;color:var(--text-sec);margin-left:0.5rem;">${t.artist}</span>` : ""}
                </div>
                <a href="https://music.youtube.com/search?q=${q}" target="_blank" class="btn secondary small">🔍 Search</a>
            </div>
            ${quickAdd}
        </div>`;
    }).join("");

    panel.classList.remove("hidden");
}

$("btn-download-last-log").addEventListener("click", async () => {
    const { history } = await fetch(`${API}/history`).then(r => r.json()).catch(() => ({ history: [] }));
    if (!history.length) { alert("No history found."); return; }
    window.open(`${API}/history/${history[0].id}/log`, "_blank");
});

$("btn-sync-done").addEventListener("click", () => {
    selectedPlaylists.clear();
    excludedTracks = {};
    showSection("playlists");
    loadPlaylists();
});

// ── Analytics ──────────────────────────────────────────────────────────────────
let lastAnalyticsData = null, lastAnalyticsTime = 0;

async function loadAnalytics() {
    const now = Date.now();
    if (lastAnalyticsData && (now - lastAnalyticsTime < 3000)) {
        renderAnalytics(lastAnalyticsData); return;
    }
    if (!lastAnalyticsData) {
        $("library-overview-cards").innerHTML = `<div class="loading-text" style="grid-column: 1/-1;">Loading library stats...</div>`;
    }
    try {
        const [libRes, unRes] = await Promise.all([
            fetch(`${API}/analytics/library`).then(r => r.json()),
            fetch(`${API}/analytics/unmatched`).then(r => r.json()),
        ]);
        lastAnalyticsData = { libRes, unRes };
        lastAnalyticsTime = now;
        renderAnalytics(lastAnalyticsData);
    } catch (e) {
        if (!lastAnalyticsData)
            $("library-overview-cards").innerHTML = `<div class="error-text" style="grid-column: 1/-1;">Failed to load analytics.</div>`;
    }
}

function renderAnalytics(data) {
    const { libRes, unRes } = data;
    $("library-overview-cards").innerHTML = `
        <div class="stat-card"><div class="stat-lbl">Total Tracks Synced</div><div class="stat-val">${libRes.total_matched || 0}</div></div>
        <div class="stat-card"><div class="stat-lbl">Playlists Synced</div><div class="stat-val">${libRes.total_playlists || 0}</div></div>
        <div class="stat-card"><div class="stat-lbl">Avg Match Rate</div><div class="stat-val">${libRes.avg_match_pct ? libRes.avg_match_pct.toFixed(1) : 0}%</div></div>
        <div class="stat-card"><div class="stat-lbl">Est. Playtime (hrs)</div><div class="stat-val">${libRes.estimated_hours || 0}</div></div>
    `;
    if (libRes.best_playlist || libRes.worst_playlist) {
        $("playlist-highlights-content").innerHTML = `
            <div class="highlight-item" style="margin-bottom:1.5rem;">
                <div class="stat-lbl" style="font-size:0.75rem;color:var(--succ);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:0.3rem;">Best Performance 🏆</div>
                <div style="font-weight:600;font-size:1rem;margin-bottom:0.2rem;">${libRes.best_playlist?.spotify_name || 'N/A'}</div>
                <div style="font-size:0.85rem;color:var(--text-sec);">${libRes.best_playlist?.avg_pct?.toFixed(1) || 0}% average match rate</div>
            </div>
            <div class="highlight-item">
                <div class="stat-lbl" style="font-size:0.75rem;color:var(--err);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:0.3rem;">Needs Attention ⚠️</div>
                <div style="font-weight:600;font-size:1rem;margin-bottom:0.2rem;">${libRes.worst_playlist?.spotify_name || 'N/A'}</div>
                <div style="font-size:0.85rem;color:var(--text-sec);">${libRes.worst_playlist?.avg_pct?.toFixed(1) || 0}% average match rate</div>
            </div>`;
    } else {
        $("playlist-highlights-content").innerHTML = `<div class="muted">Not enough data to highlight playlists.</div>`;
    }
    const unTbody = $("unmatched-artists-tbody");
    unTbody.innerHTML = "";
    if (unRes.top_unmatched?.length > 0) {
        unRes.top_unmatched.slice(0, 10).forEach(u => {
            const tr = document.createElement("tr");
            tr.innerHTML = `<td>${u.artist}</td><td style="text-align:right;">${u.count}</td><td style="text-align:right;">${u.playlists}</td>`;
            unTbody.appendChild(tr);
        });
    } else {
        unTbody.innerHTML = `<tr><td colspan="3" class="muted">No missing tracks recorded yet.</td></tr>`;
    }
}

// ── History Tab ────────────────────────────────────────────────────────────────
async function loadHistory() {
    $("history-list").innerHTML = `<div class="loading-text">Loading...</div>`;
    try {
        const { history } = await fetch(`${API}/history`).then(r => r.json());
        if (!history.length) {
            $("history-list").innerHTML = `<div class="empty-text">No sync runs yet. Start a sync to see history here.</div>`;
            return;
        }
        $("history-list").innerHTML = "";
        history.forEach(run => {
            const date = new Date(run.timestamp * 1000).toLocaleString();
            const statusColor = run.status === "skipped" ? "var(--err)" : run.status === "created" ? "#a78bfa" : "var(--succ)";
            const el = document.createElement("div");
            el.className = "history-row glass-card";
            el.innerHTML = `
                <div class="history-info">
                    <span class="history-name">${run.yt_name}</span>
                    <span class="history-orig muted">← ${run.spotify_name}</span>
                    <span class="history-date muted">${date}</span>
                </div>
                <div class="history-stats">
                    <span class="badge" style="background:${statusColor}20;color:${statusColor}">${run.status}</span>
                    <span class="muted">✅ ${run.matched_count} matched</span>
                    <span class="muted">➕ ${run.added_count} added</span>
                    <span class="muted">${run.match_pct}% match</span>
                </div>
                <button class="btn secondary small" onclick="window.open('${API}/history/${run.id}/log','_blank')">⬇ Log</button>`;
            $("history-list").appendChild(el);
        });
    } catch (e) {
        $("history-list").innerHTML = `<div class="error-text">Failed to load history.</div>`;
    }
}

// ── Schedules ──────────────────────────────────────────────────────────────────
async function loadSchedules() {
    $("active-schedules-list").innerHTML = `<div class="loading-text">Loading schedules...</div>`;
    try {
        const { schedules } = await fetch(`${API}/schedules`).then(r => r.json());
        if (!schedules?.length) {
            $("active-schedules-list").innerHTML = `<div class="empty-text">No active schedules. Set one up to sync automatically!</div>`;
            return;
        }
        $("active-schedules-list").innerHTML = "";
        schedules.forEach(s => {
            const playlistIds = JSON.parse(s.playlist_ids || "[]");
            const el = document.createElement("div");
            el.className = "history-row glass-card";
            el.innerHTML = `
                <div class="history-info">
                    <span class="history-name">${s.spotify_name} Sync</span>
                    <span class="history-orig muted">${playlistIds.length} playlists • ${s.frequency}</span>
                    <span class="history-date muted">Last run: ${s.last_run ? new Date(s.last_run * 1000).toLocaleString() : 'Never'}</span>
                </div>
                <div class="history-stats">
                    <span class="badge" style="background:var(--succ)20;color:var(--succ)">Active</span>
                </div>
                <button class="btn secondary small" style="color:var(--err);" onclick="deleteSchedule('${s.spotify_id}')">🗑 Stop</button>`;
            $("active-schedules-list").appendChild(el);
        });
    } catch (e) {
        $("active-schedules-list").innerHTML = `<div class="error-text">Failed to load schedules.</div>`;
    }
}

async function saveSchedule() {
    const freq = $("schedule-freq").value;
    const playlistIds = Array.from(selectedPlaylists);
    if (!playlistIds.length) return;
    const btn = $("btn-save-schedule");
    btn.disabled = true; btn.textContent = "Saving...";
    try {
        const res = await fetch(`${API}/schedules`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ spotify_id: "library", spotify_name: "My Automated", frequency: freq, playlist_ids: playlistIds })
        });
        if (res.ok) { alert("✅ Auto-sync schedule saved successfully!"); loadSchedules(); }
        else alert("❌ Failed to save schedule.");
    } catch (e) { alert("Error: " + e.message); }
    finally { btn.disabled = false; btn.textContent = "Save Schedule"; }
}

async function deleteSchedule(spotifyId) {
    if (!confirm("Are you sure you want to stop this automatic sync?")) return;
    try {
        const res = await fetch(`${API}/schedules/${spotifyId}`, { method: "DELETE" });
        if (res.ok) loadSchedules();
    } catch (e) { alert("Delete failed: " + e.message); }
}

window.deleteSchedule = deleteSchedule;
$("btn-save-schedule").addEventListener("click", saveSchedule);
updateActions();

// ── Health Badge ────────────────────────────────────────────────────────────────
async function loadHealthBadge() {
    try {
        const h = await fetch(`${API}/health`).then(r => r.json());

        // Sync auth state from health check — keeps sidebar & auth section consistent
        if (h.spotify && h.spotify.status === "ok" && !spotifyAuthed) setAuth("spotify", true, false);
        if (h.ytmusic && (h.ytmusic.status === "ok" || h.ytmusic.status === "warn") && !ytAuthed) setAuth("yt", true, false);
        if (spotifyAuthed && ytAuthed && document.getElementById("section-auth") && !document.getElementById("section-auth").classList.contains("hidden")) {
            proceedToPlaylists();
        }

        let el = $("health-badge");
        if (!el) {
            el = document.createElement("div");
            el.id = "health-badge";
            el.style.cssText =
                "margin:1rem 0;padding:1rem 1.25rem;background:var(--glass);" +
                "border:1px solid var(--border);border-radius:12px;backdrop-filter:blur(8px);";
            const settingsTab = document.getElementById("section-settings");
            if (settingsTab) settingsTab.prepend(el);
        }

        const dot = s => {
            const c = s === "ok" ? "#22c55e" : s === "warn" ? "#f59e0b"
                     : s === "error" ? "#ef4444" : "#6b7280";
            return `<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${c};margin-right:6px;vertical-align:middle;"></span>`;
        };

        const lastSync = h.last_sync ? new Date(h.last_sync).toLocaleString() : "Never";

        el.innerHTML = `
            <div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.08em;color:var(--text-sec);margin-bottom:0.65rem;font-weight:600;">System Health</div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.5rem;margin-bottom:0.75rem;">
                <div style="display:flex;align-items:center;font-size:0.82rem;">${dot(h.spotify.status)}<span title="${h.spotify.detail}">Spotify</span></div>
                <div style="display:flex;align-items:center;font-size:0.82rem;">${dot(h.ytmusic.status)}<span title="${h.ytmusic.detail}">YT Music</span></div>
                <div style="display:flex;align-items:center;font-size:0.82rem;">${dot(h.database.status)}<span title="${h.database.detail}">Database</span></div>
            </div>
            <div style="font-size:0.78rem;color:var(--text-sec);display:flex;gap:1.5rem;flex-wrap:wrap;">
                <span>🕐 Last sync: <strong style="color:var(--text);">${lastSync}</strong></span>
                <span>📊 Total syncs: <strong style="color:var(--text);">${h.total_syncs}</strong></span>
            </div>`;
    } catch (_) {}
}

// ── Boot ───────────────────────────────────────────────────────────────────────

// ── Feature: Cookie Expiry Global Banner ───────────────────────────────────────
async function checkCookieExpiryBanner() {
    try {
        const expiry = await fetch(`${API}/ytmusic/cookie-expiry`).then(r => r.json());
        const days = expiry.days_remaining;
        if (days === undefined || days === null || days > 7) return;

        let banner = document.getElementById("cookie-expiry-banner");
        if (!banner) {
            banner = document.createElement("div");
            banner.id = "cookie-expiry-banner";
            banner.style.cssText =
                "position:fixed;top:0;left:0;right:0;z-index:9999;padding:0.6rem 1.25rem;" +
                "display:flex;align-items:center;justify-content:space-between;" +
                `background:${days <= 0 ? "#7f1d1d" : days <= 3 ? "#78350f" : "#3d1a00"};` +
                "border-bottom:1px solid rgba(255,255,255,0.12);font-size:0.84rem;";
            document.body.prepend(banner);
        }
        const icon = days <= 0 ? "💀" : days <= 3 ? "🚨" : "⚠️";
        const msg  = days <= 0
            ? "YT Music cookies have EXPIRED — sync is broken. Update now."
            : `YT Music cookies expire in ${days} day${days === 1 ? "" : "s"}. Update soon.`;
        banner.innerHTML = `
            <span>${icon} <strong>${msg}</strong></span>
            <a href="#" onclick="document.querySelector('[data-tab=settings]')?.click();return false;"
               style="color:#fbbf24;text-decoration:underline;white-space:nowrap;margin-left:1rem;">Open Settings →</a>`;

        if (days >= 0 && Notification.permission === "granted") {
            new Notification(`${icon} YT Music cookie expiry`, { body: msg });
        }
    } catch (_) {}
}

// ── Feature: Per-Playlist SVG Progress Rings ──────────────────────────────────
const _rings = {};

function createPlaylistRing(name, totalBatches) {
    let container = document.getElementById("playlist-rings-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "playlist-rings-container";
        container.style.cssText =
            "display:flex;flex-wrap:wrap;gap:1rem;margin:0.75rem 0;padding:0.75rem 1rem;" +
            "background:var(--glass);border:1px solid var(--border);border-radius:12px;";
        const logEl = document.getElementById("sync-log");
        if (logEl && logEl.parentNode) logEl.parentNode.insertBefore(container, logEl);
    }
    const safeId = "ring-" + name.replace(/[^a-z0-9]/gi, "_");
    if (document.getElementById(safeId)) return;
    const size = 52, r = 20, circ = 2 * Math.PI * r;
    const wrap = document.createElement("div");
    wrap.id = safeId;
    wrap.style.cssText = "display:flex;flex-direction:column;align-items:center;gap:0.2rem;";
    wrap.innerHTML = `
        <svg width="${size}" height="${size}" style="transform:rotate(-90deg);">
            <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="var(--border)" stroke-width="4"/>
            <circle class="ring-fill" cx="${size/2}" cy="${size/2}" r="${r}" fill="none"
                stroke="var(--accent)" stroke-width="4"
                stroke-dasharray="${circ}" stroke-dashoffset="${circ}"
                style="transition:stroke-dashoffset 0.4s ease;"/>
        </svg>
        <span style="font-size:0.65rem;color:var(--text-sec);max-width:58px;text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${name}">
            ${name.replace(/^SP_/, "").substring(0, 10)}
        </span>
        <span class="ring-pct" style="font-size:0.68rem;color:var(--text);font-variant-numeric:tabular-nums;">0%</span>`;
    container.appendChild(wrap);
    _rings[name] = { el: wrap, total: totalBatches, circ };
}

function updatePlaylistRing(name, batch, totalBatches) {
    const ring = _rings[name];
    if (!ring) return;
    const pct = Math.min(100, Math.round((batch / totalBatches) * 100));
    const fill = ring.el.querySelector(".ring-fill");
    const pctEl = ring.el.querySelector(".ring-pct");
    if (fill) fill.style.strokeDashoffset = ring.circ * (1 - pct / 100);
    if (pctEl) pctEl.textContent = pct + "%";
    if (pct >= 100 && fill) fill.style.stroke = "#22c55e";
}

function clearPlaylistRings() {
    const c = document.getElementById("playlist-rings-container");
    if (c) c.remove();
    for (const k of Object.keys(_rings)) delete _rings[k];
}

// ── Feature: Parallelism Slider ───────────────────────────────────────────────
async function loadConfig() {
    try {
        const cfg = await fetch(`${API}/config`).then(r => r.json());
        renderParallelSlider(cfg.parallel_playlists || 2);
    } catch (_) { renderParallelSlider(2); }
}

function renderParallelSlider(current = 2) {
    if (document.getElementById("parallel-slider")) {
        document.getElementById("parallel-slider").value = current;
        const lbl = document.getElementById("parallel-label");
        if (lbl) lbl.textContent = current;
        return;
    }
    const settingsTab = document.getElementById("section-settings");
    if (!settingsTab) return;
    const card = document.createElement("div");
    card.id = "parallel-config-card";
    card.style.cssText = "margin:0.75rem 0;padding:1rem 1.25rem;background:var(--glass);border:1px solid var(--border);border-radius:12px;";
    card.innerHTML = `
        <div style="font-size:0.72rem;font-weight:600;margin-bottom:0.5rem;text-transform:uppercase;letter-spacing:0.06em;color:var(--text-sec);">⚡ Parallel Playlists</div>
        <div style="display:flex;align-items:center;gap:1rem;">
            <input type="range" id="parallel-slider" min="1" max="6" value="${current}"
                style="flex:1;accent-color:var(--accent);"
                oninput="document.getElementById('parallel-label').textContent=this.value">
            <strong id="parallel-label" style="min-width:1.4rem;text-align:center;">${current}</strong>
            <button id="btn-save-parallel" style="padding:0.3rem 0.8rem;border-radius:8px;border:1px solid var(--border);background:var(--glass);color:var(--text);cursor:pointer;font-size:0.8rem;" onclick="saveConfig()">Save</button>
        </div>
        <div style="font-size:0.74rem;color:var(--text-sec);margin-top:0.35rem;">
            Sync N playlists simultaneously. Higher = faster but more API load. Recommended: 2.
        </div>`;
    const badge = document.getElementById("health-badge");
    if (badge && badge.nextSibling) badge.parentNode.insertBefore(card, badge.nextSibling);
    else settingsTab.prepend(card);
}

async function saveConfig() {
    const slider = document.getElementById("parallel-slider");
    if (!slider) return;
    const btn = document.getElementById("btn-save-parallel");
    if (btn) { btn.textContent = "Saving..."; btn.disabled = true; }
    try {
        await fetch(`${API}/config`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ parallel_playlists: parseInt(slider.value, 10) })
        });
        if (btn) { btn.textContent = "✅ Saved"; setTimeout(() => { btn.textContent = "Save"; btn.disabled = false; }, 1500); }
    } catch (e) {
        if (btn) { btn.textContent = "Save"; btn.disabled = false; }
    }
}
window.saveConfig = saveConfig;

// ── Feature: Quick Add by YT Music URL ───────────────────────────────────────
async function quickAddTrack(ytPid, trackName, artist, inputId, btnId, rowId) {
    const input = document.getElementById(inputId);
    const btn   = document.getElementById(btnId);
    if (!input || !input.value.trim()) return;
    btn.textContent = "Adding..."; btn.disabled = true;
    try {
        const res = await fetch(`${API}/playlist/${ytPid}/add-by-id`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video_id_or_url: input.value.trim(), track_name: trackName, artist })
        });
        const d = await res.json();
        if (res.ok) {
            const row = document.getElementById(rowId);
            if (row) { row.style.opacity = "0.35"; row.style.pointerEvents = "none"; }
            btn.textContent = "✅ Added";
        } else {
            btn.textContent = "❌ Error"; btn.disabled = false;
            alert("Quick Add failed: " + (d.detail || "unknown error"));
        }
    } catch (e) {
        btn.textContent = "❌ Error"; btn.disabled = false;
    }
}
window.quickAddTrack = quickAddTrack;

// ── Feature: YT Music Library Management ──────────────────────────────────────
let activeYTPid = null;

async function loadYTLibrary() {
    $("yt-lib-playlists").innerHTML = `<div class="loading-text">Loading YouTube Music Library...</div>`;
    $("yt-lib-editor").classList.add("hidden");
    
    try {
        const r = await fetch(`${API}/ytmusic/playlists`);
        const d = await r.json();
        renderYTLibrary(d.playlists || []);
    } catch (e) {
        $("yt-lib-playlists").innerHTML = `<div class="status-badge error" style="margin:1rem auto;display:table;">Failed to load library. Is YouTube Music authenticated?</div>`;
    }
}
window.loadYTLibrary = loadYTLibrary;

function renderYTLibrary(playlists) {
    const list = $("yt-lib-playlists");
    if (playlists.length === 0) {
        list.innerHTML = `<div style="text-align:center;color:var(--text-sec);padding:2rem;">No playlists found in your YouTube Music library.</div>`;
        return;
    }
    
    const html = playlists.map(p => {
        const thumb = p.thumbnails && p.thumbnails.length ? p.thumbnails[0].url : "";
        const bg = thumb ? `background-image:url('${thumb}');background-size:cover;` : `background:var(--card-bg-hover);`;
        return `
            <div class="playlist-card" onclick="openYTPlaylist('${p.playlistId}', '${(p.title || '').replace(/'/g, "\\'")}', '${p.count || 0}')" style="cursor:pointer;">
                <div class="playlist-cover" style="${bg}"></div>
                <div class="playlist-info">
                    <h3 title="${p.title}">${p.title}</h3>
                    <p>${p.count || 0} tracks</p>
                </div>
            </div>
        `;
    }).join("");
    
    list.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(140px, 1fr));gap:1rem;">${html}</div>`;
}

window.openYTPlaylist = async function(pid, title, count) {
    activeYTPid = pid;
    $("yt-lib-editor").classList.remove("hidden");
    $("yt-lib-title").textContent = title;
    $("yt-lib-meta").textContent = `${count} tracks`;
    $("yt-lib-tracks").innerHTML = `<div style="padding:1.5rem;text-align:center;color:var(--text-sec);">Loading tracks...</div>`;
    
    try {
        const r = await fetch(`${API}/ytmusic/playlists/${pid}/tracks`);
        const d = await r.json();
        const tracks = d.tracks || [];
        $("yt-lib-meta").textContent = `${tracks.length} tracks`;
        
        if (tracks.length === 0) {
            $("yt-lib-tracks").innerHTML = `<div style="padding:1.5rem;text-align:center;color:var(--text-sec);">This playlist is empty.</div>`;
            return;
        }
        
        const html = tracks.map(t => {
            const thumb = t.thumbnails && t.thumbnails.length ? t.thumbnails[0].url : "";
            const vId = t.videoId;
            const svId = t.setVideoId;
            return `
                <div class="track-row" id="yt-track-${svId}">
                    <img src="${thumb}" style="width:36px;height:36px;border-radius:4px;object-fit:cover;background:#333;">
                    <div class="track-info" style="flex:1;">
                        <div class="track-name" title="${t.title}">${t.title}</div>
                        <div class="track-artist">${t.artists ? t.artists.map(a=>a.name).join(', ') : 'Unknown'}</div>
                    </div>
                    <button class="btn danger small" onclick="removeYTTrack('${vId}', '${svId}')" style="padding:0.3rem 0.6rem;font-size:0.75rem;">✕ Remove</button>
                </div>
            `;
        }).join("");
        
        $("yt-lib-tracks").innerHTML = html;
        
    } catch (e) {
        $("yt-lib-tracks").innerHTML = `<div style="padding:1.5rem;text-align:center;color:var(--warn);">Failed to load tracks.</div>`;
    }
}

function setupLibraryHandlers() {
    const renBtn = $("btn-yt-rename");
    if (renBtn) {
        renBtn.addEventListener("click", async () => {
            console.log("YT Rename clicked - pid:", activeYTPid);
            if (!activeYTPid) return;
            const currentName = $("yt-lib-title").textContent;
            const newName = prompt(`Rename playlist "${currentName}" to:`, currentName);
            if (!newName || newName === currentName) return;
            
            try {
                const btn = $("btn-yt-rename");
                btn.textContent = "Renaming..."; btn.disabled = true;
                
                const r = await fetch(`${API}/ytmusic/playlists/${activeYTPid}/rename`, {
                    method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ title: newName })
                });
                
                btn.textContent = "Rename"; btn.disabled = false;
                if (r.ok) {
                    $("yt-lib-title").textContent = newName;
                    loadYTLibrary();
                    setTimeout(() => { openYTPlaylist(activeYTPid, newName, $("yt-lib-meta").textContent.split(' ')[0]); }, 1000);
                } else alert("Failed to rename playlist.");
            } catch (e) {
                console.error("Rename error:", e);
                $("btn-yt-rename").textContent = "Rename"; $("btn-yt-rename").disabled = false;
                alert("Error renaming playlist.");
            }
        });
    }

    const delBtn = $("btn-yt-delete");
    if (delBtn) {
        delBtn.addEventListener("click", async () => {
            console.log("YT Delete clicked - pid:", activeYTPid);
            if (!activeYTPid) return;
            const currentName = $("yt-lib-title").textContent;
            if (!confirm(`Are you absolutely sure you want to DELETE "${currentName}" from YouTube Music? This cannot be undone.`)) return;
            if (!confirm(`Warning: If this playlist is active in any synced schedules, they will break. Proceed with deletion?`)) return;
            
            try {
                const btn = $("btn-yt-delete");
                btn.textContent = "Deleting..."; btn.disabled = true;
                
                const r = await fetch(`${API}/ytmusic/playlists/${activeYTPid}`, { method: "DELETE" });
                btn.textContent = "Delete Playlist"; btn.disabled = false;
                if (r.ok) {
                    activeYTPid = null;
                    $("yt-lib-editor").classList.add("hidden");
                    loadYTLibrary();
                } else alert("Failed to delete playlist.");
            } catch (e) {
                console.error("Delete error:", e);
                $("btn-yt-delete").textContent = "Delete Playlist"; $("btn-yt-delete").disabled = false;
                alert("Error deleting playlist.");
            }
        });
    }
}

window.removeYTTrack = async function(videoId, setVideoId) {
    if (!activeYTPid || !setVideoId) return;
    try {
        const row = document.getElementById(`yt-track-${setVideoId}`);
        if(row) row.style.opacity = "0.3";
        
        await fetch(`${API}/ytmusic/playlists/${activeYTPid}/remove-tracks`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video_ids: [{ videoId: videoId, setVideoId: setVideoId }] })
        });
        
        if (row) row.remove();
        
        // update count visually
        const m = document.getElementById("yt-lib-meta");
        if (m) {
            const current = parseInt(m.textContent, 10) || 0;
            m.textContent = `${Math.max(0, current - 1)} tracks`;
        }
    } catch (e) {
        alert("Failed to remove track.");
        const row = document.getElementById(`yt-track-${setVideoId}`);
        if(row) row.style.opacity = "1";
    }
}


init();
