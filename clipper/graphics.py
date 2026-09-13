"""Rendered graphics for the b-roll pass: Remotion templates -> alpha ProRes.

The templates live in ``graphics/`` at the repo root, a small Node project (see
``graphics/templates.json`` for the list). This module is the Python side of the
seam: it checks props against that list, stages any image a prop points at,
works out the exact size, rate and frame count the file has to have, hands a
batch to ``graphics/render.mjs``, and attaches what comes back to the b-roll
entry it was rendered for.

Why the frame count comes from here and not from the caller: an overlay that is
a frame longer than its b-roll entry is silently trimmed by Premiere, and one a
frame shorter leaves a single-frame flash of nothing at the end. The entry's
length on the program timeline is already defined — by the same
round-then-accumulate rule the compiler uses for picture — so it is computed,
never passed in.
"""
import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from caption_engine.media import ffmpeg_bin

from .captions import program_ranges
from .edl import BRoll, Clip, EDL
from .timebase import Timebase

GRAPHICS_DIR = Path(__file__).resolve().parent.parent / "graphics"
MANIFEST_PATH = GRAPHICS_DIR / "templates.json"
# Images a prop points at are copied here so the renderer can serve them —
# headless Chrome cannot read an arbitrary path off disk.
STAGED_DIR = GRAPHICS_DIR / "public" / "_assets"
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
_POSITIONS = ("top", "center", "bottom")


def manifest() -> Dict[str, dict]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["templates"]


def template_kind(template: str) -> str:
    """The b-roll kind a template's file belongs on: "overlay" or "footage"."""
    return "footage" if manifest()[template].get("frame") == "full" else "overlay"


def ensure_installed() -> None:
    if not (GRAPHICS_DIR / "node_modules" / "@remotion" / "renderer").exists():
        raise RuntimeError(
            f"the graphics renderer isn't installed — run `npm install` in "
            f"{GRAPHICS_DIR}")
    if shutil.which("node") is None:
        raise RuntimeError("node is not on PATH; the graphics renderer needs it")


def check_props(template: str, props: dict) -> List[str]:
    """Problems with ``props`` for ``template``, empty when it will render.

    Unknown keys are errors rather than being ignored: a misspelt ``sufix`` would
    otherwise render a number with no unit and nothing would say why.
    """
    templates = manifest()
    spec = templates.get(template)
    if spec is None:
        return [f"unknown template {template!r} — one of: "
                f"{', '.join(sorted(templates))}"]
    errors = []
    unknown = sorted(set(props) - set(spec["props"]))
    if unknown:
        errors.append(f"{template}: unknown prop(s) {', '.join(unknown)} — "
                      f"allowed: {', '.join(spec['props'])}")
    for key in spec["required"]:
        if props.get(key) in (None, "", []):
            errors.append(f"{template}: {key!r} is required")
    if "position" in props and props["position"] not in _POSITIONS:
        errors.append(f"{template}: position must be one of {', '.join(_POSITIONS)}")
    for key in spec["image_props"]:
        p = props.get(key)
        if not p or str(p).startswith(("http://", "https://", "data:")):
            continue
        path = Path(p)
        if not path.is_file():
            errors.append(f"{template}: {key} {p!r} does not exist")
        elif path.suffix.lower() not in _IMAGE_EXTS:
            errors.append(f"{template}: {key} {p!r} is not an image "
                          f"({', '.join(sorted(_IMAGE_EXTS))})")
    return errors


def stage_images(template: str, props: dict) -> dict:
    """Copy local image props into the renderer's public dir; return new props.

    Named by content hash, so staging the same screenshot twice is free and two
    different files called ``screenshot.png`` cannot collide.
    """
    out = dict(props)
    for key in manifest()[template]["image_props"]:
        p = props.get(key)
        if not p or str(p).startswith(("http://", "https://", "data:")):
            continue
        src = Path(p)
        digest = hashlib.sha1(src.read_bytes()).hexdigest()[:16]
        STAGED_DIR.mkdir(parents=True, exist_ok=True)
        dest = STAGED_DIR / f"{digest}{src.suffix.lower()}"
        if not dest.exists():
            shutil.copyfile(src, dest)
        out[key] = f"_assets/{dest.name}"
    return out


def broll_frames(clip: Clip, tb: Timebase, b: BRoll) -> Tuple[int, int]:
    """(program_start_frame, frame_count) of a b-roll entry in the finished short.

    Raises when the entry does not sit inside one kept segment — the validator
    rejects that shape anyway, and rendering a file for it would be wasted work.
    """
    for m_start, m_end, p_start in program_ranges(clip, tb):
        if m_start - 1e-9 <= b.start and b.end <= m_end + 1e-9:
            start = p_start + tb.to_frames(b.start) - tb.to_frames(m_start)
            end = p_start + tb.to_frames(b.end) - tb.to_frames(m_start)
            if end <= start:
                break
            return start, end - start
    raise ValueError(f"b-roll {b.id!r} ({b.start:.2f}-{b.end:.2f}) is not inside "
                     f"one kept segment of clip {clip.id!r}")


def stale_graphics(edl: EDL) -> List[str]:
    """Warnings for rendered graphics whose entry has since changed length.

    Moving an entry keeps its file, and a file rendered for 90 frames laid on a
    75-frame entry loses its exit animation to Premiere's trim — nothing errors,
    the graphic just cuts off hard.
    """
    out = []
    for clip in edl.clips:
        for b in clip.broll:
            if not b.graphic or not b.source:
                continue
            try:
                _, frames = broll_frames(clip, edl.timebase, b)
            except ValueError:
                continue
            if frames != b.graphic.get("frames"):
                out.append(f"clip {clip.id}: graphic {b.id!r} was rendered for "
                           f"{b.graphic.get('frames')} frames but the entry is "
                           f"now {frames} — re-render it with render_graphics")
    return out


