"""Open a clipper project inside the caption editor.

The editor's original shape is one file at a time: pick a source, transcribe it,
refine the words, export somewhere. A clipper project is a different shape — a
dozen-plus clips that already carry forced-aligned words, a house preset, and a
rendered overlay that an exported Premiere sequence is already pointing at.
Driving that through the file-at-a-time flow would mean re-transcribing audio
the project already holds, and exporting to a path Premiere has never heard of.

So this blueprint adds only the missing verbs: list projects, list a project's
clips, load one clip's words plus its *resolved* style, and re-render *in place*
over the overlay the exported XML already references. Premiere re-reads that
file on its next refresh, so fixing a caption is one render away from being on
the timeline — no re-export, no relink.

Two things are deliberate:

* **The style is resolved the same way ``render_all_captions`` resolves it**
  (``captions.build_style`` with the project's preset and the EDL's frame size
  and fps). If the GUI built its own style the overlay would quietly stop
  matching the other fifteen clips.
* **The render writes to a temp file and then replaces the target.** A partially
  written ProRes at the path Premiere is reading is worse than a failed render,
  and on Windows the replace is also where a lock shows up as a clean error
  instead of a corrupt file.

``server.py`` registers this only if ``clipper`` imports, so a checkout without
it still serves the normal single-file UI.
"""
import os
import shutil
import subprocess
from pathlib import Path

from flask import Blueprint, jsonify, request

from clipper import captions as captions_mod
from clipper import paths as clipper_paths
from clipper import transcript as transcript_mod
from clipper.edl import EDL
from clipper.project import Project

from .. import preferences
from ..style import CaptionStyle
from . import jobs

bp = Blueprint("clipper", __name__, url_prefix="/api/clipper")


# ── lookups ──────────────────────────────────────────────────────────────────

def _load(project_id: str) -> Project:
    project = Project.load(project_id)
    if project is None:
        raise LookupError(f"no such project: {project_id!r}")
    return project


def _edl(project: Project) -> EDL:
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise LookupError(f"project {project.id!r} has no EDL saved yet")
    return edl


def _clip(edl: EDL, clip_id: str):
    clip = edl.clip(clip_id)
    if clip is None:
        raise LookupError(f"no clip {clip_id!r} in this EDL")
    return clip


@bp.errorhandler(LookupError)
def _not_found(e):
    return jsonify({"error": str(e)}), 404


# ── project / clip listing ───────────────────────────────────────────────────

