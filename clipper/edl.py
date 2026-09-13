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
# What a BRoll may be. Order is bottom-to-top on the timeline.
BROLL_KINDS = ("footage", "overlay")


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
    """Something laid over the camera stack. Never changes clip duration — it
    covers or decorates, it does not extend.

    ``kind`` distinguishes two genuinely different things, which is why they get
    their own tracks:

    * ``footage`` — full-frame stock or cutaway that *replaces* the picture for
      its duration. What a b-roll pull produces.
    * ``overlay`` — an alpha graphic sitting *on top* of the picture: a stat
      animation, a screenshot card, a lower third. It augments rather than
      covers, so it may legitimately run at the same time as footage. Two of the
      same kind may not — one track cannot carry both.

    ``source is None`` means placeholder: the agent knows what it wants but the
    file doesn't exist yet. Placeholders export as sequence markers rather than
    offline clips (offline items make Premiere nag on every import).
    """
    start: float
    end: float
    id: str = ""
    query: str = ""
    kind: str = "footage"        # "footage" | "overlay"
    source: Optional[str] = None
    source_in: float = 0.0
    audio: str = "mute"          # "mute" | "keep"
    status: str = "placeholder"  # "placeholder" | "attached"
    # Set when ``source`` was rendered from a template: {template, props, frames}.
    # Kept so the file can be re-rendered after the entry moves, rather than the
    # graphic having to be re-authored from a description.
    graphic: Optional[dict] = None
    # The attached file as probed: {width, height, fps, duration, has_audio}.
    # The compiler needs the size to scale footage to fill a vertical frame, and
    # the XML needs all of it for the <file> element — stock footage is rarely
    # the sequence's size, and declaring it wrong makes Premiere scale it.
    media: Optional[dict] = None
    # Stock candidates found for a placeholder: [{url, title, note}]. Carried
    # into the placeholder's marker so the editor sees them too.
    candidates: Optional[List[dict]] = None


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


# ── b-roll and marker editing ────────────────────────────────────────────────
#
# The graphics pass runs in its own session, after the cut is settled, and has no
# business rewriting ``segments`` or ``camera_cuts``. Those were snapped to
# silence and checked against the rendered audio; a session that never saw that
# work cannot reconstruct it faithfully through a whole-document JSON round trip,
# and a near-miss reconstruction is worse than a loud failure because it still
# validates. So that pass edits through these instead, and the parts of the EDL
# it must not touch are simply not reachable from here.


def next_broll_id(clip: Clip) -> str:
    """``b1``, ``b2``, … — the lowest id not already used on this clip."""
    used = {b.id for b in clip.broll}
    n = 1
    while f"b{n}" in used:
        n += 1
    return f"b{n}"


def add_broll(clip: Clip, start: float, end: float, kind: str = "footage",
              query: str = "", broll_id: str = "", source: Optional[str] = None,
              source_in: float = 0.0, audio: str = "mute") -> BRoll:
    """Append one b-roll entry to ``clip`` and return it.

    An explicit ``broll_id`` that is already taken raises rather than updating in
    place: silently overwriting an entry the caller believed it was adding is
    exactly how a second pass loses the first pass's work.
    """
    if broll_id and any(b.id == broll_id for b in clip.broll):
        raise ValueError(f"b-roll {broll_id!r} already exists on clip {clip.id!r}")
    b = BRoll(start=start, end=end, id=broll_id or next_broll_id(clip),
              query=query, kind=kind, source=source, source_in=source_in,
              audio=audio, status="attached" if source else "placeholder")
    clip.broll.append(b)
    return b


def remove_broll(clip: Clip, broll_id: str) -> BRoll:
    """Drop one b-roll entry from ``clip`` and return what was removed."""
    b = next((x for x in clip.broll if x.id == broll_id), None)
    if b is None:
        raise ValueError(f"no b-roll {broll_id!r} on clip {clip.id!r}")
    clip.broll.remove(b)
    return b


def parse_broll(items: List[dict]) -> List[BRoll]:
    """Build a b-roll list from plain dicts, naming a bad field clearly.

    ``BRoll(**d)`` on a stray key raises a bare TypeError naming the constructor,
    which tells an agent nothing about which entry it got wrong.
    """
    return [_parse(BRoll, d, i, "b-roll") for i, d in enumerate(items)]


def parse_markers(items: List[dict]) -> List[Marker]:
    return [_parse(Marker, d, i, "marker") for i, d in enumerate(items)]


def _parse(cls, d: dict, i: int, what: str):
    allowed = set(cls.__dataclass_fields__)
    unknown = sorted(set(d) - allowed)
    if unknown:
        raise ValueError(f"{what} #{i}: unknown field(s) {', '.join(unknown)} — "
                         f"allowed: {', '.join(sorted(allowed))}")
    try:
        return cls(**d)
    except TypeError as e:
        raise ValueError(f"{what} #{i}: {e}") from None


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

        broll_ids = set()
        for b in clip.broll:
            if b.end <= b.start:
                errors.append(f"{tag}: b-roll {b.id!r} is empty or inverted")
            if not any(s.start - 1e-6 <= b.start and b.end <= s.end + 1e-6
                       for s in segs):
                errors.append(f"{tag}: b-roll {b.id!r} ({b.start:.2f}-{b.end:.2f}) "
                              f"is not inside a kept segment")
            if b.kind not in BROLL_KINDS:
                errors.append(f"{tag}: b-roll {b.id!r} has unknown kind "
                              f"{b.kind!r} (expected one of "
                              f"{', '.join(BROLL_KINDS)})")
            if b.id in broll_ids:
                errors.append(f"{tag}: duplicate b-roll id {b.id!r}")
            broll_ids.add(b.id)
            if b.source and not Path(b.source).exists():
                warnings.append(f"{tag}: b-roll source {b.source!r} does not exist")

        # Each kind is one video track, so two of a kind may not overlap — that
        # would be two clipitems on one track, which is not a valid timeline.
        # Across kinds it is the whole point: a stat card over a stock shot.
        for kind in BROLL_KINDS:
            same = sorted((b for b in clip.broll if b.kind == kind),
                          key=lambda b: b.start)
            for a, nxt in zip(same, same[1:]):
                if nxt.start < a.end - 1e-6:
                    errors.append(f"{tag}: {kind} {a.id!r} and {nxt.id!r} overlap "
                                  f"at {nxt.start:.2f}s — one track can't carry "
                                  f"both")

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
