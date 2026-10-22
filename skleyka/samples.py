"""A look at each camera angle: program frames with their faces.

Premiere wedges after a few hundred 4K frame exports in a row, so the budget
is small: a handful of frames per angle, spread over the episode (podcast
cameras are locked off, so an angle's people sit where they sit), plus a
grab on demand for the exact cut a graphic is going on. Samples are keyed by
the cut's identity (angle and multicam-source time), so a re-trim reuses
them. Grabbing goes through the bridge, about three seconds a frame, so the
batch runs as a child process: ``python -m skleyka.samples <project> <seq>``.

<episode>/skleyka/samples/<key>.jpg      a 960-wide look at the frame
<episode>/skleyka/samples/index.json     key -> faces, sample time, cut
<episode>/skleyka/samples/job.json       progress of the running job
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from . import bridge, frames, timeline

PYTHON = Path(sys.executable)
PER_ANGLE = 10        # frames per angle in a batch
GRAB_PAUSE_S = 2.0    # between frame exports; Premiere wedged after ~100-200 back to back


def samples_dir(project_path: str) -> Path:
    d = timeline.workdir(project_path) / "samples"
    d.mkdir(exist_ok=True)
    return d


def _key(shot: dict, at: float) -> str:
    src = shot["in_point"] + (at - shot["start"])
    return f"a{shot['angle']}_{int(round(src * 10)):08d}"


def _item(shot: dict, at: float) -> dict:
    return {"key": _key(shot, at), "at": round(at, 3), "angle": shot["angle"], "camera": shot["camera"],
            "cut_start": shot["start"], "cut_end": shot["end"]}


def cut_at(tl: dict, at: float) -> dict | None:
    for shot in timeline.program(tl):
        if shot["start"] <= at < shot["end"] and shot["angle"] is not None:
            return shot
    return None


def plan(tl: dict, per_angle: int = PER_ANGLE) -> list[dict]:
    """A few cuts per angle, spread over the episode, one frame each (a
    second in)."""
    by_angle: dict[int, list[dict]] = {}
    for shot in timeline.program(tl):
        if shot["angle"] is not None and shot["end"] - shot["start"] >= 2.0:
            by_angle.setdefault(shot["angle"], []).append(shot)
    out = []
    for angle, shots in sorted(by_angle.items()):
        n = min(per_angle, len(shots))
        picks = [shots[round(i * (len(shots) - 1) / max(1, n - 1))] for i in range(n)] if n > 1 else shots[:1]
        for shot in picks:
            out.append(_item(shot, shot["start"] + 1.0))
    return out


def load_index(project_path: str) -> dict:
    p = samples_dir(project_path) / "index.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_index(project_path: str, index: dict) -> None:
    p = samples_dir(project_path) / "index.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def grab_one(project_path: str, sequence_id: str, item: dict) -> dict:
    """Export the frame, keep a small JPEG, detect faces, record it."""
    import cv2
    from . import occupancy
    d = samples_dir(project_path)
    shot = frames.grab(item["at"], sequence=sequence_id, width=960)
    dst = d / f"{item['key']}.jpg"
    Path(shot["path"]).replace(dst)
    faces = occupancy.detect_faces(cv2.imread(str(dst)))
    rec = {"at": item["at"], "angle": item["angle"], "camera": item["camera"], "faces": faces,
           "image": str(dst), "timecode": shot["timecode"], "grabbed": time.strftime("%Y-%m-%d %H:%M:%S")}
    index = load_index(project_path)
    index[item["key"]] = rec
    _save_index(project_path, index)
    return rec


def grab_at(project_path: str, sequence_id: str, tl: dict, at: float) -> dict | None:
    """One export, now, for the cut at ``at`` (its own key, reused later)."""
    shot = cut_at(tl, at)
    if shot is None:
        return None
    item = _item(shot, max(shot["start"], min(at, shot["end"] - 0.1)))
    index = load_index(project_path)
    if item["key"] in index:
        return index[item["key"]] | {"key": item["key"]}
    return grab_one(project_path, sequence_id, item) | {"key": item["key"]}


def run(project_path: str, sequence_id: str) -> None:
    """The batch: grab every planned frame not in the index yet; stop as soon
    as the bridge stops answering, so it can resume later."""
    job = samples_dir(project_path) / "job.json"
    tl = timeline.read(sequence_id, save=False)
    todo = [p for p in plan(tl) if p["key"] not in load_index(project_path)]
    total, done, errors = len(todo), 0, []
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    job.write_text(json.dumps({"state": "running", "total": total, "done": 0, "started": started}))
    failures_in_a_row = 0
    for item in todo:
        try:
            grab_one(project_path, sequence_id, item)
            failures_in_a_row = 0
        except Exception as exc:
            errors.append({"key": item["key"], "at": item["at"], "error": str(exc)[:200]})
            failures_in_a_row += 1
            if failures_in_a_row >= 2 or bridge.heartbeat() is None:
                job.write_text(json.dumps({"state": "stopped", "total": total, "done": done, "errors": errors,
                                           "reason": "bridge not answering",
                                           "finished": time.strftime("%Y-%m-%d %H:%M:%S")}))
                return
        done += 1
        job.write_text(json.dumps({"state": "running", "total": total, "done": done, "errors": len(errors)}))
        time.sleep(GRAB_PAUSE_S)
    job.write_text(json.dumps({"state": "done", "total": total, "done": done, "errors": errors,
                               "finished": time.strftime("%Y-%m-%d %H:%M:%S")}))


def _alive(pid: int) -> bool:
    if not pid or pid <= 0:  # 0 is the Idle process; a stopped job is recorded as pid 0
        return False
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
    return str(pid) in out.stdout


def start(project_path: str, sequence_id: str) -> dict:
    d = samples_dir(project_path)
    job = d / "job.json"
    if job.exists():
        state = json.loads(job.read_text(encoding="utf-8"))
        if state.get("state") == "running" and state.get("pid") and _alive(state["pid"]):
            return state
    log = open(d / "job.log", "w", encoding="utf-8")
    proc = subprocess.Popen([str(PYTHON), "-m", "skleyka.samples", project_path, sequence_id],
                            cwd=str(Path(__file__).resolve().parents[1]), stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    state = {"state": "running", "pid": proc.pid, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
             "total": None, "done": 0}
    job.write_text(json.dumps(state))
    return state


def status(project_path: str) -> dict:
    job = samples_dir(project_path) / "job.json"
    index = load_index(project_path)
    per_angle: dict = {}
    for rec in index.values():
        per_angle[f"{rec['angle']}: {rec['camera']}"] = per_angle.get(f"{rec['angle']}: {rec['camera']}", 0) + 1
    base = {"samples": len(index), "per_angle": per_angle}
    if not job.exists():
        return {"state": "not_started"} | base
    return json.loads(job.read_text(encoding="utf-8")) | base


def sample_at(project_path: str, tl: dict, at: float) -> dict | None:
    """The best look at sequence time ``at``: this cut's own sample if it has
    one (``exact``), else every sample of the same angle merged (their faces
    together, so free space is free in all of them)."""
    shot = cut_at(tl, at)
    if shot is None:
        return None
    index = load_index(project_path)
    prefix = f"a{shot['angle']}_"
    src = shot["in_point"] + (at - shot["start"])
    own = [(k, v) for k, v in index.items()
           if k.startswith(prefix) and shot["in_point"] <= int(k[len(prefix):]) / 10 < shot["out_point"]]
    if own:
        k, v = min(own, key=lambda kv: abs(int(kv[0][len(prefix):]) / 10 - src))
        return v | {"key": k, "exact": True, "angle_samples": 1}
    same = [v for k, v in index.items() if k.startswith(prefix)]
    if not same:
        return None
    nearest = min(same, key=lambda v: abs(v["at"] - at))
    return {"at": nearest["at"], "angle": shot["angle"], "camera": shot["camera"],
            "faces": [f for v in same for f in v["faces"]], "image": nearest["image"],
            "timecode": nearest["timecode"], "key": None, "exact": False, "angle_samples": len(same)}


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    run(sys.argv[1], sys.argv[2])
