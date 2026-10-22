"""Baked overlays: a card rendered over the program footage itself.

Glass and blur need the pixels under them, so, as the editor does with an AE
comp over a duplicate of the clip, Skleyka exports the program span from
Premiere (its own lanes muted), renders the card with that span as the
bottom layer, and places the opaque result on the camera's lane ("SKL
<camera>") over the cut, where the editor's grade for that angle applies.

The result goes stale if the cut under it changes. Each baked overlay
records the multicam cuts it was made over (angle and source time); ``stale``
compares them with the timeline now, and ``rebake`` redoes one.
"""
from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path

from . import audio, bridge, overlays, render, timeline

PRESET = Path(r"C:\Program Files\Adobe\Adobe Premiere Pro 2025\MediaIO\systempresets\3F3F3F3F_4D6F6F56\01 - Match Source.epr")


def baked_templates() -> tuple[str, ...]:
    """Templates rendered over the footage: graphics/templates.json entries
    with "placement": "baked", read fresh, so a new glass template needs no
    restart of this server."""
    return tuple(k for k, v in render.cg.manifest().items() if v.get("placement") == "baked")


def across_cuts() -> tuple[str, ...]:
    """Baked cards that run across camera cuts ("across_cuts": true; the blitz
    strips span a run of quick answers, cut as the editor cut it): no clamp
    to the shot, the frost is the program span as cut, and they sit on their
    own lane, "SKL glass"."""
    return tuple(k for k, v in render.cg.manifest().items() if v.get("placement") == "baked" and v.get("across_cuts"))

_EXPORT = r"""
var v = SK.activate(ARGS.sequence), seq = v.seq;
var keepIn = SK.call(function () { return seq.getInPointAsTime().seconds; }, null);
var keepOut = SK.call(function () { return seq.getOutPointAsTime().seconds; }, null);
var muted = [];
for (var t = 0; t < seq.videoTracks.numTracks; t++) {
    var tr = seq.videoTracks[t];
    if (SK.isLane(tr) && !tr.isMuted()) { tr.setMute(1); muted.push(t); }
}
var result, error = null;
try {
    seq.setInPoint(ARGS.start);
    seq.setOutPoint(ARGS.end);
    result = String(seq.exportAsMediaDirect(ARGS.out, ARGS.preset, app.encoder.ENCODE_IN_TO_OUT));
} catch (e) { error = String(e); }
for (var m = 0; m < muted.length; m++) seq.videoTracks[muted[m]].setMute(0);
if (keepIn !== null) seq.setInPoint(keepIn);
if (keepOut !== null) seq.setOutPoint(keepOut);
if (error) throw new Error(error);
return {result: result, exists: new File(ARGS.out).exists};
"""


class BakeError(RuntimeError):
    pass


def export_span(project_path: str, sequence_id: str, start: float, end: float) -> Path:
    """The program picture for [start, end), without Skleyka's lanes, as a
    QuickTime matching the sequence (Premiere's 'Match Source')."""
    d = render.renders_dir(project_path) / "spans"
    d.mkdir(exist_ok=True)
    out = d / f"span_{int(round(start * 1000)):09d}_{int(round(end * 1000)):09d}.mov"
    r = bridge.run(_EXPORT, {"sequence": sequence_id, "start": start, "end": end, "out": str(out),
                             "preset": str(PRESET)}, timeout=600)
    if r.get("result") != "No Error" or not out.exists():
        raise BakeError(f"export failed: {r}")
    return out


