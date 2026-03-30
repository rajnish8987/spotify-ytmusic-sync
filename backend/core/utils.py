import os
import json

def format_yt_name(spotify_name: str) -> str:
    """Format Spotify playlist name to YT-Ready name with prefix."""
    if spotify_name.startswith("[CSV] "):
        spotify_name = spotify_name[6:]
    words = spotify_name.strip().split()
    # Use MORE words (up to 12) for better recognition and accuracy
    name = ' '.join(words[:12])
    return f"SP_{name}"

def load_excluded() -> list:
    from core.config import EXCLUDED_FILE
    if os.path.exists(EXCLUDED_FILE):
        try:
            with open(EXCLUDED_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_excluded(data: list):
    from core.config import EXCLUDED_FILE
    with open(EXCLUDED_FILE, "w") as f:
        json.dump(data, f)
