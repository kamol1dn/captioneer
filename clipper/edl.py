"""The edit decision list: the human-editable artifact between agent and NLE.

One EDL holds *many* clips, because the real workflow is "pull 14 shorts out of
a 1-hour episode", not "cut one video". Each clip compiles to its own Premiere
sequence; they all share the same source cameras and timebase.

All times are **master seconds** on the shared t=0 timeline that every camera
export starts from. Program time (position within a finished clip) is derived at
compile time and never stored — storing it guarantees it drifts out of sync with
the segments it was derived from.

Two orthogonal lists describe a clip:

* ``segments`` — the keep list. The clip is exactly their ordered concatenation;
  cuts are implicit (anything not in a segment is discarded).
* ``camera_cuts`` — a piecewise-constant function over the whole master
  timeline. The camera at time t is the one from the last cut with ``at <= t``.
  Cuts landing in discarded regions are harmless.

Keeping them independent is the point: you can retime a segment boundary without
touching camera assignments, and switch cameras without re-deciding what to keep.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import paths
from .timebase import Timebase

SCHEMA_VERSION = 1

# Shots under this read as a glitch rather than a cut.
MIN_SHOT_SEC = 0.5
# Below this a segment isn't a thought, it's a fragment.
MIN_SEGMENT_SEC = 0.4


@dataclass
class Segment:
    """A kept range of the master timeline."""
    start: float
    end: float
    id: str = ""
    label: str = ""
    note: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class CameraCut:
    """Switch to ``camera`` at master time ``at``, until the next cut."""
    at: float
    camera: str
    why: str = ""


@dataclass
class BRoll:
    """An overlay on V2. Never changes clip duration — it covers, not extends.

    ``source is None`` means placeholder: the agent knows what it wants but the
    footage doesn't exist yet. Placeholders export as sequence markers rather
    than offline clips (offline items make Premiere nag on every import).
    """
    start: float
    end: float
    id: str = ""
    query: str = ""
    source: Optional[str] = None
    source_in: float = 0.0
    audio: str = "mute"          # "mute" | "keep"
    status: str = "placeholder"  # "placeholder" | "attached"


@dataclass
class Marker:
    at: float
    name: str = ""
    comment: str = ""


@dataclass
class Clip:
    """One short. Compiles to one Premiere sequence."""
    id: str
    title: str = ""
    segments: List[Segment] = field(default_factory=list)
    camera_cuts: List[CameraCut] = field(default_factory=list)
    broll: List[BRoll] = field(default_factory=list)
    markers: List[Marker] = field(default_factory=list)
    note: str = ""

    @property
    def duration(self) -> float:
        """Program duration — the sum of kept segments."""
        return sum(s.duration for s in self.segments)

    @property
    def master_start(self) -> float:
        return min((s.start for s in self.segments), default=0.0)

    @property
    def master_end(self) -> float:
        return max((s.end for s in self.segments), default=0.0)

    def camera_at(self, t: float, default: str) -> str:
        """Resolve the active camera at master time t."""
        cam = default
        for c in sorted(self.camera_cuts, key=lambda c: c.at):
            if c.at <= t + 1e-9:
                cam = c.camera
            else:
                break
        return cam


@dataclass
class AudioPlan:
    """How audio is laid out.

    ``pinned`` is the default and right whenever one source hears the whole room:
    cutting audio at each visual switch produces an audible tonal jump, so pin
    one good mic and let it run continuously under the picture edit. An
    audio-only combined mix is the best thing to pin when there is one.

    ``multitrack`` is the answer for isolated per-subject mics, where no single
    camera carries the full conversation: every source lands on its own track to
    be mixed downstream. ``pinned_camera`` may name an audio-only source; camera
    *cuts* may not.

    ``source_tracks`` reproduces the master timeline's own audio tracks under the
    cut, one reel track per master track. It is the right mode whenever the
    project has a master XML, because what the editor mixed is the *sum* of those
    tracks — lavs, camera scratch, music and mix layers, each covering a
    different part of the episode — and pinning any single one of them would drop
    most of the sound. It reads no cameras at all, so ``pinned_camera`` is unused.
    """
    mode: str = "pinned"   # "pinned" | "follow_video" | "multitrack" | "source_tracks"
    pinned_camera: str = ""
    channels: int = 2


@dataclass
class StylePlan:
    """Finishing applied at compile time rather than written into every clip.

    ``jump_cut_punch`` conceals same-camera cuts. Dropping filler out of one
    continuous take leaves a jump cut: the speaker's head teleports because the
    framing either side is identical. Alternating a small zoom across those cuts
    makes the framing differ, so the cut reads as a deliberate reframe instead of
    a glitch. It is deliberately subtle — a few percent is enough to break the
    match; more looks like a zoom effect. Only cuts with a real gap in the source
    are punched, and an angle change resets it, since a different camera already
    hides the join. 0 disables.
    """
    jump_cut_punch: float = 4.0


@dataclass
class EDL:
    timebase: Timebase
    frame_size: tuple
    default_camera: str
    clips: List[Clip] = field(default_factory=list)
    audio: AudioPlan = field(default_factory=AudioPlan)
    style: StylePlan = field(default_factory=StylePlan)
    version: int = SCHEMA_VERSION

    def clip(self, clip_id: str) -> Optional[Clip]:
        return next((c for c in self.clips if c.id == clip_id), None)

    # ── serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "timebase": self.timebase.to_dict(),
            "frame_size": {"width": self.frame_size[0],
                           "height": self.frame_size[1]},
            "default_camera": self.default_camera,
            "audio": {"mode": self.audio.mode,
                      "pinned_camera": self.audio.pinned_camera,
                      "channels": self.audio.channels},
            "style": {"jump_cut_punch": self.style.jump_cut_punch},
            "clips": [
                {
                    "id": c.id, "title": c.title, "note": c.note,
                    "segments": [_clean(vars(s)) for s in c.segments],
                    "camera_cuts": [_clean(vars(x)) for x in c.camera_cuts],
                    "broll": [_clean(vars(b)) for b in c.broll],
                    "markers": [_clean(vars(m)) for m in c.markers],
                }
                for c in self.clips
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EDL":
        fs = d.get("frame_size") or {}
        aud = d.get("audio") or {}
        return cls(
            version=int(d.get("version", SCHEMA_VERSION)),
            timebase=Timebase.from_dict(d["timebase"]),
            frame_size=(int(fs.get("width", 1080)), int(fs.get("height", 1920))),
            default_camera=d.get("default_camera", ""),
            audio=AudioPlan(mode=aud.get("mode", "pinned"),
                            pinned_camera=aud.get("pinned_camera", ""),
                            channels=int(aud.get("channels", 2))),
            style=StylePlan(jump_cut_punch=float(
                (d.get("style") or {}).get("jump_cut_punch", 4.0))),
            clips=[
                Clip(
                    id=c["id"], title=c.get("title", ""), note=c.get("note", ""),
                    segments=[Segment(**s) for s in c.get("segments", [])],
                    camera_cuts=[CameraCut(**x) for x in c.get("camera_cuts", [])],
                    broll=[BRoll(**b) for b in c.get("broll", [])],
                    markers=[Marker(**m) for m in c.get("markers", [])],
                )
                for c in d.get("clips", [])
            ],
        )

    def save(self, path: Path) -> None:
        paths.write_json_atomic(Path(path), self.to_dict())

    @classmethod
    def load(cls, path: Path) -> Optional["EDL"]:
        data = paths.read_json(Path(path))
        return cls.from_dict(data) if data else None


def _clean(d: dict) -> dict:
    """Drop empty optional fields so the on-disk EDL stays readable by hand."""
    return {k: v for k, v in d.items()
            if v not in ("", None) or k in ("start", "end", "at")}


# ── validation ───────────────────────────────────────────────────────────────

def validate(edl: EDL, camera_ids: List[str],
             master_duration: Optional[float] = None,
             video_camera_ids: Optional[List[str]] = None) -> dict:
    """Check an EDL for anything that would produce a broken or ugly export.

    Errors block export; warnings don't. The split matters — the agent should be
    able to hand you a rough cut with a 0.4s shot in it and still get an XML.

    ``video_camera_ids`` narrows which cameras may carry *picture*; audio-only
    sources are valid to pin audio to but cannot be cut to. Defaults to
    ``camera_ids``, so callers that predate audio-only sources are unaffected.
    """
    errors: List[str] = []
    warnings: List[str] = []
    with_video = set(camera_ids if video_camera_ids is None else video_camera_ids)

    if not edl.clips:
        errors.append("EDL has no clips")
    if edl.default_camera and edl.default_camera not in camera_ids:
        errors.append(f"default_camera {edl.default_camera!r} is not a known camera")
    elif edl.default_camera and edl.default_camera not in with_video:
        errors.append(f"default_camera {edl.default_camera!r} has no video stream")

    if edl.audio.mode not in ("pinned", "follow_video", "multitrack",
                              "source_tracks"):
        errors.append(f"audio.mode {edl.audio.mode!r} is not valid")
    if edl.audio.mode == "pinned":
        if not edl.audio.pinned_camera:
            errors.append("audio.mode is 'pinned' but no pinned_camera is set")
        elif edl.audio.pinned_camera not in camera_ids:
            errors.append(f"pinned_camera {edl.audio.pinned_camera!r} is unknown")

    seen_ids = set()
    for clip in edl.clips:
        tag = f"clip {clip.id!r}"
        if clip.id in seen_ids:
            errors.append(f"duplicate clip id {clip.id!r}")
        seen_ids.add(clip.id)

        if not clip.segments:
            errors.append(f"{tag} has no segments")
            continue

        segs = sorted(clip.segments, key=lambda s: s.start)
        if [s.start for s in clip.segments] != [s.start for s in segs]:
            warnings.append(f"{tag}: segments were out of order (sorted on compile)")

        prev = None
        for s in segs:
            if s.end <= s.start:
                errors.append(f"{tag}: segment {s.start:.2f}-{s.end:.2f} is empty "
                              f"or inverted")
            if prev is not None and s.start < prev.end - 1e-6:
                errors.append(f"{tag}: segments overlap at {s.start:.2f}s")
            if master_duration and s.end > master_duration + 0.1:
                errors.append(f"{tag}: segment ends at {s.end:.2f}s, past the "
                              f"{master_duration:.2f}s source")
            if s.duration < MIN_SEGMENT_SEC:
                warnings.append(f"{tag}: segment at {s.start:.2f}s is only "
                                f"{s.duration:.2f}s")
            prev = s

        for c in clip.camera_cuts:
            if c.camera not in camera_ids:
                errors.append(f"{tag}: camera cut at {c.at:.2f}s names unknown "
                              f"camera {c.camera!r}")
            elif c.camera not in with_video:
                errors.append(f"{tag}: camera cut at {c.at:.2f}s points at "
                              f"{c.camera!r}, which has no video stream")

        for shot_start, shot_end, cam in iter_shots(clip, edl.default_camera):
            if shot_end - shot_start < MIN_SHOT_SEC:
                warnings.append(f"{tag}: {shot_end - shot_start:.2f}s shot on "
                                f"cam {cam} at {shot_start:.2f}s reads as a glitch")

        for b in clip.broll:
            if b.end <= b.start:
                errors.append(f"{tag}: b-roll {b.id!r} is empty or inverted")
            if not any(s.start - 1e-6 <= b.start and b.end <= s.end + 1e-6
                       for s in segs):
                errors.append(f"{tag}: b-roll {b.id!r} ({b.start:.2f}-{b.end:.2f}) "
                              f"is not inside a kept segment")
            if b.source and not Path(b.source).exists():
                warnings.append(f"{tag}: b-roll source {b.source!r} does not exist")

    return {
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
        "clips": [{"id": c.id, "title": c.title,
                   "duration": round(c.duration, 2),
                   "n_segments": len(c.segments),
                   "n_shots": len(list(iter_shots(c, edl.default_camera)))}
                  for c in edl.clips],
    }


def iter_shots(clip: Clip, default_camera: str):
    """Yield (start, end, camera) for every continuous shot in a clip.

    A shot ends at a segment boundary *or* a camera cut, whichever comes first.
    This is the unit that becomes one xmeml clipitem.
    """
    for seg in sorted(clip.segments, key=lambda s: s.start):
        # Camera cuts strictly inside this segment split it further.
        boundaries = [seg.start]
        boundaries += sorted(c.at for c in clip.camera_cuts
                             if seg.start + 1e-9 < c.at < seg.end - 1e-9)
        boundaries.append(seg.end)
        for a, b in zip(boundaries, boundaries[1:]):
            if b - a > 1e-9:
                yield a, b, clip.camera_at(a, default_camera)