def stage_video(project_path: str, path: Path) -> str:
    """The span as H.264 in the episode's public dir, under spans/ (Premiere's
    Match Source export is CineForm 10-bit, which the renderer's browser
    cannot play); returns the staticFile path."""
    staged = render.public_dir(project_path) / "spans"
    staged.mkdir(parents=True, exist_ok=True)
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:16]
    dst = staged / f"{key}.mp4"
    if not dst.exists():
        # Left untagged on purpose: tagging it bt709/tv made the renderer decode
        # it darker than Premiere shows it (measured on behzod tahlil 2:29).
        subprocess.run([str(audio.FFMPEG), "-v", "error", "-y", "-i", str(path), "-an", "-c:v", "libx264", "-preset", "fast",
                        "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)],
                       check=True, stdin=subprocess.DEVNULL)
    return f"spans/{dst.name}"


def _cuts_under(tl: dict, start: float, end: float) -> list[dict]:
    return [{"angle": s["angle"], "in": round(s["in_point"] + max(0.0, start - s["start"]), 3),
             "from": round(max(start, s["start"]), 3), "to": round(min(end, s["end"]), 3)}
            for s in timeline.program(tl) if s["start"] < end and s["end"] > start]


def bake(template: str, props: dict, start: float, seconds: float, *, label: str = "",
         sequence: str | None = None, overlay_id: str | None = None, whoosh: bool = True) -> dict:
    """Export the span, render ``template`` over it, place it on the camera's lane,
    with the editor's whoosh as the card comes in."""
    baked, crossing = baked_templates(), across_cuts()
    if template not in baked:
        raise BakeError(f"{template} is not a baked template; one of {baked}")
    tl = timeline.read(sequence, save=False)
    seq = tl["sequence"]
    # On whole frames: the renderer refuses a span a fraction of a frame off.
    fps = seq["fps"]
    start, seconds = round(start * fps) / fps, round(seconds * fps) / fps
    end = start + seconds
    shots = timeline.program(tl)
    i = next((k for k, s in enumerate(shots) if s["start"] <= start < s["end"]), None)
    if i is None:
        raise BakeError(f"No multicam cut at {start:.3f}s")
    shot = shots[i]
    # A same-angle through edit (join "same", left behind by an angle switch)
    # is no cut on screen: the shot runs on across it.
    shot_end = shot["end"]
    for s in shots[i + 1:]:
        if s.get("join") != "same" or s["angle"] != shot["angle"]:
            break
        shot_end = s["end"]
    clamped = None
    # A baked card carries one camera's footage and sits on that camera's
    # lane, so it must not run past the shot into another angle.
    if template not in crossing and end > shot_end + 1e-6:
        clamped = {"asked_end": round(end, 3), "cut_ends": round(shot_end, 3)}
        end = shot_end
        if end - start < 1.0:
            raise BakeError(f"The cut at {start:.3f}s ends at {shot_end:.3f}s, too soon for a card; "
                            "start it later or pick another moment")
        seconds = end - start
    span = export_span(tl["project_path"], seq["sequence_id"], start, end)
    cuts = _cuts_under(tl, start, end)
    camera = "glass" if template in crossing else (shot["camera"] or "mixed")
    # Card only, with alpha (ProRes 4444): the footage is used for the frost
    # alone, and the picture around the card stays the live cut. An opaque H.264
    # bake of the whole frame drifted from the cut (crushed blacks, +3%
    # saturation, from the browser's video decode) and hid any later grade.
    props = dict(props) | {"footage": stage_video(tl["project_path"], span), "cardOnly": True}
    out = render.render(tl["project_path"], template, props, seq["width"], seq["height"], seconds, fps=seq["fps"],
                        name=label or template.lower())
    entry = overlays.place(out["file"], start, end, kind="video", lane=camera, label=label,
                           style={"position": [0.5, 0.5], "scale": 100}, sequence=seq["sequence_id"],
                           overlay_id=overlay_id)
    data = overlays._load(tl["project_path"])
    rec = data["sequences"][seq["sequence_id"]]["overlays"][entry["id"]]
    rec["baked"] = {"template": template, "props": {k: v for k, v in props.items() if k != "footage"},
                    "cuts": cuts, "span": str(span)}
    overlays._store(tl["project_path"], data)
    sound = None
    if whoosh:
        from . import fx
        sound = fx.whoosh(entry["start"], label=label, sequence=seq["sequence_id"])["id"]
    return rec | {"still": out["still"], "clamped_to_cut": clamped, "whoosh": sound}


def stale(sequence: str | None = None) -> list[dict]:
    """Baked overlays whose cuts underneath no longer match the timeline."""
    tl = timeline.read(sequence, save=False)
    data = overlays._load(tl["project_path"])
    entry = data["sequences"].get(tl["sequence"]["sequence_id"], {"overlays": {}})
    out = []
    for oid, rec in entry["overlays"].items():
        if not rec.get("baked"):
            continue
        now = _cuts_under(tl, rec["start"], rec["end"])
        if now != rec["baked"]["cuts"]:
            out.append({"id": oid, "label": rec.get("label"), "start": rec["start"], "end": rec["end"],
                        "was": rec["baked"]["cuts"], "now": now})
    return out


def rebake(overlay_id: str, sequence: str | None = None) -> dict:
    tl = timeline.read(sequence, save=False)
    data = overlays._load(tl["project_path"])
    rec = data["sequences"][tl["sequence"]["sequence_id"]]["overlays"].get(overlay_id)
    if not rec or not rec.get("baked"):
        raise BakeError(f"{overlay_id} is not a baked overlay")
    overlays.remove(overlay_id, sequence=tl["sequence"]["sequence_id"], forget=False)
    return bake(rec["baked"]["template"], rec["baked"]["props"], rec["start"], rec["end"] - rec["start"],
                label=rec.get("label", ""), sequence=tl["sequence"]["sequence_id"], overlay_id=overlay_id,
                whoosh=False)
