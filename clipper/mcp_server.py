"""The clipper engine as an MCP server: the tools Claude Code calls to turn a
multicam episode into 14 short clips.

Every tool body is a thin wrapper over a plain function in ``clipper/*.py`` —
``clipper/__main__.py`` exposes the identical functions as a CLI, so the whole
surface is testable without an MCP client in the loop at all.

**The stdout rule.** In a stdio MCP server, stdout *is* the JSON-RPC channel.
WhisperX, faster-whisper, tqdm, and HuggingFace all print to it by default, and
one stray line corrupts the protocol with an opaque parse error on the client
side. So stdout is redirected to stderr at import time, before anything that
might transcribe gets a chance to run.
"""
import sys

# Windows consoles default to a legacy codepage (often cp1252), not UTF-8. Tool
# docstrings in this codebase use non-ASCII characters (em dashes) and become
# part of the protocol's tool-list response, so an unreconfigured stdout would
# mis-encode them — cp1252's em dash is a single 0x97 byte where UTF-8 needs
# three — and corrupt the strict-UTF-8 JSON-RPC stream. Pin both streams before
# anything else runs.
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# Must happen before any transcription code is imported — see module docstring.
_real_stdout = sys.stdout
sys.stdout = sys.stderr

import contextlib  # noqa: E402
import io  # noqa: E402
import warnings as _warnings  # noqa: E402
from typing import List, Optional  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

from . import captions as captions_mod  # noqa: E402
from . import energy as energy_mod  # noqa: E402
from . import paths  # noqa: E402
from . import sanity as sanity_mod  # noqa: E402
from . import verify as verify_mod  # noqa: E402
from . import ingest as ingest_mod  # noqa: E402
from . import transcript as transcript_mod  # noqa: E402
from caption_engine.transcriber.word import load_words  # noqa: E402

from .compile import compile_edl  # noqa: E402
from .edl import EDL, validate  # noqa: E402
from .preview import render_preview  # noqa: E402
from .project import Project, create
from .project import list_projects as _list_projects  # noqa: E402
from .xmeml import write_xmeml  # noqa: E402

_warnings.filterwarnings("default")  # routed to stderr by the redirect above

mcp = FastMCP("clipper-engine")


@contextlib.contextmanager
def _quiet():
    """Belt-and-suspenders: swallow any stray print from a library that grabbed
    a stdout reference before the module-level redirect took effect."""
    with contextlib.redirect_stdout(sys.stderr):
        yield


def _load(project_id: str) -> Project:
    """Accepts a project id, the project directory, or the media folder."""
    project = Project.load(project_id)
    if project is None:
        raise ValueError(
            f"no such project: {project_id!r} — pass a project id, the "
            f"project directory, or the folder the camera files are in")
    return project


# ── lifecycle ────────────────────────────────────────────────────────────────

@mcp.tool()
def create_project(name: str, cameras: List[dict],
                   primary_audio_camera: str = "",
                   project_dir: Optional[str] = None) -> dict:
    """Register a new multicam project. Each camera export must share a common
    t=0 (same Premiere sequence, same range) — that's what lets the compiler
    skip sync/offset math by default.

    cameras: [{"id": "A", "path": "D:/episodes/EP12/for claude/CamA.mp4",
               "label": "host", "offset_sec": 0.0, "transcribe": false}, ...]

    ``transcribe`` selects what ingest runs Whisper on, and defaults to the
    primary alone. A source may be audio-only (an mp3 mix sharing the same t=0):
    it can be transcribed and pinned as audio, but never cut to as picture, and
    it is held out of speaker scoring.

    The project is created as `clipper/` beside the media, so the episode folder
    stays self-contained and movable; pass project_dir to override. Returns
    camera durations/fps plus warnings about fps or duration mismatches or a
    non-zero start timecode — any of those silently break the shared-t=0
    assumption if ignored.
    """
    with _quiet():
        project, warnings_ = create(name, cameras, primary_audio_camera,
                                   project_dir=project_dir)
    return {
        "project_id": project.id,
        "project_dir": str(project.dir),
        "media_dir": str(project.media_dir),
        "cameras": [{"id": c.id, "label": c.label, "duration": c.duration,
                    "fps": str(c.probe.get("fps")), "width": c.probe.get("width"),
                    "height": c.probe.get("height"),
                    "has_audio": c.probe.get("has_audio")}
                   for c in project.cameras],
        "primary_audio_camera": project.primary_audio_camera,
        "warnings": warnings_,
    }


