"""Claude's eyes on the program: export the composited frame at a time.

QE exportFramePNG writes the full-resolution frame (4K PNG, ~5 MB). It takes a
timecode in the sequence's display format and a backslash path without an
extension (it appends .png; a dot in the name truncates it). The PNG is
turned into a smaller JPEG for viewing and then deleted.
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from . import bridge, timeline

_EXPORT = r"""
var v = SK.activate(ARGS.sequence), seq = v.seq, qs = v.qs;
var t = SK.ticksAt(seq, ARGS.at);
var code = SK.timecode(seq, t);
return {ok: String(qs.exportFramePNG(code, ARGS.base)), timecode: code,
        at: SK.secondsAt(seq, t), project: app.project.path};
"""


def grab(at: float, sequence: str | None = None, width: int = 1600) -> dict:
    project = bridge.run("return app.project.path;")
    out_dir = timeline.workdir(project) / "frames"
    out_dir.mkdir(exist_ok=True)
    stem = f"frame_{int(round(at * 1000)):09d}"
    base = out_dir / stem
    png = base.with_name(stem + ".png")
    png.unlink(missing_ok=True)
    r = bridge.run(_EXPORT, {"sequence": sequence, "at": at, "base": str(base)}, timeout=60)
    if r["ok"] != "true":
        raise bridge.BridgeError(f"exportFramePNG returned {r['ok']}")
    last = -1
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if png.exists():
            size = png.stat().st_size
            if size > 0 and size == last:
                break
            last = size
        time.sleep(0.15)
    else:
        raise bridge.BridgeError(f"Premiere did not write {png}")
    jpg = png.with_suffix(".jpg")
    with Image.open(png) as im:
        full = im.size
        im = im.convert("RGB")
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        im.save(jpg, quality=88)
    png.unlink(missing_ok=True)
    return {"path": str(jpg), "timecode": r["timecode"], "at": round(r["at"], 6),
            "full_size": list(full)}
