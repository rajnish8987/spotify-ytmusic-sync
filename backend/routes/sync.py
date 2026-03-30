from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json as json_lib
import time
import queue
import threading
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from spotify_client import get_playlists, get_playlist_tracks
from ytmusic_client import (
    get_yt_playlists, get_yt_playlist_tracks, search_yt_track,
    rename_yt_playlist, get_ytmusic_client, _with_retry, BATCH_SIZE
)
from sync_history import (
    save_sync_run, get_last_synced,
    get_playlist_state, set_playlist_state,
    save_unmatched_tracks, get_retry_candidates, 
    increment_retry_count, mark_retry_resolved,
    get_recent_unmatched
)
from core.config import SYNC_STATE, PARALLEL_PLAYLISTS, RESUME_FILE, UNDO_FILE
from core.utils import format_yt_name

router = APIRouter(prefix="/api", tags=["Sync"])

class PreviewRequest(BaseModel):
    spotify_playlist_ids: list[str]

@router.post("/preview")
def preview_playlists(req: PreviewRequest):
    """Return Spotify track listings for selected playlists (no YT search yet)."""
    try:
        sp_playlists = get_playlists()
        sp_dict = {p['id']: p for p in sp_playlists}
        result = []
        for sp_id in req.spotify_playlist_ids:
            if sp_id not in sp_dict:
                continue
            p = sp_dict[sp_id]
            tracks_raw = get_playlist_tracks(sp_id)
            tracks = []
            for item in tracks_raw:
                t = item.get('track')
                if t and t.get('name'):
                    tracks.append({
                        "id": t.get('id', ''),
                        "name": t['name'],
                        "artist": t.get('artists', [{}])[0].get('name', ''),
                        "duration_ms": t.get('duration_ms', 0),
                        "album": t.get('album', {}).get('name', ''),
                    })
            result.append({
                "id": sp_id,
                "name": p.get('name', ''),
                "image": p.get('images', [{}])[0].get('url', '') if p.get('images') else '',
                "tracks": tracks,
            })
        return {"playlists": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class SyncRequest(BaseModel):
    spotify_playlist_ids: list[str]
    excluded_track_ids: dict[str, list[str]] = {}
    dry_run: bool = False
    resume: bool = False
    force_resync: bool = False
    csv_playlists: list[dict] = None

UPLOAD_STATE_PREFIX = "upload_state_"

def _upload_state_file(sp_id: str) -> str:
    return f"{UPLOAD_STATE_PREFIX}{sp_id}.json"

def _load_upload_state(sp_id: str) -> dict:
    f = _upload_state_file(sp_id)
    if os.path.exists(f):
        try:
            with open(f) as fh:
                return json_lib.load(fh)
        except Exception:
            pass
    return {}

def _save_upload_state(sp_id: str, yt_pid: str, last_batch: int):
    try:
        with open(_upload_state_file(sp_id), "w") as fh:
            json_lib.dump({"yt_pid": yt_pid, "last_batch": last_batch}, fh)
    except Exception:
        pass

def _clear_upload_state(sp_id: str):
    f = _upload_state_file(sp_id)
    if os.path.exists(f):
        try: os.remove(f)
        except Exception: pass

def _sync_generator(playlist_ids: list[str], excluded: dict[str, list[str]], dry_run: bool = False, resume_run: bool = False, force_resync: bool = False, csv_playlists: list[dict] = None):
    def event(data: dict) -> str:
        return f"data: {json_lib.dumps(data)}\n\n"

    def search_one(t: dict) -> dict:
        try:
            result = search_yt_track(t["query"], t.get("duration_ms"), t.get("name"))
            if result and result.get('videoId'):
                confidence = result.get("confidence", "high")
                return {"ok": True, "query": t["query"], "name": t["name"],
                        "artist": t.get("artist", ""),
                        "videoId": result['videoId'],
                        "ytTitle": result.get('title', t['name']),
                        "confidence": confidence}
        except Exception:
            pass
        return {"ok": False, "query": t["query"], "name": t["name"], "artist": t.get("artist", "")}

    _lock = threading.Lock()
    total_matched = 0
    total_not_found = 0
    total_added = 0
    playlist_stats = []
    all_log_lines = []
    completed_sp_ids = set()

    if resume_run and os.path.exists(RESUME_FILE):
        try:
            with open(RESUME_FILE, "r") as f:
                state = json_lib.load(f)
                completed_sp_ids = set(state.get("completed_sp_ids", []))
                total_matched = state.get("total_matched", 0)
                total_not_found = state.get("total_not_found", 0)
                total_added = state.get("total_added", 0)
                playlist_stats = state.get("playlist_stats", [])
        except Exception:
            pass

    SYNC_STATE["is_paused"] = False
    SYNC_STATE["is_cancelled"] = False
    SYNC_STATE["is_running"] = True

    def log_str(data: dict) -> str:
        if data.get("type") == "log":
            with _lock:
                all_log_lines.append(data.get("msg", ""))
        return event(data)

    ev_queue: queue.Queue = queue.Queue()

    def put(ev_str: str):
        ev_queue.put(ev_str)

    def put_log(data: dict):
        put(log_str(data))

    def _process_one_playlist(sp_id: str, sp_dict: dict, yt_playlist_names: dict, idx: int, total: int):
        nonlocal total_matched, total_not_found, total_added

        if sp_id not in sp_dict:
            return
        if sp_id in completed_sp_ids:
            put_log({"type": "log", "level": "info",
                     "msg": f"━━━ [{idx+1}/{total}] \"{sp_dict[sp_id]['name']}\" (Already synced in previous run) ━━━"})
            return

        sp_p = sp_dict[sp_id]
        raw_title = sp_p['name']
        yt_title = format_yt_name(raw_title)
        excluded_ids = set(excluded.get(sp_id, []))
        progress = int((idx / total) * 100)

        put(event({"type": "progress", "value": progress}))
        put_log({"type": "log", "level": "info",
                 "msg": f"━━━ [{idx+1}/{total}] \"{raw_title}\" ━━━"})

        is_csv = sp_p.get("is_csv", False)
        sp_tracks_data = []
        track_list = []
        current_count = 0

        if is_csv:
            raw_tracks = sp_p.get("tracks", [])
            track_list = []
            for i, t in enumerate(raw_tracks):
                if f"csv_track_{i}" not in excluded_ids:
                    track_list.append(t)
            current_count = len(track_list)
        else:
            try:
                from spotify_client import get_playlist_tracks as _sp_tracks
                sp_tracks_data = _sp_tracks(sp_id)
            except Exception as e:
                put_log({"type": "log", "level": "error", "msg": f"🛑 Spotify API failed: {e}. Skipping playlist."})
                return
            current_count = len([i for i in sp_tracks_data if i and i.get('track') and i.get('track').get('id','') not in excluded_ids])

        if current_count == 0:
            put_log({"type": "log", "level": "warn", "msg": "  ⚠️ Playlist empty or all tracks excluded. Skipping."})
            return

        with _lock:
            exists_on_yt = (yt_title in yt_playlist_names)
        state_db = None if (force_resync or not exists_on_yt) else get_playlist_state(raw_title)

        is_delta = False
        new_tracks_since = None

        if state_db and state_db['last_track_count'] == current_count and state_db['last_added_at']:
            put_log({"type": "log", "level": "success",
                     "msg": f"  ⚡ Delta: playlist unchanged ({current_count} tracks). Skipping."})
            with _lock:
                playlist_stats.append({"name": raw_title, "yt_name": yt_title,
                                       "status": "up-to-date", "matched": 0, "not_found": 0,
                                       "added": 0, "total": current_count, "match_pct": 100, "low_conf": 0})
            set_playlist_state(raw_title, current_count, state_db['last_added_at'])
            if not dry_run:
                save_sync_run(raw_title, yt_title, "up-to-date", 0, 0, 0,
                               current_count, all_log_lines.copy())
            return

        elif state_db and state_db['last_added_at']:
            new_tracks_since = state_db['last_added_at']
            is_delta = True
            put_log({"type": "log", "level": "info",
                     "msg": f"  ⚡ Delta sync: {(current_count - state_db['last_track_count']):+d} new tracks since {new_tracks_since[:10]}."})

        if not is_csv:
            track_list = []
            newest_added_at = state_db['last_added_at'] if state_db else None
            for item in sp_tracks_data:
                if not item: continue
                t = item.get('track')
                if not t or not t.get('name'): continue
                tid = t.get('id', '')
                if tid in excluded_ids: continue
                added_at = item.get('added_at', '')
                if added_at and (newest_added_at is None or added_at > newest_added_at):
                    newest_added_at = added_at
                if is_delta and new_tracks_since and added_at and added_at <= new_tracks_since:
                    continue
                name = t['name']
                artist = t.get('artists', [{}])[0].get('name', '')
                track_list.append({"name": name, "artist": artist,
                                   "query": f"{name} {artist}",
                                   "duration_ms": t.get('duration_ms')})
        else:
             newest_added_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

        skipped_excl = len([i for i in sp_tracks_data if i and i.get('track') and i.get('track', {}).get('id', '') in excluded_ids])
        delta_note = f", delta: only {len(track_list)} new" if is_delta else ""
        put_log({"type": "log", "level": "info",
                 "msg": f"  Found {current_count} tracks total{delta_note}"
                        f"{f' ({skipped_excl} excluded)' if skipped_excl else ''}. Searching YT Music (5 concurrent)..."})
        put(event({"type": "playlist_ring_init", "playlist": raw_title,
                   "total_batches": max(1, (len(track_list) + 49) // 50)}))

        search_cache_file = f"search_cache_{sp_id}.json"
        matched, not_found, low_conf = [], [], []

        if os.path.exists(search_cache_file):
            try:
                with open(search_cache_file, "r") as f:
                    cache = json_lib.load(f)
                matched = cache.get("matched", [])
                not_found = cache.get("not_found", [])
                low_conf = [m for m in matched if m.get("confidence") == "low"]
                put_log({"type": "log", "level": "success",
                         "msg": f"  ⚡ Loaded search cache: {len(matched)} matched, {len(not_found)} missed. Skipping search!"})
            except Exception:
                os.remove(search_cache_file)

        if not matched and not not_found:
            SEARCH_BATCH_SIZE = 50
            total_tracks = len(track_list)
            cancelled = False
            _batch_times = []
            for i in range(0, total_tracks, SEARCH_BATCH_SIZE):
                while SYNC_STATE["is_paused"]:
                    put_log({"type": "log", "level": "warn", "msg": f"  ⏸️ [{raw_title}] Search paused..."})
                    time.sleep(2)
                if SYNC_STATE["is_cancelled"]:
                    cancelled = True; break
                batch = track_list[i:i + SEARCH_BATCH_SIZE]
                batch_num = (i // SEARCH_BATCH_SIZE) + 1
                total_batches = (total_tracks + SEARCH_BATCH_SIZE - 1) // SEARCH_BATCH_SIZE
                put_log({"type": "log", "level": "info", "msg": f"    [{raw_title}] 🔍 Searching Batch {batch_num}/{total_batches}..."})
                _t0 = time.monotonic()
                results_map = {}
                with ThreadPoolExecutor(max_workers=5) as pool:
                    fut_map = {pool.submit(search_one, t): bi for bi, t in enumerate(batch)}
                    for future in as_completed(fut_map):
                        results_map[fut_map[future]] = future.result()
                _batch_times.append(time.monotonic() - _t0)
                for bi in range(len(batch)):
                    r = results_map[bi]
                    if r["ok"]:
                        matched.append(r); 
                        if r.get("confidence") == "low": low_conf.append(r)
                    else: not_found.append(r)
                batch_matched = sum(1 for r in results_map.values() if r["ok"])
                put_log({"type": "log", "level": "info", "msg": f"    ✅ [{raw_title}] Batch {batch_num} ({batch_matched} matched, {len(batch)-batch_matched} missed)"})
                batches_left = total_batches - batch_num
                put(event({"type": "playlist_progress", "playlist": raw_title, "batch": batch_num, "total_batches": total_batches, "phase": "search"}))
                if _batch_times and batches_left > 0:
                    avg = sum(_batch_times) / len(_batch_times)
                    eta_secs = int(avg * batches_left)
                    m, s = divmod(eta_secs, 60); eta_label = (f"~{m}m {s}s" if m else f"~{s}s") + " remaining"
                    put(event({"type": "eta", "seconds": eta_secs, "label": eta_label, "playlist": raw_title, "phase": "search"}))
                time.sleep(0.3)
            if cancelled:
                put_log({"type": "log", "level": "error", "msg": f"🛑 [{raw_title}] Search cancelled."})
                return
            if not dry_run and matched:
                try:
                    with open(search_cache_file, "w") as f:
                        json_lib.dump({"matched": matched, "not_found": not_found}, f)
                    put_log({"type": "log", "level": "info", "msg": f"  💾 [{raw_title}] Search cached."})
                except Exception: pass

        with _lock:
            total_matched += len(matched); total_not_found += len(not_found)

        retry_candidates = get_retry_candidates(raw_title, max_retries=2)
        if retry_candidates and not SYNC_STATE["is_cancelled"]:
            put_log({"type": "log", "level": "info", "msg": f"  🔄 [{raw_title}] Retrying {len(retry_candidates)} previously unmatched tracks..."})
            retry_ids_tried = [c["id"] for c in retry_candidates]
            retry_resolved_ids = []; retry_matched = []
            for cand in retry_candidates:
                if SYNC_STATE["is_cancelled"]: break
                name, artist = cand["track_name"], cand["artist"]
                for q in [artist, name, f"{name} official audio"]:
                    if not q.strip(): continue
                    try:
                        r = search_yt_track(q, None, name)
                        if r and r.get('videoId'):
                            retry_matched.append({"ok": True, "query": q, "name": name, "artist": artist, "videoId": r['videoId'], "ytTitle": r.get('title', name), "confidence": r.get("confidence", "high")})
                            retry_resolved_ids.append(cand["id"]); break
                    except Exception: pass
            if retry_matched:
                put_log({"type": "log", "level": "success", "msg": f"  ✅ [{raw_title}] Retry recovered {len(retry_matched)}/{len(retry_candidates)} tracks!"})
                matched.extend(retry_matched)
                with _lock:
                    total_matched += len(retry_matched); total_not_found = max(0, total_not_found - len(retry_matched))
                mark_retry_resolved(retry_resolved_ids)
            increment_retry_count([i for i in retry_ids_tried if i not in retry_resolved_ids])

        if not_found:
            put_log({"type": "log", "level": "info", "msg": f"  ✅ Matched: {len(matched)}  ❌ Not found: {len(not_found)}" + (f"  ⚠ Low conf: {len(low_conf)}" if low_conf else "")})
        for nf in not_found[:3]: put_log({"type": "log", "level": "warn", "msg": f"    ❌ Not found: {nf['query']}"})
        if len(not_found) > 3: put_log({"type": "log", "level": "warn", "msg": f"    ❌ ...and {len(not_found)-3} more."})
        for lc in low_conf[:3]: put_log({"type": "log", "level": "warn", "msg": f"    ⚠ Low conf: {lc['name']} → {lc['ytTitle']}"})

        if not matched:
            put_log({"type": "log", "level": "error", "msg": f"  ❌ Skipped \"{raw_title}\" — no tracks matched."})
            with _lock:
                playlist_stats.append({"name": raw_title, "yt_name": yt_title, "status": "skipped", "matched": 0, "not_found": len(not_found), "added": 0, "total": current_count, "match_pct": 0})
            save_sync_run(raw_title, yt_title, "skipped", 0, len(not_found), 0, current_count, all_log_lines.copy())
            return

        matched_ids = [m['videoId'] for m in matched]
        added_count = 0; status = "updated"

        def _upload_batches(video_ids: list, yt_pid: str, label: str) -> int:
            upload_state = _load_upload_state(sp_id)
            start_batch = 0
            if upload_state.get("yt_pid") == yt_pid and upload_state.get("last_batch", 0) > 0:
                start_batch = upload_state["last_batch"]
                put_log({"type": "log", "level": "success", "msg": f"  ⚡ [{raw_title}] Resuming upload from batch {start_batch+1} (batches 1-{start_batch} already done)."})
            total_b = (len(video_ids) + BATCH_SIZE - 1) // BATCH_SIZE
            uploaded = start_batch * BATCH_SIZE; _upload_times = []
            for i in range(start_batch * BATCH_SIZE, len(video_ids), BATCH_SIZE):
                while SYNC_STATE["is_paused"]:
                    put_log({"type": "log", "level": "warn", "msg": f"  ⏸️ [{raw_title}] Upload paused..."})
                    time.sleep(2)
                if SYNC_STATE["is_cancelled"]:
                    put_log({"type": "log", "level": "error", "msg": f"🛑 [{raw_title}] Upload cancelled."}); break
                batch_ids = video_ids[i:i + BATCH_SIZE]; batch_num = (i // BATCH_SIZE) + 1
                put_log({"type": "log", "level": "info", "msg": f"    [{raw_title}] 🚀 {label} Batch {batch_num}/{total_b}..."})
                _t0 = time.monotonic()
                if not dry_run:
                    yt = get_ytmusic_client()
                    _with_retry(yt.add_playlist_items, yt_pid, batch_ids, duplicates=False)
                    _save_upload_state(sp_id, yt_pid, batch_num); time.sleep(0.5)
                _upload_times.append(time.monotonic() - _t0); uploaded += len(batch_ids)
                batches_left = total_b - batch_num
                if _upload_times and batches_left > 0:
                    avg = sum(_upload_times) / len(_upload_times); eta_secs = int(avg * batches_left)
                    m, s = divmod(eta_secs, 60); eta_label = (f"~{m}m {s}s" if m else f"~{s}s") + " remaining"
                    put(event({"type": "eta", "seconds": eta_secs, "label": eta_label, "playlist": raw_title, "phase": "upload"}))
            return uploaded

        with _lock:
            exists_on_yt_now = (yt_title in yt_playlist_names); raw_exists = (raw_title in yt_playlist_names)

        if exists_on_yt_now:
            with _lock: yt_pid = yt_playlist_names[yt_title]
            put_log({"type": "log", "level": "info", "msg": f"  📂 [{raw_title}] Found \"{yt_title}\". Checking missing tracks..."})
            yt_tracks = get_yt_playlist_tracks(yt_pid)
            existing = {t['videoId'] for t in yt_tracks if t.get('videoId')}
            missing = [m for m in matched if m['videoId'] not in existing]
            if missing:
                put_log({"type": "log", "level": "info", "msg": f"  ➕ [{raw_title}] Adding {len(missing)} missing tracks..."})
                added_count = _upload_batches([m['videoId'] for m in missing], yt_pid, "Upload")
                put_log({"type": "log", "level": "success", "msg": f"  ✅ [{raw_title}] Done adding {added_count} tracks."})
            else: put_log({"type": "log", "level": "success", "msg": f"  ✅ [{raw_title}] Up to date."})
        elif raw_exists:
            with _lock: yt_pid = yt_playlist_names[raw_title]
            put_log({"type": "log", "level": "info", "msg": f"  ✏️ [{raw_title}] Renaming → \"{yt_title}\"..."})
            if not dry_run: rename_yt_playlist(yt_pid, yt_title)
            with _lock:
                yt_playlist_names[yt_title] = yt_pid; del yt_playlist_names[raw_title]
            yt_tracks = get_yt_playlist_tracks(yt_pid)
            existing = {t['videoId'] for t in yt_tracks if t.get('videoId')}
            missing = [m for m in matched if m['videoId'] not in existing]
            if missing:
                put_log({"type": "log", "level": "info", "msg": f"  ➕ [{raw_title}] Adding {len(missing)} new tracks..."})
                added_count = _upload_batches([m['videoId'] for m in missing], yt_pid, "Upload")
            put_log({"type": "log", "level": "success", "msg": f"  ✅ [{raw_title}] Renamed + synced ({added_count} tracks added)."})
            status = "renamed+updated"
        else:
            put_log({"type": "log", "level": "info", "msg": f"  🆕 [{raw_title}] Creating \"{yt_title}\" with {len(matched_ids)} tracks..."})
            yt_pid = ""
            if not dry_run:
                yt = get_ytmusic_client()
                yt_pid = _with_retry(yt.create_playlist, yt_title, f"Synced from Spotify: {raw_title}")
                with _lock: yt_playlist_names[yt_title] = yt_pid
            added_count = _upload_batches(matched_ids, yt_pid, "Create")
            put_log({"type": "log", "level": "success", "msg": f"  ✅ [{raw_title}] Created with {added_count} tracks."})
            status = "created"

        match_pct = round(len(matched) / current_count * 100, 1) if current_count else 0
        with _lock:
            total_added += added_count
            playlist_stats.append({
                "name": raw_title, "yt_name": yt_title, "status": status, "matched": len(matched),
                "not_found": len(not_found), "added": added_count, "total": current_count,
                "match_pct": match_pct, "low_conf": len(low_conf), "yt_pid": yt_pid,
                "not_found_tracks": [{"name": nf["name"], "artist": nf.get("artist",""), "yt_playlist_id": yt_pid} for nf in not_found],
            }); completed_sp_ids.add(sp_id)

        if not dry_run:
            run_id = save_sync_run(raw_title, yt_title, status, len(matched), len(not_found), added_count, current_count, all_log_lines.copy())
            set_playlist_state(raw_title, current_count, newest_added_at)
            if not_found: save_unmatched_tracks(run_id, raw_title, [(nf["name"], nf.get("artist", "")) for nf in not_found])
            _clear_upload_state(sp_id)
        if os.path.exists(search_cache_file):
            try: os.remove(search_cache_file); 
            except Exception: pass
        if not dry_run:
            try:
                with open(RESUME_FILE, "w") as f:
                    json_lib.dump({"completed_sp_ids": list(completed_sp_ids), "total_matched": total_matched, "total_not_found": total_not_found, "total_added": total_added, "playlist_stats": playlist_stats}, f)
            except Exception: pass

    try:
        if dry_run: put(log_str({"type": "log", "level": "warn", "msg": "🧪 DRY RUN MODE ACTIVE — No changes will be made to YouTube Music."}))
        else: put(log_str({"type": "log", "level": "info", "msg": f"🚀 Starting sync for {len(playlist_ids)} playlists (up to {PARALLEL_PLAYLISTS} at once)..."}))
        put(log_str({"type": "log", "level": "info", "msg": "📋 Fetching your YouTube Music playlists..."}))
        yt_playlists = get_yt_playlists(synced_only=True)
        yt_playlist_names = {p['title']: p['playlistId'] for p in yt_playlists if p.get('title')}
        put(log_str({"type": "log", "level": "info", "msg": f"Found {len(yt_playlists)} existing YT Music playlists."}))
        put(log_str({"type": "log", "level": "info", "msg": "🎵 Fetching your Spotify playlists..."}))
        sp_dict = {}
        if csv_playlists:
            for p in csv_playlists:
                sp_dict[p["id"]] = {"name": p["name"], "is_csv": True, "tracks": p["tracks"]}
                if p["id"] not in playlist_ids: playlist_ids.append(p["id"])
            put(log_str({"type": "log", "level": "info", "msg": f"Added {len(csv_playlists)} playlists from CSV upload."}))
        spotify_ids_present = any(not str(pid).startswith("csv_") for pid in playlist_ids)
        if spotify_ids_present:
            try:
                sp_playlists = get_playlists()
                for p in sp_playlists:
                    if p: sp_dict[p['id']] = p
                put(log_str({"type": "log", "level": "info", "msg": f"Found {len(sp_playlists)} Spotify playlists."}))
            except Exception as e: put_log({"type": "log", "level": "error", "msg": f"🛑 Spotify API fetch blocked/failed: {e}"})
        put(log_str({"type": "log", "level": "info", "msg": f"🔔 SYNC ENGINE STARTED ({PARALLEL_PLAYLISTS} parallel)"}))
        total = len(playlist_ids); pending_futures = []
        with ThreadPoolExecutor(max_workers=PARALLEL_PLAYLISTS) as pl_pool:
            for idx, sp_id in enumerate(playlist_ids):
                if SYNC_STATE["is_cancelled"]: break
                fut = pl_pool.submit(_process_one_playlist, sp_id, sp_dict, yt_playlist_names, idx, total)
                pending_futures.append(fut)
            done_count = 0
            while done_count < len(pending_futures):
                try: item = ev_queue.get(timeout=0.2); yield item
                except queue.Empty:
                    done_count = sum(1 for f in pending_futures if f.done())
                    while not ev_queue.empty(): yield ev_queue.get_nowait()
        while not ev_queue.empty(): yield ev_queue.get_nowait()
        yield event({"type": "progress", "value": 100})
        if dry_run: yield log_str({"type": "log", "level": "success", "msg": "🧪 Dry run completed."})
        else:
            yield log_str({"type": "log", "level": "success", "msg": "🎉 All playlists synced successfully!"})
            if os.path.exists(RESUME_FILE): os.remove(RESUME_FILE)
        yield event({"type": "stats", "total_matched": total_matched, "total_not_found": total_not_found, "total_added": total_added, "playlists": playlist_stats})
        yield event({"type": "done", "allow_notification": True})
    except Exception as e:
        import traceback; tb = traceback.format_exc()
        yield log_str({"type": "log", "level": "error", "msg": f"💥 Fatal error: {str(e)}"}); yield log_str({"type": "log", "level": "error", "msg": tb})
        yield event({"type": "done"})

@router.post("/sync")
def sync_playlists(req: SyncRequest):
    return StreamingResponse(
        _sync_generator(req.spotify_playlist_ids, req.excluded_track_ids, req.dry_run, req.resume, req.force_resync, req.csv_playlists),
        media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

@router.post("/sync/pause")
def pause_sync():
    SYNC_STATE["is_paused"] = True
    return {"status": "paused"}

@router.post("/sync/resume")
def resume_sync():
    SYNC_STATE["is_paused"] = False
    return {"status": "resumed"}

@router.post("/sync/cancel")
def cancel_sync():
    SYNC_STATE["is_cancelled"] = True
    SYNC_STATE["is_paused"] = False
    return {"status": "cancelled"}

@router.get("/sync/status")
def get_sync_status():
    return SYNC_STATE

@router.get("/sync/resume-state")
def get_resume_state():
    if os.path.exists(RESUME_FILE):
        try:
            with open(RESUME_FILE, "r") as f:
                state = json_lib.load(f)
                return {"can_resume": True, "completed": len(state.get("completed_sp_ids", []))}
        except Exception: pass
    return {"can_resume": False}

@router.delete("/sync/resume-state")
def clear_resume_state():
    if os.path.exists(RESUME_FILE):
        try: os.remove(RESUME_FILE)
        except Exception: pass
    return {"status": "cleared"}

@router.post("/sync/save-undo")
def save_undo_state(data: dict):
    try:
        with open(UNDO_FILE, "w") as f:
            json_lib.dump(data, f)
        return {"status": "saved"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@router.get("/sync/undo-state")
def get_undo_state():
    if os.path.exists(UNDO_FILE):
        try:
            with open(UNDO_FILE) as f: return json_lib.load(f)
        except Exception: pass
    return {"available": False}

@router.post("/sync/undo")
def undo_last_sync():
    if not os.path.exists(UNDO_FILE): raise HTTPException(status_code=404, detail="No undo state available")
    try:
        with open(UNDO_FILE) as f: state = json_lib.load(f)
        removed = 0; yt = get_ytmusic_client()
        for entry in state.get("entries", []):
            pid, vids = entry.get("playlist_id"), entry.get("video_ids", [])
            if pid and vids:
                try: _with_retry(yt.remove_playlist_items, pid, vids); removed += len(vids)
                except Exception as e: print(f"Undo warning: {e}")
        os.remove(UNDO_FILE)
        return {"status": "undone", "tracks_removed": removed}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