@mcp.tool(name="list_projects")
def list_projects_tool() -> List[dict]:
    """List all clipper projects."""
    return _list_projects()


@mcp.tool()
def get_project(project_id: str) -> dict:
    """Full project state: cameras, timebase, ingest status, EDL summary."""
    project = _load(project_id)
    d = project.to_dict()
    d["project_dir"] = str(project.dir)
    d["media_dir"] = str(project.media_dir)
    edl = EDL.load(project.edl_path)
    d["edl_summary"] = ({"n_clips": len(edl.clips),
                         "clip_ids": [c.id for c in edl.clips]}
                        if edl else None)
    missing = project.missing_media()
    if missing:
        d["missing_media"] = missing
    return d


@mcp.tool()
def ingest(project_id: str, model_size: str = "large-v3",
          language: Optional[str] = None,
          cameras: Optional[List[str]] = None,
          diarize: bool = False) -> dict:
    """Start transcription + energy analysis. Returns immediately with a job id
    — call ingest_status to poll.

    Two modes:

    * **default** — transcribe the single primary source (the one created with
      `transcribe: true`). Fast, one Whisper pass, but the transcript has no
      speaker labels: who said what is inferred afterwards from the per-camera
      energy line, and two people talking at once collapse into one stream.

    * **diarize=True** — transcribe every *camera* mic separately and merge them
      into one speaker-labelled timeline. Costs one Whisper pass per camera and
      needs at least two, but each line comes back attributed, overlapping
      speech survives on both mics, and captions are cut from each speaker's own
      isolated mic. Every mic hears the whole room, so bleed is rejected per
      word against the energy envelopes; `ingest_status` reports how much of
      each mic's transcript survived, under `diarization`.

    A combined mix is never a diarization target — it contains every voice at
    once and would win every bleed comparison. Register it as an audio-only
    source and it stays available to pin as the audio you hear.

    `cameras` filters which cameras this run touches.
    """
    project = _load(project_id)
    with _quiet():
        job = ingest_mod.start_ingest(project, model_size, language, cameras,
                                      diarize=diarize)
    return {"job_id": job.id}


@mcp.tool()
def ingest_status(project_id: str) -> dict:
    """Poll ingest progress: {state, progress, message, per_camera}."""
    return ingest_mod.ingest_status(_load(project_id))


# ── content inspection ──────────────────────────────────────────────────────

@mcp.tool()
def get_outline(project_id: str, bucket_sec: float = 20.0,
                start: float = 0.0, end: Optional[float] = None) -> str:
    """A map of the whole episode: one line per ~20s bucket showing the likely
    speaking camera, utterance count, and a text snippet. Read this before
    get_transcript — a 1-hour episode outlines in about 2k tokens."""
    project = _load(project_id)
    utterances = transcript_mod.load_utterances(project)
    envelopes = ingest_mod.load_envelopes(project)
    return transcript_mod.build_outline(utterances, envelopes, bucket_sec,
                                        start, end)


@mcp.tool()
def get_transcript(project_id: str, start: float = 0.0,
                   end: Optional[float] = None, max_chars: int = 8000) -> dict:
    """Word-adjacent transcript text for a time window, with a per-utterance
    energy line (e.g. 'A88 B09 C04') showing which camera's mic was loudest —
    that's the speaker-ID signal; there is no diarization model. Capped at
    max_chars (hard ceiling 20000); truncated=True means call again with
    start=next_start."""
    project = _load(project_id)
    utterances = transcript_mod.load_utterances(project)
    envelopes = ingest_mod.load_envelopes(project)
    return transcript_mod.format_transcript(utterances, envelopes, start, end,
                                            min(max_chars, 20000))