@bp.get("/projects")
def api_projects():
    """Every registered project whose directory still exists.

    Registry entries outlive the folders they point at (a deleted episode leaves
    its id behind), so a missing project.json is skipped rather than raised —
    the sidebar should show what's openable, not what was once created.

    Deduplicated by directory, not by registry key: re-creating a project under a
    new id leaves the old key pointing at the same folder, and both resolve to
    the same project. Listing it twice would put two identical rows in the
    sidebar that open the same clips.
    """
    out, seen = [], set()
    for project_id in sorted(clipper_paths.read_registry()):
        try:
            project = Project.load(project_id)
        except Exception:                                   # noqa: BLE001
            continue
        if project is None:
            continue
        key = str(Path(project.dir).resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        edl = EDL.load(project.edl_path)
        out.append({
            "id": project.id,
            "name": project.name,
            "dir": str(project.dir),
            "language": project.language,
            "caption_preset": project.caption_preset,
            "n_clips": len(edl.clips) if edl else 0,
        })
    return jsonify({"projects": out})


@bp.get("/projects/<project_id>/clips")
def api_clips(project_id):
    """The sidebar list: one row per sequence, with what state its captions are in.

    ``stale`` uses the same mtime rule ``caption_status`` does, so the GUI and
    the MCP tool never disagree about which clips still need a render.
    """
    project = _load(project_id)
    edl = _edl(project)
    edl_mtime = clipper_paths.mtime(project.edl_path) or 0
    out = []
    for clip in edl.clips:
        words_t = clipper_paths.mtime(captions_mod.words_path(project, clip.id))
        mov_t = clipper_paths.mtime(captions_mod.mov_path(project, clip.id))
        out.append({
            "id": clip.id,
            "title": clip.title or clip.id,
            "duration": round(clip.duration, 2),
            "n_segments": len(clip.segments),
            "polished": words_t is not None,
            "rendered": mov_t is not None,
            "stale": bool(words_t and edl_mtime > words_t + 1),
        })
    return jsonify({
        "project": {"id": project.id, "name": project.name,
                    "language": project.language,
                    "caption_preset": project.caption_preset},
        "clips": out,
    })


# ── one clip: words + resolved style ─────────────────────────────────────────

def _resolved_style(project: Project, edl: EDL):
    return captions_mod.build_style(
        project.caption_preset or None, edl.frame_size,
        int(round(float(edl.timebase.fps))),
    )


@bp.get("/projects/<project_id>/clips/<clip_id>")
def api_clip(project_id, clip_id):
    """Words for one clip, polished if they exist, freshly remapped if not.

    Falling back to the remapped master words means a clip that was never
    polished still opens with something to edit, rather than an empty editor
    and no hint that the transcript is right there.
    """
    project = _load(project_id)
    edl = _edl(project)
    clip = _clip(edl, clip_id)

    words = captions_mod.load_clip_words(project, clip_id)
    polished = words is not None
    if not polished:
        words = captions_mod.words_for_clip(
            transcript_mod.master_words(project), clip, edl.timebase)

    style = _resolved_style(project, edl)
    return jsonify({
        "clip": {"id": clip.id, "title": clip.title or clip.id,
                 "duration": round(clip.duration, 3),
                 "note": clip.note},
        "polished": polished,
        "words": [w.to_dict() for w in words],
        "style": style.to_dict(),
        "preset": project.caption_preset or captions_mod.DEFAULT_PRESET,
        "language": project.language,
        "mov_path": str(captions_mod.mov_path(project, clip_id)),
        "prompt": captions_mod.refinement_prompt(
            words, use_emojis=True, language=project.language or None),
    })


@bp.put("/projects/<project_id>/clips/<clip_id>/words")
def api_save_words(project_id, clip_id):
    """Save polished words without rendering.

    Validated against the clip's real duration by the same check the MCP path
    uses, so a hand edit can't put a word past the end of the clip and have it
    only surface at render time.
    """
    project = _load(project_id)
    edl = _edl(project)
    clip = _clip(edl, clip_id)

    body = request.get_json(force=True) or {}
    try:
        words = captions_mod.words_from_payload(body.get("words") or [])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    report = captions_mod.validate_words(words, clip.duration)
    if not report["ok"]:
        return jsonify({"error": "; ".join(report["errors"]),
                        "warnings": report["warnings"]}), 400

    path = captions_mod.save_clip_words(project, clip_id, words)
    return jsonify({"saved": str(path), "n_words": len(words),
                    "warnings": report["warnings"]})


# ── render in place ──────────────────────────────────────────────────────────

@bp.post("/projects/<project_id>/clips/<clip_id>/render")
def api_render_clip(project_id, clip_id):
    """Save the words and re-render the overlay over the file Premiere links to.

    The output path is ``captions/<clip_id>.captions.mov`` — not a name the user
    types — because that is the path already baked into the exported XML. Render
    somewhere else and Premiere goes on showing the old captions.
    """
    project = _load(project_id)
    edl = _edl(project)
    clip = _clip(edl, clip_id)

    body = request.get_json(force=True) or {}
    try:
        words = captions_mod.words_from_payload(body.get("words") or [])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    report = captions_mod.validate_words(words, clip.duration)
    if not report["ok"]:
        return jsonify({"error": "; ".join(report["errors"])}), 400

    # Style tweaks made in the editor apply to this clip only. Persisting them
    # would silently re-style the other clips on their next render, which is a
    # surprise nobody asked for — change the preset if that's what you want.
    #
    # Merged as a dict and rebuilt through ``from_dict`` rather than set
    # attribute-by-attribute: a JSON round trip turns every colour tuple into a
    # list, and PIL rejects lists outright ("color must be int or tuple"). That
    # constructor is where the coercion lives, and it's the same one the
    # single-file render path uses.
    #
    # fps is dropped because it belongs to the EDL's timebase — a stale value
    # from the browser would drift word highlighting against picture. font_path
    # arrives as a display label (that's what the editor's dropdown holds), so it
    # goes through the same resolver.
    base = _resolved_style(project, edl).to_dict()
    for key, value in (body.get("style") or {}).items():
        if key not in base or key == "fps":
            continue
        base[key] = (preferences._resolve_font(value) if key == "font_path"
                     else value)
    style = CaptionStyle.from_dict(base)
    style.fps = int(round(float(edl.timebase.fps)))

    target = captions_mod.mov_path(project, clip_id)
    duration = clip.duration

    def work(job: jobs.Job):
        captions_mod.save_clip_words(project, clip_id, words)
        # `.mov` has to stay the *last* extension — ffmpeg picks the container
        # from it, and a trailing `.tmp` makes it refuse to open the output.
        tmp = target.with_name(f"{target.stem}.tmp{target.suffix}")
        try:
            captions_mod.render_captions(
                project, clip_id, words, duration, style, out_path=tmp,
                progress_cb=lambda c, t: job.progress(c, t, "Rendering overlay…"))
        except Exception:
            tmp.unlink(missing_ok=True)     # don't leave a half-written overlay
            raise
        try:
            os.replace(tmp, target)
        except PermissionError:
            # Premiere (or anything else) is holding the old overlay open. The
            # freshly rendered file is intact — say where, and don't leave the
            # caller guessing why the timeline still shows the old captions.
            return {"output": str(tmp), "replaced": False,
                    "note": f"{target.name} is locked by another program — "
                            f"rendered alongside it as {tmp.name}. Close the "
                            f"file in Premiere and rename, or retry."}
        return {"output": str(target), "replaced": True,
                "n_words": len(words),
                "warnings": report["warnings"]}

    return jsonify({"job_id": jobs.submit(work).id})


# ── clip preview (real picture + audio to edit against) ──────────────────────

@bp.post("/projects/<project_id>/clips/<clip_id>/preview")
def api_clip_preview(project_id, clip_id):
    """The clip's **audio**, cut to its segments, for the editor to scrub against.

    Audio-only on purpose. ``clipper.preview.render_preview`` builds the real
    picture, but it selects segments with ffmpeg's ``trim`` *filter*, which
    decodes from the start of each input — for a clip starting near the end of a
    two-hour 1440x2560 HEVC master that is minutes of decoding for a 35-second
    result. Fine for its own job (checking a cut before Premiere); far too slow
    to sit between clicking a clip and editing its captions.

    Captions are timed against speech, and the editor already renders a black
    stage for audio-only sources, so cutting the pinned mix with input-level
    ``-ss`` (a seek, not a decode) gives the same editing signal in about a
    second. Cached on the EDL's mtime, so re-opening is instant and a re-cut
    clip still rebuilds.
    """
    from caption_engine.media import ffmpeg_bin

    from .server import WORKDIR                    # late: avoids a circular import

    project = _load(project_id)
    edl = _edl(project)
    clip = _clip(edl, clip_id)

    cameras = project.camera_map()
    source = cameras.get(project.primary_audio_camera) or {}
    src_path = source.get("path")
    if not src_path or not os.path.exists(src_path):
        return jsonify({"error": "the project's primary audio source is missing"}), 400
    offset = float(source.get("offset_sec") or 0.0)

    segments = sorted(clip.segments, key=lambda s: s.start)
    if not segments:
        return jsonify({"error": "clip has no segments"}), 400

    stamp = int(clipper_paths.mtime(project.edl_path) or 0)
    name = f"clip_{project.id}_{clip_id}_{stamp}.m4a".replace(os.sep, "_")
    out = Path(WORKDIR) / name
    if out.exists():
        return jsonify({"url": f"/media/{name}", "audio_only": True, "cached": True})

    def work(job: jobs.Job):
        job.emit({"type": "progress", "current": 0, "total": 0,
                  "message": "Cutting clip audio…"})
        cmd = [ffmpeg_bin("ffmpeg"), "-y", "-nostdin"]
        for seg in segments:
            # -ss before -i is the fast seek: ffmpeg jumps in the file rather
            # than decoding up to the mark.
            cmd += ["-ss", f"{seg.start + offset:.3f}",
                    "-t", f"{seg.end - seg.start:.3f}", "-i", src_path]
        parts = "".join(f"[{i}:a]asetpts=PTS-STARTPTS[a{i}];"
                        for i in range(len(segments)))
        joins = "".join(f"[a{i}]" for i in range(len(segments)))
        cmd += ["-filter_complex",
                f"{parts}{joins}concat=n={len(segments)}:v=0:a=1[out]",
                "-map", "[out]", "-c:a", "aac", "-b:a", "160k",
                "-movflags", "+faststart", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            out.unlink(missing_ok=True)
            raise RuntimeError("clip audio preview failed:\n"
                               + (proc.stderr or "")[-1500:])
        return {"url": f"/media/{name}", "audio_only": True, "cached": False}

    return jsonify({"job_id": jobs.submit(work).id})


# ── reveal in explorer ───────────────────────────────────────────────────────

@bp.post("/projects/<project_id>/reveal")
def api_reveal(project_id):
    """Open the project's captions folder in the OS file manager."""
    project = _load(project_id)
    folder = captions_mod.captions_dir(project)
    opener = ("explorer" if os.name == "nt"
              else "open" if shutil.which("open") else "xdg-open")
    try:
        os.startfile(folder) if os.name == "nt" else os.spawnlp(  # noqa: S606
            os.P_NOWAIT, opener, opener, str(folder))
    except Exception as e:                                        # noqa: BLE001
        return jsonify({"error": str(e)}), 500
    return jsonify({"opened": str(folder)})
