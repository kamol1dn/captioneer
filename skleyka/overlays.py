"""Overlays: the renders and sounds Skleyka places above the edit.

Everything Skleyka places lives on its own lanes (tracks named "SKL <n>",
created on top when needed) and is tagged by clip name "SKL <id> <label>", so
it can be found again after the user rearranges things, and the user's own
tracks are never written to.

Each overlay is recorded in <episode>/skleyka/overlays.json with its source
anchors (see anchors.py). ``resync`` uses them to put overlays back on the
moment they belong to after the user re-trims the edit.

Video renders must have no audio stream: overwriteClip would also lay the
render's audio onto the dialogue tracks.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from . import anchors, bridge, timeline

TICKS = 254016000000
FFPROBE = Path(__file__).resolve().parents[1] / "ffmpeg-7.1" / "bin" / "ffprobe.exe"

# Premiere's Opacity > Blend Mode indices, measured on 25.6 by rendering each
# mode over a known pixel (see README).
STILL_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd"}

BLEND = {
    "normal": 18, "screen": 22, "add": 14, "multiply": 17, "overlay": 19,
    "lighten": 11, "darken": 3, "color_dodge": 2, "color_burn": 1,
    "linear_burn": 13, "difference": 5, "exclusion": 7, "subtract": 25,
}


class OverlayError(RuntimeError):
    pass


# --- manifest -----------------------------------------------------------------

def _manifest_path(project_path: str) -> Path:
    return timeline.workdir(project_path) / "overlays.json"


def _load(project_path: str) -> dict:
    path = _manifest_path(project_path)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"sequences": {}}


def _store(project_path: str, data: dict) -> None:
    path = _manifest_path(project_path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _seq_entry(data: dict, ctx: dict) -> dict:
    entry = data["sequences"].setdefault(ctx["id"], {"name": ctx["name"], "next": {}, "overlays": {}})
    entry["name"] = ctx["name"]
    return entry


def _new_id(seq_entry: dict, kind: str) -> str:
    prefix = "g" if kind == "video" else "a"
    n = seq_entry["next"].get(prefix, 1)
    seq_entry["next"][prefix] = n + 1
    return f"{prefix}{n:03d}"


# --- Premiere context -----------------------------------------------------------

_CONTEXT = r"""
var seq = SK.sequence(ARGS.sequence);
return {project: app.project.path, id: seq.sequenceID, name: seq.name,
        frame: String(seq.timebase), zero: String(seq.zeroPoint),
        width: seq.frameSizeHorizontal, height: seq.frameSizeVertical,
        cuts: ARGS.cuts ? SK.programCuts(seq) : null};
