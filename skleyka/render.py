"""Render a graphic for the timeline through the clipper's Remotion renderer.

Overlays are rendered at the pixel size of the box they will fill (from
free_space), as ProRes 4444 with alpha and no audio, so ``place_overlay`` can
lay them in at 100% centred on the box. Full-frame cards are rendered at the
sequence size.

Nothing episode-specific is kept in the repo (as with reel-studio's engine
and reel folders). Each episode has its own Remotion public dir,
<episode>/skleyka/public (the fonts, synced from graphics/public/fonts;
staged images under _assets/; exported footage spans under spans/; a
scene's own art under scenes/), and its own full-screen scenes as .tsx files
in <episode>/skleyka/scenes/, copied into graphics/src/_episode/ (generated,
git-ignored) with a generated entry per scene (entry_<scene>.tsx), so scenes
can render side by side. Renders land in <episode>/skleyka/renders/.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import timeline

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from clipper import graphics as cg  # noqa: E402  (manifest, prop checks, image staging)

GRAPHICS = REPO / "graphics"
EPISODE_SRC = GRAPHICS / "src" / "_episode"
# Remotion leaves a bundle (a copy of the whole public dir) and asset copies in
# %TEMP% on every run; C: is nearly full, so each run gets its own temp on D:,
# deleted afterwards (as reel-studio does).
TMP_ROOT = Path("D:/skleyka-tmp")


class RenderError(RuntimeError):
    pass


def longform() -> tuple[str, ...]:
    """Templates Skleyka places on a long-form timeline: those a show's
    templates.json marks ``"longform": true``, and every baked one
    (``"placement": "baked"``). Read fresh, so a new template needs no restart
    of this server."""
    man = cg.manifest()
    return tuple(k for k, v in man.items() if v.get("longform") or v.get("placement") == "baked")


def templates() -> dict:
    """The long-form templates with their prop docs."""
    man = cg.manifest()
    return {name: man[name] for name in longform() if name in man}


def renders_dir(project_path: str) -> Path:
    d = timeline.workdir(project_path) / "renders"
    d.mkdir(exist_ok=True)
    return d


def public_dir(project_path: str) -> Path:
    """The episode's Remotion public dir, with the engine's fonts in it."""
    d = timeline.workdir(project_path) / "public"
    src = GRAPHICS / "public" / "fonts"
    for f in src.iterdir():
        dst = d / "fonts" / f.name
        if f.is_file() and (not dst.exists() or dst.stat().st_size != f.stat().st_size):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
    return d


def scenes_dir(project_path: str) -> Path:
    d = timeline.workdir(project_path) / "scenes"
    d.mkdir(exist_ok=True)
    return d


def _even(n: float) -> int:
    v = max(2, int(round(n)))
    return v if v % 2 == 0 else v + 1


def _run(project_path: str, jobs: list[dict], entry: str | None = None, timeout: float = 600) -> tuple[list[dict], str]:
    cg.ensure_installed()
    spec_obj = {"jobs": jobs, "publicDir": str(public_dir(project_path))}
    if entry:
        spec_obj["entryPoint"] = entry
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TMP_ROOT, ignore_cleanup_errors=True) as tmp:
        spec = Path(tmp) / "jobs.json"
        spec.write_text(json.dumps(spec_obj), encoding="utf-8")
        env = {**os.environ, "TEMP": tmp, "TMP": tmp, "TMPDIR": tmp}
        proc = subprocess.run(["node", str(GRAPHICS / "render.mjs"), str(spec)], cwd=str(GRAPHICS),
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    results = []
    for line in proc.stdout.splitlines():
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    tail = " | ".join((proc.stderr or "").strip().splitlines()[-12:])
    return results, tail


def _job(project_path: str, template: str, props: dict, width: int, height: int, seconds: float, fps: float,
         name: str | None, codec: str | None, still_only: bool = False, at: float = 0.6) -> dict:
    frames = max(2, int(round(seconds * fps)))
    # The name is often an overlay label ("Blitz B1: Import boji?"); Windows
    # refuses : ? and the like in a file name, and the render fails at the end.
    safe = re.sub(r'\s*[<>:"/\\|?*]+\s*', " ", name or template.lower()).strip(" .") or template.lower()
    stem = f"{safe}_{time.strftime('%H%M%S')}"
    if still_only:
        d = renders_dir(project_path) / "stills"
        d.mkdir(exist_ok=True)
        out = d / f"{stem}.png"
        return {"template": template, "props": props, "width": _even(width), "height": _even(height), "fps": float(fps),
                "frames": frames, "out": str(out), "still": str(out), "stillOnly": True, "stillAt": at}
    out = renders_dir(project_path) / f"{stem}.mov"
    job = {"template": template, "props": props, "width": _even(width), "height": _even(height),
           "fps": float(fps), "frames": frames, "out": str(out), "still": str(out.with_suffix(".png")),
           "proResProfile": "4444"}
    if codec == "h264":
        job["codec"] = "h264"
        job["crf"] = 15
    elif codec == "prores":
        job["proResProfile"] = "standard"  # opaque; a tenth of the size of 4444
    return job


def _one(project_path: str, job: dict, entry: str | None = None, timeout: float = 600) -> dict:
    results, tail = _run(project_path, [job], entry=entry, timeout=timeout)
    result = next((r for r in results if r.get("out") == job["out"]), None)
    if result is None or not result.get("ok"):
        raise RenderError((result or {}).get("error") or f"renderer failed: {tail}")
    out = Path(job["out"])
    if job.get("stillOnly"):
        return {"still": str(out)}
    still = Path(job["still"])
    return {"file": str(out), "still": str(still) if still.exists() else None, "frames": job["frames"],
            "seconds": round(job["frames"] / job["fps"], 3), "width": job["width"], "height": job["height"]}


def _checked(project_path: str, template: str, props: dict) -> dict:
    allowed = longform()
    if template not in allowed:
        raise RenderError(f"{template} is not a long-form template; one of {allowed}")
    errors = cg.check_props(template, props)
    if errors:
        raise RenderError("; ".join(errors))
    return cg.stage_images(template, props, public_dir=public_dir(project_path))


def render(project_path: str, template: str, props: dict, width: int, height: int, seconds: float,
           fps: float = 30.0, name: str | None = None, timeout: float = 600, codec: str | None = None) -> dict:
    """One graphic to a .mov (+ a .png still of it). Sizes are pixels."""
    props = _checked(project_path, template, props)
    if template == "GashtakFull" and codec is None:
        codec = "prores"
    return _one(project_path, _job(project_path, template, props, width, height, seconds, fps, name, codec), timeout=timeout)


def still(project_path: str, template: str, props: dict, width: int, height: int, at: float = 0.85,
          seconds: float = 4.0, fps: float = 30.0, name: str | None = None, timeout: float = 300) -> str:
    """One frame of a graphic as a PNG (``at`` = fraction of its length), for
    judging a design or a placement without rendering video. A few seconds."""
    props = _checked(project_path, template, props)
    job = _job(project_path, template, props, width, height, seconds, fps, name, None, still_only=True, at=at)
    return _one(project_path, job, timeout=timeout)["still"]


# --- an episode's own full-screen scenes ------------------------------------------

_ID = re.compile(r"[^A-Za-z0-9]")


def _scene_id(stem: str) -> str:
    return "Scene" + "".join(w[:1].upper() + w[1:] for w in _ID.split(stem) if w)


def _write_if_changed(path: Path, text: str) -> None:
    """Write ``text`` unless the file already holds it, through a temp file and
    a rename, so a render bundling at the same moment never reads half a file."""
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except FileNotFoundError:
        pass
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows: the bundler has it open for a moment
            time.sleep(0.25)
    raise RenderError(f"could not write {path}")


def install_scene(project_path: str, scene: str) -> tuple[str, str]:
    """Copy one scene, <episode>/skleyka/scenes/<scene>.tsx, into
    graphics/src/_episode/ and write its own entry (the engine's compositions
    plus this scene). Returns (entry, composition id).

    One entry per scene, and nothing else in the folder rewritten, so several
    scenes can be built and rendered at once: one scene mid-edit (or broken)
    never breaks another's bundle."""
    src = scenes_dir(project_path) / f"{scene}.tsx"
    if not src.exists():
        have = sorted(f.stem for f in scenes_dir(project_path).glob("*.tsx"))
        raise RenderError(f"No scene {scene!r} in {scenes_dir(project_path)}; have {have}")
    EPISODE_SRC.mkdir(parents=True, exist_ok=True)
    _write_if_changed(EPISODE_SRC / src.name, src.read_text(encoding="utf-8"))
    cid = _scene_id(scene)
    entry = EPISODE_SRC / f"entry_{scene}.tsx"
    _write_if_changed(entry,
        f"// Generated by skleyka/render.py for {src}. Do not edit; edit the scene there.\n"
        'import React from "react";\n'
        'import { Composition, registerRoot } from "remotion";\n'
        'import { Root } from "../Root";\n'
        f'import Scene from "./{scene}";\n\n'
        "const EpisodeRoot: React.FC = () => (\n  <>\n    <Root />\n"
        f'    <Composition id="{cid}" component={{Scene as React.FC<Record<string, unknown>>}} '
        f'width={{3840}} height={{2160}} fps={{30}} durationInFrames={{150}} />\n'
        "  </>\n);\n\nregisterRoot(EpisodeRoot);\n")
    return f"src/_episode/{entry.name}", cid


