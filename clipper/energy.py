"""Per-camera loudness envelopes — the speaker-ID signal, and the cut-point finder.

Two jobs:

* **Who is talking.** Each camera has its own mic. Whoever's track is hot at a
  given moment is almost certainly the one speaking. That replaces a diarization
  model entirely, costs one ffmpeg decode per camera, and hands the agent a
  number it can reason about instead of a black-box label.

* **Where it's safe to cut.** Cutting mid-phoneme is the most audible failure of
  automated editing. ``find_silences`` gives the agent legal boundaries and
  ``snap`` nudges a proposed cut onto the nearest one.

Envelopes are stored at 20 Hz — 50 ms resolution is plenty for both jobs and
keeps an hour-long episode at ~72k floats per camera.
"""
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from caption_engine.transcriber.audio import load_audio

from . import paths

RESOLUTION_HZ = 20
_SILENCE_FLOOR_DB = -90.0


def compute_envelope(media_path: str, resolution_hz: int = RESOLUTION_HZ) -> dict:
    """Decode a file and reduce it to an RMS-per-bucket envelope in dBFS."""
    audio = load_audio(media_path)          # 16 kHz mono float32
    if audio.size == 0:
        return {"resolution_hz": resolution_hz, "db": [], "duration": 0.0}

    sr = 16000
    hop = max(1, sr // resolution_hz)
    n = audio.size // hop
    if n == 0:
        return {"resolution_hz": resolution_hz, "db": [], "duration": 0.0}

    frames = audio[:n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    db = 20.0 * np.log10(np.maximum(rms, 1e-10))
    db = np.maximum(db, _SILENCE_FLOOR_DB)

    return {
        "resolution_hz": resolution_hz,
        "duration": float(audio.size / sr),
        # Rounded to 0.1 dB — the extra precision is noise and triples the file.
        "db": [round(float(x), 1) for x in db],
    }


def save_envelope(env: dict, path: Path) -> None:
    paths.write_json_atomic(Path(path), env)


def load_envelope(path: Path) -> Optional[dict]:
    return paths.read_json(Path(path))


# ── querying ─────────────────────────────────────────────────────────────────

def _slice(env: dict, start: float, end: float) -> np.ndarray:
    hz = env.get("resolution_hz", RESOLUTION_HZ)
    db = np.asarray(env.get("db") or [], dtype=np.float64)
    if db.size == 0:
        return db
    a = max(0, int(start * hz))
    b = min(db.size, int(math.ceil(end * hz)))
    return db[a:b] if b > a else db[a:a + 1]


def mean_db(env: dict, start: float, end: float) -> float:
    """Mean loudness over a window, in dBFS. Energy-domain mean, not dB-domain —
    averaging decibels directly under-weights the loud parts that matter."""
    seg = _slice(env, start, end)
    if seg.size == 0:
        return _SILENCE_FLOOR_DB
    power = np.power(10.0, seg / 10.0)
    return float(10.0 * np.log10(max(power.mean(), 1e-12)))


def merge_envelopes(envs: List[dict]) -> dict:
    """Collapse several mics into one envelope by taking the loudest at each bin.

    This is how a *speaker* who owns more than one camera gets a single loudness
    line. Max, not mean: two cameras on one person are rarely matched — a lav and
    a camera mic 20 dB behind it are both "that person present", and averaging
    them would halve their presence and hand the comparison to whoever happens
    to be miked once. Max keeps the group as loud as its best mic, which is what
    "is this person talking" means.

    Bins are positional (all envelopes are computed at the same resolution from
    sources sharing t=0), and the result is as long as the longest input — a
    shorter mic simply contributes nothing past its end.
    """
    usable = [e for e in envs if e and e.get("db")]
    if not usable:
        return {"resolution_hz": RESOLUTION_HZ, "db": [], "duration": 0.0}
    if len(usable) == 1:
        return usable[0]

    hz = usable[0].get("resolution_hz", RESOLUTION_HZ)
    n = max(len(e["db"]) for e in usable)
    out = np.full(n, _SILENCE_FLOOR_DB, dtype=np.float64)
    for e in usable:
        db = np.asarray(e["db"], dtype=np.float64)
        out[:db.size] = np.maximum(out[:db.size], db)
    return {
        "resolution_hz": hz,
        "duration": max(float(e.get("duration") or 0.0) for e in usable),
        "db": [round(float(x), 1) for x in out],
    }


def group_by_speaker(envs: Dict[str, dict],
                     speaker_of: Dict[str, str]) -> Dict[str, dict]:
    """Re-key per-camera envelopes to per-speaker, merging each speaker's mics.

    With one camera per speaker — the default, where a camera's speaker is its
    own id — this is the identity, so callers can group unconditionally.
    """
    grouped: Dict[str, List[dict]] = {}
    for cam, env in envs.items():
        grouped.setdefault(speaker_of.get(cam, cam), []).append(env)
    return {spk: merge_envelopes(group) for spk, group in grouped.items()}


def speaker_scores(envs: Dict[str, dict], start: float, end: float) -> Dict[str, int]:
    """Normalize each track's loudness over a window to 0-99.

    Relative, not absolute: mic gain varies per camera, so the useful question
    is "which track is hottest right now", not "how many dB". The top track is
    always 99, so the agent reads the *gap* between tracks as its confidence.

    Keys are whatever the caller keyed ``envs`` by — camera ids for "which angle
    is hottest", speaker ids (via ``group_by_speaker``) for "who is talking".
    Speaker-keyed is the right question whenever one person owns two cameras,
    where per-camera scoring splits that person's evidence in two.
    """
    raw = {cam: mean_db(env, start, end) for cam, env in envs.items()}
    if not raw:
        return {}
    top = max(raw.values())
    floor = top - 40.0        # 40 dB below the hottest mic is effectively silent
    out = {}
    for cam, db in raw.items():
        if top <= _SILENCE_FLOOR_DB + 1:
            out[cam] = 0
            continue
        frac = (db - floor) / 40.0
        out[cam] = int(max(0.0, min(1.0, frac)) * 99)
    return out


def find_silences(env: dict, start: float = 0.0, end: Optional[float] = None,
                  min_sec: float = 0.35,
                  threshold_db: float = -38.0) -> List[Tuple[float, float]]:
    """Ranges quiet enough to cut through without clipping a word."""
    hz = env.get("resolution_hz", RESOLUTION_HZ)
    db = np.asarray(env.get("db") or [], dtype=np.float64)
    if db.size == 0:
        return []
    end = end if end is not None else db.size / hz
    a, b = max(0, int(start * hz)), min(db.size, int(math.ceil(end * hz)))
    quiet = db[a:b] < threshold_db

    out, run_start = [], None
    for i, q in enumerate(quiet):
        if q and run_start is None:
            run_start = i
        elif not q and run_start is not None:
            _emit(out, run_start, i, a, hz, min_sec)
            run_start = None
    if run_start is not None:
        _emit(out, run_start, len(quiet), a, hz, min_sec)
    return out


def _emit(out: list, i0: int, i1: int, offset: int, hz: int, min_sec: float):
    s = (offset + i0) / hz
    e = (offset + i1) / hz
    if e - s >= min_sec:
        out.append((round(s, 3), round(e, 3)))


def snap(times: List[float], silences: List[Tuple[float, float]],
         max_shift: float = 0.4) -> List[float]:
    """Move each cut onto the middle of the nearest silence, if one is close.

    Snapping to the *middle* rather than an edge leaves headroom on both sides,
    so neither the outgoing nor incoming word gets clipped.
    """
    out = []
    for t in times:
        best, best_d = t, max_shift
        for s, e in silences:
            target = t if s <= t <= e else (s + e) / 2.0
            d = abs(target - t)
            if d < best_d:
                best, best_d = target, d
        out.append(round(best, 3))
    return out
