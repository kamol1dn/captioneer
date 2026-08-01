"""Emit FCP7 XML (xmeml v5) — the interchange format Premiere imports natively.

Not FCPXML 1.x: Premiere cannot import that without a Resolve or Final Cut
round trip. xmeml is the older, uglier format, and it's the one that works.

Two stateful details cause most import problems and are handled here:

1. A source file's ``<file>`` element is defined **once**, on first appearance.
   Every later reference is the bare ``<file id="file-1"/>``. Repeating the
   definition makes Premiere create duplicate bin items and, on some builds,
   prompt to relink per clipitem. The id map spans all sequences in the
   document, so 14 clips off one episode share 3 file definitions total.

2. ``<link>`` elements are only emitted for video/audio clipitems that are
   genuinely frame-identical. A link whose ``clipindex`` is off by one makes
   Premiere pair the wrong items and flag everything out of sync — worse than
   no links at all, since unlinked clips still play correctly.

A third applies once clips are cut from an existing episode timeline rather than
from flat per-angle exports. Those clipitems carry a ``SourceRef``: the source
definition exactly as Premiere wrote it, which may be a ``<file>`` or a whole
nested ``<sequence>`` with its own frame size and internal framing. Those are
re-emitted **verbatim**, so a crop expressed as nest-plus-offset survives without
this module having to understand it. Ids generated here are namespaced (``reel-``)
precisely so a copied subtree can keep Premiere's own ids and stay internally
consistent; a definition is still written once and referenced by id thereafter,
including definitions that arrive nested inside a copied sequence.
"""
import copy
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..compile import ClipItem, CompiledClip
from ..sources import SourceRef
from ..timebase import Timebase
from .pathurl import to_pathurl

_HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'

# Fixed namespace so a clip id always maps to the same sequence UUID.
_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


