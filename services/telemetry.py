import json
import os
import statistics
import tempfile
import threading
from datetime import datetime, timedelta, timezone


_LOCK = threading.Lock()
_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "runtime"))
_PATH = os.path.join(_BASE_DIR, "telemetry.json")
_COMPONENT_HISTORY_LIMIT = 60
_JOB_HISTORY_LIMIT = 200


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _ensure_base_dir():
    os.makedirs(_BASE_DIR, exist_ok=True)


def _load():
    if not os.path.exists(_PATH):
        return {"components": {}, "jobs": {}, "updated_at": ""}
    try:
        with open(_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                data.setdefault("components", {})
                data.setdefault("jobs", {})
                return data
    except Exception:
        pass
    return {"components": {}, "jobs": {}, "updated_at": ""}


def _save(data):
    _ensure_base_dir()
    data["updated_at"] = _now_iso()
    fd, temp_path = tempfile.mkstemp(prefix="telemetry-", suffix=".json", dir=_BASE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(temp_path, _PATH)
    finally:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass


def _trim_runs(runs, limit):
    if len(runs) > limit:
        del runs[limit:]


def _as_duration(value):
    try:
        if value is None:
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def record_job_event(scope, job_id, status, summary=""):
    with _LOCK:
        data = _load()
        jobs = data["jobs"].setdefault(scope, [])
        jobs.insert(0, {
            "job_id": job_id,
            "status": status,
            "summary": (summary or "").strip()[:400],
            "at": _now_iso(),
        })
        _trim_runs(jobs, _JOB_HISTORY_LIMIT)
        _save(data)


def record_component_run(scope, component, job_id, status, summary="", raw_error="", duration_seconds=None):
    with _LOCK:
        data = _load()
        key = f"{scope}:{component}"
        entry = data["components"].setdefault(key, {
            "scope": scope,
            "component": component,
            "counts": {},
            "durations": [],
            "recent_runs": [],
            "last_failure": {},
        })

        now = _now_iso()
        duration = _as_duration(duration_seconds)
        safe_summary = (summary or "").strip()[:500]
        safe_raw = " ".join((raw_error or "").split())[:1000]

        entry["scope"] = scope
        entry["component"] = component
        entry["last_status"] = status
        entry["last_summary"] = safe_summary
        entry["updated_at"] = now
        entry["counts"][status] = int(entry["counts"].get(status, 0)) + 1

        run_entry = {
            "job_id": job_id,
            "status": status,
            "summary": safe_summary,
            "raw_error": safe_raw,
            "duration_seconds": duration,
            "at": now,
        }
        entry["recent_runs"].insert(0, run_entry)
        _trim_runs(entry["recent_runs"], _COMPONENT_HISTORY_LIMIT)

        if duration is not None and duration >= 0:
            entry["durations"].append(duration)
            entry["durations"] = entry["durations"][-_COMPONENT_HISTORY_LIMIT:]

        if status not in {"success", "ok", "complete", "warning"}:
            entry["last_failure"] = {
                "job_id": job_id,
                "at": now,
                "summary": safe_summary,
                "raw_error": safe_raw,
            }
        else:
            entry["last_success_at"] = now

        _save(data)


def snapshot():
    with _LOCK:
        data = _load()

    rows = []
    for entry in data.get("components", {}).values():
        durations = [d for d in entry.get("durations", []) if isinstance(d, (int, float))]
        median_runtime = round(statistics.median(durations), 2) if durations else None
        rows.append({
            "scope": entry.get("scope", ""),
            "component": entry.get("component", ""),
            "last_status": entry.get("last_status", ""),
            "last_summary": entry.get("last_summary", ""),
            "last_success_at": entry.get("last_success_at", ""),
            "last_failure": entry.get("last_failure", {}) or {},
            "median_runtime_seconds": median_runtime,
            "counts": entry.get("counts", {}),
            "recent_runs": entry.get("recent_runs", [])[:10],
            "updated_at": entry.get("updated_at", ""),
        })

    rows.sort(key=lambda row: (row["scope"], row["component"]))
    return {
        "components": rows,
        "jobs": data.get("jobs", {}),
        "updated_at": data.get("updated_at", ""),
    }


def recent_job_counts(hours=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    snap = snapshot()
    output = {}

    for scope, entries in snap.get("jobs", {}).items():
        by_job = {}
        for entry in entries:
            try:
                when = datetime.fromisoformat(entry.get("at", ""))
            except Exception:
                continue
            if when < cutoff:
                continue
            job_id = entry.get("job_id")
            if not job_id:
                continue
            by_job[job_id] = entry

        counts = {"total": len(by_job)}
        for item in by_job.values():
            status = item.get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1
        output[scope] = counts

    return output
