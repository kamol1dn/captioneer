"""What a picture or sound source *is*, independent of where it was read from.

The original model was one camera = one media file, and master time mapped to
source time by adding a constant. That holds only when the editor exports a flat
video per angle. The cheaper workflow — export the audio, hand over the episode
timeline as XML, and cut picture straight from what V1/V2 already point at —
breaks it: an edited two-hour timeline has a cut every few seconds, so master
time maps to source time through a *piecewise* function with hundreds of
discontinuities.

``SourceTrack`` is that function, and ``slice`` is the operation everything
downstream needs: give me the pieces covering this range. A range that crosses a
cut comes back as several pieces, which is precisely why a track cannot be
collapsed back into a path plus an offset.

Sources are held **opaquely**. A ``SourceRef`` carries the definition subtree
exactly as the NLE wrote it — a media file, or a nested sequence with its own
frame size and internal framing — and the writer re-emits it verbatim. Reels
therefore inherit crops this code never has to understand, and flat files and
arbitrarily deep nests travel one code path.

These types live here rather than beside the XML parser because ``compile``
needs them and ``xmeml`` imports ``compile``.
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .timebase import Timebase


@dataclass
class SourceRef:
    """Whatever a clipitem points at: a media file, or a nested sequence."""
    kind: str                      # "file" | "sequence"
    key: str                       # id within the source document
    name: str
    path: str = ""                 # absolute media path; "" for a nest
    element: Optional[ET.Element] = None   # definition subtree, re-emitted as-is

    @property
    def is_nest(self) -> bool:
        return self.kind == "sequence"

    @property
    def ref_key(self) -> str:
        """Identity for de-duplication when writing: one definition per source."""
        return self.path or f"{self.kind}:{self.key}:{self.name}"


@dataclass
class Segment:
    """One clipitem's worth of a track, in timeline frames.

    ``in_`` is the source frame aligned with ``start``. Because a segment is
    never retimed (the reader rejects anything that is), every point inside maps
    to its source by simple addition.
    """
    start: int                     # timeline frame, inclusive
    end: int                       # timeline frame, exclusive
    in_: int                       # source frame at `start`
    source: SourceRef
    name: str = ""
    filters: List[ET.Element] = field(default_factory=list)
    source_channel: int = 1        # audio: 1-based index into the source's tracks
    # The source clipitem's own mute/disable state. An editor who muted a camera
    # scratch track on the master meant it; carrying the flag is what makes a
    # reel sound like the episode instead of like every mic at once.
    enabled: bool = True

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass
class SourceTrack:
    """One V- or A-track of the master timeline, as an ordered segment list."""
    kind: str                      # "video" | "audio"
    index: int                     # 1-based within its media type
    label: str                     # "V1", "A3" — how the editor refers to it
    name: str = ""                 # dominant clipitem name, for identification
    enabled: bool = True
    segments: List[Segment] = field(default_factory=list)
    skipped_transitions: int = 0

    @property
    def coverage(self) -> int:
        return sum(s.length for s in self.segments)

    def sources(self) -> List[str]:
        """Distinct source names on this track, in first-use order."""
        out: List[str] = []
        for s in self.segments:
            if s.source.name not in out:
                out.append(s.source.name)
        return out

    def slice(self, start: int, length: int) -> List[Segment]:
        """The pieces covering timeline ``[start, start+length)``.

        Ranges the track doesn't cover produce nothing rather than a guess, so a
        caller comparing returned lengths against ``length`` learns exactly where
        an angle has no footage.
        """
        end = start + length
        out: List[Segment] = []
        for seg in self.segments:
            if seg.end <= start or seg.start >= end:
                continue
            a, b = max(seg.start, start), min(seg.end, end)
            out.append(Segment(
                start=a, end=b,
                in_=seg.in_ + (a - seg.start),
                source=seg.source, name=seg.name,
                filters=seg.filters, source_channel=seg.source_channel,
                enabled=seg.enabled,
            ))
        return out

    def gaps(self, start: int, length: int) -> List[tuple]:
        """Uncovered sub-ranges of ``[start, start+length)``, as (from, to)."""
        out, cur = [], start
        for p in self.slice(start, length):
            if p.start > cur:
                out.append((cur, p.start))
            cur = max(cur, p.end)
        if cur < start + length:
            out.append((cur, start + length))
        return out

    def summary(self) -> dict:
        return {
            "track": self.label,
            "name": self.name,
            "enabled": self.enabled,
            "segments": len(self.segments),
            "coverage_frames": self.coverage,
            "sources": self.sources(),
            "nested": any(s.source.is_nest for s in self.segments),
            "skipped_transitions": self.skipped_transitions,
        }


@dataclass
class MasterTimeline:
    """The episode timeline every reel is cut out of."""
    name: str
    timebase: Timebase
    frame_size: tuple
    duration: int                  # frames
    video: List[SourceTrack] = field(default_factory=list)
    audio: List[SourceTrack] = field(default_factory=list)
    start_frame: int = 0           # sequence start timecode, in frames
    warnings: List[str] = field(default_factory=list)
    path: str = ""                 # the XML this was read from

    def track(self, label: str) -> Optional[SourceTrack]:
        """Look a track up as the editor names it: "V1", "A3"."""
        want = (label or "").strip().upper()
        return next((t for t in self.video + self.audio if t.label == want), None)

    @property
    def duration_seconds(self) -> float:
        return self.timebase.to_seconds(self.duration)

    def track_map(self) -> Dict[str, SourceTrack]:
        return {t.label: t for t in self.video + self.audio}

    def summary(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "timebase": str(self.timebase),
            "frame_size": list(self.frame_size),
            "duration_frames": self.duration,
            "duration_seconds": round(self.duration_seconds, 3),
            "start_timecode": self.timebase.to_timecode(self.start_frame),
            "video": [t.summary() for t in self.video if t.segments],
            "audio": [t.summary() for t in self.audio if t.segments],
            "warnings": self.warnings,
        }
