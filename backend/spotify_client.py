import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from fastapi import HTTPException

# Special virtual ID for Liked Songs
LIKED_SONGS_ID = "__liked_songs__"

def get_spotify_oauth():
    return SpotifyOAuth(
        client_id=os.getenv("CLIENT_ID", os.getenv("SPOTIPY_CLIENT_ID", "unconfigured")),
        client_secret=os.getenv("CLIENT_SECRET", os.getenv("SPOTIPY_CLIENT_SECRET", "unconfigured")),
        redirect_uri=os.getenv("REDIRECT_URI", os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8000/api/spotify/callback")),
        scope="playlist-read-private playlist-read-collaborative user-library-read"
    )

def get_spotify_client():
    sp_oauth = get_spotify_oauth()
    token_info = sp_oauth.get_cached_token()
    if not token_info:
        raise HTTPException(status_code=401, detail="Spotify not authenticated")
    return spotipy.Spotify(auth=token_info['access_token'])

def is_spotify_authenticated():
    """Check if we have a cached Spotify token (lightweight, no API call)."""
    try:
        sp_oauth = get_spotify_oauth()
        token_info = sp_oauth.get_cached_token()
        return token_info is not None
    except Exception:
        return False

def get_auth_url():
    sp_oauth = get_spotify_oauth()
    return sp_oauth.get_authorize_url()

def handle_callback(code: str):
    sp_oauth = get_spotify_oauth()
    token_info = sp_oauth.get_access_token(code)
    return token_info

def get_playlists():
    sp = get_spotify_client()

    # Fetch all regular playlists (paginated)
    playlists = []
    results = sp.current_user_playlists(limit=50)
    playlists.extend(results['items'])
    while results['next']:
        results = sp.next(results)
        playlists.extend(results['items'])

    # Count liked songs and prepend as a virtual playlist
    liked = sp.current_user_saved_tracks(limit=1)
    liked_count = liked.get('total', 0)
    virtual_liked = {
        "id": LIKED_SONGS_ID,
        "name": "❤️ Liked Songs",
        "tracks": {"total": liked_count},
        "images": [],
        "owner": {"display_name": "You"},
    }
    return [virtual_liked] + [p for p in playlists if p is not None]

def get_playlist_tracks(playlist_id: str):
    sp = get_spotify_client()

    # Handle Liked Songs specially
    if playlist_id == LIKED_SONGS_ID:
        results = sp.current_user_saved_tracks(limit=50)
        tracks = results['items']
        while results['next']:
            results = sp.next(results)
            tracks.extend(results['items'])
        # Liked songs items have format {"added_at": ..., "track": {...}}
        # Same shape as playlist items, so compatible with existing logic
        return tracks

    # Regular playlist - paginate
    results = sp.playlist_items(playlist_id)
    tracks = results['items']
    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])
    return tracks