def render_scene(project_path: str, scene: str, seconds: float, props: dict | None = None,
                 width: int = 3840, height: int = 2160, fps: float = 30.0, still_at: float | None = None,
                 timeout: float = 1200) -> dict:
    """Render <episode>/skleyka/scenes/<scene>.tsx (its default export) full
    frame, opaque, as ProRes 422; or one frame of it as a PNG when
    ``still_at`` (fraction of its length) is given."""
    entry, cid = install_scene(project_path, scene)
    if still_at is not None:
        job = _job(project_path, cid, props or {}, width, height, seconds, fps, scene, None,
                   still_only=True, at=still_at)
    else:
        job = _job(project_path, cid, props or {}, width, height, seconds, fps, scene, "prores")
    return _one(project_path, job, entry=entry, timeout=timeout)


# Scene videos rendered in the background (render_scene(background=True)): the
# MCP server answers one call at a time, so a blocking 4K render (a minute per
# second) would hold up every other agent's calls, Premiere's included.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def render_scene_background(project_path: str, scene: str, seconds: float, **kw) -> dict:
    """Start render_scene's video in a thread and return at once; see jobs()."""
    job_id = f"{scene}_{time.strftime('%H%M%S')}"
    rec = {"job": job_id, "scene": scene, "seconds": seconds, "status": "running",
           "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    with _JOBS_LOCK:
        _JOBS[job_id] = rec

    def work():
        t0 = time.time()
        try:
            out = render_scene(project_path, scene, seconds, **kw)
            upd = {"status": "done", **out}
        except Exception as e:  # reported through jobs(), not raised into a dead thread
            upd = {"status": "failed", "error": str(e)[-1500:]}
        upd["took_s"] = round(time.time() - t0)
        with _JOBS_LOCK:
            rec.update(upd)

    threading.Thread(target=work, name=f"render {job_id}", daemon=True).start()
    return dict(rec)


def jobs(job: str | None = None) -> list[dict]:
    with _JOBS_LOCK:
        recs = [dict(r) for r in _JOBS.values() if job is None or r["job"] == job or r["scene"] == job]
    return recs