class XmemlWriter:
    """Builds one xmeml document containing any number of sequences."""

    def __init__(self, stereo_as_two_tracks: bool = True):
        self.stereo_as_two_tracks = stereo_as_two_tracks
        self._file_ids: Dict[str, str] = {}     # abs path -> file id
        self._ids: Dict[int, str] = {}          # id(ClipItem) -> xml id
        # Ids already carrying a full definition in this document, as
        # "file:file-11" / "sequence:sequence-3". Spans both the ids we mint and
        # the ones that arrive inside a copied nest, so a source referenced both
        # at top level and from within a nest is still defined exactly once.
        self._defined: Set[str] = set()
        self._n_files = 0
        self._n_items = 0

    # ── public ───────────────────────────────────────────────────────────────

    def build(self, clips: List[CompiledClip], project_name: str = "Clipper",
              file_meta: Optional[Dict[str, dict]] = None) -> str:
        """Return the full XML text for a set of compiled clips."""
        self._file_meta = file_meta or {}
        self._assign_ids(clips)
        root = ET.Element("xmeml", version="5")
        # A bin keeps 14 sequences tidy in Premiere's project panel instead of
        # dumping them at the root.
        bin_el = ET.SubElement(root, "bin")
        _text(bin_el, "name", project_name)
        children = ET.SubElement(bin_el, "children")
        for clip in clips:
            children.append(self._sequence(clip))
        ET.indent(root, space="\t")
        return _HEADER + ET.tostring(root, encoding="unicode")

    def write(self, clips: List[CompiledClip], out_path,
              project_name: str = "Clipper",
              file_meta: Optional[Dict[str, dict]] = None) -> Path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.build(clips, project_name, file_meta),
                       encoding="utf-8")
        return out

    def _assign_ids(self, clips: List[CompiledClip]) -> None:
        """Give every clipitem a stable, document-order id.

        Deterministic ids matter: the golden-XML test diffs whole documents, and
        identity-derived ids would make every run differ for no real reason.
        """
        n = 0
        for clip in clips:
            for track in clip.video_tracks + clip.audio_tracks:
                for item in track:
                    n += 1
                    self._ids[id(item)] = f"reel-clipitem-{n}"

    # ── sequence ─────────────────────────────────────────────────────────────

    def _sequence(self, clip: CompiledClip) -> ET.Element:
        seq = ET.Element("sequence", id=f"reel-{_safe(clip.id)}")
        # Deterministic per-clip UUID: re-exporting the same EDL then produces a
        # byte-identical file, and Premiere treats a re-import as the same
        # sequence rather than spawning a duplicate.
        _text(seq, "uuid", str(uuid.uuid5(_NS, clip.id)))
        _text(seq, "duration", clip.duration)
        seq.append(_rate(clip.timebase))
        _text(seq, "name", clip.name)
        seq.append(_timecode(clip.timebase, 0))

        media = ET.SubElement(seq, "media")
        self._video(media, clip)
        self._audio(media, clip)

        # Markers hang off the sequence, not a track.
        for m in clip.markers:
            mk = ET.SubElement(seq, "marker")
            _text(mk, "comment", m.comment)
            _text(mk, "name", m.name)
            _text(mk, "in", m.frame)
            _text(mk, "out", m.frame + m.duration if m.duration else -1)

        return seq

    def _video(self, media: ET.Element, clip: CompiledClip) -> None:
        video = ET.SubElement(media, "video")
        fmt = ET.SubElement(video, "format")
        sc = ET.SubElement(fmt, "samplecharacteristics")
        sc.append(_rate(clip.timebase))
        _text(sc, "width", clip.frame_size[0])
        _text(sc, "height", clip.frame_size[1])
        _text(sc, "anamorphic", "FALSE")
        _text(sc, "pixelaspectratio", "square")
        _text(sc, "fielddominance", "none")

        links = self._link_map(clip)
        for track_items in clip.video_tracks:
            track = ET.SubElement(video, "track")
            for idx, item in enumerate(track_items, start=1):
                track.append(self._clipitem(item, clip.timebase, links))
            _text(track, "enabled", "TRUE")
            _text(track, "locked", "FALSE")

    def _audio(self, media: ET.Element, clip: CompiledClip) -> None:
        if not clip.audio_tracks:
            return
        audio = ET.SubElement(media, "audio")
        fmt = ET.SubElement(audio, "format")
        sc = ET.SubElement(fmt, "samplecharacteristics")
        _text(sc, "depth", 16)
        _text(sc, "samplerate", 48000)
        outputs = ET.SubElement(audio, "outputs")
        # One stereo output group; each mono track routes into it.
        for ch in (1, 2):
            g = ET.SubElement(outputs, "group")
            _text(g, "index", ch)
            _text(g, "numchannels", 1)
            _text(g, "downmix", 0)
            ch_el = ET.SubElement(g, "channel")
            _text(ch_el, "index", ch)

        links = self._link_map(clip)
        for track_items in clip.audio_tracks:
            track = ET.SubElement(audio, "track")
            for item in track_items:
                track.append(self._clipitem(item, clip.timebase, links))
            # The *track* stays enabled even when its clips are disabled — the
            # per-clipitem flag is what the editor toggles, and a disabled track
            # would hide the toggle behind a second one.
            _text(track, "enabled", "TRUE")
            _text(track, "locked", "FALSE")

    # ── clipitem ─────────────────────────────────────────────────────────────

    def _clipitem(self, item: ClipItem, tb: Timebase,
                  links: Dict[int, List[dict]]) -> ET.Element:
        self._n_items += 1
        el = ET.Element("clipitem", id=self._item_id(item))
        _text(el, "name", item.name)
        _text(el, "enabled", "TRUE" if item.enabled else "FALSE")
        _text(el, "duration", item.out - item.in_)
        el.append(_rate(tb))
        _text(el, "start", item.start)
        _text(el, "end", item.end)
        _text(el, "in", item.in_)
        _text(el, "out", item.out)
        el.append(self._source(item, tb))

        if item.media_type == "audio":
            st = ET.SubElement(el, "sourcetrack")
            _text(st, "mediatype", "audio")
            _text(st, "trackindex", item.source_channel)
        else:
            st = ET.SubElement(el, "sourcetrack")
            _text(st, "mediatype", "video")
            _text(st, "trackindex", 1)

        for f in self._filters(item):
            el.append(f)

        # Every member of a link group carries the full membership list,
        # including itself.
        if item.link_group is not None:
            for member in links.get(item.link_group, []):
                lk = ET.SubElement(el, "link")
                _text(lk, "linkclipref", member["ref"])
                _text(lk, "mediatype", member["mediatype"])
                _text(lk, "trackindex", member["trackindex"])
                _text(lk, "clipindex", member["clipindex"])
                if member["mediatype"] == "audio":
                    _text(lk, "groupindex", 1)
        return el

    # ── sources ──────────────────────────────────────────────────────────────

    def _source(self, item: ClipItem, tb: Timebase) -> ET.Element:
        """What this clipitem points at, defined once and referenced after."""
        if item.source is not None:
            return self._passthrough(item.source)
        return self._file(item, tb)

    def _passthrough(self, ref: SourceRef) -> ET.Element:
        """Re-emit a source read off the master timeline, unchanged.

        The definition is copied whole on first use — for a nest that means its
        tracks, its frame size and the clipitems inside it, which is where the
        framing of a reframed angle actually lives. Later uses are the bare id
        reference Premiere itself would have written.
        """
        key = f"{ref.kind}:{ref.key}"
        if key in self._defined:
            return ET.Element(ref.kind, id=ref.key)
        self._defined.add(key)
        el = copy.deepcopy(ref.element) if ref.element is not None \
            else ET.Element(ref.kind, id=ref.key)
        if ref.kind == "sequence":
            self._collapse_known(el)
        return el

    def _collapse_known(self, root: ET.Element) -> None:
        """Strip definitions inside a copied nest that this document already has.

        A camera file can be referenced both by a top-level angle track and from
        inside a nest. Emitting the full ``<file>`` twice makes Premiere create
        two bin items for one piece of media, so the second occurrence is reduced
        to a bare id reference — in place, since position within a clipitem is
        part of the schema.
        """
        found = [(parent, child)
                 for parent in root.iter()
                 for child in parent
                 if child.tag in ("file", "sequence") and len(child)]
        for _parent, child in found:
            key = f"{child.tag}:{child.get('id') or ''}"
            if key in self._defined:
                cid = child.get("id")
                child.clear()
                if cid:
                    child.set("id", cid)
            else:
                self._defined.add(key)

    def _filters(self, item: ClipItem) -> List[ET.Element]:
        """The clipitem's filters: whatever the source carried, plus the punch.

        A jump-cut punch is a scale, and the source may already have a Basic
        Motion holding the crop that fits a landscape camera into a vertical
        frame. Two Basic Motion blocks on one clipitem is undefined, so the punch
        multiplies into the existing one rather than being appended beside it —
        which also keeps the punch relative to the framing instead of replacing
        it with an absolute zoom.
        """
        # No punch on this shot: hand the source's filters back byte-identical
        # rather than round-tripping their numbers through float.
        if item.media_type != "video" or abs(item.scale - 100.0) <= 1e-6:
            return [copy.deepcopy(f) for f in item.filters]

        punch = item.scale / 100.0
        out: List[ET.Element] = []
        composed = False
        for f in item.filters:
            f = copy.deepcopy(f)
            if not composed and (f.findtext("effect/effectid") or "") == "basic":
                for p in f.findall("effect/parameter"):
                    if p.findtext("parameterid") == "scale":
                        base = float(p.findtext("value") or 100.0)
                        p.find("value").text = str(round(base * punch, 4))
                        composed = True
            out.append(f)

        if not composed:
            out.append(_basic_motion(item.scale))
        return out

    def _file(self, item: ClipItem, tb: Timebase) -> ET.Element:
        """Full <file> on first use of a path, bare reference thereafter."""
        key = str(Path(item.path).resolve()) if item.path else item.name
        known = self._file_ids.get(key)
        if known:
            return ET.Element("file", id=known)

        self._n_files += 1
        fid = f"reel-file-{self._n_files}"
        self._file_ids[key] = fid
        self._defined.add(f"file:{fid}")

        meta = self._file_meta.get(key, {}) or self._file_meta.get(item.path, {})
        el = ET.Element("file", id=fid)
        _text(el, "name", Path(item.path).name if item.path else item.name)
        _text(el, "pathurl", to_pathurl(item.path) if item.path else "")
        el.append(_rate(tb))
        if meta.get("duration_frames"):
            _text(el, "duration", int(meta["duration_frames"]))
        el.append(_timecode(tb, meta.get("start_frame", 0)))

        fmedia = ET.SubElement(el, "media")
        if meta.get("has_video", True):
            v = ET.SubElement(fmedia, "video")
            vsc = ET.SubElement(v, "samplecharacteristics")
            vsc.append(_rate(tb))
            _text(vsc, "width", meta.get("width", 1080))
            _text(vsc, "height", meta.get("height", 1920))
        if meta.get("has_audio", True):
            a = ET.SubElement(fmedia, "audio")
            _text(a, "channelcount", meta.get("channels", 2))
            asc = ET.SubElement(a, "samplecharacteristics")
            _text(asc, "depth", 16)
            _text(asc, "samplerate", meta.get("sample_rate", 48000))
        return el

    def _item_id(self, item: ClipItem) -> str:
        return self._ids.get(id(item), "clipitem-0")

    # ── links ────────────────────────────────────────────────────────────────

    def _link_map(self, clip: CompiledClip) -> Dict[int, List[dict]]:
        """Build link membership, but only for genuinely aligned items.

        clipindex is the 1-based position of an item within its own track, and
        trackindex is 1-based within its media type. Both are computed here from
        the actual layout rather than assumed.
        """
        groups: Dict[int, List[dict]] = {}
        for t_idx, items in enumerate(clip.video_tracks, start=1):
            for c_idx, item in enumerate(items, start=1):
                if item.link_group is None:
                    continue
                groups.setdefault(item.link_group, []).append({
                    "ref": self._item_id(item), "mediatype": "video",
                    "trackindex": t_idx, "clipindex": c_idx,
                    "item": item,
                })
        for t_idx, items in enumerate(clip.audio_tracks, start=1):
            for c_idx, item in enumerate(items, start=1):
                if item.link_group is None:
                    continue
                groups.setdefault(item.link_group, []).append({
                    "ref": self._item_id(item), "mediatype": "audio",
                    "trackindex": t_idx, "clipindex": c_idx,
                    "item": item,
                })

        # Drop any group whose members aren't frame-identical — a wrong link is
        # worse than none.
        clean: Dict[int, List[dict]] = {}
        for gid, members in groups.items():
            spans = {(m["item"].start, m["item"].end,
                      m["item"].in_, m["item"].out) for m in members}
            if len(members) > 1 and len(spans) == 1:
                clean[gid] = [{k: v for k, v in m.items() if k != "item"}
                              for m in members]
        return clean


