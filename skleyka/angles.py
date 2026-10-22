"""Changing which camera is on screen, without breaking the edit.

Three operations, all on the multicam edit track:

- ``set_angle``: a cut shows another angle (QE multicam.changeCamera with the
  playhead on the cut's first frame, as pressing a camera number does).
- ``set_angle(..., whole_cut=False)``: switch from a frame to the end of that
  cut (the same call with the playhead mid-cut splits there).
- ``move_switch``: roll an existing switch point some frames, e.g. so a
  graphic gets more time on the current shot. Only for ``switch`` joins: at a
  ``trim`` join, rolling would change what is said.

The guard: a ``trim`` join (material cut out, hidden by an angle change) must
keep different angles on its two sides, or it becomes a visible jump cut.
Angle changes that would do that are refused unless ``force``.
"""
from __future__ import annotations

from . import bridge, timeline

TICKS = 254016000000
DISCONTINUOUS = ("trim", "jump")


class AngleError(RuntimeError):
    pass


_LIGHT = r"""
if (ARGS.save) app.project.save();
var seq = SK.sequence(ARGS.sequence);
var angles = 0;
for (var t = 0; t < seq.videoTracks.numTracks && !angles; t++) {
    var track = seq.videoTracks[t];
    for (var i = 0; i < track.clips.numItems; i++) {
        var item = track.clips[i].projectItem;
        if (item && SK.call(function () { return item.isMulticamClip(); }, false)) {
            var src = SK.sequenceForItem(item.nodeId);
            if (src) for (var a = 0; a < src.videoTracks.numTracks; a++) if (src.videoTracks[a].clips.numItems) angles = a + 1;
            break;
        }
    }
}
return {project: app.project.path, id: seq.sequenceID, name: seq.name, frame: String(seq.timebase),
        zero: String(seq.zeroPoint), angles: angles, cuts: SK.programCuts(seq)};
"""


def _program(sequence: str | None, save: bool) -> tuple[dict, list[dict]]:
    """The multicam cuts with their angles: positions live (fast, ~1 s), angles
    from the saved project file. read_timeline has the full picture; this is
    the part angle changes need."""
    raw = bridge.run(_LIGHT, {"sequence": sequence, "save": save}, timeout=60)
    saved = timeline.cuts_from_project(raw["project"])
    zero = int(raw["zero"])
    shots = []
    for track, start, end, src_in, src_out, disabled in raw["cuts"]:
        if disabled:
            continue
        cut = saved.get((raw["id"], int(track), int(start)))
        shots.append({
            "track": int(track),
            "start": (int(start) - zero) / TICKS,
            "end": (int(end) - zero) / TICKS,
            "in_point": int(src_in) / TICKS,
            "out_point": int(src_out) / TICKS,
            "start_ticks": start,
            "angle": cut.angle if cut else None,
        })
    if not shots:
        raise AngleError("No multicam clips on this sequence")
    tracks = {s["track"] for s in shots}
    if len(tracks) > 1:
        raise AngleError(f"Multicam clips sit on several tracks ({sorted(t + 1 for t in tracks)}); "
                         "angle changes need them on one")
    shots.sort(key=lambda s: s["start"])
    info = {"sequence_id": raw["id"], "name": raw["name"], "frame_ticks": int(raw["frame"]),
            "zero_point_ticks": zero, "angles": raw["angles"]}
    return info, timeline.mark_joins(shots)


def _shot_at(prog: list[dict], at: float) -> int:
    for i, s in enumerate(prog):
        if s["start"] <= at < s["end"]:
            return i
    raise AngleError(f"No multicam cut at {at:.3f}s")


def jump_risks(prog: list[dict], i: int, angle: int, whole_cut: bool) -> list[str]:
    """Joins that would become jump cuts if cut ``i`` (or its tail) showed ``angle``."""
    risks = []
    if whole_cut and i > 0 and prog[i]["join"] in DISCONTINUOUS and prog[i - 1]["angle"] == angle:
        risks.append(f"{prog[i]['start']:.3f}s (trim against the previous cut, also angle {angle})")
    if i + 1 < len(prog) and prog[i + 1]["join"] in DISCONTINUOUS and prog[i + 1]["angle"] == angle:
        risks.append(f"{prog[i + 1]['start']:.3f}s (trim against the next cut, also angle {angle})")
    return risks


_CHANGE = r"""
var v = SK.activate(ARGS.sequence), seq = v.seq, qs = v.qs;
var keep = String(seq.getPlayerPosition().ticks);
var track = seq.videoTracks[ARGS.track];
var targeted = SK.call(function () { return track.isTargeted(); }, true);
if (!targeted) track.setTargeted(true, true);
var ok;
try {
    seq.setPlayerPosition(String(ARGS.at));
    ok = qs.multicam.changeCamera(ARGS.angle + 1);
} finally {
    seq.setPlayerPosition(keep);
    if (!targeted) track.setTargeted(false, true);
}
return String(ok);
"""


