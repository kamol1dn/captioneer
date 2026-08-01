"""Read an FCP7 XML exported from Premiere into ``clipper.sources`` tracks.

The workflow this exists for: instead of exporting one flat vertical video per
angle (14 GB each, an hour of encoding), the editor exports **only audio** and
hands over the episode timeline as XML. Picture then comes from whatever V1, V2,
… already point at, sliced to the same in/out the reel needs.

Two facts about Premiere's exporter shape everything here.

1. **Multicam items are dropped, not flattened.** A timeline whose V-tracks hold
   multicam clips exports with *empty* video tracks and a translation-log line
   saying so. The angles have to be flattened (or stacked as plain clips) before
   export. ``read_master`` raises when no video track has a single clipitem,
   because the alternative is silently producing reels with no picture.

2. **Nested sequences survive, and the nesting carries framing.** A nest is
   defined inline at its first use and referenced as a bare ``<sequence id=…/>``
   thereafter — the same define-once pattern the writer uses for ``<file>``.
   Crucially the nest has its *own* frame size, and the crop that fits a
   landscape camera into a vertical reel is split across two stages: an inner
   scale within the nest's frame, then an outer centre offset on the clipitem.
   Resolving a nest down to the camera file it ultimately contains would throw
   that framing away, so ``SourceRef`` keeps the definition subtree instead.
"""
import copy
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse

from ..sources import MasterTimeline, Segment, SourceRef, SourceTrack
from ..timebase import Timebase

# Filters that change the relationship between program time and source time.
# The compile step assumes end - start == out - in, which a speed change breaks.
_RETIMING = ("time remap", "timeremap", "speed")


def read_master(xml_path: str, sequence_name: Optional[str] = None) -> MasterTimeline:
    """Parse an exported FCP7 XML into a MasterTimeline.

    ``sequence_name`` picks one when the document holds several top-level
    sequences; nests don't count, since they are defined inside the clipitems
    that use them rather than beside their parent.
    """
    root = ET.parse(xml_path).getroot()
    defs = _definition_map(root)
    seq = _pick_sequence(root, sequence_name)

    tb = _rate(seq.find("rate")) or Timebase(30)
    sc = seq.find("media/video/format/samplecharacteristics")
    frame_size = ((int(sc.findtext("width") or 0), int(sc.findtext("height") or 0))
                  if sc is not None else (0, 0))
    tc = seq.find("timecode")
    start_frame = int((tc.findtext("frame") if tc is not None else 0) or 0)

    master = MasterTimeline(
        name=seq.findtext("name") or "",
        timebase=tb, frame_size=frame_size,
        duration=int(seq.findtext("duration") or 0),
        start_frame=start_frame, path=str(xml_path),
    )

    for kind, prefix in (("video", "V"), ("audio", "A")):
        media = seq.find(f"media/{kind}")
        if media is None:
            continue
        bucket = master.video if kind == "video" else master.audio
        for i, tr in enumerate(media.findall("track"), start=1):
            bucket.append(_read_track(tr, kind, i, f"{prefix}{i}", defs,
                                      master.warnings))

    if not any(t.segments for t in master.video):
        raise ValueError(
            f"{xml_path}: sequence {master.name!r} has no video clipitems on any "
            f"track. Premiere drops multicam items on FCP XML export rather than "
            f"flattening them — check the translation-results log for 'multicam "
            f"sequences are not supported'. Flatten the multicams (or stack the "
            f"angles as plain clips) and export again.")
    if start_frame:
        master.warnings.append(
            f"sequence starts at {tb.to_timecode(start_frame)}, not zero; master "
            f"time is measured from the sequence start, so the exported audio "
            f"must begin at that same point")
    return master


