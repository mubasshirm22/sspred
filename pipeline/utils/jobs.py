"""
Job folder management for the protein analysis pipeline.
Each job lives in pipeline_jobs/<job_id>/ and has a status.json file.
"""

import os
import json
import uuid
from datetime import datetime, timezone

# Absolute path to the pipeline_jobs directory (sibling of this package)
_BASE = os.path.join(os.path.dirname(__file__), "..", "..", "pipeline_jobs")
JOBS_DIR = os.path.abspath(_BASE)


def new_job_id() -> str:
    """Return a short unique job ID (12 hex chars)."""
    return uuid.uuid4().hex[:12]


def job_dir(job_id: str) -> str:
    return os.path.join(JOBS_DIR, job_id)


def create_job_dir(job_id: str) -> str:
    """Create the job directory and initialise status.json. Returns the path."""
    d = job_dir(job_id)
    os.makedirs(d, exist_ok=True)
    _write_status(d, "pending", modules={})
    return d


def _write_status(
    d: str,
    status: str,
    modules: dict = None,
    error: str = "",
    module_details: dict = None,
):
    path = os.path.join(d, "status.json")
    existing = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            pass

    existing["status"] = status
    existing.setdefault("started", datetime.now(timezone.utc).isoformat())
    if status in ("complete", "error"):
        existing["finished"] = datetime.now(timezone.utc).isoformat()
    if modules is not None:
        existing.setdefault("modules", {})
        existing["modules"].update(modules)
    if module_details is not None:
        existing.setdefault("module_details", {})
        for module_name, details in module_details.items():
            existing["module_details"].setdefault(module_name, {})
            if isinstance(details, dict):
                existing["module_details"][module_name].update(details)
    if error:
        existing["error"] = error

    with open(path, "w") as f:
        json.dump(existing, f, indent=2)


def set_status(job_id: str, status: str, error: str = ""):
    """Set the top-level job status (running / complete / error)."""
    _write_status(job_dir(job_id), status, error=error)


def set_module_status(job_id: str, module: str, status: str):
    """Update the status of one module (pending / running / complete / error / skipped)."""
    _write_status(job_dir(job_id), _get_top_status(job_id), modules={module: status})


def set_module_detail(job_id: str, module: str, **details):
    """Update rich metadata for one module without changing its status shape."""
    if not details:
        return
    _write_status(
        job_dir(job_id),
        _get_top_status(job_id),
        module_details={module: details},
    )


def _get_top_status(job_id: str) -> str:
    path = os.path.join(job_dir(job_id), "status.json")
    try:
        with open(path) as f:
            return json.load(f).get("status", "running")
    except Exception:
        return "running"


def get_status(job_id: str) -> dict:
    """Return the full status dict for a job, or {"status": "not_found"} if missing."""
    path = os.path.join(job_dir(job_id), "status.json")
    if not os.path.exists(path):
        return {"status": "not_found"}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {"status": "error", "error": "Could not read status file."}


def write_result(job_id: str, filename: str, data):
    """Write a result file (dict → JSON, or str → text)."""
    path = os.path.join(job_dir(job_id), filename)
    if isinstance(data, (dict, list)):
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    else:
        with open(path, "w") as f:
            f.write(str(data))


def read_result(job_id: str, filename: str):
    """Read a result file. Returns dict/list for JSON, str for text, None if missing."""
    path = os.path.join(job_dir(job_id), filename)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        content = f.read()
    try:
        return json.loads(content)
    except Exception:
        return content


def get_summary(job_id: str) -> dict:
    """Return the combined summary.json for a completed job."""
    return read_result(job_id, "summary.json") or {}


def list_jobs(limit: int = 100):
    """Return recent jobs from the filesystem archive."""
    if not os.path.isdir(JOBS_DIR):
        return []

    entries = []
    for job_id in os.listdir(JOBS_DIR):
        job_path = job_dir(job_id)
        if not os.path.isdir(job_path):
            continue
        try:
            sort_key = os.path.getmtime(os.path.join(job_path, "status.json"))
        except OSError:
            sort_key = os.path.getmtime(job_path)
        entries.append((sort_key, job_id))

    jobs = []
    for _, job_id in sorted(entries, reverse=True):
        status = get_status(job_id)
        summary = get_summary(job_id)
        retrieval = summary.get("retrieval", {}) if isinstance(summary, dict) else {}
        input_label = (
            retrieval.get("header")
            or retrieval.get("resolved_acc")
            or retrieval.get("accession")
            or retrieval.get("resolved_from")
            or "Sequence input"
        )
        jobs.append({
            "job_id": job_id,
            "status": status.get("status", "unknown"),
            "started": status.get("started", ""),
            "finished": status.get("finished", ""),
            "input_label": input_label,
            "length": (summary.get("properties") or {}).get("length"),
        })
        if len(jobs) >= limit:
            break
    return jobs