@dataclass
class Job:
    clip_id: str
    broll_id: str
    template: str
    props: dict           # as the caller gave them — what the EDL records
    render_props: dict    # with images staged — what the renderer sees
    frames: int
    program_start: int
    out: Path
    still: Path


def plan_jobs(edl: EDL, items: List[dict], out_dir: Path) -> Tuple[List[Job], List[str]]:
    """Resolve render requests against the EDL. Nothing is rendered here.

    Every item is checked before any rendering starts, so one bad prop in a
    batch of twelve fails in a second rather than after eleven renders.
    """
    jobs, errors = [], []
    for i, item in enumerate(items):
        tag = f"item #{i}"
        unknown = sorted(set(item) - {"clip_id", "broll_id", "template", "props"})
        if unknown:
            errors.append(f"{tag}: unknown field(s) {', '.join(unknown)}")
            continue
        clip = edl.clip(item.get("clip_id", ""))
        if clip is None:
            errors.append(f"{tag}: no clip {item.get('clip_id')!r}")
            continue
        b = next((x for x in clip.broll if x.id == item.get("broll_id")), None)
        if b is None:
            errors.append(f"{tag}: no b-roll {item.get('broll_id')!r} on clip "
                          f"{clip.id!r} — add it with add_broll first")
            continue
        template, props = item.get("template", ""), item.get("props") or {}
        problems = check_props(template, props)
        if problems:
            errors.extend(f"{tag}: {p}" for p in problems)
            continue
        # A card sits over the speaker, so it goes on the overlay track; a
        # full-screen frame replaces the picture, so it goes where footage does.
        # The other way round still renders, but lands on the wrong track — a
        # full-screen frame on overlay would hide any card meant to sit on it.
        want = template_kind(template)
        if b.kind != want:
            errors.append(f"{tag}: {template} is a "
                          f"{'full-screen' if want == 'footage' else 'card'} "
                          f"template and renders onto a kind={want!r} entry; "
                          f"b-roll {b.id!r} is {b.kind!r}")
            continue
        try:
            p_start, frames = broll_frames(clip, edl.timebase, b)
        except ValueError as e:
            errors.append(f"{tag}: {e}")
            continue
        stem = f"{clip.id}_{b.id}"
        jobs.append(Job(clip_id=clip.id, broll_id=b.id, template=template,
                        props=props, render_props=stage_images(template, props),
                        frames=frames, program_start=p_start,
                        out=out_dir / f"{stem}.mov",
                        still=out_dir / f"{stem}.still.png"))
    return jobs, errors


def render(jobs: List[Job], edl: EDL, timeout: float = 1800) -> List[dict]:
    """Render a batch through ``graphics/render.mjs``; one result per job."""
    ensure_installed()
    w, h = edl.frame_size
    spec = {"jobs": [{
        "template": j.template, "props": j.render_props,
        "width": w, "height": h, "fps": float(edl.timebase.fps),
        "frames": j.frames, "out": str(j.out), "still": str(j.still),
    } for j in jobs]}
    for j in jobs:
        j.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = Path(tmp) / "jobs.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        proc = subprocess.run(
            ["node", str(GRAPHICS_DIR / "render.mjs"), str(spec_path)],
            cwd=GRAPHICS_DIR, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            shell=False)
    by_out = {}
    for line in proc.stdout.splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "out" in r:
            by_out[r["out"]] = r
    results = []
    for j in jobs:
        r = by_out.get(str(j.out))
        if r is None:
            tail = (proc.stderr or "").strip().splitlines()[-15:]
            r = {"ok": False, "error": "renderer exited before this job: "
                 + " | ".join(tail)}
        results.append(r)
    return results


def composite_check(still: Path, background: Optional[Path], out: Path,
                    frame_size: Tuple[int, int]) -> Path:
    """Lay a graphic's still over the picture it will sit on.

    A transparent PNG on its own says nothing about whether the graphic covers a
    face or fights the captions, which is most of what is worth checking. When
    the camera frame is not available the check falls back to mid grey, which
    at least shows the card against something.
    """
    w, h = frame_size
    ff = ffmpeg_bin("ffmpeg")
    if background and background.exists():
        bg = ["-i", str(background)]
        base = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}[bg]"
    else:
        bg = ["-f", "lavfi", "-i", f"color=c=0x555555:s={w}x{h}"]
        base = "[0:v]null[bg]"
    subprocess.run(
        [ff, "-y", "-v", "error", *bg, "-i", str(still),
         "-filter_complex", f"{base};[bg][1:v]overlay=0:0,scale={w // 2}:{h // 2}",
         "-frames:v", "1", str(out)],
        check=True, capture_output=True)
    return out


def grab_program_frame(compiled, program_frame: int, out: Path) -> Optional[Path]:
    """The camera frame shown at ``program_frame`` of a compiled clip, or None.

    Approximate on purpose — it ignores punch-in scale — because it only has to
    show what is roughly underneath a graphic, not match picture to the pixel.
    """
    fps = float(compiled.timebase.fps)
    item = next((it for it in compiled.program_video()
                 if it.start <= program_frame < it.end), None)
    if item is None or not item.path or not Path(item.path).is_file():
        return None
    t = (item.in_ + program_frame - item.start) / fps
    try:
        subprocess.run(
            [ffmpeg_bin("ffmpeg"), "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", item.path,
             "-frames:v", "1", str(out)],
            check=True, capture_output=True, timeout=60)
    except (subprocess.SubprocessError, OSError):
        return None
    return out if out.exists() else None
