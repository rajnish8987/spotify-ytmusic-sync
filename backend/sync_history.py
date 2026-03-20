"""
Sync History + Schedule + Analytics DB Manager
"""
import sqlite3
import time

DB_FILE = "sync_history.db"


def _get_conn():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _get_conn()

    # ── Core sync history ────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            spotify_name TEXT NOT NULL,
            yt_name TEXT NOT NULL,
            status TEXT NOT NULL,
            matched_count INTEGER DEFAULT 0,
            not_found_count INTEGER DEFAULT 0,
            added_count INTEGER DEFAULT 0,
            total_tracks INTEGER DEFAULT 0,
            match_pct REAL DEFAULT 0.0,
            log_text TEXT DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sync_runs_name ON sync_runs(spotify_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sync_runs_ts ON sync_runs(timestamp)")

    # ── Delta sync state ──────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS playlist_state (
            spotify_name TEXT PRIMARY KEY,
            last_sync_ts INTEGER NOT NULL,
            last_track_count INTEGER NOT NULL DEFAULT 0,
            last_added_at TEXT DEFAULT NULL
        )
    """)

    # ── Unmatched tracks (for artist analytics + auto-retry) ────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS unmatched_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            playlist_name TEXT NOT NULL,
            track_name TEXT NOT NULL,
            artist TEXT NOT NULL DEFAULT '',
            ts INTEGER NOT NULL,
            retry_count INTEGER NOT NULL DEFAULT 0,
            resolved INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Migration: add columns if they don't exist yet
    for col, definition in [("retry_count", "INTEGER NOT NULL DEFAULT 0"),
                             ("resolved",    "INTEGER NOT NULL DEFAULT 0")]:
        try:
            conn.execute(f"ALTER TABLE unmatched_tracks ADD COLUMN {col} {definition}")
        except Exception:
            pass
    # Migration: add started_at to sync_runs if missing
    try:
        conn.execute("ALTER TABLE sync_runs ADD COLUMN started_at TEXT DEFAULT NULL")
    except Exception:
        pass
    conn.execute("CREATE INDEX IF NOT EXISTS idx_unmatched_artist ON unmatched_tracks(artist)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_unmatched_ts ON unmatched_tracks(ts)")

    # ── Auto-sync schedules ───────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            spotify_id TEXT PRIMARY KEY,
            spotify_name TEXT NOT NULL,
            frequency TEXT NOT NULL,
            playlist_ids TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            last_run INTEGER DEFAULT NULL,
            next_run INTEGER DEFAULT NULL
        )
    """)

    conn.commit()
    conn.close()


# ── Sync Runs ─────────────────────────────────────────────────────────────────

def save_sync_run(spotify_name, yt_name, status, matched, not_found, added, total, log_lines) -> int:
    conn = _get_conn()
    match_pct = round((matched / total * 100) if total > 0 else 0, 1)
    started_at = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())
    cur = conn.execute(
        """INSERT INTO sync_runs
           (timestamp, started_at, spotify_name, yt_name, status, matched_count,
            not_found_count, added_count, total_tracks, match_pct, log_text)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (int(time.time()), started_at, spotify_name, yt_name, status,
         matched, not_found, added, total, match_pct, "\n".join(log_lines))
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return int(run_id) if run_id is not None else 0


def get_history() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM sync_runs ORDER BY timestamp DESC LIMIT 200").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_run_log(run_id: int) -> str | None:
    conn = _get_conn()
    row = conn.execute("SELECT log_text, spotify_name, timestamp FROM sync_runs WHERE id=?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(row['timestamp']))
    return f"Sync Log — {row['spotify_name']} — {ts}\n{'='*60}\n{row['log_text']}"


def get_last_synced(spotify_name: str) -> int | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT timestamp FROM sync_runs WHERE spotify_name=? ORDER BY timestamp DESC LIMIT 1",
        (spotify_name,)
    ).fetchone()
    conn.close()
    return row['timestamp'] if row else None


# ── Delta Sync State ──────────────────────────────────────────────────────────

def get_playlist_state(spotify_name: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM playlist_state WHERE spotify_name=?", (spotify_name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_playlist_state(spotify_name: str, track_count: int, last_added_at: str | None):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO playlist_state (spotify_name, last_sync_ts, last_track_count, last_added_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(spotify_name) DO UPDATE SET
            last_sync_ts=excluded.last_sync_ts,
            last_track_count=excluded.last_track_count,
            last_added_at=excluded.last_added_at
    """, (spotify_name, int(time.time()), track_count, last_added_at))
    conn.commit()
    conn.close()