@mcp.tool()
def search_transcript(project_id: str, query: str, regex: bool = False,
                      max_hits: int = 30) -> List[dict]:
    """Find where something was said, e.g. search_transcript(pid, "tashkent")."""
    project = _load(project_id)
    utterances = transcript_mod.load_utterances(project)
    return transcript_mod.search(utterances, query, regex, max_hits)


@mcp.tool()
def get_energy(project_id: str, start: float, end: float) -> dict:
    """Normalized 0-99 loudness per camera over a window — the raw signal
    behind the transcript's energy line, useful when you need a finer look
    than one utterance's average."""
    project = _load(project_id)
    envelopes = ingest_mod.load_envelopes(project)
    return energy_mod.speaker_scores(envelopes, start, end)


@mcp.tool()
def find_silences(project_id: str, start: float, end: float,
                  min_sec: float = 0.35, camera: Optional[str] = None) -> List[List[float]]:
    """Legal cut points in [start, end) — ranges quiet enough that a cut there
    won't clip a word. Uses the pinned/primary camera's audio unless a camera
    id is given."""
    project = _load(project_id)
    cam = camera or project.primary_audio_camera
    env = energy_mod.load_envelope(project.energy_path(cam))
    if not env:
        raise ValueError(f"no energy envelope for camera {cam!r} — run ingest first")
    return [list(s) for s in energy_mod.find_silences(env, start, end, min_sec)]


@mcp.tool()
def snap_to_silence(project_id: str, times: List[float], max_shift: float = 0.4,
                    camera: Optional[str] = None) -> List[float]:
    """Nudge proposed cut points onto the nearest silence, within max_shift
    seconds. Call this on segment/camera-cut boundaries before set_edl — cuts
    that land mid-word are the most common flaw in an automated cut."""
    project = _load(project_id)
    cam = camera or project.primary_audio_camera
    env = energy_mod.load_envelope(project.energy_path(cam))
    if not env:
        raise ValueError(f"no energy envelope for camera {cam!r} — run ingest first")
    lo, hi = min(times) - 2.0, max(times) + 2.0
    silences = energy_mod.find_silences(env, max(0, lo), hi)
    return energy_mod.snap(times, silences, max_shift)


# ── EDL ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_edl(project_id: str) -> dict:
    """The current edit decision list, plus validation."""
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        return {"edl": None, "validation": None}
    return {"edl": edl.to_dict(),
           "validation": validate(edl, project.camera_ids,
                                  project.master_duration,
                                  project.video_camera_ids)}


@mcp.tool()
def set_edl(project_id: str, edl: dict) -> dict:
    """Replace the EDL. Rejected (and not persisted) if validation finds
    errors — fix those first; warnings alone don't block. A full-document
    replace is fine here: even 14 clips is a small JSON document."""
    project = _load(project_id)
    parsed = EDL.from_dict(edl)
    result = validate(parsed, project.camera_ids, project.master_duration)
    if not result["ok"]:
        return {"ok": False, "errors": result["errors"],
               "warnings": result["warnings"], "summary": None}
    parsed.save(project.edl_path)
    return {"ok": True, "errors": [], "warnings": result["warnings"],
           "summary": result["clips"]}


@mcp.tool()
def validate_edl(project_id: str) -> dict:
    """Re-check the saved EDL without changing it."""
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        return {"errors": ["no EDL saved yet"], "warnings": [], "ok": False}
    return validate(edl, project.camera_ids, project.master_duration,
                    project.video_camera_ids)


@mcp.tool()
def check_segments(project_id: str, clip_ids: Optional[List[str]] = None,
                   as_text: bool = True, min_confidence: str = "high"):
    """Read every clip the way a viewer hears it and report joins that don't.

    `validate_edl` checks the EDL is *legal*; this checks it *reads*. They catch
    different mistakes. A boundary can sit in a clean silence — so snapping is
    happy and validation passes — and still open the clip on "of 25 US tech
    companies" because "A coalition" fell into the trimmed gap.

    Flags `orphan_open` (starts mid-clause), `orphan_close` (ends on a dangling
    "So"/"And"), `hook` (opens on filler, wasting the first 2 seconds), and
    `empty_segment`. Run it after set_edl and before captioning — fixing a
    boundary afterwards makes the clip stale and costs the caption polish.

    Everything here is a warning. English resists word lists, so read the
    findings and decide; don't apply them blindly.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved — call set_edl first")
    words = transcript_mod.master_words(project)
    if not words:
        raise ValueError("no transcript — run ingest first")

    clips = [c for c in edl.clips if clip_ids is None or c.id in clip_ids]
    reports = [sanity_mod.check_clip(words, c) for c in clips]
    if as_text:
        return sanity_mod.format_report(reports, min_confidence)
    return {"clips": reports,
            "n_issues": sum(len(r["issues"]) for r in reports)}


@mcp.tool()
def verify_clip_audio(project_id: str, clip_ids: Optional[List[str]] = None,
                      model_size: str = "base", as_text: bool = True,
                      min_confidence: str = "high"):
    """Render each clip's audio, transcribe it, and diff it against the plan.

    `check_segments` reasons about the cut from the transcript; this listens to
    the result. It is the check that catches what only exists once the segments
    are concatenated — a boundary landing inside a word so the clip stutters
    ("...compliance issues. issues. They said..."), or a trim leaving a stray
    word behind ("...the same day. is there is no signatory"). Both of those
    shipped in OTG ep12 and both read perfectly in the EDL.

    Slower than the other checks: one ffmpeg pass plus one Whisper pass per
    clip. `base` is the default model because it only has to notice a word
    appearing twice, not produce a caption.

    Read `mismatch` findings sceptically — ASR disagrees with itself on names
    and numbers, so a lone substitution is usually the recognizer wavering.
    `stutter` and anything landing next to a boundary are the real signal.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved — call set_edl first")
    master = transcript_mod.master_words(project)
    if not master:
        raise ValueError("no transcript — run ingest first")

    clips = [c for c in edl.clips if clip_ids is None or c.id in clip_ids]
    work = project.dir / "verify"
    results = []
    with _quiet():
        for clip in clips:
            compiled = compile_edl(edl, project.camera_map(), [clip.id])[0]
            wav = verify_mod.export_clip_audio(compiled, work / f"{clip.id}.wav")
            heard = verify_mod.transcribe_file(
                wav, work / f"{clip.id}.heard.json", model_size=model_size)
            expected = captions_mod.words_for_clip(master, clip, edl.timebase)
            # Segment joins in program time — where an artifact would land.
            bounds, acc = [], 0.0
            for m_start, m_end, _p in captions_mod.program_ranges(clip, edl.timebase):
                acc += (m_end - m_start)
                bounds.append(round(acc, 3))
            results.append({
                "clip_id": clip.id, "title": clip.title,
                "audio": str(wav),
                "findings": verify_mod.diff_words(expected, heard, bounds[:-1]),
            })

    if as_text:
        return verify_mod.format_report(results, min_confidence)
    return {"clips": results,
            "n_findings": sum(len(r["findings"]) for r in results)}


@mcp.tool()
def preview_edl_text(project_id: str) -> str:
    """A human-readable rundown of every clip — what you'd show the user to
    get sign-off before export."""
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        return "(no EDL saved yet)"
    lines = [f"{len(edl.clips)} clip(s), timebase {edl.timebase}, "
            f"audio: {edl.audio.mode}\n"]
    for clip in edl.clips:
        m, s = divmod(clip.duration, 60)
        lines.append(f"## {clip.id} — {clip.title or '(untitled)'} "
                    f"({int(m)}:{s:04.1f})")
        for seg in sorted(clip.segments, key=lambda s: s.start):
            lines.append(f"   keep {seg.start:7.2f}-{seg.end:7.2f}  {seg.label}")
        for c in sorted(clip.camera_cuts, key=lambda c: c.at):
            lines.append(f"   cam  {c.at:7.2f} -> {c.camera}  {c.why}")
        for b in clip.broll:
            tag = "attached" if b.source else "PLACEHOLDER"
            lines.append(f"   broll {b.start:7.2f}-{b.end:7.2f} [{tag}] {b.query}")
        lines.append("")
    return "\n".join(lines)


# ── captions ─────────────────────────────────────────────────────────────────

@mcp.tool()
def get_clip_captions(project_id: str, clip_id: str,
                      use_emojis: bool = True,
                      language: Optional[str] = None) -> dict:
    """Word-level captions for a clip, plus the project's refinement prompt.

    No audio export and no re-transcription: the words are the master-timeline
    transcript remapped onto this clip's program time, so they already match the
    cut frame for frame.

    Returns {words, prompt, duration, polished}. Read `prompt` — it carries the
    project's own tuned rules (capitalization, number handling, Uzbek
    orthography, emoji placement, line_break decisions) from prompts.txt — apply
    them to `words`, then send the result to set_clip_captions. `polished` says
    whether a refined version was already saved.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved — call set_edl first")
    clip = edl.clip(clip_id)
    if clip is None:
        raise ValueError(f"no clip {clip_id!r} in EDL")

    existing = captions_mod.load_clip_words(project, clip_id)
    if existing is not None:
        words = existing
    else:
        master = transcript_mod.master_words(project)
        words = captions_mod.words_for_clip(master, clip, edl.timebase)

    return {
        "words": [{"text": w.text, "start": round(w.start, 3),
                  "end": round(w.end, 3), "line_break": w.line_break}
                 for w in words],
        "prompt": captions_mod.refinement_prompt(words, use_emojis, language),
        "duration": round(clip.duration, 3),
        "polished": existing is not None,
    }


@mcp.tool()
def set_clip_captions(project_id: str, clip_id: str, words: List[dict]) -> dict:
    """Save polished caption words for a clip (the JSON the prompt asks for:
    objects with text/start/end and optional line_break). Validated against the
    clip's duration and rejected if words are out of order or run past the end."""
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved")
    clip = edl.clip(clip_id)
    if clip is None:
        raise ValueError(f"no clip {clip_id!r} in EDL")

    parsed = captions_mod.words_from_payload(words)
    result = captions_mod.validate_words(parsed, clip.duration)
    if not result["ok"]:
        return {"ok": False, **result}
    path = captions_mod.save_clip_words(project, clip_id, parsed)
    return {"ok": True, "path": str(path), **result}


@mcp.tool()
def render_captions(project_id: str, clip_id: str,
                    preset: Optional[str] = None,
                    vertical_anchor: Optional[float] = None,
                    full_frame: bool = False,
                    scale_to_width: bool = False) -> dict:
    """Render the alpha caption overlay (.mov) for a clip.

    Strip-sized by default, matching the preset's own canvas — you position it
    by hand in Premiere. export_xml still places it on the top video track over
    the right time span, so the only manual step is nudging it vertically.

    full_frame=True renders the whole sequence frame so no positioning is
    needed, at roughly 1.5x the file size. Use it only if asked — hand
    positioning is the preferred workflow here.

    scale_to_width resizes the strip to the sequence width, scaling typography
    proportionally. Uses polished words if set_clip_captions has been called,
    otherwise the raw remapped transcript.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved")
    clip = edl.clip(clip_id)
    if clip is None:
        raise ValueError(f"no clip {clip_id!r} in EDL")

    words = captions_mod.load_clip_words(project, clip_id)
    polished = words is not None
    if words is None:
        master = transcript_mod.master_words(project)
        words = captions_mod.words_for_clip(master, clip, edl.timebase)

    compiled = compile_edl(edl, project.camera_map(), [clip_id])[0]
    style = captions_mod.build_style(
        preset, edl.frame_size, round(float(edl.timebase.fps)),
        full_frame=full_frame, vertical_anchor=vertical_anchor,
        scale_to_width=scale_to_width)
    with _quiet():
        out = captions_mod.render_captions(
            project, clip_id, words,
            duration=compiled.duration_seconds, style=style)
    return {"path": str(out), "polished": polished, "n_words": len(words),
           "duration_sec": compiled.duration_seconds,
           "canvas": [style.width, style.height],
           "vertical_anchor": style.vertical_anchor}


@mcp.tool()
def render_all_captions(project_id: str, preset: Optional[str] = None,
                        only_polished: bool = True,
                        force: bool = False) -> dict:
    """Render caption overlays for every clip in one call.

    At 14 clips an episode this replaces 14 round trips. Runs in the foreground
    (~11s per 60s clip, so a full episode is a couple of minutes) and skips
    clips already rendered unless force=True.

    only_polished=True (default) renders just the clips whose captions you've
    reviewed via set_clip_captions — the raw transcript is rarely worth burning
    a render on. Set False to render everything regardless.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved")

    master = transcript_mod.master_words(project)

    style = captions_mod.build_style(
        preset, edl.frame_size, round(float(edl.timebase.fps)))

    rendered, skipped, failed = [], [], []
    for clip in edl.clips:
        polished = captions_mod.load_clip_words(project, clip.id)
        if polished is None and only_polished:
            skipped.append({"clip_id": clip.id, "reason": "not polished"})
            continue
        if captions_mod.mov_path(project, clip.id).exists() and not force:
            skipped.append({"clip_id": clip.id, "reason": "already rendered"})
            continue

        words = polished if polished is not None else \
            captions_mod.words_for_clip(master, clip, edl.timebase)
        if not words:
            skipped.append({"clip_id": clip.id, "reason": "no words"})
            continue

        compiled = compile_edl(edl, project.camera_map(), [clip.id])[0]
        try:
            with _quiet():
                out = captions_mod.render_captions(
                    project, clip.id, words,
                    duration=compiled.duration_seconds, style=style)
        except Exception as e:      # one bad clip shouldn't lose the batch
            failed.append({"clip_id": clip.id, "error": str(e)})
            continue
        rendered.append({"clip_id": clip.id, "path": str(out),
                        "polished": polished is not None,
                        "duration_sec": compiled.duration_seconds})

    return {"rendered": rendered, "skipped": skipped, "failed": failed,
           "canvas": [style.width, style.height]}


@mcp.tool()
def caption_status(project_id: str) -> dict:
    """Per-clip caption state: polished yet, rendered yet, and how stale.

    At production volume this is the "what's left to do" view — call it instead
    of probing clips one at a time.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        return {"clips": [], "note": "no EDL saved"}

    edl_mtime = paths.mtime(project.edl_path) or 0
    out = []
    for clip in edl.clips:
        words_p = captions_mod.words_path(project, clip.id)
        mov_p = captions_mod.mov_path(project, clip.id)
        words_t = paths.mtime(words_p)
        mov_t = paths.mtime(mov_p)
        out.append({
            "clip_id": clip.id, "title": clip.title,
            "duration": round(clip.duration, 2),
            "polished": words_t is not None,
            "rendered": mov_t is not None,
            # The cut changed after the captions were made, so their program
            # timings no longer match picture — re-polish and re-render.
            "stale": bool(words_t and edl_mtime > words_t + 1),
        })
    return {"clips": out,
           "todo": [c["clip_id"] for c in out
                    if not c["rendered"] or c["stale"]]}


@mcp.tool()
def list_caption_presets() -> List[str]:
    """Caption style presets available for render_captions."""
    from caption_engine import presets as _presets
    return list(_presets.names())


# ── output ───────────────────────────────────────────────────────────────────

@mcp.tool()
def export_xml(project_id: str, out_path: Optional[str] = None,
               clip_ids: Optional[List[str]] = None,
               include_captions: bool = True) -> dict:
    """Compile the EDL to FCP7 XML (xmeml) and write it. Import via Premiere's
    File > Import — this is NOT FCPXML 1.x, which Premiere can't read. All
    clips land in one XML as separate sequences sharing the source media, so
    Premiere's project panel gets one bin item per camera, not one per clip.

    Any caption overlay already rendered by render_captions is placed on the top
    video track of its clip, so captions arrive on the timeline rather than as a
    file you drag in per clip. Pass include_captions=False to omit them.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved — call set_edl first")
    result = validate(edl, project.camera_ids, project.master_duration,
                      project.video_camera_ids)
    if not result["ok"]:
        raise ValueError(f"EDL has errors, fix before export: {result['errors']}")

    movs = captions_mod.caption_movs(project, edl) if include_captions else {}
    compiled = compile_edl(edl, project.camera_map(), clip_ids, movs)

    meta = dict(project.file_meta())
    meta.update(captions_mod.caption_file_meta(
        movs, edl.frame_size, edl.timebase,
        {c.id: c.duration for c in compiled}))

    out = out_path or str(project.exports_dir / f"{project.id}.xml")
    write_xmeml(compiled, out, project_name=project.name, file_meta=meta)

    captioned = [c.id for c in compiled if c.id in movs]
    warnings_ = list(result["warnings"])
    uncaptioned = [c.id for c in compiled if c.id not in movs]
    if include_captions and uncaptioned:
        warnings_.append(
            f"no caption overlay rendered for: {', '.join(uncaptioned)} "
            f"(run render_captions to include them)")
    return {
        "path": out,
        "n_clips": len(compiled),
        "captioned_clips": captioned,
        "clips": [{"id": c.id, "name": c.name,
                  "duration_frames": c.duration,
                  "duration_tc": c.timebase.to_timecode(c.duration)}
                 for c in compiled],
        "warnings": warnings_,
    }


