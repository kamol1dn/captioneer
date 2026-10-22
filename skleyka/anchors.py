"""Anchoring overlays to what is being said, so they survive re-trims.

All multicam angles share one clock: the multicam source sequence. A moment in
the conversation is a point on that clock, wherever the edit puts it. So each
overlay stores its start and last frame as *source* times, and after the user
re-trims, the same source times are looked up in the new edit to find where
the overlay belongs now.

Everything here works in integer ticks and is pure, so it is unit-tested
without Premiere (tests/test_anchors.py).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    """A stretch of the program where one multicam clip is on screen."""
    start: int      # sequence ticks
    end: int
    src: int        # source ticks at ``start``
    track: int

    def src_at(self, t: int) -> int:
        return self.src + (t - self.start)


def segments(cuts: list[list]) -> list[Segment]:
    """Flatten multicam clips into what is on screen: the topmost enabled clip
    wins wherever clips overlap. ``cuts`` rows come from SK.programCuts:
    [track, start, end, in_point, out_point, disabled]."""
    clips = [
        (int(track), int(start), int(end), int(src_in))
        for track, start, end, src_in, _out, disabled in cuts
        if not disabled and int(end) > int(start)
    ]
    bounds = sorted({c[1] for c in clips} | {c[2] for c in clips})
    out: list[Segment] = []
    # Clips sorted by start; a sweep keeps those covering the current stretch.
    clips.sort(key=lambda c: c[1])
    active: list[tuple[int, int, int, int]] = []
    k = 0
    for a, b in zip(bounds, bounds[1:]):
        while k < len(clips) and clips[k][1] <= a:
            active.append(clips[k])
            k += 1
        active = [c for c in active if c[2] > a]
        if not active:
            continue
        top = max(active, key=lambda c: c[0])
        seg = Segment(start=a, end=b, src=top[3] + (a - top[1]), track=top[0])
        prev = out[-1] if out else None
        if prev and prev.end == a and prev.track == seg.track and prev.src_at(a) == seg.src:
            out[-1] = Segment(prev.start, b, prev.src, prev.track)  # same clip continues
        else:
            out.append(seg)
    return out


def src_at(segs: list[Segment], t: int) -> int | None:
    """Source time on screen at sequence time ``t`` (None in a gap)."""
    for s in segs:
        if s.start <= t < s.end:
            return s.src_at(t)
    return None


def seq_at(segs: list[Segment], src: int, near: int | None = None) -> int | None:
    """Where source time ``src`` is in the edit now, or None if it was cut.

    Material used twice resolves to the use closest to ``near``."""
    hits = [s.start + (src - s.src) for s in segs if s.src <= src < s.src + (s.end - s.start)]
    if not hits:
        return None
    if near is None:
        return hits[0]
    return min(hits, key=lambda t: abs(t - near))


def anchor(segs: list[Segment], start: int, end: int, frame: int) -> dict | None:
    """Source anchors for an overlay on [start, end): its first and last frame."""
    first = src_at(segs, start)
    last = src_at(segs, end - frame)
    if first is None or last is None:
        return None
    return {"src_start": first, "src_last": last}


def relocate(segs: list[Segment], anch: dict, start: int, end: int, frame: int) -> dict:
    """Where an overlay anchored by ``anch`` (placed on [start, end)) belongs now.

    status: ``ok`` (in place), ``moved`` (same span, new position),
    ``span_changed`` (its first frame maps but material inside it was trimmed
    or added, so whatever it was timed to may be off), ``orphaned`` (the moment
    it starts on was cut).
    """
    new_start = seq_at(segs, anch["src_start"], near=start)
    if new_start is None:
        return {"status": "orphaned", "start": None, "end": None}
    new_end = new_start + (end - start)
    last = seq_at(segs, anch["src_last"], near=new_end - frame)
    if last != new_end - frame:
        status = "span_changed"
    elif new_start == start:
        status = "ok"
    else:
        status = "moved"
    return {"status": status, "start": new_start, "end": new_end}