def delete_playlist_state(spotify_name: str):
    conn = _get_conn()
    conn.execute("DELETE FROM playlist_state WHERE spotify_name=?", (spotify_name,))
    conn.commit()
    conn.close()


# ── Unmatched Tracks ──────────────────────────────────────────────────────────

def save_unmatched_tracks(run_id: int, playlist_name: str, tracks: list[tuple[str, str]]):
    """Save list of (track_name, artist) tuples that weren't matched."""
    if not tracks:
        return
    conn = _get_conn()
    ts = int(time.time())
    conn.executemany(
        "INSERT INTO unmatched_tracks (run_id, playlist_name, track_name, artist, ts) VALUES (?,?,?,?,?)",
        [(run_id, playlist_name, t[0], t[1], ts) for t in tracks]
    )
    conn.commit()
    conn.close()


def get_top_unmatched_artists(limit: int = 15) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT artist, COUNT(*) as count, COUNT(DISTINCT playlist_name) as playlists
        FROM unmatched_tracks
        WHERE artist != '' AND resolved = 0
        GROUP BY artist
        ORDER BY count DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_unmatched(limit: int = 200) -> list[dict]:
    """Return unmatched tracks from the most recent sync run, for the persistent Not Found panel."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT u.track_name as name, u.artist, u.playlist_name
        FROM unmatched_tracks u
        INNER JOIN (
            SELECT MAX(id) as max_id, run_id
            FROM unmatched_tracks
            WHERE run_id = (SELECT MAX(run_id) FROM unmatched_tracks WHERE resolved = 0)
        ) latest ON u.run_id = latest.run_id
        WHERE u.resolved = 0
        ORDER BY u.playlist_name, u.id
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_retry_candidates(playlist_name: str, max_retries: int = 2) -> list[dict]:
    """Return unmatched tracks for a playlist that haven't been retried too many times."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT id, track_name, artist
        FROM unmatched_tracks
        WHERE playlist_name = ? AND resolved = 0 AND retry_count < ?
        ORDER BY ts DESC
    """, (playlist_name, max_retries)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def increment_retry_count(ids: list[int]):
    """Bump retry_count for a list of unmatched_track IDs."""
    if not ids:
        return
    conn = _get_conn()
    conn.execute(
        f"UPDATE unmatched_tracks SET retry_count = retry_count + 1 WHERE id IN ({','.join('?'*len(ids))})",
        ids
    )
    conn.commit()
    conn.close()


def mark_retry_resolved(ids: list[int]):
    """Mark tracks as resolved (successfully found on retry)."""
    if not ids:
        return
    conn = _get_conn()
    conn.execute(
        f"UPDATE unmatched_tracks SET resolved = 1 WHERE id IN ({','.join('?'*len(ids))})",
        ids
    )
    conn.commit()
    conn.close()


# ── Analytics ─────────────────────────────────────────────────────────────────


def get_library_stats() -> dict:
    conn = _get_conn()

    try:
        totals = conn.execute("""
            SELECT
                COUNT(*) as total_runs,
                COUNT(DISTINCT spotify_name) as total_playlists,
                SUM(matched_count) as total_matched,
                SUM(added_count) as total_added,
                SUM(total_tracks) as total_tracks,
                AVG(match_pct) as avg_match_pct
            FROM sync_runs
            WHERE status NOT IN ('skipped')
        """).fetchone()

        best = conn.execute("""
            SELECT spotify_name, yt_name, AVG(match_pct) as avg_pct
            FROM sync_runs WHERE total_tracks >= 5
            GROUP BY spotify_name
            ORDER BY avg_pct DESC LIMIT 1
        """).fetchone()

        worst = conn.execute("""
            SELECT spotify_name, yt_name, AVG(match_pct) as avg_pct
            FROM sync_runs WHERE total_tracks >= 5
            GROUP BY spotify_name
            ORDER BY avg_pct ASC LIMIT 1
        """).fetchone()

        biggest = conn.execute("""
            SELECT spotify_name, yt_name, MAX(total_tracks) as max_tracks
            FROM sync_runs GROUP BY spotify_name ORDER BY max_tracks DESC LIMIT 1
        """).fetchone()

        playlist_sizes = conn.execute("""
            SELECT spotify_name, MAX(total_tracks) as tracks
            FROM sync_runs GROUP BY spotify_name ORDER BY tracks DESC LIMIT 20
        """).fetchall()
    finally:
        conn.close()

    AVERAGE_TRACK_DURATION_SECONDS = 210  # ~3.5 min average
    total_matched: int = 0
    avg_match_pct: float = 0.0
    
    if totals:
        total_matched = totals['total_matched'] or 0
        avg_match_pct = float(totals['avg_match_pct'] or 0.0)

    estimated_hours = round(float(total_matched * AVERAGE_TRACK_DURATION_SECONDS) / 3600.0, 1)

    return {
        "total_runs": totals['total_runs'] if totals else 0,
        "total_playlists": totals['total_playlists'] if totals else 0,
        "total_matched": total_matched,
        "total_added": totals['total_added'] if (totals and 'total_added' in totals.keys()) else (totals['total_added'] if totals else 0),
        "avg_match_pct": round(avg_match_pct, 1),
        "estimated_hours": estimated_hours,
        "best_playlist": dict(best) if best else None,
        "worst_playlist": dict(worst) if worst else None,
        "biggest_playlist": dict(biggest) if biggest else None,
        "playlist_sizes": [dict(r) for r in playlist_sizes],
    }


# ── Schedules ─────────────────────────────────────────────────────────────────

def get_all_schedules() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM schedules ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_schedule(spotify_id: str, spotify_name: str, frequency: str, playlist_ids: list[str]) -> dict:
    import json
    conn = _get_conn()
    now = int(time.time())
    next_run = _calc_next_run(frequency, now)
    conn.execute("""
        INSERT INTO schedules (spotify_id, spotify_name, frequency, playlist_ids, created_at, next_run)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(spotify_id) DO UPDATE SET
            frequency=excluded.frequency,
            playlist_ids=excluded.playlist_ids,
            next_run=excluded.next_run
    """, (spotify_id, spotify_name, frequency, json.dumps(playlist_ids), now, next_run))
    conn.commit()
    row = conn.execute("SELECT * FROM schedules WHERE spotify_id=?", (spotify_id,)).fetchone()
    conn.close()
    return dict(row)


def delete_schedule(spotify_id: str):
    conn = _get_conn()
    conn.execute("DELETE FROM schedules WHERE spotify_id=?", (spotify_id,))
    conn.commit()
    conn.close()


def update_schedule_last_run(spotify_id: str):
    conn = _get_conn()
    row = conn.execute("SELECT frequency FROM schedules WHERE spotify_id=?", (spotify_id,)).fetchone()
    if row:
        now = int(time.time())
        next_run = _calc_next_run(row['frequency'], now)
        conn.execute("UPDATE schedules SET last_run=?, next_run=? WHERE spotify_id=?",
                     (now, next_run, spotify_id))
        conn.commit()
    conn.close()


def _calc_next_run(frequency: str, from_ts: int) -> int:
    if frequency == "daily":
        return from_ts + 86400
    elif frequency == "weekly":
        return from_ts + 7 * 86400
    elif frequency == "hourly":
        return from_ts + 3600
    return from_ts + 86400


# Initialise
init_db()
