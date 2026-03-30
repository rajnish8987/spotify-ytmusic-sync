import os
import sys
import json
import logging
import hashlib
import time
import re
import requests
from typing import List, Dict, Optional
from ytmusicapi import YTMusic
from fastapi import HTTPException

# Base directory for relative file access (backend/)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

HEADERS_FILE = os.path.join(BASE_DIR, "browser_headers.json")
EXPIRY_FILE = os.path.join(BASE_DIR, "cookie_expiry.json")
BATCH_SIZE = 25  # Reduced from 50 to lower timeout risk per batch
MAX_RETRIES = 5
RETRY_DELAY = 5  # seconds base delay for retries


def _parse_netscape_cookies(content: str) -> str:
    """Convert Netscape tab-separated cookies to a semicolon-separated string."""
    cookies = []
    lines = content.split('\n')
    for line in lines:
        if not line.strip() or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) >= 7:
            name = parts[5].strip()
            value = parts[6].strip()
            cookies.append(f"{name}={value}")
    return "; ".join(cookies)


def get_auth_headers() -> dict | None:
    """Helper to safely load and lowercase headers from file."""
    if not os.path.exists(HEADERS_FILE):
        return None
    try:
        with open(HEADERS_FILE) as f:
            h = json.load(f)
        h = {k.lower(): v for k, v in h.items()}
        if "authorization" not in h:
            h["authorization"] = "SAPISIDHASH 1"
        return h
    except:
        return None


def get_ytmusic_client():
    headers = get_auth_headers()
    if not headers:
        raise HTTPException(
            status_code=401,
            detail="YouTube Music not authenticated. Please provide your browser headers or cookies."
        )
    try:
        # Use the official constructor with lowercase headers dictionary
        yt = YTMusic(auth=headers)
        return yt
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"YouTube Music auth error: {str(e)}")

def get_yt_account_info():
    """
    Returns (name, email) for the current authenticated session.
    Used for UI identity verification.
    """
    try:
        yt = get_ytmusic_client()
        try:
            info = yt.get_account_info()
            return info.get('name', 'Unknown User'), info.get('email', '')
        except:
            # Fallback for Brand Accounts
            me = yt.get_channel('FEme')
            return me.get('name', 'Brand Channel'), ''
    except:
        return None, None


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


def save_ytmusic_headers(headers_data: dict) -> tuple[bool, str]:
    """
    Save YouTube Music browser headers or cookies.
    Returns (success, message).
    """
    try:
        brand_id = headers_data.get("brand_id")
        processed = {}
        
        # Priority 1: Netscape Cookies (Manual parse avoid library bugs/mismatch)
        if "cookies_netscape" in headers_data:
            cookie_str = _parse_netscape_cookies(headers_data["cookies_netscape"])
            if not cookie_str:
                return False, "Failed to parse any cookies from Netscape file. Please check format."
            processed = {
                "cookie": cookie_str,
                "x-goog-authuser": "0"
            }
            
        # Priority 2: Raw Header block (Original method)
        elif "headers_raw" in headers_data:
            from ytmusicapi.setup import setup as ytmusic_browser_setup
            ytmusic_browser_setup(filepath=HEADERS_FILE, headers_raw=headers_data["headers_raw"])
            
            # Injection logic if Brand ID was provided
            if brand_id:
                with open(HEADERS_FILE) as f:
                    h = json.load(f)
                h["x-goog-pageid"] = brand_id
                with open(HEADERS_FILE, "w") as f:
                    json.dump(h, f, indent=4)
            # Re-read to check verify (below)
            with open(HEADERS_FILE) as f:
                processed = json.load(f)
            
        # Priority 3: Processed dictionary (JSON Array/Cookie string)
        else:
            FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:88.0) Gecko/20100101 Firefox/88.0"
            processed = {
                "user-agent": headers_data.get("user-agent") or headers_data.get("User-Agent", FIREFOX_UA),
                "cookie": headers_data.get("cookie") or headers_data.get("Cookie"),
                "accept": headers_data.get("accept") or headers_data.get("Accept", "*/*"),
                "accept-language": headers_data.get("accept-language") or headers_data.get("Accept-Language", "en-US,en;q=0.5"),
                "x-goog-authuser": str(headers_data.get("x-goog-authuser") or headers_data.get("X-Goog-AuthUser", "0")),
                "authorization": "SAPISIDHASH 1"
            }
                
        if brand_id:
            processed["x-goog-pageid"] = brand_id
        
        if not processed.get("cookie"):
            return False, "No cookies found in the provided input."
                
        # Save as JSON (always standardized)
        # ytmusicapi 1.11.x is CASE-SENSITIVE for certain keys if passed as dict
        final_h = {k.lower(): v for k, v in processed.items()}
        if "authorization" not in final_h:
            final_h["authorization"] = "SAPISIDHASH 1"

        with open(HEADERS_FILE, "w") as f:
            json.dump(final_h, f, indent=4)
            
        # Verify
        yt = YTMusic(auth=final_h)
        yt.get_home()
        return True, "Success"
    except Exception as e:
        if os.path.exists(HEADERS_FILE):
            os.remove(HEADERS_FILE)
        error_msg = str(e)
        print(f"Browser headers setup error: {error_msg}")
        # Improve message for common cookie errors
        if "__Secure-3PAPISID" in error_msg:
            error_msg = "Your cookies are missing the required '__Secure-3PAPISID' value. Please ensure you are logged in and copy ALL cookies."
        return False, error_msg

