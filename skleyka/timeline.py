"""The edit as Claude sees it: every cut, which camera is on screen, and where.

The live bridge gives the clips on each track, and the multicam source
sequences behind them. The saved .prproj gives the angle of each multicam cut
(see prproj.py). Joined, each cut resolves to a camera file and a time in that
file, which is what face tracking, framing and graphics placement work from.

All times leave this module in seconds (sequence time, zero-based), with the
original ticks kept alongside for exact round trips back into Premiere.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import bridge, prproj

TICKS = 254016000000

_READ = r"""
if (ARGS.save) app.project.save();
var seq = SK.sequence(ARGS.sequence);
var info = SK.sequenceInfo(seq, true, true);
var sources = {};
for (var t = 0; t < info.video.length; t++) {
    var clips = info.video[t].clips;
    for (var c = 0; c < clips.length; c++) {
        var id = clips[c].project_item;
        if (!clips[c].multicam || !id || sources[id]) continue;
        var src = SK.sequenceForItem(id);
        sources[id] = src ? SK.sequenceInfo(src, false, true) : null;
    }
}
// Angles can be nested sequences (a punch-in on the wide, say); fetch those
// too, and whatever they nest, so every angle resolves to a camera file.
var pending = [];
for (var k in sources) if (sources[k]) pending.push(sources[k]);
while (pending.length) {
    var s = pending.pop();
    for (var vt = 0; vt < s.video.length; vt++) {
        for (var vc = 0; vc < s.video[vt].clips.length; vc++) {
            var clip = s.video[vt].clips[vc];
            if (!clip.is_sequence || !clip.project_item || sources[clip.project_item] !== undefined) continue;
            var nested = SK.sequenceForItem(clip.project_item);
            sources[clip.project_item] = nested ? SK.sequenceInfo(nested, false, true) : null;
            if (nested) pending.push(sources[clip.project_item]);
        }
    }
}
return {project_path: app.project.path, sequence: info, multicam_sources: sources};
"""

# Parsing a large .prproj takes a couple of seconds; reuse it until it changes.
_prproj_cache: dict[str, tuple[float, dict]] = {}


def cuts_from_project(project_path: str) -> dict:
    mtime = Path(project_path).stat().st_mtime
    hit = _prproj_cache.get(project_path)
    if hit and hit[0] == mtime:
        return hit[1]
    cuts = prproj.multicam_cuts(prproj.load_root(project_path))
    _prproj_cache[project_path] = (mtime, cuts)
    return cuts


def _sec(ticks) -> float | None:
    return None if ticks is None else round(int(ticks) / TICKS, 6)


def _clip_at(track: dict, t: int) -> dict | None:
    for clip in track["clips"]:
        if int(clip["start"]) <= t < int(clip["end"]):
            return clip
    return None


def _layers(clip: dict, at: int, sources: dict, via: list[str]) -> list[dict]:
    """Every camera layer a clip shows at a time in its sequence, bottom first.

    A plain clip is one layer. A nested sequence (a punch-in, a split screen)
    is all of its enabled clips at that time, each with its own Motion, so a
    split screen comes back as two cameras with their position, scale and crop.
    Each layer's Motion is its own inside the nest; the Motion of the angle
    clip itself, on the multicam source track, is reported as ``angle_motion``.
    """
    media = int(clip["in_point"]) + at - int(clip["start"])
    if not clip.get("is_sequence"):
        return [{
            "name": clip["name"],
            "media_path": clip["media_path"],
            "media_time": _sec(media),
            "motion": clip.get("motion"),
            "via": via,
        }]
    nested = sources.get(clip["project_item"])
    if not nested or len(via) >= 8:
        return [{"name": clip["name"], "media_path": None, "media_time": None,
                 "motion": clip.get("motion"), "via": via, "unresolved": True}]
    layers = []
    for track in nested["video"]:
        inner = _clip_at(track, media)
        if inner is not None and not inner.get("disabled"):
            layers += _layers(inner, media, sources, via + [clip["name"]])
    for layer in layers:
        layer.setdefault("frame", {"width": nested["width"], "height": nested["height"]})
    return layers


def _angle_source(source: dict | None, angle: int, at: int, sources: dict) -> dict:
    """Camera layers for one angle at a multicam-sequence time.

    ``media_path``/``media_time`` are set only when the angle is a single
    camera; composites (split screens) leave them None and list ``layers``.
    """
    if source is None or angle >= len(source["video"]):
        return {"camera": None, "media_path": None, "media_time": None, "layers": [], "angle_motion": None}
    track = source["video"][angle]
    clip = _clip_at(track, at)
    if clip is None:
        return {"camera": track["name"], "media_path": None, "media_time": None, "layers": [],
                "angle_motion": None}
    layers = _layers(clip, at, sources, [])
    single = layers[0] if len(layers) == 1 else None
    return {
        "camera": clip["name"],
        "media_path": single["media_path"] if single else None,
        "media_time": single["media_time"] if single else None,
        "layers": layers,
        "angle_motion": clip.get("motion"),
    }


def workdir(project_path: str) -> Path:
    d = Path(project_path).parent / "skleyka"
    d.mkdir(exist_ok=True)
    return d


def read(sequence: str | None = None, save: bool = True) -> dict:
    """Read the active (or named) sequence and resolve every multicam cut."""
    raw = bridge.run(_READ, {"sequence": sequence, "save": save}, timeout=120)
    project_path = raw["project_path"]
    seq = raw["sequence"]
    sources = raw["multicam_sources"]
    # A cut the saved file doesn't know (unsaved edit) is counted, not guessed.
    cuts = cuts_from_project(project_path)

    zero = int(seq["zero_point"])
    frame = int(seq["frame_ticks"])
    unresolved = 0
    tracks = []
    for track in seq["video"]:
        clips = []
        for clip in track["clips"]:
            out = {
                "index": clip["index"],
                "name": clip["name"],
                "start": _sec(int(clip["start"]) - zero),
                "end": _sec(int(clip["end"]) - zero),
                "in_point": _sec(clip["in_point"]),
                "out_point": _sec(clip["out_point"]),
                "start_ticks": clip["start"],
                "end_ticks": clip["end"],
                "disabled": clip["disabled"],
                "speed": clip["speed"],
                "media_path": clip["media_path"],
                "node_id": clip["node_id"],
                "motion": clip.get("motion"),
            }
            if clip["multicam"]:
                cut = cuts.get((seq["sequence_id"], track["index"], int(clip["start"])))
                if cut is None:
                    unresolved += 1
                    out.update(angle=None, camera=None, media_path=None, media_time=None,
                               layers=[], angle_motion=None)
                else:
                    out["angle"] = cut.angle
                    out.update(_angle_source(sources.get(clip["project_item"]), cut.angle,
                                             int(clip["in_point"]), sources))
            clips.append(out)
        tracks.append({k: track[k] for k in ("index", "name", "muted", "locked")} | {"clips": clips})

    audio = [
        {k: t[k] for k in ("index", "name", "muted", "locked")}
        | {"clips": [{
            "name": c["name"],
            "start": _sec(int(c["start"]) - zero),
            "end": _sec(int(c["end"]) - zero),
            "in_point": _sec(c["in_point"]),
            "media_path": c["media_path"],
        } for c in t["clips"]]}
        for t in seq["audio"]
    ]

    multicam_items = {c["project_item"] for t in seq["video"] for c in t["clips"] if c["multicam"]}
    angles = {}
    for item in multicam_items:
        src = sources.get(item)
        if src:
            angles[src["name"]] = [
                {"angle": t["index"], "name": t["name"],
                 "files": sorted({c["media_path"] for c in t["clips"] if c["media_path"]}),
                 "nested_sequences": sorted({c["name"] for c in t["clips"] if c.get("is_sequence")})}
                for t in src["video"] if t["clips"]
            ]

    return {
        "project_path": project_path,
        "read_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sequence": {
            "name": seq["name"],
            "sequence_id": seq["sequence_id"],
            "width": seq["width"],
            "height": seq["height"],
            "fps": round(TICKS / frame, 4),
            "frame_ticks": frame,
            "zero_point_ticks": zero,
            "duration": _sec(int(seq["end"]) - zero),
            "playhead": _sec(int(seq["playhead"]) - zero),
        },
        "multicam_angles": angles,
        "unresolved_multicam_cuts": unresolved,
        "video": tracks,
        "audio": audio,
        "markers": [
            m | {"start": _sec(int(m["start"]) - zero), "end": _sec(int(m["end"]) - zero)}
            for m in seq["markers"]
        ],
    }


def program(timeline: dict) -> list[dict]:
    """What is on screen, cut by cut: the topmost enabled multicam clip wins."""
    shots = []
    for track in reversed(timeline["video"]):
        for clip in track["clips"]:
            if "angle" in clip and not clip["disabled"]:
                shots.append({"track": track["index"]} | {k: clip[k] for k in (
                    "start", "end", "in_point", "out_point", "angle", "camera",
                    "media_path", "media_time", "layers", "angle_motion", "motion")})
    shots.sort(key=lambda s: (s["start"], -s["track"]))
    flat: list[dict] = []
    for s in shots:
        if flat and s["start"] < flat[-1]["end"] and s["track"] < flat[-1]["track"]:
            continue  # covered by a higher track
        flat.append(s)
    return mark_joins(flat)


def mark_joins(shots: list[dict], tolerance: float = 0.02) -> list[dict]:
    """Label each cut by how it joins the previous one.

    ``switch``: source time runs on, only the angle changes. ``trim``: source
    time jumps (material was cut out) and the angle changes, which hides it.
    ``jump``: source time jumps on the same angle, a visible jump cut. Moving
    an angle switch (e.g. to give a graphic more time) must not turn a trim
    into a jump.
    """
    for prev, shot in zip([None] + shots, shots):
        if prev is None or abs(shot["start"] - prev["end"]) > tolerance:
            shot["join"] = None
            continue
        continuous = abs(shot["in_point"] - prev["out_point"]) <= tolerance
        if continuous:
            shot["join"] = "same" if shot["angle"] == prev["angle"] else "switch"
        else:
            shot["join"] = "jump" if shot["angle"] == prev["angle"] else "trim"
    return shots


def save(timeline: dict) -> Path:
    name = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in timeline["sequence"]["name"])
    path = workdir(timeline["project_path"]) / f"timeline_{name}.json"
    path.write_text(json.dumps(timeline | {"program": program(timeline)}, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def summary(timeline: dict, path: Path) -> dict:
    prog = program(timeline)
    usage: dict = {}
    for s in prog:
        key = f"{s['angle']}: {s['camera']}"
        usage[key] = round(usage.get(key, 0) + s["end"] - s["start"], 1)
    return {
        "saved_to": str(path),
        "sequence": timeline["sequence"],
        "tracks": {
            "video": [f"V{t['index'] + 1} {t['name']}: {len(t['clips'])} clips" for t in timeline["video"]],
            "audio": [f"A{t['index'] + 1} {t['name']}: {len(t['clips'])} clips" for t in timeline["audio"]],
        },
        "multicam_angles": timeline["multicam_angles"],
        "multicam_cuts": len(prog),
        "joins": {j: sum(1 for s in prog if s["join"] == j) for j in ("switch", "trim", "jump", "same")},
        "jump_cuts_at_s": [s["start"] for s in prog if s["join"] == "jump"][:20],
        "unresolved_multicam_cuts": timeline["unresolved_multicam_cuts"],
        "screen_time_by_angle_s": usage,
        "markers": len(timeline["markers"]),
        "first_cuts": prog[:5],
    }