def _read_track(tr: ET.Element, kind: str, index: int, label: str,
                defs: Dict[str, ET.Element], warnings: List[str]) -> SourceTrack:
    track = SourceTrack(
        kind=kind, index=index, label=label,
        enabled=(tr.findtext("enabled") or "TRUE").upper() != "FALSE",
        skipped_transitions=len(tr.findall("transitionitem")),
    )
    names: Dict[str, int] = {}

    for c in tr.findall("clipitem"):
        start = int(c.findtext("start") or -1)
        end = int(c.findtext("end") or -1)
        in_ = int(c.findtext("in") or 0)
        out = int(c.findtext("out") or 0)
        name = c.findtext("name") or ""
        length = out - in_

        # A -1 endpoint does NOT mean "no position" — it means "this edge is
        # defined by the transition next to me", and the value is recoverable
        # from the other edge plus the source length. Treating -1 as unplaceable
        # silently drops a third of a track that has crossfades on it (112 of 333
        # items on one real lav track), which sounds exactly like audio randomly
        # cutting out. Only an item with *both* edges at -1 is genuinely
        # unplaceable: it sits entirely inside a transition.
        if start < 0 and end < 0:
            continue
        if start < 0:
            start = end - length
        elif end < 0:
            end = start + length

        drift = (end - start) - (out - in_)
        if drift:
            # Audio in/out come from sample positions, so Premiere writes the
            # occasional one-frame disagreement with the program range on an
            # audio clipitem. Program position is the edit; the source range is
            # what gives, since a frame of audio shift is inaudible where a frame
            # of program shift would slide the rest of the track. Anything larger
            # — or any drift at all on picture — is a real speed change.
            if kind == "audio" and abs(drift) <= 1:
                warnings.append(
                    f"{label}: clip {name!r} at frame {start} is {drift:+d}f out "
                    f"between program and source; snapped to the program range")
                out = in_ + (end - start)
            else:
                raise ValueError(
                    f"{label}: clip {name!r} at frame {start} is retimed "
                    f"(program {end - start}f vs source {out - in_}f). Reels are "
                    f"cut by frame arithmetic, which a speed change invalidates — "
                    f"remove it, or pre-render that section.")

        for f in c.findall("filter"):
            fname = (f.findtext("effect/name") or "").lower()
            if any(r in fname for r in _RETIMING):
                raise ValueError(
                    f"{label}: clip {name!r} at frame {start} carries a "
                    f"{f.findtext('effect/name')!r} filter, which retimes it.")

        ref = _source_ref(c, defs)
        if ref is None:
            warnings.append(
                f"{label}: clip {name!r} at frame {start} has no file or sequence "
                f"reference (adjustment layer or title?) — skipped")
            continue

        st = c.find("sourcetrack")
        track.segments.append(Segment(
            start=start, end=end, in_=in_, source=ref, name=name,
            filters=[copy.deepcopy(f) for f in c.findall("filter")],
            source_channel=int((st.findtext("trackindex") if st is not None else 1) or 1),
            enabled=(c.findtext("enabled") or "TRUE").upper() != "FALSE",
        ))
        names[name] = names.get(name, 0) + 1

    track.segments.sort(key=lambda s: s.start)
    _resolve_overlaps(track)
    if names:
        track.name = max(names, key=lambda n: names[n])
    return track


def _resolve_overlaps(track: SourceTrack) -> None:
    """Butt-join segments that a crossfade left overlapping.

    Both halves of a transition extend into it, so once the -1 edges are
    recovered the two clips overlap by the transition's length. One track cannot
    hold two clips at one time, so the outgoing clip is trimmed back to where the
    incoming one starts — the crossfade becomes a hard cut at its own start,
    within a frame or two of where the dissolve was centred.

    Trimming moves ``end``, and ``out`` is always derived from ``in_`` plus the
    length, so this cannot introduce a retime.
    """
    kept: List[Segment] = []
    for seg in track.segments:
        if kept and seg.start < kept[-1].end:
            prev = kept[-1]
            prev.end = seg.start
            if prev.length <= 0:
                kept.pop()          # wholly swallowed by the incoming clip
        if seg.length > 0:
            kept.append(seg)
    track.segments = kept


