"""Read the active multicam angle of every cut straight from a .prproj.

Premiere's scripting API can see that a timeline clip is a multicam clip but not
which angle it shows. The project file can: a .prproj is gzipped XML, and each
multicam cut is stored as

    Sequence ──Second──▶ VideoTrackGroup ──Track──▶ VideoClipTrack
      ──TrackItem──▶ VideoClipTrackItem (Start, End in sequence ticks)
      ──SubClip──▶ SubClip ──Clip──▶ VideoClip
            IsMulticam = true
            SelectedTrackIndex = the angle (0-based video track of the multicam
                                 source sequence)
            InPoint/OutPoint   = time inside the multicam source sequence
            Source ──▶ VideoSequenceSource ──Sequence──▶ the multicam sequence

so the angle of a cut is keyed by (sequence UID, video track index, Start),
which is exactly what the live bridge reports for the same clip. The file only
reflects the last save, which is why the bridge saves before reading.
"""
from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MulticamCut:
    sequence_uid: str
    track_index: int
    start: int
    end: int
    angle: int
    source_sequence_uid: str | None
    in_point: int
    out_point: int


def _ident(el: ET.Element) -> str | None:
    return el.get("ObjectID") or el.get("ObjectUID")


def _ref(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    return el.get("ObjectRef") or el.get("ObjectURef")


def _int(el: ET.Element, path: str, default: int = 0) -> int:
    node = el.find(path)
    return int(node.text) if node is not None and node.text else default


def load_root(path: str | Path) -> ET.Element:
    with gzip.open(path, "rb") as fh:
        return ET.parse(fh).getroot()


def multicam_cuts(root: ET.Element) -> dict[tuple[str, int, int], MulticamCut]:
    """Every multicam cut in the project, keyed by (sequence UID, track, start)."""
    objects = {}
    for el in root:
        oid = _ident(el)
        if oid:
            objects[oid] = el

    cuts: dict[tuple[str, int, int], MulticamCut] = {}
    for seq in root.iter("Sequence"):
        seq_uid = seq.get("ObjectUID")
        if not seq_uid:
            continue  # the <Sequence ObjectURef=...> pointers inside sources
        for group_ref in seq.iterfind("TrackGroups/TrackGroup/Second"):
            group = objects.get(_ref(group_ref))
            if group is None or group.tag != "VideoTrackGroup":
                continue
            for track_ref in group.iterfind("TrackGroup/Tracks/Track"):
                track = objects.get(_ref(track_ref))
                if track is None:
                    continue
                index = int(track_ref.get("Index", "0"))
                for item_ref in track.iterfind("ClipTrack/ClipItems/TrackItems/TrackItem"):
                    item = objects.get(_ref(item_ref))
                    if item is None or item.tag != "VideoClipTrackItem":
                        continue
                    sub = objects.get(_ref(item.find("ClipTrackItem/SubClip")))
                    clip_el = objects.get(_ref(sub.find("Clip"))) if sub is not None else None
                    clip = clip_el.find("Clip") if clip_el is not None else None
                    if clip is None or (clip.findtext("IsMulticam") or "").strip() != "true":
                        continue
                    source = objects.get(_ref(clip.find("Source")))
                    source_seq = _ref(source.find("SequenceSource/Sequence")) if source is not None else None
                    start = _int(item, "ClipTrackItem/TrackItem/Start")
                    cut = MulticamCut(
                        sequence_uid=seq_uid,
                        track_index=index,
                        start=start,
                        end=_int(item, "ClipTrackItem/TrackItem/End"),
                        angle=_int(clip, "SelectedTrackIndex"),
                        source_sequence_uid=source_seq,
                        in_point=_int(clip, "InPoint"),
                        out_point=_int(clip, "OutPoint"),
                    )
                    cuts[(seq_uid, index, start)] = cut
    return cuts
