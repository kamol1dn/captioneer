"""Native graphics: a Motion Graphics Template (.mogrt) placed on a lane with
its text controls filled in, instead of a rendered file.

Only After Effects-authored templates can be filled by script: their MGT
component exposes each text control as a JSON string whose ``textEditValue``
is the visible text (the rest is styling, kept). A graphic built inside
Premiere has no such component and its text is a blob scripting can't write
(writing a plain string blanks it), so those are left to the user.

Placed templates are recorded in overlays.json like renders (kind "mgt"), so
resync/list/move/remove work on them too.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import anchors, bridge, overlays

_PLACE = r"""
var v = SK.activate(ARGS.sequence), seq = v.seq, qs = v.qs;
var f = SK.frameTicks(seq);
var lane = SK.pickLane(seq, qs, 'video', ARGS.start, ARGS.end, ARGS.lane);
var track = seq.videoTracks[lane];
var item = seq.importMGT(ARGS.mogrt, SK.timeFromTicks(ARGS.start), lane, 0);
if (!item) throw new Error('importMGT failed for ' + ARGS.mogrt);
// It arrives at the template's own length; trim to the asked span.
if (Number(item.end.ticks) !== ARGS.end) item.end = SK.timeFromTicks(ARGS.end);
item.name = ARGS.tag;
var mgt = item.getMGTComponent();
var report = [];
if (!mgt) {
    item.remove(false, true);
    throw new Error('This template has no MGT component (built in Premiere, not After Effects); its text cannot be set by script');
}
function setText(name, plain, encoded) {
    var prop = SK.param(mgt, name);
    if (!prop) { report.push({control: name, missing: true}); return; }
    var before = SK.call(function () { return prop.getValue(); }, null);
    var next = plain;
    if (typeof before === 'string' && /"textEditValue"\s*:\s*"/.test(before)) {
        next = before.replace(/"textEditValue"\s*:\s*"(?:[^"\\]|\\.)*"/, function () { return '"textEditValue":' + encoded; });
    } else if (typeof before === 'string' && before.charAt(0) !== '{') {
        report.push({control: name, warning: 'not a text control; set as plain value'});
    }
    var ok = SK.call(function () { return prop.setValue(next, true); }, false);
    var after = SK.call(function () { return String(prop.getValue()); }, '');
    report.push({control: name, ok: String(ok), now: after.indexOf(encoded) !== -1 || after === plain});
}
for (var k in ARGS.texts) if (ARGS.texts.hasOwnProperty(k)) setText(k, ARGS.texts[k], ARGS.encoded[k]);
var controls = [];
for (var p = 0; p < mgt.properties.numItems; p++) controls.push(mgt.properties[p].displayName);
var state = SK.clipState(seq, item, lane);
state.track_name = track.name;
state.report = report;
state.controls = controls;
return state;
"""

_CONTROLS = r"""
var v = SK.activate(ARGS.sequence), seq = v.seq;
var vt = seq.videoTracks.numTracks - 1;
var item = seq.importMGT(ARGS.mogrt, SK.timeFromTicks(SK.ticksAt(seq, ARGS.at)), vt, 0);
if (!item) throw new Error('importMGT failed');
var mgt = item.getMGTComponent();
var out = {ae_authored: !!mgt, controls: []};
if (mgt) for (var p = 0; p < mgt.properties.numItems; p++) {
    var pr = mgt.properties[p];
    var val = SK.call(function () { return String(pr.getValue()); }, '');
    var m = /"textEditValue"\s*:\s*"((?:[^"\\]|\\.)*)"/.exec(val);
    out.controls.push({name: pr.displayName, text: m ? m[1] : null, kind: m ? 'text' : (val.charAt(0) === '{' ? 'json' : typeof pr.getValue())});
}
item.remove(false, true);
return out;
"""


def controls(mogrt: str, sequence: str | None = None, at: float = 0.0) -> dict:
    """What a template offers: whether scripting can fill it, and its controls.
    Imports it for a moment on the top track and removes it again."""
    path = Path(mogrt)
    if not path.exists():
        raise overlays.OverlayError(f"No such template: {path}")
    return bridge.run(_CONTROLS, {"sequence": sequence, "mogrt": str(path), "at": at}, timeout=120)


def place(mogrt: str, start: float, seconds: float, texts: dict | None = None, *, lane: str | int | None = None,
          label: str = "", sequence: str | None = None, overlay_id: str | None = None) -> dict:
    path = Path(mogrt)
    if not path.exists():
        raise overlays.OverlayError(f"No such template: {path}")
    texts = texts or {}
    ctx = overlays._context(sequence, cuts=True)
    frame, zero = int(ctx["frame"]), int(ctx["zero"])
    s = overlays._snap(start, frame, zero)
    e = overlays._snap(start + seconds, frame, zero)
    data = overlays._load(ctx["project"])
    seq_entry = overlays._seq_entry(data, ctx)
    oid = overlay_id or overlays._new_id(seq_entry, "video")
    tag = f"SKL {oid}" + (f" {label}" if label else "")
    state = bridge.run(_PLACE, {
        "sequence": ctx["id"], "mogrt": str(path), "start": s, "end": e, "lane": lane, "tag": tag,
        "texts": texts, "encoded": {k: json.dumps(v, ensure_ascii=False) for k, v in texts.items()},
    }, timeout=120)
    segs = anchors.segments(ctx["cuts"])
    entry = {
        "id": oid, "kind": "video", "mgt": True, "label": label, "file": str(path), "texts": texts,
        "lane": state["track_name"],
        "start": overlays._sec(state["start_ticks"], zero), "end": overlays._sec(state["end_ticks"], zero),
        "start_ticks": state["start_ticks"], "end_ticks": state["end_ticks"],
        "media_in": 0.0, "style": None,
        "anchor": anchors.anchor(segs, int(state["start_ticks"]), int(state["end_ticks"]), frame),
        "placed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    seq_entry["overlays"][oid] = entry
    overlays._store(ctx["project"], data)
    return entry | {"report": state["report"], "controls": state["controls"]}
