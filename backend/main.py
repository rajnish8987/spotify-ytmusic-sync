import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# Import core and routes
from core.config import SYNC_STATE, PARALLEL_PLAYLISTS, save_app_config
from routes import spotify, ytmusic, sync, history, scheduler, excluded

# Initialize logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("api")

# Load environment variables
load_dotenv()

app = FastAPI(title="Spotify-YTMusic Sync API", version="2.1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect Routers
app.include_router(spotify.router)
app.include_router(ytmusic.router)
app.include_router(sync.router)
app.include_router(history.router)
app.include_router(scheduler.router)
app.include_router(excluded.router)

@app.on_event("startup")
def startup_event():
    # Initialize DB
    from sync_history import init_db
    init_db()
    
    # Restore schedules
    from scheduler import restore_schedules_from_db
    restore_schedules_from_db()
    
    log.info("Backend started and initialized.")

@app.get("/api/health")
def health_check():
    from spotify_client import is_spotify_authenticated
    from ytmusic_client import check_ytmusic_auth
    return {
        "status": "online",
        "sync": SYNC_STATE,
        "spotify": {"authenticated": is_spotify_authenticated()},
        "ytmusic": {"authenticated": check_ytmusic_auth()},
        "version": "2.1.0"
    }

class ConfigUpdateRequest(BaseModel):
    parallel_playlists: int

@app.get("/api/config")
def get_config():
    from core.config import load_app_config
    return load_app_config()

@app.post("/api/config")
def update_config(req: ConfigUpdateRequest):
    global PARALLEL_PLAYLISTS
    PARALLEL_PLAYLISTS = req.parallel_playlists
    save_app_config({"parallel_playlists": PARALLEL_PLAYLISTS})
    return {"status": "updated", "parallel_playlists": PARALLEL_PLAYLISTS}

# Mount frontend — must be last!
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
else:
    log.warning(f"Frontend directory not found at {frontend_path}. Static files will not be served.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
