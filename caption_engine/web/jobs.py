"""Background job runner with Server-Sent-Events progress streaming.

Transcription and rendering are slow and blocking, so each runs on a daemon
thread while the request returns a job id immediately. The browser then opens an
``EventSource`` to ``/api/jobs/<id>/events`` and receives ``progress`` /
``done`` / ``error`` events. This mirrors the old Tkinter ``queue`` +
``after(50, poll)`` pattern, just over HTTP instead of a Tk mainloop.
"""
import json
import queue
import threading
import uuid
from typing import Callable, Dict, Optional


class Job:
    """A single background task and the event queue the browser drains."""

    def __init__(self):
        self.id = uuid.uuid4().hex[:12]
        self._q: "queue.Queue[dict]" = queue.Queue()
        self.result = None
        self.error: Optional[str] = None
        self.done = threading.Event()

    def emit(self, event: dict) -> None:
        self._q.put(event)

    def progress(self, current: int, total: int, message: str = "") -> None:
        self.emit({"type": "progress", "current": current,
                   "total": total, "message": message})


_JOBS: Dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def submit(target: Callable[[Job], object]) -> Job:
    """Run ``target(job)`` on a daemon thread; return the Job immediately.

    ``target`` returns the result (embedded in the terminal ``done`` event) and
    may call ``job.progress(...)`` / ``job.emit(...)`` as it runs.
    """
    job = Job()
    with _JOBS_LOCK:
        _JOBS[job.id] = job

    def run():
        try:
            job.result = target(job)
            job.emit({"type": "done", "result": job.result})
        except Exception as e:  # noqa: BLE001 — surface any failure to the UI
            job.error = str(e)
            job.emit({"type": "error", "message": str(e)})
        finally:
            job.done.set()

    threading.Thread(target=run, daemon=True).start()
    return job


def get(job_id: str) -> Optional[Job]:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


def stream(job_id: str):
    """Yield SSE ``data:`` frames for a job until it terminates.

    Safe to connect after the job started — events are buffered in the queue, so
    nothing emitted before the browser connects is lost.
    """
    job = get(job_id)
    if job is None:
        yield f"data: {json.dumps({'type': 'error', 'message': 'unknown job'})}\n\n"
        return
    while True:
        event = job._q.get()
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        if event["type"] in ("done", "error"):
            break
    # Job is finished; forget it so the dict doesn't grow unbounded.
    with _JOBS_LOCK:
        _JOBS.pop(job_id, None)