def is_ytmusic_authenticated() -> bool:
    return os.path.exists(HEADERS_FILE)


def check_ytmusic_auth() -> bool:
    """Returns True if auth is currently valid."""
    auth = get_auth_headers()
    if not auth:
        return False
    try:
        yt = YTMusic(auth=auth)
        yt.get_home()
        return True
    except Exception:
        return False


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
    Search YT Music for a track with multi-query fallback strategy.
    """
    yt = get_ytmusic_client()
    
    def _try_search(q: str) -> dict | None:
        try:
            results = _with_retry(yt.search, q, filter="songs", limit=5)
            if not results:
                return None
            
            # Selection logic
            best = results[0]
            for r in results:
                if spotify_duration_ms:
                    yt_dur = _parse_yt_duration(r.get("duration"))
                    if yt_dur and abs((spotify_duration_ms/1000) - yt_dur) <= 20:
                        best = r
                        best["confidence"] = "high"
                        return best
            
            # Fallback best
            best["confidence"] = "low"
            return best
        except Exception:
            return None

    # Strategy 1: Official Audio
    result = _try_search(f"{query} official audio")
    if result and result.get("confidence") == "high":
        return result

    # Strategy 2: Plain original query
    result2 = _try_search(query)
    if result2 and result2.get("confidence") == "high":
        return result2

    # Strategy 3: Title only
    if track_name and track_name.lower() not in query.lower():
        result3 = _try_search(track_name)
        if result3:
            result3["confidence"] = "low"
            return result3

    return result2 or result


def rename_yt_playlist(playlist_id: str, new_title: str):
    yt = get_ytmusic_client()
    return _with_retry(yt.edit_playlist, playlist_id, title=new_title)


def get_yt_playlists(synced_only=False):
    """
    Fetch playlists from YouTube Music.
    If synced_only=True, use fallback logic to find where synced playlists (SP_) are stored.
    If synced_only=False, just return all playlists from the authenticated account.
    """
    headers = get_auth_headers()
    if not headers:
        return []

    try:
        # Layer 1: Direct Internal Browse (Proven most robust)
        manual_pls = _fetch_library_playlists_manual(headers)
        if manual_pls:
            print(f"DEBUG: Found {len(manual_pls)} playlists via Manual Browse.")
            all_found = {p['playlistId']: p for p in manual_pls}
            if not synced_only:
                return list(all_found.values())
            if any(p.get('title', '').startswith('SP_') for p in all_found.values()):
                return list(all_found.values())

        # Layer 2: Standard Library Scan (Fallback)
        yt = YTMusic(auth=headers)
        library_pls = _with_retry(yt.get_library_playlists, limit=None) or []
        
        # Layer 3: Deep Home Feed Scan (resilience)
        home_pls = _deep_scan_home_playlists(headers)
        
        # Combine and deduplicate
        all_found = {p['playlistId']: p for p in (library_pls + home_pls)}
        
        if not synced_only:
            return list(all_found.values())

        # SYNC DISCOVERY MODE - specifically looking for 'SP_' prefix
        if any(p.get('title', '').startswith('SP_') for p in all_found.values()):
            return list(all_found.values())

        # Fallback 1: Check other brand account indices (1-3)
        for i in range(1, 4):
            try:
                indexed_headers = headers.copy()
                indexed_headers['x-goog-authuser'] = str(i)
                yt_indexed = YTMusic(auth=indexed_headers)
                
                indexed_pls = _with_retry(yt_indexed.get_library_playlists, limit=None)
                if indexed_pls and any(p.get('title', '').startswith('SP_') for p in indexed_pls):
                    # We found the synced account! Suggest switching to it or just return these.
                    return indexed_pls
            except:
                continue

        # Fallback 2: Deep Scan Home Feed (last resort)
        return _deep_scan_home_playlists(headers)

    except Exception as e:
        print(f"ERROR reaching playlists: {e}")
        return []

def _deep_scan_home_playlists(headers):
    """Fallback to find playlists on the home page if library is restricted."""
    try:
        yt = YTMusic(auth=headers)
        home = _with_retry(yt.get_home)
        found = []
        for section in home:
            contents = section.get('contents', [])
            # Some sections have a 'contents' list directly
            if not contents and 'items' in section:
                contents = section.get('items', [])
            
            for item in contents:
                if 'playlistId' in item:
                    found.append({
                        'title': item.get('title', 'Unknown Playlist'),
                        'playlistId': item['playlistId'],
                        'thumbnails': item.get('thumbnails', []),
                        'count': str(item.get('count', '0'))
                    })
                # Sometimes playlists are nested in a 'renderer'
                elif 'playlistRenderer' in item:
                    pr = item['playlistRenderer']
                    found.append({
                        'title': pr.get('title', {}).get('runs', [{'text': 'Unknown'}])[0].get('text'),
                        'playlistId': pr.get('playlistId'),
                        'thumbnails': pr.get('thumbnails', []),
                        'count': pr.get('videoCount', '0')
                    })
        
        # Deduplicate
        seen = set()
        unique = []
        for p in found:
            if p['playlistId'] not in seen:
                seen.add(p['playlistId'])
                unique.append(p)
        return unique
    except Exception as e:
        print(f"DEBUG: Home scan failed: {e}")
        return []


def _get_sapisid_hash(cookie_str: str) -> str:
    """Generate the SAPISIDHASH from the given cookie string."""
    cookies = {}
    for part in cookie_str.split(';'):
        if '=' in part:
            k, v = part.strip().split('=', 1)
            cookies[k.strip()] = v.strip()
    
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")
    ts = int(time.time())
    h = hashlib.sha1(f"{ts} {sapisid} https://music.youtube.com".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{h}"


def _api_post(endpoint: str, body: dict, headers: dict) -> dict:
    """Low-level helper to make direct POST requests to the internal YTM API."""
    base_url = "https://music.youtube.com/youtubei/v1/"
    api_key = "AIzaSyC9XL3ZjWddXya6X74dJoCTL-WEYFDNX30"
    url = f"{base_url}{endpoint}?key={api_key}"
    
    cookie_str = headers.get('cookie', '')
    
    internal_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Content-Type": "application/json",
        "X-Goog-AuthUser": str(headers.get('x-goog-authuser', '0')),
        "X-Origin": "https://music.youtube.com",
        "Authorization": _get_sapisid_hash(cookie_str),
        "Cookie": cookie_str,
    }
    
    # Support Brand Accounts
    if 'x-goog-pageid' in headers:
        internal_headers["X-Goog-PageId"] = headers["x-goog-pageid"]

    body["context"] = {
        "client": {
            "clientName": "WEB_REMIX",
            "clientVersion": "1.20240101.00.00",
            "hl": "en",
            "gl": "US",
        }
    }
    
    resp = requests.post(url, headers=internal_headers, json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _fetch_library_playlists_manual(headers: dict) -> list:
    """Uses direct internal API calls to browse library when ytmusicapi fails."""
    try:
        body = {"browseId": "FEmusic_liked_playlists"}
        data = _api_post("browse", body, headers)

        def safe_text(obj):
            if not obj: return ""
            if isinstance(obj, str): return obj
            runs = obj.get("runs", [])
            return "".join(r.get("text", "") for r in runs)

        found = []

        # Use recursive search to find any playlist renderers
        def find_renderers(obj):
            if isinstance(obj, dict):
                for key in ["musicTwoRowItemRenderer", "musicNavigationButtonRenderer"]:
                    if key in obj:
                        r = obj[key]
                        title = safe_text(r.get("title"))
                        nav = r.get("navigationEndpoint", {})
                        pid = (nav.get("browseEndpoint", {}).get("browseId", "") or 
                              nav.get("watchPlaylistEndpoint", {}).get("playlistId", ""))
                        if pid and title:
                            subtitle = safe_text(r.get("subtitle"))
                            count = "0"
                            if subtitle:
                                m = re.search(r"(\d+)", subtitle)
                                if m: count = m.group(1)
                            
                            found.append({
                                'title': title,
                                'playlistId': pid,
                                'thumbnails': r.get('thumbnailRenderer', {}).get('musicThumbnailRenderer', {}).get('thumbnail', {}).get('thumbnails', []),
                                'count': count
                            })
                for v in obj.values():
                    find_renderers(v)
            elif isinstance(obj, list):
                for item in obj:
                    find_renderers(item)

        find_renderers(data)
        return found
    except Exception as e:
        print(f"DEBUG: Manual browse failed: {e}")
        return []


def get_yt_playlist_tracks(playlist_id: str):
    """Fetch playlist tracks using a hybrid approach."""
    headers = get_auth_headers()
    if headers:
        # Strategy 1: Direct Internal API (matches fetch_direct_1.py)
        try:
            # Strip VL prefix if present
            pid = playlist_id[2:] if playlist_id.startswith("VL") else playlist_id
            body = {"playlistId": pid}
            data = _api_post("next", body, headers)
            
            def safe_text(obj):
                if not obj: return ""
                if isinstance(obj, str): return obj
                runs = obj.get("runs", [])
                return "".join(r.get("text", "") for r in runs)

            tracks = []
            try:
                contents = (
                    data.get("contents", {})
                    .get("singleColumnMusicWatchNextResultsRenderer", {})
                    .get("tabbedRenderer", {})
                    .get("watchNextTabbedResultsRenderer", {})
                    .get("tabs", [{}])[0]
                    .get("tabRenderer", {})
                    .get("content", {})
                    .get("musicQueueRenderer", {})
                    .get("content", {})
                    .get("playlistPanelRenderer", {})
                    .get("contents", [])
                )
                for item in contents:
                    r = item.get("playlistPanelVideoRenderer", {})
                    if not r: continue
                    title = safe_text(r.get("title"))
                    artist_runs = r.get("longBylineText", {}).get("runs", [])
                    artists = ", ".join(
                        run["text"] for run in artist_runs
                        if run.get("navigationEndpoint", {}).get("browseEndpoint", {}).get("browseEndpointContextSupportedConfigs", {})
                    )
                    tracks.append({
                        "title": title,
                        "artists": [{"name": artists}],  # Standardized format
                        "videoId": r.get("videoId", ""),
                        "duration": safe_text(r.get("lengthText")),
                        "duration_seconds": _parse_yt_duration(safe_text(r.get("lengthText")))
                    })
                if tracks:
                    return tracks
            except Exception as e:
                print(f"DEBUG: Direct track parse error: {e}")
        except Exception as e:
            print(f"DEBUG: Direct track fetch failed: {e}")

    # Strategy 2: Fallback to ytmusicapi
    yt = get_ytmusic_client()
    playlist = _with_retry(yt.get_playlist, playlist_id, limit=None)
    return playlist.get('tracks', [])


def create_yt_playlist(title: str, description: str, video_ids: list):
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
