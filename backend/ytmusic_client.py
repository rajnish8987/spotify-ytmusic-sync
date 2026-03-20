import os
import time
import json
import requests
from ytmusicapi import YTMusic
from fastapi import HTTPException

HEADERS_FILE = "browser_headers.json"
EXPIRY_FILE = "cookie_expiry.json"
BATCH_SIZE = 25  # Reduced from 50 to lower timeout risk per batch
MAX_RETRIES = 5
RETRY_DELAY = 5  # seconds base delay for retries


def get_ytmusic_client():
    if not os.path.exists(HEADERS_FILE):
        raise HTTPException(
            status_code=401,
            detail="YouTube Music not authenticated. Please provide your browser headers."
        )
    try:
        yt = YTMusic(HEADERS_FILE)
        return yt
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"YouTube Music auth error: {str(e)}")


def _with_retry(fn, *args, **kwargs):
    """Call fn with automatic retry on transient errors (429, JSON, timeout, 409)."""
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except json.JSONDecodeError:
            # Empty / malformed response from YT — transient server glitch
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"DEBUG: transient error in {fn.__name__} (JSON). Retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise
        except (requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError) as e:
            # Network timeout — server took too long. Retry with a longer wait.
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (attempt + 2)  # Longer wait for timeouts
                print(f"DEBUG: timeout in {fn.__name__}. Retrying in {wait}s... (attempt {attempt+1}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            msg = str(e)
            # ReadTimeout may also surface as a plain Exception string
            if "timed out" in msg.lower() or "timeout" in msg.lower():
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_DELAY * (attempt + 2)
                    print(f"DEBUG: timeout in {fn.__name__} (string match). Retrying in {wait}s...")
                    time.sleep(wait)
                    continue
            # 429 / quota: rate-limited, back off and retry
            if "429" in msg or "too many requests" in msg.lower() or "quota" in msg.lower():
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_DELAY * (attempt + 1)
                    print(f"DEBUG: rate-limited in {fn.__name__} (429). Retrying in {wait}s...")
                    time.sleep(wait)
                    continue
            # 409 Conflict: duplicate add or rapid call — skip gracefully
            if "409" in msg or "conflict" in msg.lower():
                print(f"DEBUG: Catching 409 Conflict in {fn.__name__}. Skipping batch.")
                return None
            raise
    raise Exception(f"Failed after {MAX_RETRIES} retries")


def save_cookie_expiry(min_expiry_ts: float):
    """Persist the minimum cookie expiry timestamp to disk."""
    with open(EXPIRY_FILE, "w") as f:
        json.dump({"expires": int(min_expiry_ts)}, f)


def get_cookie_expiry_info() -> dict:
    """
    Returns {"expires_ts": int, "days_remaining": int, "status": str}.
    status is one of: "ok", "warning" (<14d), "critical" (<3d), "expired", "unknown".
    """
    if not os.path.exists(EXPIRY_FILE):
        return {"expires_ts": None, "days_remaining": None, "status": "unknown"}
    try:
        with open(EXPIRY_FILE) as f:
            data = json.load(f)
        ts = data.get("expires")
        if not ts:
            return {"expires_ts": None, "days_remaining": None, "status": "unknown"}
        remaining = (ts - time.time()) / 86400
        days = int(remaining)
        if remaining <= 0:
            status = "expired"
        elif days < 3:
            status = "critical"
        elif days < 14:
            status = "warning"
        else:
            status = "ok"
        return {"expires_ts": ts, "days_remaining": max(0, days), "status": status}
    except Exception:
        return {"expires_ts": None, "days_remaining": None, "status": "unknown"}


def save_ytmusic_headers(headers_raw: str) -> bool:
    """Save YouTube Music browser headers from raw copy-paste."""
    try:
        from ytmusicapi.setup import setup as ytmusic_browser_setup
        ytmusic_browser_setup(filepath=HEADERS_FILE, headers_raw=headers_raw)
        yt = YTMusic(HEADERS_FILE)
        yt.get_home()
        return True
    except Exception as e:
        print(f"Browser headers setup error: {e}")
        return False


def is_ytmusic_authenticated() -> bool:
    return os.path.exists(HEADERS_FILE)


def check_ytmusic_auth() -> bool:
    """Returns True if auth is currently valid."""
    if not os.path.exists(HEADERS_FILE):
        return False
    try:
        yt = YTMusic(HEADERS_FILE)
        yt.get_home()
        return True
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "403" in msg or "unauthorized" in msg or "forbidden" in msg:
            return False
        # If it's a 429 Rate Limit error or general timeout, assume session is still fundamentally valid
        return True


def _parse_yt_duration(duration_str: str | None) -> int | None:
    """Convert 'M:SS' or 'H:MM:SS' string to total seconds."""
    if not duration_str:
        return None
    try:
        parts = duration_str.strip().split(":")
        parts = [int(p) for p in parts]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except Exception:
        return None


def search_yt_track(query: str, spotify_duration_ms: int | None = None, track_name: str | None = None) -> dict | None:
    """
    Search YT Music for a track with multi-query fallback strategy:
      1. "{name} {artist} official audio"  — best match quality
      2. "{name} {artist}"                 — fallback
      3. "{name}" only                     — last resort
    Returns result dict with added 'confidence' key:
       'high'   → duration diff ≤ 20s  (or no duration available to compare)
       'low'    → duration diff > 20s
    """
    yt = get_ytmusic_client()
    
    def _try_search(q: str) -> dict | None:
        """Run a single search query and return best match."""
        try:
            results = _with_retry(yt.search, q, filter="songs", limit=5)
            if not results:
                return None
            if spotify_duration_ms:
                spotify_sec = spotify_duration_ms / 1000
                for r in results:
                    yt_dur = _parse_yt_duration(r.get("duration"))
                    if yt_dur and abs(yt_dur - spotify_sec) <= 20:
                        r["confidence"] = "high"
                        return r
                best = results[0]
                yt_dur = _parse_yt_duration(best.get("duration"))
                best["confidence"] = "low" if yt_dur else "high"
                return best
            results[0]["confidence"] = "high"
            return results[0]
        except Exception:
            return None

    # Strategy 1: Query + "official audio" suffix (best quality signal)
    result = _try_search(f"{query} official audio")
    if result and result.get("confidence") == "high":
        return result

    # Strategy 2: Plain original query
    result2 = _try_search(query)
    if result2 and result2.get("confidence") == "high":
        return result2

    # Strategy 3: Title only (last resort for tracks not found by artist name)
    if track_name and track_name.lower() not in query.lower():
        result3 = _try_search(track_name)
        if result3:
            result3["confidence"] = "low"
            return result3

    # Return best we got (even if low confidence)
    if result2:
        return result2
    return result



def rename_yt_playlist(playlist_id: str, new_title: str):
    yt = get_ytmusic_client()
    return _with_retry(yt.edit_playlist, playlist_id, title=new_title)


def get_yt_playlists():
    yt = get_ytmusic_client()
    return _with_retry(yt.get_library_playlists)


def get_yt_playlist_tracks(playlist_id: str):
    yt = get_ytmusic_client()
    playlist = _with_retry(yt.get_playlist, playlist_id, limit=None)
    return playlist.get('tracks', [])


def create_yt_playlist(title: str, description: str, video_ids: list):
    """Create empty playlist then add tracks in batches."""
    yt = get_ytmusic_client()
    playlist_id = _with_retry(yt.create_playlist, title, description)
    if not isinstance(playlist_id, str):
        raise Exception(f"Failed to create playlist: {playlist_id}")
    if video_ids:
        for i in range(0, len(video_ids), BATCH_SIZE):
            batch = video_ids[i:i + BATCH_SIZE]
            _with_retry(yt.add_playlist_items, playlist_id, batch, duplicates=False)
    return playlist_id


def add_to_yt_playlist(playlist_id: str, video_ids: list):
    """Add tracks in batches with retry."""
    yt = get_ytmusic_client()
    for i in range(0, len(video_ids), BATCH_SIZE):
        batch = video_ids[i:i + BATCH_SIZE]
        _with_retry(yt.add_playlist_items, playlist_id, batch, duplicates=False)

def delete_yt_playlist(playlist_id: str):
    yt = get_ytmusic_client()
    return _with_retry(yt.delete_playlist, playlist_id)

def remove_from_yt_playlist(playlist_id: str, videos: list):
    yt = get_ytmusic_client()
    return _with_retry(yt.remove_playlist_items, playlist_id, videos)
