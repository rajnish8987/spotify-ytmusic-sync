from fastapi import APIRouter
from pydantic import BaseModel
from core.utils import load_excluded, save_excluded

router = APIRouter(prefix="/api/excluded-playlists", tags=["Excluded Playlists"])

class ExcludeRequest(BaseModel):
    playlist_id: str
    playlist_name: str

@router.get("")
def get_excluded_api():
    return {"excluded": load_excluded()}

@router.post("")
def add_excluded_playlist(req: ExcludeRequest):
    data = load_excluded()
    if not any(e["id"] == req.playlist_id for e in data):
        data.append({"id": req.playlist_id, "name": req.playlist_name})
        save_excluded(data)
    return {"excluded": data}

@router.delete("/{playlist_id}")
def remove_excluded_playlist(playlist_id: str):
    data = [e for e in load_excluded() if e["id"] != playlist_id]
    save_excluded(data)
    return {"excluded": data}