def _cut_view(s: dict) -> dict:
    return {"start": round(s["start"], 6), "end": round(s["end"], 6), "angle": s["angle"]}


def set_angle(at: float, angle: int, whole_cut: bool = True, force: bool = False,
              sequence: str | None = None) -> dict:
    """Show ``angle`` (0-based, as read_timeline numbers them) for the cut at
    ``at`` seconds, or from ``at`` to the end of that cut if not whole_cut.
    Saves the project (angles are read from the saved file) and verifies."""
    info, prog = _program(sequence, save=True)
    if not 0 <= angle < info["angles"]:
        raise AngleError(f"angle must be 0-{info['angles'] - 1}")
    i = _shot_at(prog, at)
    shot = prog[i]
    if shot["angle"] == angle:
        return {"changed": False, "reason": f"the cut at {shot['start']:.3f}s already shows angle {angle}"}
    frame, zero = info["frame_ticks"], info["zero_point_ticks"]
    at_ticks = round(at * TICKS / frame) * frame + zero
    if whole_cut or at_ticks <= int(shot["start_ticks"]):
        whole_cut = True
        at_ticks = int(shot["start_ticks"])
    risks = jump_risks(prog, i, angle, whole_cut)
    if risks and not force:
        raise AngleError("Would make a jump cut at " + "; ".join(risks) + ". Pick another angle, or force.")

    bridge.run(_CHANGE, {"sequence": info["sequence_id"], "track": shot["track"], "at": at_ticks,
                         "angle": angle}, timeout=60)

    _, after = _program(info["sequence_id"], save=True)
    # Half a frame in: the cut's own first frame, clear of float rounding.
    now = after[_shot_at(after, (at_ticks + frame / 2 - zero) / TICKS)]
    if now["angle"] != angle:
        raise AngleError(f"Premiere did not switch: the cut at {now['start']:.3f}s shows angle "
                         f"{now['angle']}. Is the sequence or its multicam track locked?")
    return {"changed": True, "cut": _cut_view(now), "was": _cut_view(shot),
            "jump_cuts_created": risks}


_ROLL = r"""
var v = SK.activate(ARGS.sequence), seq = v.seq, qs = v.qs;
var qt = qs.getVideoTrackAt(ARGS.track), item = null;
for (var i = 0; i < qt.numItems; i++) {
    var it = qt.getItemAt(i);
    if (it.type !== 'Empty' && String(it.start.ticks) === ARGS.boundary) { item = it; break; }
}
if (!item) throw new Error('no clip starts exactly at the switch point');
return String(item.roll(String(ARGS.frames), true, true));
"""


def move_switch(at: float, frames: int, sequence: str | None = None) -> dict:
    """Roll the switch point nearest ``at`` seconds by ``frames`` (positive =
    later: the earlier shot gets longer). Only plain switches can roll."""
    if frames == 0:
        return {"moved": False}
    # Rolling needs positions and source continuity, both live; no save.
    info, prog = _program(sequence, save=False)
    frame = info["frame_ticks"]
    joins = [k for k in range(1, len(prog)) if prog[k]["join"] is not None]
    if not joins:
        raise AngleError("No switch points")
    k = min(joins, key=lambda j: abs(prog[j]["start"] - at))
    left, right = prog[k - 1], prog[k]
    if abs(right["start"] - at) > 1.0:
        raise AngleError(f"No switch point within 1s of {at:.3f}s (nearest {right['start']:.3f}s)")
    if right["join"] in DISCONTINUOUS:
        raise AngleError(f"The cut at {right['start']:.3f}s hides a trim; rolling it would change what is "
                         "said. Move a plain switch, or change angles instead.")
    left_frames = round((left["end"] - left["start"]) * TICKS / frame)
    right_frames = round((right["end"] - right["start"]) * TICKS / frame)
    if not -left_frames < frames < right_frames:
        raise AngleError(f"Can roll between -{left_frames - 1} and +{right_frames - 1} frames here")
    ok = bridge.run(_ROLL, {"sequence": info["sequence_id"], "track": right["track"],
                            "boundary": right["start_ticks"], "frames": frames})
    if ok != "true":
        raise AngleError(f"Premiere refused the roll ({ok})")
    return {"moved": True, "switch_was": round(right["start"], 6),
            "switch_now": round(right["start"] + frames * frame / TICKS, 6),
            "left_angle": left["angle"], "right_angle": right["angle"]}
