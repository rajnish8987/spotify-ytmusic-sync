from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json
from ytmusic_client import (
    get_yt_playlists, get_yt_playlist_tracks, 
    rename_yt_playlist, check_ytmusic_auth, is_ytmusic_authenticated,
    get_cookie_expiry_info, save_cookie_expiry, save_ytmusic_headers,
    delete_yt_playlist, remove_from_yt_playlist, get_ytmusic_client, _with_retry
)

router = APIRouter(prefix="/api/ytmusic", tags=["YT Music"])

class YTHeadersRequest(BaseModel):
    headers_raw: str
    brand_id: str | None = None

@router.post("/save-headers")
def ytmusic_save_headers(req: YTHeadersRequest):
    try:
        raw = req.headers_raw.strip()
        final_headers = {}
        
        # Determine if it is a JSON cookie array from an extension
        try:
            cookies = json.loads(raw)
            if isinstance(cookies, list):
                # Standard cookie array from extension
                cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                final_headers = {
                    "Cookie": cookie_str,
                    "X-Goog-AuthUser": "0"
                }
        except (json.JSONDecodeError, TypeError):
            # Check for Netscape format
            if raw.startswith("# Netscape HTTP Cookie File"):
                final_headers = {"cookies_netscape": raw}
            # Not JSON — check if it's a plain cookie string (e.g., "name=val; name2=val2")
            elif "=" in raw and ";" in raw:
                final_headers = {
                    "Cookie": raw,
                    "X-Goog-AuthUser": "0"
                }
            else:
                # Treat as raw header block (the old way)
                final_headers = {"headers_raw": raw}

        # The new save_ytmusic_headers takes a dict and returns (ok, message)
        final_headers["brand_id"] = req.brand_id
        ok, msg = save_ytmusic_headers(final_headers)
        if ok:
            return {"status": "success"}
        raise HTTPException(status_code=400, detail=f"Validation failed: {msg}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/whoami")
def ytmusic_whoami():
    from ytmusic_client import get_yt_account_info
    name, email = get_yt_account_info()
    if not name:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "name": (name or "Connected"),
        "email": (email or "")
    }

@router.get("/check-auth")
def ytmusic_check_auth():
    return {"authenticated": check_ytmusic_auth()}

@router.get("/cookie-expiry")
def ytmusic_cookie_expiry():
    return get_cookie_expiry_info()

@router.get("/playlists")
def list_yt_playlists():
    try:
        from ytmusic_client import get_yt_playlists
        return {"playlists": get_yt_playlists(synced_only=False)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/playlists/{playlist_id}/tracks")
def get_yt_tracks(playlist_id: str):
    try:
        return {"tracks": get_yt_playlist_tracks(playlist_id)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/playlists/{playlist_id}")
def delete_yt_pl(playlist_id: str):
    try:
        delete_yt_playlist(playlist_id)
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

class YTRenameRequest(BaseModel):
    title: str

@router.post("/playlists/{playlist_id}/rename")
def rename_yt_pl(playlist_id: str, req: YTRenameRequest):
    try:
        rename_yt_playlist(playlist_id, req.title)
        return {"status": "renamed"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

class YTRemoveTracksRequest(BaseModel):
    video_ids: list[dict] # formatted like {"videoId": "...", "setVideoId": "..."}

@router.post("/playlists/{playlist_id}/remove-tracks")
def remove_yt_tracks(playlist_id: str, req: YTRemoveTracksRequest):
    try:
        remove_from_yt_playlist(playlist_id, req.video_ids)
        return {"status": "removed"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

class QuickAddRequest(BaseModel):
    video_id_or_url: str
    track_name: str = ""
    artist: str = ""

@router.post("/playlist/{yt_pid}/add-by-id")
def quick_add_to_playlist(yt_pid: str, req: QuickAddRequest):
    """Manually add a video to a YT Music playlist by URL or video ID."""
    raw = req.video_id_or_url.strip()
    vid = raw
    if "youtube.com" in raw or "youtu.be" in raw or "music.youtube.com" in raw:
        import re
        m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", raw) or \
            re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", raw) or \
            re.search(r"/watch\?.*v=([A-Za-z0-9_-]{11})", raw)
        if m:
            vid = m.group(1)
    if not vid or len(vid) < 5:
        raise HTTPException(status_code=400, detail="Could not extract a valid video ID")
    try:
        yt = get_ytmusic_client()
        _with_retry(yt.add_playlist_items, yt_pid, [vid], duplicates=False)
        return {"status": "added", "video_id": vid, "playlist_id": yt_pid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
