from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from sync_history import get_history, get_run_log, get_recent_unmatched, get_library_stats, get_all_unmatched_tracks

router = APIRouter(prefix="/api", tags=["History & Analytics"])

@router.get("/history")
def history_api(limit: int = 200):
    return {"history": get_history()}

@router.get("/history/{run_id}")
def history_run_api(run_id: int):
    log_text = get_run_log(run_id)
    if not log_text:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"log": log_text}

@router.get("/analytics/summary")
def analytics_summary():
    return get_library_stats()

@router.get("/unmatched/recent")
def get_recent_unmatched_api():
    """Return the unmatched tracks from the most recent sync run."""
    try:
        return {"tracks": get_recent_unmatched()}
    except Exception as e:
        return {"tracks": [], "error": str(e)}

@router.get("/unmatched/csv")
def export_unmatched_csv():
    try:
        rows = get_all_unmatched_tracks()
        lines = ["Playlist,Track,Artist"]
        for r in rows:
            def _esc(s):
                return f'"{str(s).replace(chr(34), chr(34)+chr(34))}"'
            lines.append(f"{_esc(r[0])},{_esc(r[1])},{_esc(r[2])}")
        csv_text = "\n".join(lines)
        return PlainTextResponse(
            csv_text,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=unmatched_tracks.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
