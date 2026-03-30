from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from spotify_client import get_auth_url, handle_callback, get_playlists, get_playlist_tracks, is_spotify_authenticated
from sync_history import get_last_synced, delete_playlist_state

router = APIRouter(prefix="/api/spotify", tags=["Spotify"])

@router.get("/check-auth")
def spotify_check_auth():
    """Lightweight check — only verifies a cached token exists (no Spotify API call)."""
    return {"authenticated": is_spotify_authenticated()}

@router.get("/auth-url")
def spotify_auth_url():
    return {"url": get_auth_url()}

@router.get("/callback")
def spotify_callback(code: str):
    handle_callback(code)
    return HTMLResponse("""
    <html><body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#0f0f1a;color:white">
    <div style="text-align:center"><div style="font-size:3rem">✅</div>
    <h2>Spotify Authenticated!</h2><p>You can close this window.</p></div>
    <script>setTimeout(()=>{window.close();if(window.opener)window.opener.location.reload()},1500)</script>
    </body></html>""")

@router.get("/playlists")
def list_spotify_playlists():
    try:
        playlists = get_playlists()
        # Attach last-synced info
        for p in playlists:
            ts = get_last_synced(p.get('name', ''))
            p['last_synced'] = ts
        return {"playlists": playlists}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/playlists/{playlist_id}/tracks")
def get_spotify_tracks(playlist_id: str):
    try:
        return {"tracks": get_playlist_tracks(playlist_id)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/playlists/state")
def clear_playlist_state(playlist_name: str):
    try:
        delete_playlist_state(playlist_name)
        return {"status": "cleared"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
