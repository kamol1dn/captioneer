"""Loudness envelopes of the source audio: who is on which mic, and when.

A recorder's isolated mic tracks share one clock with its mix. Each file is
reduced once to mean power per 10 ms hop (a 2-hour file becomes ~3 MB) and
cached next to the transcripts, so "which mic is loudest during this word"
is an array lookup, not a decode.
"""
from __future__ import annotations

import hashlib
import math
import subprocess
from pathlib import Path

import numpy as np

FFMPEG = Path(__file__).resolve().parents[1] / "ffmpeg-7.1" / "bin" / "ffmpeg.exe"
RATE = 16000
HOP_S = 0.01
HOP = int(RATE * HOP_S)
SILENT_DB = -70.0


def _cache_name(path: Path) -> str:
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8")).hexdigest()[:12]
    return f"{path.stem}__{key}.env.npy"


def envelope(path: str | Path, cache_dir: str | Path) -> np.ndarray:
    """Mean power per 10 ms hop of the file, mono at 16 kHz (float32)."""
    path, cache_dir = Path(path), Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / _cache_name(path)
    if cache.exists():
        return np.load(cache)
    proc = subprocess.Popen(
        [str(FFMPEG), "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
        stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    hops: list[np.ndarray] = []
    carry = np.zeros(0, dtype=np.float32)
    chunk = HOP * 6000  # one minute of audio per read
    assert proc.stdout is not None
    while True:
        raw = proc.stdout.read(chunk * 4)
        if not raw:
            break
        x = np.concatenate([carry, np.frombuffer(raw, dtype=np.float32)])
        n = len(x) // HOP
        hops.append((x[: n * HOP].reshape(n, HOP) ** 2).mean(axis=1))
        carry = x[n * HOP:]
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode {path}")
    env = np.concatenate(hops).astype(np.float32) if hops else np.zeros(0, dtype=np.float32)
    np.save(cache, env)
    return env


def db(power: float) -> float:
    return 10 * math.log10(power) if power > 0 else -120.0


def mean_db(env: np.ndarray, start: float, end: float, offset: float = 0.0) -> float:
    """Level in dBFS over [start, end) seconds of the file (``offset`` shifts
    this file's clock relative to the caller's: file_time = t + offset)."""
    a = max(0, int((start + offset) / HOP_S))
    b = min(len(env), int(math.ceil((end + offset) / HOP_S)))
    if b <= a:
        return -120.0
    return db(float(env[a:b].mean()))


def is_live(env: np.ndarray) -> bool:
    """False for a recorder track nothing was plugged into."""
    return len(env) > 0 and db(float(env.mean())) > SILENT_DB


def duration(env: np.ndarray) -> float:
    return len(env) * HOP_S


def offset_by_xcorr(reference: np.ndarray, other: np.ndarray, max_shift_s: float = 120.0) -> dict:
    """How far ``other``'s clock is ahead of ``reference``'s, in seconds, from
    the cross-correlation of their log-power envelopes (10 ms resolution).

    file_time_other = file_time_reference + offset. Mics of one recorder give
    ~0; a mix exported from a different start gives its lag. ``peak`` is the
    normalised correlation at the best shift: below ~0.3 the two files
    probably don't share material at all."""
    n = min(len(reference), len(other))
    a = np.log10(reference[:n].astype(np.float64) + 1e-10)
    b = np.log10(other[:n].astype(np.float64) + 1e-10)
    a -= a.mean()
    b -= b.mean()
    size = 1
    while size < 2 * n:
        size *= 2
    fa, fb = np.fft.rfft(a, size), np.fft.rfft(b, size)
    corr = np.fft.irfft(fa * np.conj(fb), size)
    corr = np.concatenate([corr[-n + 1:], corr[:n]])  # lags -(n-1) .. n-1
    lags = np.arange(-n + 1, n)
    keep = np.abs(lags) <= int(max_shift_s / HOP_S)
    corr, lags = corr[keep], lags[keep]
    k = int(np.argmax(corr))
    norm = float(np.sqrt((a * a).sum() * (b * b).sum())) or 1.0
    # corr[lag] = sum a[t + lag] * b[t]: a peak at a positive lag means the
    # reference shows the same moment later, so the other's clock reads less.
    # (Checked against a mix the user had synced by hand: mix 0.167 s behind
    # the mics gave lag +0.17 here.)
    return {"offset_s": round(-float(lags[k]) * HOP_S, 3), "peak": round(float(corr[k]) / norm, 3)}
