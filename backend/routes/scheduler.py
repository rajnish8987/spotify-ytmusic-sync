from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from scheduler import add_schedule, remove_schedule, get_job_next_run
from sync_history import get_all_schedules, upsert_schedule, delete_schedule
from spotify_client import get_playlists

router = APIRouter(prefix="/api/schedules", tags=["Scheduler"])

class ScheduleRequest(BaseModel):
    spotify_id: str
    playlist_ids: list[str]
    frequency: str  # hourly/daily/weekly

@router.post("")
def add_schedule_api(req: ScheduleRequest):
    try:
        # We need the name of the spotify_id to save it properly in DB
        sp_name = "Unknown Playlist"
        try:
            all_p = get_playlists()
            match = next((p for p in all_p if p['id'] == req.spotify_id), None)
            if match: sp_name = match['name']
        except Exception: pass

        add_schedule(req.spotify_id, req.playlist_ids, req.frequency)
        upsert_schedule(req.spotify_id, sp_name, req.frequency, req.playlist_ids)
        return {"status": "scheduled", "next_run": get_job_next_run(req.spotify_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("")
def list_schedules_api():
    try:
        schedules = get_all_schedules()
        for s in schedules:
            s["next_run"] = get_job_next_run(s["spotify_id"])
        return {"schedules": schedules}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{spotify_id}")
def remove_schedule_api(spotify_id: str):
    try:
        remove_schedule(spotify_id)
        delete_schedule(spotify_id)
        return {"status": "removed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