"""

_LIVE = r"""
var seq = SK.sequence(ARGS.sequence);
var out = {};
var kinds = ['video', 'audio'];
for (var k = 0; k < 2; k++) {
    var tracks = SK.tracksOf(seq, kinds[k]);
    for (var t = 0; t < tracks.numTracks; t++) {
        var track = tracks[t];
        for (var i = 0; i < track.clips.numItems; i++) {
            var c = track.clips[i];
            var name = String(c.name);
            if (name.indexOf(SK.LANE) !== 0) continue;
            var state = SK.clipState(seq, c, t);
            state.kind = kinds[k];
            state.track_name = track.name;
            out[name.split(' ')[1]] = state;
        }
    }
}
return out;
"""


def _context(sequence: str | None, cuts: bool = False) -> dict:
    return bridge.run(_CONTEXT, {"sequence": sequence, "cuts": cuts}, timeout=60)


def _live(sequence_id: str) -> dict:
    return bridge.run(_LIVE, {"sequence": sequence_id}, timeout=60)


def _snap(seconds: float, frame: int, zero: int) -> int:
    return round(seconds * TICKS / frame) * frame + zero


def _sec(ticks: int, zero: int) -> float:
    return round((int(ticks) - zero) / TICKS, 6)


def _probe(path: Path) -> dict:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "stream=codec_type:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(out.stdout)
    types = [s.get("codec_type") for s in info.get("streams", [])]
    return {
        "duration": float(info["format"]["duration"]),
        "has_video": "video" in types,
        "has_audio": "audio" in types,
    }


def _style(style: dict | None) -> dict | None:
    """User-facing style to the values the jsx sets."""
    if not style:
        return None
    out = dict(style)
    blend = out.get("blend")
    if isinstance(blend, str):
        if blend not in BLEND:
            raise OverlayError(f"Unknown blend {blend!r}; one of {sorted(BLEND)}")
        out["blend"] = BLEND[blend]
    return out


# --- placing ----------------------------------------------------------------------

_PLACE = r"""
var v = SK.activate(ARGS.sequence), seq = v.seq, qs = v.qs;
var f = SK.frameTicks(seq);
var lane = SK.pickLane(seq, qs, ARGS.kind, ARGS.start, ARGS.end, ARGS.lane);
var track = SK.tracksOf(seq, ARGS.kind)[lane];
var item = SK.importItem(ARGS.file, SK.bin('skleyka'));
if (ARGS.refresh) item.refreshMedia();
// In/out marks on the project item make overwriteClip lay down exactly
// [start, end), so nothing past ``end`` on the lane is overwritten, even for a
// long render. They take seconds and round down to a frame, so video marks
// are aimed half a frame in (60 frames asked exactly gave 59); audio marks are
// sample-accurate and need no nudge. Read them back before trusting them.
// Media type 2 (audio) keeps audio marks sample-exact; type 4 rounds them to frames.
var MT = ARGS.kind === 'audio' ? 2 : 4;
var origIn = Number(item.getInPoint(MT).ticks), origOut = Number(item.getOutPoint(MT).ticks);
var nudge = ARGS.kind === 'video' ? f / 2 : 0;
function setMarks(inT, outT, nudge) {
    if (inT >= Number(item.getOutPoint(MT).ticks)) {
        item.setOutPoint((outT + nudge) / SK.TICKS, MT);
        item.setInPoint((inT + nudge) / SK.TICKS, MT);
    } else {
        item.setInPoint((inT + nudge) / SK.TICKS, MT);
        item.setOutPoint((outT + nudge) / SK.TICKS, MT);
    }
    return Math.abs(Number(item.getInPoint(MT).ticks) - inT) < f / 4 &&
           Math.abs(Number(item.getOutPoint(MT).ticks) - outT) < f / 4;
}
if (ARGS.still) {
    var okStill = track.overwriteClip(item, SK.timeFromTicks(ARGS.start));
    if (!okStill) throw new Error('overwriteClip failed on ' + track.name);
    var stillClip = SK.clipAtStart(track, ARGS.start, item.nodeId, f);
    if (!stillClip) throw new Error('placed still not found on ' + track.name);
    // Premiere lays a still down an hour into its (virtual) media, which shows
    // nothing; pin the in-point to the image.
    stillClip.inPoint = SK.timeFromTicks(0);
    stillClip = SK.clipAtStart(track, ARGS.start, item.nodeId, f);
    if (!SK.isFree(track, Number(stillClip.end.ticks), ARGS.end, stillClip.nodeId)) throw new Error(track.name + ' is not free up to the asked end');
    stillClip.end = SK.timeFromTicks(ARGS.end);
    stillClip = SK.clipAtStart(track, ARGS.start, item.nodeId, f);
    stillClip.name = ARGS.tag;
    SK.applyStyle(stillClip, ARGS.style);
    if (ARGS.animate === 'dissolve') SK.dissolve(seq, qs, lane, ARGS.start, ARGS.dissolve_frames || 4);
    else SK.animate(seq, stillClip, ARGS.animate);
    var st = SK.clipState(seq, stillClip, lane);
    st.track_name = track.name;
    return st;
}
if (!setMarks(ARGS.media_in, ARGS.media_in + ARGS.end - ARGS.start, nudge)) {
    SK.call(function () { return setMarks(origIn, origOut, 0); }, null);
    throw new Error('Premiere did not take the in/out marks on ' + item.name + '; nothing placed');
}
var ok = SK.call(function () { return track.overwriteClip(item, SK.timeFromTicks(ARGS.start)); }, false);
SK.call(function () { return setMarks(origIn, origOut, 0); }, null);
if (!ok) throw new Error('overwriteClip failed on ' + track.name);
var clip = SK.clipAtStart(track, ARGS.start, item.nodeId, f);
if (!clip) throw new Error('placed clip not found on ' + track.name);
var placedEnd = Number(clip.end.ticks);
// Marks at a file's very end can land a frame short; a frame is tolerated.
if (Math.abs(placedEnd - ARGS.end) > f) {
    throw new Error('placed ' + SK.secondsAt(seq, clip.start.ticks) + '-' + SK.secondsAt(seq, placedEnd) +
                    ' instead of ending at ' + SK.secondsAt(seq, ARGS.end) + ' (tag not applied; check ' + track.name + ')');
}
clip.name = ARGS.tag;
SK.applyStyle(clip, ARGS.style);
if (ARGS.animate === 'dissolve') SK.dissolve(seq, qs, lane, ARGS.start, ARGS.dissolve_frames || 4);
else SK.animate(seq, clip, ARGS.animate);
var state = SK.clipState(seq, clip, lane);
state.track_name = track.name;
return state;
"""


def place(file: str, start: float, end: float | None = None, *, kind: str = "video",
          lane: int | str | None = None, label: str = "", style: dict | None = None,
          media_in: float = 0.0, sequence: str | None = None, overlay_id: str | None = None,
          refresh: bool = False, animate: str | None = None) -> dict:
    """Place a render (kind="video", ProRes 4444 with alpha, no audio) or a
    sound (kind="audio") at ``start`` seconds, until ``end`` or the end of the
    file. ``media_in`` skips into the file. ``lane`` is a lane number, or a
    name such as a camera's ("SKL otabek") for renders that carry that
    camera's footage, so the user grades them with the track. Returns the
    manifest entry."""
    if kind not in ("video", "audio"):
        raise OverlayError("kind is 'video' or 'audio'")
    path = Path(file).resolve()
    if not path.exists():
        raise OverlayError(f"No such file: {path}")
    still = path.suffix.lower() in STILL_EXT
    info = {"duration": 1e9, "has_video": True, "has_audio": False} if still else _probe(path)
    if kind == "video" and info["has_audio"]:
        raise OverlayError(f"{path.name} has an audio stream. Render overlays without audio (-an); "
                           "placing it would also overwrite the dialogue tracks.")
    if kind == "video" and not info["has_video"]:
        raise OverlayError(f"{path.name} has no video stream")
    if kind == "audio" and not info["has_audio"]:
        raise OverlayError(f"{path.name} has no audio stream")

    ctx = _context(sequence, cuts=True)
    frame, zero = int(ctx["frame"]), int(ctx["zero"])
    s = _snap(start, frame, zero)
    m_in = round(media_in * TICKS / frame) * frame
    available = round(info["duration"] * TICKS / frame) * frame - m_in
    if still and end is None:
        raise OverlayError("a still needs an end time")
    e = _snap(end, frame, zero) if end is not None else s + available
    if e <= s:
        raise OverlayError("end must be after start")
    if e - s > available:
        raise OverlayError(f"{path.name} has {available / TICKS:.3f}s from media_in; "
                           f"asked for {(e - s) / TICKS:.3f}s. Render it longer.")

    data = _load(ctx["project"])
    seq_entry = _seq_entry(data, ctx)
    oid = overlay_id or _new_id(seq_entry, kind)
    tag = f"SKL {oid}" + (f" {label}" if label else "")
    state = bridge.run(_PLACE, {
        "sequence": ctx["id"], "kind": kind, "file": str(path), "start": s, "end": e,
        "media_in": m_in, "lane": lane, "tag": tag, "style": _style(style), "refresh": refresh, "still": still, "animate": animate,
    }, timeout=120)

    segs = anchors.segments(ctx["cuts"])
    entry = {
        "id": oid,
        "kind": kind,
        "label": label,
        "file": str(path),
        "lane": state["track_name"],
        "start": _sec(state["start_ticks"], zero),
        "end": _sec(state["end_ticks"], zero),
        "start_ticks": state["start_ticks"],
        "end_ticks": state["end_ticks"],
        "media_in": round(m_in / TICKS, 6),
        "style": style,
        "animate": animate,
        "anchor": anchors.anchor(segs, int(state["start_ticks"]), int(state["end_ticks"]), frame),
        "placed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    seq_entry["overlays"][oid] = entry
    _store(ctx["project"], data)
    return entry


# --- finding and changing ---------------------------------------------------------

def _entry(sequence: str | None, overlay_id: str) -> tuple[dict, dict, dict]:
    ctx = _context(sequence, cuts=True)
    data = _load(ctx["project"])
    seq_entry = _seq_entry(data, ctx)
    entry = seq_entry["overlays"].get(overlay_id)
    if entry is None:
        raise OverlayError(f"No overlay {overlay_id} on {ctx['name']}")
    return ctx, data, entry


def _record(ctx: dict, data: dict, entry: dict, state: dict, reanchor: bool = True) -> dict:
    frame, zero = int(ctx["frame"]), int(ctx["zero"])
    entry.update({
        "lane": state.get("track_name", entry["lane"]),
        "start": _sec(state["start_ticks"], zero),
        "end": _sec(state["end_ticks"], zero),
        "start_ticks": state["start_ticks"],
        "end_ticks": state["end_ticks"],
    })
    if reanchor:
        segs = anchors.segments(ctx["cuts"])
        entry["anchor"] = anchors.anchor(segs, int(state["start_ticks"]), int(state["end_ticks"]), frame)
    _store(ctx["project"], data)
    return entry


_MOVE = r"""
var seq = SK.sequence(ARGS.sequence);
var found = SK.findTagged(seq, ARGS.kind, ARGS.id);
if (!found) throw new Error('SKL ' + ARGS.id + ' is not on the timeline');
var clip = found.clip, track = SK.tracksOf(seq, ARGS.kind)[found.track];
var s0 = Number(clip.start.ticks), e0 = Number(clip.end.ticks);
var delta = ARGS.start !== null ? ARGS.start - s0 : 0;
if (delta !== 0) {
    if (!SK.isFree(track, s0 + delta, e0 + delta, clip.nodeId)) throw new Error(track.name + ' is not free at the new position');
    clip.move(SK.timeFromTicks(delta));
    found = SK.findTagged(seq, ARGS.kind, ARGS.id);
}
var state = SK.clipState(seq, found.clip, found.track);
state.track_name = SK.tracksOf(seq, ARGS.kind)[found.track].name;
return state;
"""


def move(overlay_id: str, start: float | None = None, frames: int | None = None,
         sequence: str | None = None) -> dict:
    """Move an overlay to ``start`` seconds, or by ``frames``. Re-anchors it to
    the moment it now sits on."""
    ctx, data, entry = _entry(sequence, overlay_id)
    frame, zero = int(ctx["frame"]), int(ctx["zero"])
    if start is not None:
        target = _snap(start, frame, zero)
    elif frames is not None:
        target = int(entry["start_ticks"]) + frames * frame
    else:
        raise OverlayError("give start or frames")
    state = bridge.run(_MOVE, {"sequence": ctx["id"], "kind": entry["kind"], "id": overlay_id,
                               "start": target})
    return _record(ctx, data, entry, state)


_TRIM_END = r"""
var seq = SK.sequence(ARGS.sequence);
var found = SK.findTagged(seq, ARGS.kind, ARGS.id);
if (!found) throw new Error('SKL ' + ARGS.id + ' is not on the timeline');
var clip = found.clip, track = SK.tracksOf(seq, ARGS.kind)[found.track];
var e0 = Number(clip.end.ticks);
if (ARGS.end > e0 && !SK.isFree(track, e0, ARGS.end, clip.nodeId)) throw new Error(track.name + ' is not free up to the new end');
clip.end = SK.timeFromTicks(ARGS.end);
found = SK.findTagged(seq, ARGS.kind, ARGS.id);
var state = SK.clipState(seq, found.clip, found.track);
state.track_name = track.name;
return state;
"""


def trim(overlay_id: str, start: float | None = None, end: float | None = None,
         sequence: str | None = None) -> dict:
    """Change where an overlay starts and/or ends. The end is trimmed in place;
    a new start re-places the render from the matching point inside it (a
    plain start change in Premiere slides the content instead)."""
    ctx, data, entry = _entry(sequence, overlay_id)
    frame, zero = int(ctx["frame"]), int(ctx["zero"])
    if start is not None:
        new_start = _snap(start, frame, zero)
        new_end = _snap(end, frame, zero) if end is not None else int(entry["end_ticks"])
        shift = new_start - int(entry["start_ticks"])
        media_in = entry.get("media_in", 0.0) + shift / TICKS
        if media_in < -1e-6:
            raise OverlayError("the render does not reach back that far; render a longer head")
        remove(overlay_id, sequence=ctx["id"], forget=False)
        return place(entry["file"], _sec(new_start, zero), _sec(new_end, zero), kind=entry["kind"],
                     label=entry["label"], style=entry.get("style"), media_in=max(media_in, 0.0),
                     sequence=ctx["id"], overlay_id=overlay_id)
    if end is None:
        raise OverlayError("give start and/or end")
    target = _snap(end, frame, zero)
    if target <= int(entry["start_ticks"]):
        raise OverlayError("end must be after start")
    state = bridge.run(_TRIM_END, {"sequence": ctx["id"], "kind": entry["kind"], "id": overlay_id,
                                   "end": target})
    return _record(ctx, data, entry, state)


_STYLE = r"""
var seq = SK.sequence(ARGS.sequence);
var found = SK.findTagged(seq, ARGS.kind, ARGS.id);
if (!found) throw new Error('SKL ' + ARGS.id + ' is not on the timeline');
SK.applyStyle(found.clip, ARGS.style);
var state = SK.clipState(seq, found.clip, found.track);
state.track_name = SK.tracksOf(seq, ARGS.kind)[found.track].name;
return state;
"""


def restyle(overlay_id: str, style: dict, sequence: str | None = None) -> dict:
    """Change position/scale/rotation/opacity/blend (video) or gain_db (audio)."""
    ctx, data, entry = _entry(sequence, overlay_id)
    state = bridge.run(_STYLE, {"sequence": ctx["id"], "kind": entry["kind"], "id": overlay_id,
                                "style": _style(style)})
    entry["style"] = (entry.get("style") or {}) | style
    return _record(ctx, data, entry, state, reanchor=False)


def replace(overlay_id: str, file: str | None = None, keep_end: bool = False,
            sequence: str | None = None) -> dict:
    """Swap in a new render. Same path (re-rendered in place) or a new file;
    the overlay keeps its id, start, lane style and anchor. Its end follows the
    new render's length unless ``keep_end``."""
    ctx, data, entry = _entry(sequence, overlay_id)
    zero = int(ctx["zero"])
    new_file = file or entry["file"]
    remove(overlay_id, sequence=ctx["id"], forget=False)
    return place(new_file, _sec(int(entry["start_ticks"]), zero),
                 _sec(int(entry["end_ticks"]), zero) if keep_end else None,
                 kind=entry["kind"], label=entry["label"], style=entry.get("style"),
                 media_in=entry.get("media_in", 0.0), sequence=ctx["id"],
                 overlay_id=overlay_id, refresh=True)


