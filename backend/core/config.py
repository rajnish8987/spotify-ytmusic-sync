import os
import json

# Global File Paths
APP_CONFIG_FILE = "app_config.json"
RESUME_FILE = "sync_resume.json"
UNDO_FILE = "undo_last_sync.json"
EXCLUDED_FILE = "excluded_playlists.json"
DB_FILE = "sync_history.db"

# Global Sync State
SYNC_STATE = {
    "is_paused": False,
    "is_cancelled": False,
    "is_running": False
}

def load_app_config() -> dict:
    defaults = {"parallel_playlists": 2}
    if os.path.exists(APP_CONFIG_FILE):
        try:
            with open(APP_CONFIG_FILE) as f:
                cfg = json.load(f)
            defaults.update(cfg)
        except Exception:
            pass
    return defaults

def save_app_config(cfg: dict):
    try:
        with open(APP_CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

# Initial Parallelism
PARALLEL_PLAYLISTS = load_app_config()["parallel_playlists"]