# ── element helpers ──────────────────────────────────────────────────────────

def _text(parent: ET.Element, tag: str, value) -> ET.Element:
    el = ET.SubElement(parent, tag)
    if value is not None:
        el.text = str(value)
    return el


def _basic_motion(scale: float) -> ET.Element:
    """A Basic Motion filter carrying a scale, which Premiere reads as its own
    Motion > Scale.

    Scale is the one geometric change that survives an FCP7 round trip intact,
    which is why the punch-in is expressed this way rather than as a Premiere
    effect: the editor can still grab the clip and adjust it by hand afterwards.
    """
    filt = ET.Element("filter")
    eff = ET.SubElement(filt, "effect")
    _text(eff, "name", "Basic Motion")
    _text(eff, "effectid", "basic")
    _text(eff, "effectcategory", "motion")
    _text(eff, "effecttype", "motion")
    _text(eff, "mediatype", "video")

    p = ET.SubElement(eff, "parameter")
    _text(p, "parameterid", "scale")
    _text(p, "name", "Scale")
    _text(p, "valuemin", 0)
    _text(p, "valuemax", 1000)
    _text(p, "value", round(scale, 3))

    # Centre and rotation are written at their identity values so the filter is
    # complete; a partial Basic Motion block is where importers start guessing.
    c = ET.SubElement(eff, "parameter")
    _text(c, "parameterid", "center")
    _text(c, "name", "Center")
    cv = ET.SubElement(c, "value")
    _text(cv, "horiz", 0)
    _text(cv, "vert", 0)

    r = ET.SubElement(eff, "parameter")
    _text(r, "parameterid", "rotation")
    _text(r, "name", "Rotation")
    _text(r, "valuemin", -8640)
    _text(r, "valuemax", 8640)
    _text(r, "value", 0)
    return filt


def _rate(tb: Timebase) -> ET.Element:
    """xmeml always carries the integer timebase plus an ntsc flag."""
    el = ET.Element("rate")
    _text(el, "timebase", tb.timebase)
    _text(el, "ntsc", "TRUE" if tb.ntsc else "FALSE")
    return el


def _timecode(tb: Timebase, start_frame: int = 0) -> ET.Element:
    el = ET.Element("timecode")
    el.append(_rate(tb))
    _text(el, "string", tb.to_timecode(start_frame))
    _text(el, "frame", start_frame)
    _text(el, "displayformat", "DF" if tb.drop_frame else "NDF")
    return el


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s)


def write_xmeml(clips: List[CompiledClip], out_path,
                project_name: str = "Clipper",
                file_meta: Optional[Dict[str, dict]] = None) -> Path:
    return XmemlWriter().write(clips, out_path, project_name, file_meta)
