import json
import os
import tempfile
import uuid
from datetime import datetime, timezone


_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "disorder_jobs"))


def _ensure_base():
    os.makedirs(_BASE, exist_ok=True)


def new_job_id():
    return uuid.uuid4().hex[:12]


def job_dir(job_id):
    return os.path.join(_BASE, job_id)


def create_job(job_id):
    _ensure_base()
    os.makedirs(job_dir(job_id), exist_ok=True)
    write_status(job_id, {"status": "pending", "started": datetime.now(timezone.utc).isoformat()})


def write_status(job_id, data):
    _ensure_base()
    path = os.path.join(job_dir(job_id), "status.json")
    _atomic_json(path, data)


def read_status(job_id):
    path = os.path.join(job_dir(job_id), "status.json")
    if not os.path.exists(path):
        return {"status": "not_found"}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {"status": "error", "error": "Could not read status file."}


def write_result(job_id, filename, data):
    _ensure_base()
    path = os.path.join(job_dir(job_id), filename)
    if isinstance(data, (dict, list)):
        _atomic_json(path, data)
    else:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(str(data))


def read_result(job_id, filename):
    path = os.path.join(job_dir(job_id), filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read()
    try:
        return json.loads(content)
    except Exception:
        return content


def _atomic_json(path, data):
    directory = os.path.dirname(path)
    fd, temp_path = tempfile.mkstemp(prefix="tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(temp_path, path)
    finally:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass
