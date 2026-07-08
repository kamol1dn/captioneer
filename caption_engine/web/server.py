"""Flask app for the local browser UI.

The heavy lifting stays in the existing engine (``engine.transcribe``,
``build_phrases``, ``render_to_mov``); this module is a thin HTTP layer plus a
couple of media helpers (proxy transcode, preview composite) so the browser can
play the source video and review a true render before exporting.

Everything is single-user localhost, so there's no auth and the "Browse" route
is allowed to open a native OS file dialog and hand back an absolute path.
"""
import os
import subprocess
import tempfile
from dataclasses import fields
from pathlib import Path
from typing import List

from flask import (Flask, Response, jsonify, request, send_file,
                   send_from_directory)

from .. import engine, preferences
from ..layout import build_phrases
from ..prompt import build_prompt
from ..renderer.preview import render_preview_overlay
from ..style import CaptionStyle, list_available_fonts
from ..transcriber import Word
from . import jobs

# ── Per-language UI config (moved out of the old Tkinter GUI) ────────────────
# Drives the model dropdown and alignment toggle. `code` is passed to
# engine.transcribe(language=...): None lets WhisperX auto-detect; "uz" routes
# to the Kotib backend (fixed model, always MMS-aligned).
LANGUAGES = {
    "English": {"code": None,
                "models": ["tiny", "base", "small", "medium", "large-v3"],
                "default_model": "large-v3", "whisper": True},
    "Uzbek": {"code": "uz", "models": ["Kotib"],
              "default_model": "Kotib", "whisper": False},
}

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
_STATIC = _HERE / "static"

# Scratch space for generated proxies/previews served back to the browser.
WORKDIR = Path(tempfile.mkdtemp(prefix="captioneer_"))

_STYLE_FIELDS = {f.name for f in fields(CaptionStyle)}

app = Flask(__name__, static_folder=None)


# ── ffmpeg/ffprobe resolution ────────────────────────────────────────────────

def _bin(name: str) -> str:
    """Prefer the bundled ffmpeg-7.1 binaries; fall back to PATH."""
    bundled = _PROJECT_ROOT / "ffmpeg-7.1" / "bin" / f"{name}.exe"
    return str(bundled) if bundled.exists() else name