@mcp.tool()
def export_preview(project_id: str, clip_id: str,
                   out_path: Optional[str] = None,
                   quality: str = "fast") -> dict:
    """Render one clip with ffmpeg so you can watch the cut before touching
    Premiere. Approximate: b-roll placeholders don't render (no footage yet),
    and only the pinned/first audio track plays — the real mix happens in
    Premiere."""
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved — call set_edl first")
    clip = edl.clip(clip_id)
    if clip is None:
        raise ValueError(f"no clip {clip_id!r} in EDL")
    compiled = compile_edl(edl, project.camera_map(), [clip_id])[0]
    out = out_path or str(project.exports_dir / f"{clip_id}_preview.mp4")
    with _quiet():
        render_preview(compiled, out, quality)
    return {"path": out, "duration_sec": compiled.duration_seconds}


@mcp.tool()
def attach_broll(project_id: str, clip_id: str, broll_id: str,
                 source_path: str, source_in: float = 0.0) -> dict:
    """Fill in a b-roll placeholder with real footage — the seam for a future
    b-roll pull pipeline. Turns the placeholder marker into a real V2 clip on
    the next export."""
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved")
    clip = edl.clip(clip_id)
    if clip is None:
        raise ValueError(f"no clip {clip_id!r} in EDL")
    b = next((x for x in clip.broll if x.id == broll_id), None)
    if b is None:
        raise ValueError(f"no b-roll {broll_id!r} in clip {clip_id!r}")
    b.source = source_path
    b.source_in = source_in
    b.status = "attached"
    edl.save(project.edl_path)
    return {"ok": True,
            "edl_summary": validate(edl, project.camera_ids,
                                    project.master_duration,
                                    project.video_camera_ids)["clips"]}


async def _run_stdio() -> None:
    """Hand-rolled version of FastMCP.run_stdio_async().

    FastMCP.run() calls mcp.server.stdio.stdio_server() with no arguments,
    which wraps whatever ``sys.stdout`` is *at that moment* — and by then this
    module has already repointed ``sys.stdout`` at stderr (see the top of this
    file). Calling it unmodified would silently route every JSON-RPC response
    into the redirect too, and the client would hang waiting on a stdout pipe
    that never receives anything. So the transport is wired up by hand here,
    explicitly against the real stdout handle saved before the redirect.
    """
    import anyio
    from mcp.server.stdio import stdio_server

    async with stdio_server(stdout=anyio.wrap_file(_real_stdout)) as (read, write):
        await mcp._mcp_server.run(
            read, write, mcp._mcp_server.create_initialization_options())


def main() -> None:
    import anyio
    anyio.run(_run_stdio)


if __name__ == "__main__":
    main()
