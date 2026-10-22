"""Transitions and sound design.

The burn: the editor's transition between segments and in and out of a
full-screen is a "Burning Light Transition" clip (by default number 4) laid
over the cut, as the editor does it (behzod tahlil 192.9 s): screen blend at
90% opacity, scaled to fill, starting so its brightest frame lands on the
cut (10 frames early at 30 fps for no. 4), the clip's own sound at -12 dB.
The .mov carries audio, and an overlay with audio would also be laid onto
the dialogue tracks, so the clip is split once into a silent copy and a
.wav, cached in the episode's skleyka/assets, and the two are placed on
lanes "SKL burn" (video and audio).

Sound effects: the SOUNDS library is measured in reel-studio's
sfx/sfx_index.json (hit time, loudness). ``hit`` lands a sound's loudest
moment on a given time and sets its gain from its loudness, so every effect
sits as loud as the editor's own whoosh under a lower third (-15 dB on a
-20.3 LUFS file, so about -35 LUFS). ``whoosh`` is that whoosh, shared by
type 1 and type 2.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import audio, explain, overlays

BURNS = Path(r"C:\Users\User\Documents\editing assets\transitions overlay\Burning Light Transitions")
# Brightest frame of each burn (25 fps), measured by mean luma. The cut goes
# in the middle of it.
BURN_PEAK_FRAME = {1: 8, 2: 7, 3: 18, 4: 8, 5: 7, 6: 9, 7: 14, 8: 14, 9: 11, 10: 9}
BURN_FPS = 25
BURN_OPACITY = 90
BURN_GAIN_DB = -12.0  # the user, 2026-10-08 (their own timeline had 0 dB)

SFX_INDEX = Path(r"D:\coding\reel-studio\sfx\sfx_index.json")
SFX_LUFS = -35.3   # the editor's whoosh: -20.3 LUFS at -15 dB


class FxError(RuntimeError):
    pass


# --- the burn ------------------------------------------------------------------

def _burn_parts(project_path: str, n: int, fps: float) -> tuple[Path, Path]:
    """A silent copy at the sequence's frame rate (Premiere snaps in/out marks
    to the media's own 25 fps frames, which miss the sequence's), and a .wav."""
    src = BURNS / f"_Burning Light Transition {n}.mov"
    if not src.exists():
        raise FxError(f"No burn {n}: {src}")
    d = explain.assets_dir(project_path)
    rate = f"{fps:.3f}".rstrip("0").rstrip(".")
    vid, wav = d / f"burn_{n}_{rate}fps.mov", d / f"burn_{n}.wav"
    ff = str(audio.FFMPEG)
    if not vid.exists():
        subprocess.run([ff, "-v", "error", "-y", "-i", str(src), "-an", "-vf", f"fps={rate}", "-c:v", "mjpeg",
                        "-q:v", "2", str(vid)], check=True, stdin=subprocess.DEVNULL)
    if not wav.exists():
        subprocess.run([ff, "-v", "error", "-y", "-i", str(src), "-vn", "-c:a", "pcm_s16le", str(wav)],
                       check=True, stdin=subprocess.DEVNULL)
    return vid, wav


def place_burn(cut: float, variant: int = 4, sound: bool = True, label: str = "burn",
               sequence: str | None = None) -> dict:
    """A burn over the cut at ``cut`` seconds, brightest frame on the cut."""
    if variant not in BURN_PEAK_FRAME:
        raise FxError(f"variant is one of {sorted(BURN_PEAK_FRAME)}")
    ctx = overlays._context(sequence)
    width = int(ctx.get("width") or 3840)
    vid, wav = _burn_parts(ctx["project"], variant, overlays.TICKS / int(ctx["frame"]))
    start = max(0.0, cut - (BURN_PEAK_FRAME[variant] + 0.5) / BURN_FPS)
    placed = [overlays.place(str(vid), start, None, kind="video", lane="burn", label=label,
                             style={"scale": round(width / 1920 * 100, 3), "opacity": BURN_OPACITY,
                                    "blend": "screen"}, sequence=ctx["id"])]
    if sound:
        placed.append(overlays.place(str(wav), start, placed[0]["end"], kind="audio", lane="burn", label=label,
                                     style={"gain_db": BURN_GAIN_DB}, sequence=ctx["id"]))
    return {"ids": [p["id"] for p in placed], "start": placed[0]["start"], "end": placed[0]["end"],
            "cut": cut, "variant": variant}


# --- sound effects ----------------------------------------------------------------

def _index() -> list[dict]:
    if not SFX_INDEX.exists():
        raise FxError(f"No SFX index at {SFX_INDEX} (reel-studio tools/sfx_index.py makes it)")
    return json.loads(SFX_INDEX.read_text(encoding="utf-8"))


def _src(e: dict) -> Path:
    """Index paths are absolute (the SOUNDS library) or relative to reel-studio."""
    p = Path(e["source"])
    return p if p.is_absolute() else SFX_INDEX.parents[1] / p


def sounds(kind: str | None = None, query: str | None = None) -> list[dict]:
    """The library, measured: name, kind (hit, swell, riser, texture), length,
    hit time, loudness, and the gain ``hit`` would use."""
    out = []
    for e in _index():
        if kind and e["kind"] != kind:
            continue
        if query and query.lower() not in e["name"].lower():
            continue
        if not _src(e).exists():
            continue
        out.append({"name": e["name"], "kind": e["kind"], "seconds": e["dur_sec"], "hit_at": e["peak_at_sec"],
                    "lufs": e["lufs"], "brightness_hz": e["brightness_hz"], "gain_db": _gain(e)})
    return out


def _find(name: str) -> dict:
    idx = _index()
    key = name.lower().strip()
    for e in idx:
        if key in (e["name"].lower(), e["slug"]):
            return e
    hits = [e for e in idx if key in e["name"].lower()]
    if len(hits) == 1:
        return hits[0]
    raise FxError(f"No single sound matches {name!r}" + (f": {[e['name'] for e in hits]}" if hits else ""))


def _gain(e: dict) -> float:
    return round(max(-40.0, min(6.0, SFX_LUFS - e["lufs"])), 1)


def hit(name: str, at: float, gain_db: float | None = None, trim_db: float = 0.0, lane: str = "sfx",
        label: str = "", sequence: str | None = None) -> dict:
    """Place sound ``name`` so its loudest moment lands on ``at`` seconds.
    Gain defaults to the level that matches the editor's whoosh; ``trim_db``
    adjusts from there (+3 for an accent, -6 for something under)."""
    e = _find(name)
    src = _src(e)
    if not src.exists():
        raise FxError(f"Missing file {src}")
    g = (_gain(e) if gain_db is None else gain_db) + trim_db
    start = at - e["peak_at_sec"]
    media_in = e["start_sec"]
    if start < 0:
        media_in, start = media_in - start, 0.0
    end = start + e["dur_sec"] - (media_in - e["start_sec"])
    rec = overlays.place(str(src), start, end, kind="audio", lane=lane, label=label or e["name"][:20],
                         style={"gain_db": g}, media_in=media_in, sequence=sequence)
    return rec | {"sound": e["name"], "hit_at": at, "gain_db": g}


def cues(items: list[dict], offset: float = 0.0, sequence: str | None = None) -> list[dict]:
    """Several hits at once: [{"sound", "at", "gain_db"?, "trim_db"?}], ``at``
    relative to ``offset`` (the start of an animation)."""
    ctx = overlays._context(sequence)
    return [hit(c["sound"], offset + c["at"], gain_db=c.get("gain_db"), trim_db=c.get("trim_db", 0.0),
                label=c.get("label", ""), sequence=ctx["id"]) for c in items]


def whoosh(at: float, label: str = "", sequence: str | None = None) -> dict:
    """The editor's whoosh for a graphic appearing at ``at``: Whoosh 1, 0.1 s
    early, its first 5 s, -15 dB, on "SKL whoosh"."""
    w = explain.WHOOSH
    if not Path(w).exists():
        raise FxError(f"Missing {w}")
    s = max(0.0, at - explain.WHOOSH_LEAD)
    return overlays.place(w, s, s + explain.WHOOSH_LEN, kind="audio", lane="whoosh", label=label,
                          style={"gain_db": explain.WHOOSH_GAIN_DB}, sequence=sequence)


# --- a full-screen ----------------------------------------------------------------

def place_full(file: str, start: float, end: float | None = None, burn_in: bool = True, burn_out: bool = True,
               variant: int = 4, sound_cues: list[dict] | None = None, label: str = "full",
               sequence: str | None = None) -> dict:
    """Type 3: the full-screen render on "SKL full" (above the camera lanes),
    a burn over the cut in and the cut out, and its sound design (``cues``,
    times from ``start``)."""
    ctx = overlays._context(sequence)
    rec = overlays.place(file, start, end, kind="video", lane="full", label=label, sequence=ctx["id"])
    out = {"full": rec["id"], "start": rec["start"], "end": rec["end"], "burns": [], "cues": []}
    if burn_in:
        out["burns"].append(place_burn(rec["start"], variant, label=f"{label} in", sequence=ctx["id"]))
    if burn_out:
        out["burns"].append(place_burn(rec["end"], variant, label=f"{label} out", sequence=ctx["id"]))
    if sound_cues:
        out["cues"] = [c["id"] for c in cues(sound_cues, offset=rec["start"], sequence=ctx["id"])]
    return out