def _source_ref(clipitem: ET.Element, defs: Dict[str, ET.Element]) -> Optional[SourceRef]:
    """Resolve a clipitem's ``<file>`` or ``<sequence>`` to its definition.

    Either may be a bare ``<tag id="…"/>`` pointing back at the first use, which
    is why the whole document is indexed up front rather than resolved lazily.
    """
    for kind in ("file", "sequence"):
        el = clipitem.find(kind)
        if el is None:
            continue
        key = el.get("id") or ""
        full = defs.get(f"{kind}:{key}")
        if full is None and len(el):
            full = el
        if full is None:
            return None
        return SourceRef(
            kind=kind, key=key,
            name=full.findtext("name") or key,
            path=_path_of(full) if kind == "file" else "",
            element=copy.deepcopy(full),
        )
    return None


def _definition_map(root: ET.Element) -> Dict[str, ET.Element]:
    """``{"file:file-1": <file>, "sequence:sequence-3": <sequence>}``.

    First definition wins: Premiere writes the full element on first use and a
    bare id reference every time after, and both carry the same id.
    """
    out: Dict[str, ET.Element] = {}
    for kind in ("file", "sequence"):
        for el in root.iter(kind):
            key = f"{kind}:{el.get('id') or ''}"
            if len(el) and key not in out:
                out[key] = el
    return out


def _pick_sequence(root: ET.Element, name: Optional[str]) -> ET.Element:
    """The top-level sequence to cut from.

    Top-level means a direct child of ``<xmeml>`` or of a bin — a nest lives
    inside the clipitem that first uses it and must never be mistaken for the
    episode timeline.
    """
    tops = (root.findall("sequence")
            + root.findall("bin/children/sequence")
            + root.findall("project/children/sequence")
            + root.findall("project/children/bin/children/sequence"))
    if not tops:
        raise ValueError("no top-level <sequence> in this XML")

    if name:
        wanted = name.strip().lower()
        for s in tops:
            if (s.findtext("name") or "").strip().lower() == wanted:
                return s
        have = ", ".join(repr(s.findtext("name")) for s in tops)
        raise ValueError(f"no sequence named {name!r}; the document has {have}")

    if len(tops) > 1:
        have = ", ".join(repr(s.findtext("name")) for s in tops)
        raise ValueError(
            f"this XML holds {len(tops)} sequences ({have}); name the one to cut "
            f"from")
    return tops[0]


def list_sequences(xml_path: str) -> List[dict]:
    """Top-level sequences in a document, for picking one before committing."""
    root = ET.parse(xml_path).getroot()
    out = []
    for s in _all_tops(root):
        tb = _rate(s.find("rate")) or Timebase(30)
        dur = int(s.findtext("duration") or 0)
        out.append({
            "name": s.findtext("name") or "",
            "duration_frames": dur,
            "duration_seconds": round(tb.to_seconds(dur), 3),
            "timebase": str(tb),
            "video_tracks": len(s.findall("media/video/track")),
            "audio_tracks": len(s.findall("media/audio/track")),
            "video_clipitems": len(s.findall("media/video/track/clipitem")),
        })
    return out


def _all_tops(root: ET.Element) -> List[ET.Element]:
    return (root.findall("sequence")
            + root.findall("bin/children/sequence")
            + root.findall("project/children/sequence")
            + root.findall("project/children/bin/children/sequence"))


def _rate(el: Optional[ET.Element]) -> Optional[Timebase]:
    if el is None:
        return None
    return Timebase(timebase=int(el.findtext("timebase") or 30),
                    ntsc=(el.findtext("ntsc") or "FALSE").upper() == "TRUE")


def _path_of(file_el: ET.Element) -> str:
    """``file://localhost/D%3a/x/y.mp4`` -> ``D:/x/y.mp4``."""
    url = file_el.findtext("pathurl") or ""
    if not url:
        return ""
    p = unquote(urlparse(url).path)
    # Windows paths arrive as /D:/… once unquoted.
    if len(p) > 2 and p[0] == "/" and p[2] == ":":
        p = p[1:]
    return p