_REMOVE = r"""
var seq = SK.sequence(ARGS.sequence);
var found = SK.findTagged(seq, ARGS.kind, ARGS.id);
if (!found) return false;
found.clip.remove(false, true);
return true;
"""


def remove(overlay_id: str, sequence: str | None = None, forget: bool = True) -> dict:
    """Take an overlay off the timeline (no ripple)."""
    ctx = _context(sequence)
    data = _load(ctx["project"])
    seq_entry = _seq_entry(data, ctx)
    entry = seq_entry["overlays"].get(overlay_id)
    if entry is None:
        raise OverlayError(f"No overlay {overlay_id} on {ctx['name']}")
    was_there = bridge.run(_REMOVE, {"sequence": ctx["id"], "kind": entry["kind"], "id": overlay_id})
    if forget:
        del seq_entry["overlays"][overlay_id]
        _store(ctx["project"], data)
    return {"removed": overlay_id, "was_on_timeline": was_there}


# --- reading back and re-syncing ------------------------------------------------------

def list_overlays(sequence: str | None = None) -> dict:
    """The manifest checked against the timeline: where each overlay is now,
    whether it moved, and tagged clips the manifest doesn't know."""
    ctx = _context(sequence)
    zero = int(ctx["zero"])
    data = _load(ctx["project"])
    seq_entry = _seq_entry(data, ctx)
    live = _live(ctx["id"])
    rows = []
    for oid, entry in sorted(seq_entry["overlays"].items()):
        lv = live.get(oid)
        row = {k: entry[k] for k in ("id", "kind", "label", "lane", "start", "end")}
        row["file"] = Path(entry["file"]).name
        if lv is None:
            row["status"] = "missing"
        elif lv["start_ticks"] != entry["start_ticks"] or lv["end_ticks"] != entry["end_ticks"]:
            row["status"] = "changed_on_timeline"
            row["now"] = {"start": _sec(lv["start_ticks"], zero), "end": _sec(lv["end_ticks"], zero),
                          "track": lv["track_name"]}
        else:
            row["status"] = "ok"
        rows.append(row)
    unknown = sorted(set(live) - set(seq_entry["overlays"]))
    return {"sequence": ctx["name"], "overlays": rows, "untracked_tags": unknown}