def _probe_streams(path: str) -> dict:
    """Probe a media file: does it have video/audio, and the video size.

    Audio-only inputs (podcast mp3/wav) are a first-class use case — the
    preview then plays captions over a black stage instead of source video.
    """
    import json as _json
    try:
        out = subprocess.run(
            [_bin("ffprobe"), "-v", "error",
             "-show_entries", "stream=codec_type,width,height,disposition",
             "-of", "json", path],
            capture_output=True, text=True, check=True).stdout
        streams = _json.loads(out or "{}").get("streams", [])
    except Exception:
        streams = []
    # Ignore attached cover art (mp3 album covers show up as a video stream).
    vids = [s for s in streams if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")]
    v = vids[0] if vids else None
    return {
        "has_video": v is not None,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": (v or {}).get("width"),
        "height": (v or {}).get("height"),
    }


# ── request → engine object helpers ──────────────────────────────────────────

def _style_from_payload(d: dict) -> CaptionStyle:
    """Build a CaptionStyle from a JSON dict, ignoring unknown keys and
    resolving the font path."""
    clean = {k: v for k, v in (d or {}).items() if k in _STYLE_FIELDS}
    clean["font_path"] = preferences._resolve_font(clean.get("font_path"))
    return CaptionStyle.from_dict(clean)


def _words_from_payload(items: list) -> List[Word]:
    return [Word(text=w["text"], start=float(w["start"]), end=float(w["end"]),
                 line_break=bool(w.get("line_break", False)))
            for w in (items or [])]


def _phrases_to_json(phrases) -> list:
    return [
        {"start": p.start, "end": p.end,
         "lines": [{"words": [
             {"text": w.text, "start": w.start, "end": w.end,
              "line_break": w.line_break} for w in line.words]}
             for line in p.lines]}
        for p in phrases
    ]


# ── static / index ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file(_STATIC / "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(_STATIC, filename)


@app.route("/media/<path:filename>")
def media(filename):
    return send_from_directory(WORKDIR, filename)


# ── config / fonts ───────────────────────────────────────────────────────────

@app.route("/api/config")
def api_config():
    """Everything the UI needs to boot: languages, app settings, presets."""
    prefs = preferences.load()
    return jsonify({
        "languages": LANGUAGES,
        "app": prefs["app"],
        "presets": prefs["presets"],
        "preset_groups": prefs["preset_groups"],
        "fonts": list(list_available_fonts().keys()),
        "style_fields": sorted(_STYLE_FIELDS),
    })


@app.route("/api/fontfile")
def api_fontfile():
    """Serve a bundled .ttf/.otf by its display label so the canvas can
    @font-face it (keeps preview metrics close to the PIL render)."""
    label = request.args.get("label", "")
    fonts = list_available_fonts()
    path = fonts.get(label)
    if not path or not os.path.exists(path):
        return ("font not found", 404)
    return send_file(path)


# ── preferences / presets CRUD ───────────────────────────────────────────────

@app.route("/api/preferences", methods=["PUT"])
def api_set_prefs():
    return jsonify(preferences.set_app(request.get_json(force=True) or {}))


@app.route("/api/presets", methods=["POST"])
def api_save_preset():
    body = request.get_json(force=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    group = body.get("group") or "English"
    style = _style_from_payload(body.get("style") or {})
    data = preferences.save_preset(name, style, group)
    return jsonify({"presets": data["presets"],
                    "preset_groups": data["preset_groups"]})


@app.route("/api/presets/<name>", methods=["DELETE"])
def api_delete_preset(name):
    data = preferences.delete_preset(name)
    return jsonify({"presets": data["presets"],
                    "preset_groups": data["preset_groups"]})


@app.route("/api/presets/reset", methods=["POST"])
def api_reset_presets():
    data = preferences.reset_to_defaults()
    return jsonify({"presets": data["presets"],
                    "preset_groups": data["preset_groups"],
                    "app": data["app"]})


# ── native file browse ───────────────────────────────────────────────────────

@app.route("/api/browse", methods=["POST"])
def api_browse():
    """Open a native OS open-file dialog and return the chosen path.

    Runs a self-contained Tk instance on a dedicated thread so it doesn't need
    the (nonexistent) main-thread Tk mainloop of a Flask worker.
    """
    import threading
    result = {"path": ""}

    def pick():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            result["path"] = filedialog.askopenfilename(
                title="Select a video or audio file",
                filetypes=[("Video / Audio",
                            "*.mp4 *.mov *.avi *.mkv *.mp3 *.wav *.m4a"),
                           ("All files", "*.*")])
            root.destroy()
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)

    t = threading.Thread(target=pick)
    t.start()
    t.join()
    if result.get("error"):
        return jsonify({"error": result["error"]}), 500
    return jsonify({"path": result["path"]})


# ── media proxy (browser-playable copy of the source) ────────────────────────

@app.route("/api/proxy", methods=["POST"])
def api_proxy():
    body = request.get_json(force=True) or {}
    src = body.get("input", "")
    if not src or not os.path.exists(src):
        return jsonify({"error": "input file not found"}), 400

    info = _probe_streams(src)
    if not info["has_video"] and not info["has_audio"]:
        return jsonify({"error": "file has no audio or video streams"}), 400

    name = f"proxy_{abs(hash(src)) & 0xffffffff:x}.mp4"
    out = WORKDIR / name
    if not out.exists():
        if info["has_video"]:
            cmd = [_bin("ffmpeg"), "-y", "-i", src,
                   "-vf", "scale=-2:'min(854,ih)'",
                   "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-movflags", "+faststart", str(out)]
        else:
            # Audio-only source (podcast mp3/wav): strip any cover art and make
            # a browser-playable aac track; the stage shows captions on black.
            cmd = [_bin("ffmpeg"), "-y", "-i", src, "-vn",
                   "-c:a", "aac", "-movflags", "+faststart", str(out)]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            return jsonify({
                "error": "proxy transcode failed",
                "detail": proc.stderr.decode("utf-8", errors="ignore")[-1500:]
            }), 500
    return jsonify({"url": f"/media/{name}",
                    "audio_only": not info["has_video"]})


# ── transcribe (background job) ──────────────────────────────────────────────

@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    body = request.get_json(force=True) or {}
    src = body.get("input", "")
    if not src or not os.path.exists(src):
        return jsonify({"error": "input file not found"}), 400
    language = LANGUAGES.get(body.get("language", "English"), {}).get("code")
    model = body.get("model", "base")
    align = bool(body.get("align", True))
    use_emojis = bool(body.get("emoji", True))

    def work(job: jobs.Job):
        job.emit({"type": "progress", "current": 0, "total": 0,
                  "message": "Transcribing…"})
        words = engine.transcribe(src, model_size=model, align=align,
                                  language=language)
        prompt = build_prompt(words, use_emojis, language)
        return {"words": [w.to_dict() for w in words], "prompt": prompt}

    return jsonify({"job_id": jobs.submit(work).id})


# ── layout (fast, synchronous) ───────────────────────────────────────────────

@app.route("/api/layout", methods=["POST"])
def api_layout():
    body = request.get_json(force=True) or {}
    words = _words_from_payload(body.get("words"))
    style = _style_from_payload(body.get("style") or {})
    phrases = build_phrases(words, style)
    return jsonify({"phrases": _phrases_to_json(phrases)})


# ── render preview (true low-res render composited over the proxy) ───────────

@app.route("/api/render-preview", methods=["POST"])
def api_render_preview():
    body = request.get_json(force=True) or {}
    words = _words_from_payload(body.get("words"))
    style = _style_from_payload(body.get("style") or {})
    proxy_url = body.get("proxy_url", "")
    if not proxy_url:
        return jsonify({"error": "proxy_url required"}), 400
    proxy_path = WORKDIR / os.path.basename(proxy_url)
    if not proxy_path.exists():
        return jsonify({"error": "proxy missing; reload the file"}), 400

    phrases = build_phrases(words, style)
    if not phrases:
        return jsonify({"error": "no captions to preview"}), 400

    # Scale the overlay down to the proxy width for a fast render; the composite
    # step keeps proportions, so the result matches the real export. Audio-only
    # proxies get a black 9:16 stage instead of source video.
    info = _probe_streams(str(proxy_path))
    audio_only = not info["has_video"]
    stage = (480, 854) if audio_only else None
    pw = stage[0] if audio_only else info["width"]
    if pw and pw < style.width:
        _scale_style_px(style, pw / style.width)

    out_name = f"preview_{style.width}x{style.height}_{abs(hash(proxy_url)) & 0xffff:x}.mp4"
    out_path = WORKDIR / out_name

    def work(job: jobs.Job):
        render_preview_overlay(
            phrases, style, str(proxy_path), str(out_path),
            ffmpeg=_bin("ffmpeg"), audio_only=audio_only, stage_size=stage,
            progress_cb=lambda c, t: job.progress(c, t, "Rendering preview…"))
        return {"url": f"/media/{out_name}"}

    return jsonify({"job_id": jobs.submit(work).id})


def _scale_style_px(style: CaptionStyle, s: float) -> None:
    """Scale a style's pixel-valued fields by ``s`` in place (for low-res
    preview)."""
    style.width = max(2, int(round(style.width * s)))
    style.height = max(2, int(round(style.height * s)))
    for attr in ("font_size", "letter_spacing", "text_stroke_width",
                 "bg_padding", "bg_radius", "bg_offset_x", "bg_offset_y",
                 "highlight_box_padding", "horizontal_padding"):
        setattr(style, attr, int(round(getattr(style, attr) * s)))


# ── full export (background job) ─────────────────────────────────────────────

@app.route("/api/render", methods=["POST"])
def api_render():
    body = request.get_json(force=True) or {}
    words = _words_from_payload(body.get("words"))
    style = _style_from_payload(body.get("style") or {})
    output = (body.get("output") or "captions.mov").strip()
    if not words:
        return jsonify({"error": "no words to render"}), 400

    def work(job: jobs.Job):
        engine.make_captions(
            words=words, output_mov=output, style=style,
            progress_cb=lambda c, t: job.progress(c, t, "Rendering export…"))
        return {"output": output}

    return jsonify({"job_id": jobs.submit(work).id})


# ── SSE events ───────────────────────────────────────────────────────────────

@app.route("/api/jobs/<job_id>/events")
def api_job_events(job_id):
    return Response(jobs.stream(job_id), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})
