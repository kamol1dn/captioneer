"""Shared ffmpeg/ffprobe plumbing.

This used to live inside ``web/server.py``, which meant anything not launched
through ``run.bat`` (which prepends ``ffmpeg-7.1\\bin`` to PATH) could not find
the bundled binaries — including ``transcriber/audio.py``, which shelled out to
a bare ``"ffmpeg"``. The clipper engine runs as an MCP server launched by an
external client with no such PATH, so binary resolution has to be explicit.

Frame rates are returned as ``Fraction`` and must stay that way. 30000/1001 is
not 30, and rounding it early puts cuts ~2 frames per minute late.
"""
import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Optional

# media.py lives in caption_engine/, so the project root is one level up.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def ffmpeg_bin(name: str) -> str:
    """Prefer the bundled ffmpeg-7.1 binaries; fall back to PATH."""
    bundled = _PROJECT_ROOT / "ffmpeg-7.1" / "bin" / f"{name}.exe"
    return str(bundled) if bundled.exists() else name


def probe(path: str) -> dict:
    """Probe a media file for everything the caption and clipper engines need.

    Audio-only inputs (podcast mp3/wav) are a first-class use case — the caption
    preview then plays over a black stage instead of source video.
    """
    try:
        out = subprocess.run(
            [ffmpeg_bin("ffprobe"), "-v", "error",
             "-show_entries",
             "stream=codec_type,width,height,disposition,r_frame_rate,"
             "channels,sample_rate,duration:"
             "stream_tags=timecode:"
             "format=duration:format_tags=timecode",
             "-of", "json", path],
            capture_output=True, text=True, check=True).stdout
        data = json.loads(out or "{}")
    except Exception:
        data = {}

    streams = data.get("streams", [])
    fmt = data.get("format", {})

    # Ignore attached cover art (mp3 album covers show up as a video stream).
    vids = [s for s in streams
            if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")]
    auds = [s for s in streams if s.get("codec_type") == "audio"]
    v = vids[0] if vids else None
    a = auds[0] if auds else None

    duration = _to_float(fmt.get("duration"))
    if duration is None and v is not None:
        duration = _to_float(v.get("duration"))

    return {
        "has_video": v is not None,
        "has_audio": bool(auds),
        "width": (v or {}).get("width"),
        "height": (v or {}).get("height"),
        "fps": _to_fraction((v or {}).get("r_frame_rate")),
        "duration": duration,
        "channels": (a or {}).get("channels"),
        "sample_rate": _to_int((a or {}).get("sample_rate")),
        "start_timecode": _start_timecode(streams, fmt),
    }


def _start_timecode(streams: list, fmt: dict) -> Optional[str]:
    """Find a start timecode in stream or format tags.

    xmeml ``in``/``out`` are relative to a file's start timecode. If Premiere
    stamps a non-zero one on an export, every clip lands offset — so the clipper
    probes it, subtracts it, and warns.
    """
    for s in streams:
        tc = (s.get("tags") or {}).get("timecode")
        if tc:
            return tc
    return (fmt.get("tags") or {}).get("timecode")


def _to_fraction(value) -> Optional[Fraction]:
    """Parse ffprobe's ``"30000/1001"`` form. Returns None for 0/0 (no video)."""
    if not value:
        return None
    try:
        f = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None
    return f if f > 0 else None


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