def resync(sequence: str | None = None, apply: bool = True) -> dict:
    """After the user re-trims: put each overlay back on the moment it was
    anchored to. Overlays whose moment was cut are reported, never deleted.

    An overlay the user trimmed by hand (its length changed) is re-anchored
    where it is, on the assumption the user placed it deliberately."""
    ctx = _context(sequence, cuts=True)
    frame, zero = int(ctx["frame"]), int(ctx["zero"])
    data = _load(ctx["project"])
    seq_entry = _seq_entry(data, ctx)
    live = _live(ctx["id"])
    segs = anchors.segments(ctx["cuts"])
    report = []
    for oid, entry in sorted(seq_entry["overlays"].items()):
        lv = live.get(oid)
        if lv is None:
            report.append({"id": oid, "status": "missing"})
            continue
        s, e = int(lv["start_ticks"]), int(lv["end_ticks"])
        if e - s != int(entry["end_ticks"]) - int(entry["start_ticks"]):
            entry["anchor"] = anchors.anchor(segs, s, e, frame)
            entry.update(start_ticks=lv["start_ticks"], end_ticks=lv["end_ticks"],
                         start=_sec(s, zero), end=_sec(e, zero))
            report.append({"id": oid, "status": "user_trimmed", "reanchored_at": _sec(s, zero)})
            continue
        if not entry.get("anchor"):
            report.append({"id": oid, "status": "unanchored"})
            continue
        where = anchors.relocate(segs, entry["anchor"], s, e, frame)
        row = {"id": oid, "status": where["status"], "was": _sec(s, zero)}
        if where["start"] is not None:
            row["now"] = _sec(where["start"], zero)
        if apply and where["start"] is not None and where["start"] != s:
            try:
                state = bridge.run(_MOVE, {"sequence": ctx["id"], "kind": entry["kind"], "id": oid,
                                           "start": where["start"]})
                entry.update(start_ticks=state["start_ticks"], end_ticks=state["end_ticks"],
                             start=_sec(state["start_ticks"], zero), end=_sec(state["end_ticks"], zero))
                row["applied"] = True
            except bridge.BridgeError as exc:
                row["applied"] = False
                row["error"] = str(exc)
        elif lv["start_ticks"] != entry["start_ticks"]:
            # Already where it belongs (a ripple carried it there): record that.
            entry.update(start_ticks=lv["start_ticks"], end_ticks=lv["end_ticks"],
                         start=_sec(s, zero), end=_sec(e, zero))
        report.append(row)
    _store(ctx["project"], data)
    return {"sequence": ctx["name"], "overlays": report}
