"""
Background scheduler for auto-sync jobs using APScheduler.
"""
import json
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger("scheduler")

_scheduler = BackgroundScheduler(daemon=True)
_scheduler.start()


def _run_background_sync(spotify_id: str, playlist_ids: list[str]):
    """Consume the sync generator without SSE — results saved to history DB."""
    try:
        from sync_history import update_schedule_last_run
        # Lazy import to avoid circular dependency
        from routes.sync import _sync_generator
        log.info(f"[Scheduler] Auto-syncing schedule: {spotify_id}")
        for _ in _sync_generator(playlist_ids, {}, dry_run=False):
            pass  # generator saves history internally
        update_schedule_last_run(spotify_id)
        log.info(f"[Scheduler] Completed auto-sync for: {spotify_id}")
    except Exception as e:
        log.error(f"[Scheduler] Auto-sync error for {spotify_id}: {e}")


def add_schedule(spotify_id: str, playlist_ids: list[str], frequency: str):
    """Add or replace a scheduled sync job."""
    seconds = {"hourly": 3600, "daily": 86400, "weekly": 604800}.get(frequency, 86400)
    _scheduler.add_job(
        _run_background_sync,
        trigger=IntervalTrigger(seconds=seconds),
        args=[spotify_id, playlist_ids],
        id=spotify_id,
        replace_existing=True,
    )
    log.info(f"[Scheduler] Scheduled '{frequency}' sync for: {spotify_id}")


def remove_schedule(spotify_id: str):
    try:
        _scheduler.remove_job(spotify_id)
        log.info(f"[Scheduler] Removed job: {spotify_id}")
    except Exception:
        pass


def get_job_next_run(spotify_id: str) -> float | None:
    job = _scheduler.get_job(spotify_id)
    if job and job.next_run_time:
        return job.next_run_time.timestamp()
    return None


def restore_schedules_from_db():
    """Re-register all saved schedules on server startup."""
    try:
        from sync_history import get_all_schedules
        schedules = get_all_schedules()
        for s in schedules:
            ids = json.loads(s.get('playlist_ids', '[]'))
            if ids:
                add_schedule(s['spotify_id'], ids, s['frequency'])
        if schedules:
            log.info(f"[Scheduler] Restored {len(schedules)} schedule(s) from DB.")
    except Exception as e:
        log.error(f"[Scheduler] Error restoring schedules: {e}")
