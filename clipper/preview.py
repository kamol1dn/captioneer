"""Render a compiled clip with ffmpeg — a way to *watch* a cut before Premiere
ever sees it.

This is not the export path — Premiere still owns the final render — but it is
the fastest way to catch a bad decision. It's also the verification strategy
for the whole compiler: build synthetic multi-camera test footage with
``-f lavfi`` (distinct on-screen labels + tones per camera), cut it, and check
the burned-in labels land where the EDL says they should. See
``clipper/tests/test_preview.py``.

Deliberately approximate: b-roll placeholders render as a solid card (there's
no footage yet), and only one audio track is rendered (a full multitrack mix
belongs in Premiere, not a sanity-check preview).
"""
import subprocess
from pathlib import Path
from typing import Optional

from caption_engine.media import ffmpeg_bin

from .compile import CompiledClip


def render_preview(clip: CompiledClip, out_path, quality: str = "fast") -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tb = clip.timebase
    w, h = clip.frame_size
    fps = float(tb.fps)

    # The cut lives across the stacked angle tracks, not on any one of them:
    # take the enabled items in program order.
    v1 = clip.program_video()
    if not v1:
        raise ValueError(f"clip {clip.id!r} has no video to render")
    broll = clip.items_by_role("broll")
    audio = clip.program_audio()

    inputs, input_index = [], {}

    def _idx(path: str) -> int:
        if path not in input_index:
            input_index[path] = len(inputs)
            inputs.append(path)
        return input_index[path]

    for item in v1 + broll + audio:
        if item.path:
            _idx(item.path)

    filt = []
    for i, item in enumerate(v1):
        idx = _idx(item.path)
        s, e = item.in_ / fps, item.out / fps
        filt.append(
            f"[{idx}:v]trim=start={s:.6f}:end={e:.6f},setpts=PTS-STARTPTS,"
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}]"
        )
    concat_in = "".join(f"[v{i}]" for i in range(len(v1)))
    filt.append(f"{concat_in}concat=n={len(v1)}:v=1:a=0[vpic]")

    vout = "vpic"
    for j, b in enumerate(broll):
        idx = _idx(b.path)
        s, e = b.in_ / fps, b.out / fps
        start_t, end_t = b.start / fps, b.end / fps
        filt.append(
            f"[{idx}:v]trim=start={s:.6f}:end={e:.6f},setpts=PTS-STARTPTS+"
            f"{start_t:.6f}/TB,scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[br{j}]"
        )
        filt.append(
            f"[{vout}][br{j}]overlay=enable='between(t,{start_t:.6f},"
            f"{end_t:.6f})':eof_action=pass[vov{j}]"
        )
        vout = f"vov{j}"

    if audio:
        for i, item in enumerate(audio):
            idx = _idx(item.path)
            s, e = item.in_ / fps, item.out / fps
            filt.append(
                f"[{idx}:a]atrim=start={s:.6f}:end={e:.6f},"
                f"asetpts=PTS-STARTPTS[a{i}]"
            )
        aconcat_in = "".join(f"[a{i}]" for i in range(len(audio)))
        filt.append(f"{aconcat_in}concat=n={len(audio)}:v=0:a=1[aout]")
        amap = ["-map", "[aout]"]
    else:
        amap = ["-an"]

    preset = {"fast": "ultrafast", "final": "medium"}.get(quality, "ultrafast")
    cmd = [ffmpeg_bin("ffmpeg"), "-y", "-nostdin"]
    for path in inputs:
        cmd += ["-i", path]
    cmd += [
        "-filter_complex", ";".join(filt),
        "-map", f"[{vout}]", *amap,
        "-c:v", "libx264", "-preset", preset, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"preview render failed for clip {clip.id!r}:\n"
                          f"{proc.stderr[-3000:]}")
    return out
