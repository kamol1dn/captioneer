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
import time  # noqa: E402
import warnings as _warnings  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import List, Optional  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

from . import captions as captions_mod  # noqa: E402
from . import energy as energy_mod  # noqa: E402
from . import graphics as graphics_mod  # noqa: E402
from . import stock as stock_mod  # noqa: E402
from . import paths  # noqa: E402
from . import sanity as sanity_mod  # noqa: E402
from . import verify as verify_mod  # noqa: E402
from . import ingest as ingest_mod  # noqa: E402
from . import transcript as transcript_mod  # noqa: E402
from caption_engine.transcriber.word import load_words  # noqa: E402

from .compile import compile_for, compile_for_monitor  # noqa: E402
from . import edl as edl_mod
from . import show as show_mod  # noqa: E402
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
                   project_dir: Optional[str] = None,
                   language: str = "",
                   caption_preset: str = "",
                   master_xml: str = "",
                   master_sequence: str = "") -> dict:
    """Register a new multicam project. Each camera export must share a common
    t=0 (same Premiere sequence, same range) — that's what lets the compiler
    skip sync/offset math by default.

    cameras: [{"id": "A", "path": "D:/episodes/EP12/for claude/CamA.mp4",
               "label": "host", "offset_sec": 0.0, "transcribe": false,
               "speaker": "host"}, ...]

    **Cutting from the episode timeline instead of flat exports.** Pass
    `master_xml` (an FCP7 XML exported from Premiere, plus `master_sequence` when
    the file holds more than one) and give an angle `"source_track": "V1"` in
    place of `"path"`. That angle's picture then comes from whatever V1 already
    points at, so it costs no video export at all — on a two-hour episode that
    replaces four 14 GB renders with one XML. Only the audio you want
    transcribed still has to be exported as media.

    Call `inspect_master_xml` first: it lists the sequences and, for the one you
    name, every track with its sources and coverage, which is how you decide
    which V-track is which angle. Two caveats it will tell you about — Premiere
    *drops* multicam items on export rather than flattening them (flatten or
    stack plain clips first, or the V-tracks come through empty), and a
    track-backed angle carries no sound of its own, so set the EDL's audio mode
    to `source_tracks` to reproduce the timeline's own audio bed.

    ``transcribe`` selects what ingest runs Whisper on, and defaults to the
    primary alone. A source may be audio-only (an mp3 mix sharing the same t=0):
    it can be transcribed and pinned as audio, but never cut to as picture, and
    it is held out of speaker scoring.

    **`speaker` groups several cameras onto one person.** Set it when a subject
    has more than one angle (a tight and a wide, say) — two cameras sharing a
    speaker are two angles on one voice, which is what lets you hide a jump cut
    by changing angle instead of punching in. Everything that answers "who is
    talking" then reasons about people: one transcription pass per speaker
    (flag the best mic with `transcribe: true` to choose which), and that
    person's mics merged into one loudness line. Omit it for the normal
    one-camera-per-subject setup — a camera's speaker defaults to its own id.

    Getting this wrong is expensive and quiet: leave two angles on one person
    ungrouped and a diarized ingest transcribes both mics, both clear bleed
    rejection, and every line that person says lands in the master twice — so
    every caption is doubled. `create_project` warns when it sees a group.

    **Set `language` here** — it is remembered and used by ingest, captions and
    verification without being passed again. Ask which show this is if it isn't
    stated:

    * Gashtak (Uzbek) — `language="uz"`, `caption_preset="gashtak_2"`.
      `uz` routes transcription to the Kotib Uzbek model with MMS alignment
      (Whisper's own Uzbek is much weaker) and selects the Uzbek refinement
      prompt, with its `o‘`/`g‘` orthography and Russian-code-switch rules.
    * OTG (English) — `language="en"`, `caption_preset="otg_cyan"`.

    Leaving `language` empty means auto-detect, which on Uzbek audio quietly
    produces a mediocre English-prompt transcript. `caption_preset` defaults to
    gashtak_2 at render time.

    The project is created as `clipper/` beside the media, so the episode folder
    stays self-contained and movable; pass project_dir to override. Returns
    camera durations/fps plus warnings about fps or duration mismatches or a
    non-zero start timecode — any of those silently break the shared-t=0
    assumption if ignored.
    """
    with _quiet():
        project, warnings_ = create(name, cameras, primary_audio_camera,
                                   project_dir=project_dir,
                                   language=language,
                                   caption_preset=caption_preset,
                                   master_xml=master_xml,
                                   master_sequence=master_sequence)
    if not project.language:
        warnings_.append(
            "no language set — transcription will auto-detect and captions "
            "will use the English prompt; pass language='uz' for Gashtak")
    return {
        "project_id": project.id,
        "language": project.language,
        "caption_preset": project.caption_preset or captions_mod.DEFAULT_PRESET,
        "project_dir": str(project.dir),
        "media_dir": str(project.media_dir),
        "cameras": [{"id": c.id, "label": c.label, "duration": c.duration,
                    "speaker": c.speaker_id,
                    "source_track": c.source_track,
                    "fps": str(c.probe.get("fps")), "width": c.probe.get("width"),
                    "height": c.probe.get("height"),
                    "has_audio": c.probe.get("has_audio")}
                   for c in project.cameras],
        "speakers": project.speaker_map(),
        "primary_audio_camera": project.primary_audio_camera,
        "master_xml": project.master_xml,
        "warnings": warnings_,
    }


@mcp.tool()
def inspect_master_xml(xml_path: str, sequence: Optional[str] = None) -> dict:
    """Look inside an FCP7 XML exported from Premiere before building a project.

    Call this first when cutting from an episode timeline rather than from flat
    per-angle exports. With no `sequence` it lists what the document holds; name
    one and you get every track with its sources, how much of the timeline it
    covers, and whether it is a nested sequence — which is how you work out
    which V-track is which angle, and which A-tracks carry the sound.

    What to look for:

    * **All video tracks empty** — Premiere skipped multicam items instead of
      flattening them. Flatten the multicams (or stack the angles as plain
      clips) and export again; the translation-results log names the cause.
    * **Coverage well under 100%** on a V-track means that angle has stretches
      with no footage, and clips landing there will have no picture on it.
    * **Audio coverage** is usually split across many tracks — an enhanced mix
      often covers only part of the episode — which is why the reel takes the
      whole bed rather than one pinned source.
    """
    from .xmeml.reader import list_sequences, read_master
    if not sequence:
        seqs = list_sequences(xml_path)
        return {
            "path": xml_path,
            "sequences": seqs,
            "note": ("name one of these as `sequence` for its tracks"
                     if len(seqs) > 1 else
                     "one sequence; pass its name for track detail"),
        }
    return read_master(xml_path, sequence).summary()


@mcp.tool(name="list_projects")
def list_projects_tool() -> List[dict]:
    """List all clipper projects."""
    return _list_projects()


@mcp.tool()
def set_project_defaults(project_id: str, language: Optional[str] = None,
                        caption_preset: Optional[str] = None,
                        show: Optional[str] = None) -> dict:
    """Set the project's language, caption preset and/or show after the fact.

    For a project created before any of them was recorded, or created under the
    wrong show. All three are what every later call defaults to, so this is the
    one place to fix them — don't hand-edit project.json.

    Gashtak is `language="uz"`, `caption_preset="gashtak_2"`, `show="gashtak"`;
    OTG is `"en"`, `"otg_cyan"`, `"otg"`. `show` is what decides which graphics
    templates exist, which whooshes `add_transition` can reach and whether reels
    end on a tail card — `list_shows` has the current ones. Changing the
    language does **not** re-transcribe: if the transcript was produced with the
    wrong one, re-run ingest.
    """
    project = _load(project_id)
    if show is not None:
        known = show_mod.known()
        if show and show not in known:
            raise ValueError(f"unknown show {show!r}; have {known} "
                             f"(a show is a shows/<id>.json in the repo)")
        project.show_id = show
    if caption_preset:
        from caption_engine import presets as _presets
        # Fail here rather than at render time, three steps later.
        known = _presets.names()
        if caption_preset not in known:
            raise ValueError(f"unknown preset {caption_preset!r}; have {known}")
        project.caption_preset = caption_preset
    if language is not None:
        project.language = language.strip().lower()
    project.save()
    return {"project_id": project.id, "language": project.language,
           "caption_preset": project.caption_preset or captions_mod.DEFAULT_PRESET,
           "show": project.show_id,
           "note": ("transcript was produced under the previous language; "
                    "re-run ingest if it was wrong")
                   if language is not None and project.ingest_state.get(
                       "state") == "done" else ""}


@mcp.tool()
def get_project(project_id: str) -> dict:
    """Full project state: cameras, timebase, speakers, ingest status, EDL
    summary.

    `speakers` is {person: [camera ids]} — a person with more than one entry has
    a second angle you can cut to instead of leaving a jump cut.
    """
    project = _load(project_id)
    d = project.to_dict()
    d["project_dir"] = str(project.dir)
    d["media_dir"] = str(project.media_dir)
    d["speakers"] = project.speaker_map()
    dressing = project.show()
    d["show"] = {"id": project.show_id, "name": dressing.name,
                 "graphics": dressing.graphics,
                 "transitions": sorted(dressing.transitions),
                 "outro": bool(dressing.outro),
                 "outro_rendered": bool(project.outro_mov())}
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

    * **diarize=True** — transcribe one mic per *speaker* separately and merge
      them into one speaker-labelled timeline. Costs one Whisper pass per
      speaker and needs at least two, but each line comes back attributed,
      overlapping speech survives on both mics, and captions are cut from each
      speaker's own isolated mic. Every mic hears the whole room, so bleed is
      rejected per word against the energy envelopes; `ingest_status` reports
      how much of each speaker's transcript survived, under `diarization`,
      alongside `mics` (which camera spoke for which person) and
      `picture_only` (angles that were never transcribed because a colleague
      camera already covers that voice).

      Two angles on one person count as **one** speaker, so grouping them via
      the camera's `speaker` field is what keeps this from transcribing the same
      voice twice and doubling every line they said.

    A combined mix is never a diarization target — it contains every voice at
    once and would win every bleed comparison. Register it as an audio-only
    source and it stays available to pin as the audio you hear.

    `cameras` filters which cameras this run touches.

    `language` defaults to the project's own (set at create_project) and is
    saved back when passed here, so a project created without one can be
    corrected on the first ingest. "uz" transcribes with the Kotib Uzbek model
    plus MMS forced alignment instead of WhisperX; anything else (including
    empty, which auto-detects) goes through WhisperX.
    """
    project = _load(project_id)
    language = (language or project.language or "").strip().lower()
    if language and language != project.language:
        project.language = language
        project.save()
    with _quiet():
        job = ingest_mod.start_ingest(project, model_size, language or None,
                                      cameras, diarize=diarize)
    return {"job_id": job.id, "language": language or "auto-detect"}


@mcp.tool()
def ingest_status(project_id: str) -> dict:
    """Poll ingest progress: {state, progress, message, per_camera}."""
    return ingest_mod.ingest_status(_load(project_id))


# ── content inspection ──────────────────────────────────────────────────────

@mcp.tool()
def get_outline(project_id: str, bucket_sec: float = 20.0,
                start: float = 0.0, end: Optional[float] = None) -> str:
    """A map of the whole episode: one line per ~20s bucket showing the likely
    speaker, utterance count, and a text snippet. Read this before
    get_transcript — a 1-hour episode outlines in about 2k tokens."""
    project = _load(project_id)
    utterances = transcript_mod.load_utterances(project)
    # Who is talking is a question about people, so a speaker with two cameras
    # is scored as one line rather than competing with themselves.
    envelopes = ingest_mod.load_envelopes(project, by_speaker=True)
    return transcript_mod.build_outline(utterances, envelopes, bucket_sec,
                                        start, end)


@mcp.tool()
def get_transcript(project_id: str, start: float = 0.0,
                   end: Optional[float] = None, max_chars: int = 8000) -> dict:
    """Word-adjacent transcript text for a time window, with a per-utterance
    energy line (e.g. 'A88 B09 C04') showing which speaker's mic was loudest —
    that's the speaker-ID signal; there is no diarization model. Labels are
    speakers, so a person with two cameras appears once. Capped at max_chars
    (hard ceiling 20000); truncated=True means call again with
    start=next_start."""
    project = _load(project_id)
    utterances = transcript_mod.load_utterances(project)
    envelopes = ingest_mod.load_envelopes(project, by_speaker=True)
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
def get_energy(project_id: str, start: float, end: float,
              by_speaker: bool = False) -> dict:
    """Normalized 0-99 loudness per camera over a window — the raw signal
    behind the transcript's energy line, useful when you need a finer look
    than one utterance's average.

    `by_speaker=True` merges each person's cameras into one score. Use it to ask
    *who is talking*; leave it off to ask which angle is hottest. They differ
    only when a speaker owns more than one camera.
    """
    project = _load(project_id)
    envelopes = ingest_mod.load_envelopes(project, by_speaker=by_speaker)
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

    The dangling/filler/continuation word lists are English. On an Uzbek project
    only the language-neutral checks fire — punctuation, gaps, empty segments —
    so a thin report means less here than it does in English; read the joins
    yourself with get_transcript.
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
    partial = project.language not in ("", "en")
    note = (f"note: the word-list checks are English-only; on a "
            f"{project.language!r} project only punctuation and gap checks ran")
    if as_text:
        text = sanity_mod.format_report(reports, min_confidence)
        return f"{note}\n\n{text}" if partial else text
    out = {"clips": reports,
           "n_issues": sum(len(r["issues"]) for r in reports)}
    if partial:
        out["note"] = note
    return out


@mcp.tool()
def verify_clip_audio(project_id: str, clip_ids: Optional[List[str]] = None,
                      model_size: str = "base", as_text: bool = True,
                      min_confidence: str = "high",
                      language: Optional[str] = None):
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

    `language` defaults to the project's. It matters more here than elsewhere:
    re-transcribing Uzbek audio with an auto-detecting Whisper produces a
    "heard" transcript that shares almost no words with the plan, and every
    line of the diff becomes a false mismatch. On "uz" the pass runs through
    Kotib, and `model_size` is ignored (that backend has a fixed model), so it
    costs the same as a full Uzbek transcription of each clip.
    """
    project = _load(project_id)
    language = (language or project.language or "").strip().lower() or None
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
            compiled = compile_for_monitor(project, edl, [clip.id])[0]
            wav = verify_mod.export_clip_audio(compiled, work / f"{clip.id}.wav")
            heard = verify_mod.transcribe_file(
                wav, work / f"{clip.id}.heard.json", model_size=model_size,
                language=language)
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

    Returns {words, prompt, language, duration, polished}. Read `prompt` — it
    carries the project's own tuned rules (capitalization, number handling,
    Uzbek orthography, emoji placement, line_break decisions) from prompts.txt
    — apply them to `words`, then send the result to set_clip_captions.
    `polished` says whether a refined version was already saved.

    `language` defaults to the project's, so an Uzbek project gets the Uzbek
    prompt without asking; pass it only to override for one clip.
    """
    project = _load(project_id)
    language = (language or project.language or "").strip().lower()
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
        "prompt": captions_mod.refinement_prompt(words, use_emojis,
                                                 language or None),
        "language": language or "en",
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

    `preset` defaults to the project's own (set at create_project), and to
    gashtak_2 if the project doesn't name one.
    """
    project = _load(project_id)
    preset = preset or project.caption_preset or None
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

    compiled = compile_for(project, edl, [clip_id])[0]
    style = captions_mod.build_style(
        preset, edl.frame_size, round(float(edl.timebase.fps)),
        full_frame=full_frame, vertical_anchor=vertical_anchor,
        scale_to_width=scale_to_width)
    with _quiet():
        out = captions_mod.render_captions(
            project, clip_id, words,
            duration=compiled.duration_seconds, style=style)
    return {"path": str(out), "polished": polished, "n_words": len(words),
           "preset": preset or captions_mod.DEFAULT_PRESET,
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

    `preset` defaults to the project's own, then to gashtak_2.
    """
    project = _load(project_id)
    preset = preset or project.caption_preset or None
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

        compiled = compile_for(project, edl, [clip.id])[0]
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
           "preset": preset or captions_mod.DEFAULT_PRESET,
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
    compiled = compile_for(project, edl, clip_ids, movs)

    meta = dict(project.file_meta())
    meta.update(captions_mod.caption_file_meta(
        movs, edl.frame_size, edl.timebase,
        {c.id: c.duration for c in compiled}))
    broll_meta, broll_warnings = stock_mod.broll_file_meta(edl)
    meta.update(broll_meta)
    dressing = project.show()
    meta.update(show_mod.file_meta(
        dressing, edl.frame_size, edl.timebase, project.outro_mov(),
        dressing.outro.hold if dressing.outro else 0))

    out = out_path or str(project.exports_dir / f"{project.id}.xml")
    write_xmeml(compiled, out, project_name=project.name, file_meta=meta)

    captioned = [c.id for c in compiled if c.id in movs]
    warnings_ = (list(result["warnings"]) + broll_warnings
                 + graphics_mod.stale_graphics(edl)
                 + graphics_mod.hook_conflicts(edl))
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
    compiled = compile_for_monitor(project, edl, [clip_id])[0]
    out = out_path or str(project.exports_dir / f"{clip_id}_preview.mp4")
    with _quiet():
        render_preview(compiled, out, quality)
    return {"path": out, "duration_sec": compiled.duration_seconds}


# ── B-roll and graphics ──────────────────────────────────────────────────────
#
# The graphics pass is a second session over a finished cut, so these tools reach
# ``broll`` and ``markers`` and nothing else. ``set_edl`` would work too, but it
# replaces the whole document: a session that never watched the cut being snapped
# would be rewriting every segment boundary to change one overlay, and a slightly
# wrong reconstruction still validates. Narrow tools make that mistake
# unavailable rather than merely unlikely.


def _clip_or_raise(project, edl, clip_id: str):
    if edl is None:
        raise ValueError("no EDL saved — call set_edl first")
    clip = edl.clip(clip_id)
    if clip is None:
        raise ValueError(f"no clip {clip_id!r} in EDL")
    return clip


def _save_graphics_edit(project, edl, clip, **extra) -> dict:
    """Validate, persist only if clean, and echo the clip's graphics either way.

    Same contract as ``set_edl`` — a rejected edit is not written. Echoing the
    lists back means the caller sees the state it just produced without a second
    round trip, which is most of what a b-roll pass spends calls on.
    """
    result = validate(edl, project.camera_ids, project.master_duration,
                      project.video_camera_ids)
    if result["ok"]:
        edl.save(project.edl_path)
    return {"ok": result["ok"], "saved": result["ok"],
            "errors": result["errors"],
            "warnings": (result["warnings"] + graphics_mod.stale_graphics(edl)
                         + graphics_mod.hook_conflicts(edl)),
            "clip_id": clip.id,
            "broll": [dict(vars(b)) for b in clip.broll],
            "transitions": [dict(vars(t)) for t in clip.transitions],
            "markers": [dict(vars(m)) for m in clip.markers],
            **extra}


@mcp.tool()
def convert_clip_times(project_id: str, clip_id: str, times: List[float],
                       to: str = "master") -> dict:
    """Convert between a clip's program time and master time.

    **The graphics pass reads in one and writes in the other**, which is the
    easiest way to place something 30 seconds from where you meant it. The words
    from `get_clip_captions` are in *program* time — seconds from the start of
    the short, what you hear. Everything in the EDL, `add_broll` included, is in
    *master* time on the original episode timeline. A clip made of three
    segments has three different offsets between them.

    `to="master"` converts caption/player times into what `add_broll` wants;
    `to="program"` goes the other way, for reading an existing entry against the
    words. Frame-exact, by the same rule the compiler uses for picture.

    A null in the result means that time isn't in this clip — trimmed out, or
    past the end. That is an answer, not an error: don't substitute a nearby
    value for it.
    """
    if to not in ("master", "program"):
        raise ValueError(f"to must be 'master' or 'program', not {to!r}")
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    clip = _clip_or_raise(project, edl, clip_id)
    fn = captions_mod.to_master if to == "master" else captions_mod.to_program
    converted = [fn(clip, edl.timebase, t) for t in times]
    return {"clip_id": clip_id, "to": to,
            "times": [None if v is None else round(v, 3) for v in converted],
            "clip_duration": round(clip.duration, 3)}


@mcp.tool()
def add_broll(project_id: str, clip_id: str, start: float, end: float,
              kind: str = "footage", query: str = "", broll_id: str = "",
              source: Optional[str] = None, source_in: float = 0.0,
              audio: str = "mute") -> dict:
    """Add one b-roll or graphic to a clip without touching the cut.

    `kind` is "footage" (full-frame, replaces the picture for its duration) or
    "overlay" (an alpha graphic on top of it — a stat animation, a screenshot
    card, a lower third). They compile to separate tracks, so an overlay may run
    over footage; two of the same kind may not overlap.

    `start`/`end` are **master seconds**, like everything else in the EDL, and
    must fall inside one of the clip's kept segments — not program seconds
    counted from the start of the short.

    Leave `source` empty for a placeholder: it exports as a timeline marker
    carrying `query`, so the intent reaches the editor without Premiere nagging
    about offline media. Fill it in later with `attach_broll`.

    Returns the clip's full b-roll list. Rejected edits are not saved.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    clip = _clip_or_raise(project, edl, clip_id)
    b = edl_mod.add_broll(clip, start=start, end=end, kind=kind, query=query,
                          broll_id=broll_id, source=source,
                          source_in=source_in, audio=audio)
    return _save_graphics_edit(project, edl, clip, added=b.id)


@mcp.tool()
def remove_broll(project_id: str, clip_id: str, broll_id: str) -> dict:
    """Drop one b-roll entry from a clip. Leaves the cut untouched."""
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    clip = _clip_or_raise(project, edl, clip_id)
    edl_mod.remove_broll(clip, broll_id)
    return _save_graphics_edit(project, edl, clip, removed=broll_id)


@mcp.tool()
def set_clip_broll(project_id: str, clip_id: str, broll: List[dict]) -> dict:
    """Replace one clip's entire b-roll list, leaving the cut untouched.

    Use this when laying out a whole clip's graphics at once; `add_broll` is the
    better call for a single addition. Each entry takes {start, end, kind, query,
    id, source, source_in, audio} — see `add_broll` for what they mean. An empty
    list clears the clip's b-roll.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    clip = _clip_or_raise(project, edl, clip_id)
    clip.broll = edl_mod.parse_broll(broll)
    return _save_graphics_edit(project, edl, clip)


@mcp.tool()
def set_clip_markers(project_id: str, clip_id: str, markers: List[dict]) -> dict:
    """Replace one clip's timeline markers, leaving the cut untouched.

    Each entry is {at, name, comment}, `at` in master seconds. Markers are how an
    idea reaches the editor without committing to a file — a note about what a
    moment needs, readable in Premiere's timeline. An empty list clears them.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    clip = _clip_or_raise(project, edl, clip_id)
    clip.markers = edl_mod.parse_markers(markers)
    return _save_graphics_edit(project, edl, clip)


@mcp.tool()
def list_shows() -> dict:
    """The shows a project can wear, and what each one dresses a reel with.

    A show is the look that isn't the cut: which whoosh covers a cutaway and how
    loud it sits, which graphics family the cards come from, whether reels end
    on a tail card. Set one with `set_project_defaults(show=...)`.
    """
    out = {}
    for sid in show_mod.known():
        sh = show_mod.load(sid)
        out[sid] = {
            "name": sh.name, "graphics": sh.graphics,
            "transitions": {k: {"seconds": t.seconds, "gain_db": t.gain_db,
                                "composite": t.composite,
                                "exists": Path(t.path).is_file()}
                            for k, t in sh.transitions.items()},
            "default_transition": sh.default_transition,
            "outro": ({"template": sh.outro.template,
                       "hold_frames": sh.outro.hold,
                       "props": sh.outro.props} if sh.outro else None),
        }
    return {"shows": out}


@mcp.tool()
def add_transition(project_id: str, clip_id: str, at: float,
                   asset: str = "", transition_id: str = "",
                   note: str = "") -> dict:
    """Lay one of the show's whooshes across a cut.

    `at` is the **master second** of the cut it covers, like every other time in
    the EDL. The asset straddles that instant — its flash frame lands exactly
    there and its head runs before it — so pass the moment the picture changes,
    not the moment you want the effect to start.

    Where these earn their place: going into and out of a cutaway, and on a
    stitch between two non-adjacent parts of the conversation. On an ordinary
    same-angle jump cut they read as decoration; the compiler's own punch-in
    already hides those.

    `asset` names one of the show's transitions (`list_shows`); empty uses the
    show's default. A project with no show gets a timeline marker instead of a
    clip, so the intent still reaches the editor.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    clip = _clip_or_raise(project, edl, clip_id)
    known = project.show().transitions
    if asset and asset not in known:
        raise ValueError(f"no transition {asset!r} in show "
                         f"{project.show_id or 'none'!r}; have "
                         f"{sorted(known)}")
    if transition_id and any(t.id == transition_id for t in clip.transitions):
        raise ValueError(f"transition {transition_id!r} already exists on clip "
                         f"{clip_id!r}")
    clip.transitions = edl_mod.parse_transitions(
        [dict(vars(t)) for t in clip.transitions]
        + [{"at": at, "id": transition_id, "asset": asset, "note": note}])
    return _save_graphics_edit(project, edl, clip)


@mcp.tool()
def remove_transition(project_id: str, clip_id: str,
                      transition_id: str) -> dict:
    """Drop one whoosh from a clip. Leaves the cut untouched."""
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    clip = _clip_or_raise(project, edl, clip_id)
    t = next((x for x in clip.transitions if x.id == transition_id), None)
    if t is None:
        raise ValueError(f"no transition {transition_id!r} on clip {clip_id!r}")
    clip.transitions.remove(t)
    return _save_graphics_edit(project, edl, clip, removed=transition_id)


@mcp.tool()
def set_clip_transitions(project_id: str, clip_id: str,
                         transitions: List[dict]) -> dict:
    """Replace one clip's whooshes, leaving the cut untouched.

    Each entry is {at, asset, id, note} — see `add_transition`. Use this when
    laying out a whole clip at once; an empty list clears them.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    clip = _clip_or_raise(project, edl, clip_id)
    clip.transitions = edl_mod.parse_transitions(transitions)
    return _save_graphics_edit(project, edl, clip)


@mcp.tool()
def render_outro(project_id: str) -> dict:
    """Render the show's tail card once for the whole project.

    Until this exists on disk the compiler exports reels that end on the cut:
    it will not hold ten seconds of picture under a card that was never made.
    One file serves every clip — the card says the same thing on each.

    Re-run it after editing the show's `outro` block in `shows/<id>.json`.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved — call set_edl first")
    sh = project.show()
    jobs, errors = graphics_mod.plan_outro(edl, sh, project.graphics_dir)
    if errors or not jobs:
        return {"ok": False, "errors": errors or ["nothing to render"]}
    with _quiet():
        results = graphics_mod.render(jobs, edl)
    r, job = results[0], jobs[0]
    if not r.get("ok"):
        return {"ok": False, "errors": [r.get("error") or "render failed"]}
    return {"ok": True, "path": str(job.out), "check": str(job.still),
            "frames": job.frames,
            "seconds": round(edl.timebase.to_seconds(job.frames), 2),
            "note": "every clip's reel now runs this much longer than its cut"}


@mcp.tool()
def attach_broll(project_id: str, clip_id: str, broll_id: str,
                 source_path: str, source_in: float = 0.0) -> dict:
    """Fill in a b-roll placeholder with a real file — the seam the footage and
    animation passes deliver through. Turns the placeholder marker into a real
    clip on its kind's track at the next export.

    `source_in` is where to start inside the source file, in seconds."""
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    clip = _clip_or_raise(project, edl, clip_id)
    b = next((x for x in clip.broll if x.id == broll_id), None)
    if b is None:
        raise ValueError(f"no b-roll {broll_id!r} in clip {clip_id!r}")
    b.source = source_path
    b.source_in = source_in
    b.status = "attached"
    # A hand-attached file is not the template render any more; keeping the
    # record would let a later re-render silently replace it.
    b.graphic = None
    try:
        b.media = stock_mod.media_info(source_path)
    except Exception:
        b.media = None  # export probes again; a failed probe is not fatal here
    return _save_graphics_edit(project, edl, clip, attached=broll_id)


@mcp.tool()
def set_clip_hook(project_id: str, clip_id: str, text: str,
                  seconds: float = 3.0, kicker: str = "",
                  position: str = "") -> dict:
    """Set a clip's opening hook title — the line read in the first seconds.

    Separate from b-roll on purpose: the hook is anchored to the start of the
    short, not to a moment on the master timeline, and runs across the first
    cuts. It renders onto its own track above the cards (`render_hooks`), so an
    early card can't collide with it on the timeline — but hook_conflicts still
    warns when one starts underneath it.

    `text`: 7 words or fewer, the number or the tension first. Wrap the phrase
    that carries the tension in *asterisks* to put it on the highlighter; a
    newline forces a line break. `seconds`: how long it holds (2.5-3.5 is the
    window). Empty `text` removes the hook. Setting it clears any rendered file,
    so render_hooks afterwards.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    clip = _clip_or_raise(project, edl, clip_id)
    if not text.strip():
        clip.hook = None
        return _save_graphics_edit(project, edl, clip, hook=None)
    props = {"text": text.strip()}
    if kicker:
        props["kicker"] = kicker
    if position:
        props["position"] = position
    problems = graphics_mod.check_props("Hook", props)
    if problems:
        raise ValueError("; ".join(problems))
    clip.hook = {"template": "Hook", "props": props, "seconds": float(seconds)}
    return _save_graphics_edit(project, edl, clip, hook=clip.hook)


@mcp.tool()
def render_hooks(project_id: str, clip_ids: Optional[List[str]] = None) -> dict:
    """Render the hook titles set with set_clip_hook and attach them.

    Every clip with a hook, or just `clip_ids`. One call renders them all —
    bundling is most of the cost. Returns a `check` PNG per clip (the hook over
    the clip's own frame at about two seconds in); read them.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved — call set_edl first")
    jobs, errors = graphics_mod.plan_hooks(edl, clip_ids, project.dir / "graphics")
    if errors or not jobs:
        return {"ok": False, "rendered": 0,
                "errors": errors or ["no hooks set — use set_clip_hook"]}
    with _quiet():
        results = graphics_mod.render(jobs, edl)

    edl = EDL.load(project.edl_path)
    report = []
    for job, r in zip(jobs, results):
        clip = edl.clip(job.clip_id)
        if not r.get("ok") or clip is None or not clip.hook:
            report.append({"clip_id": job.clip_id, "ok": False,
                           "error": r.get("error") or "hook removed while rendering"})
            continue
        clip.hook.update(source=str(job.out), frames=job.frames)
        check = job.out.with_suffix(".check.png")
        try:
            compiled = compile_for_monitor(project, edl, [job.clip_id])[0]
            bg = graphics_mod.grab_program_frame(
                compiled, int(job.frames * 0.6), job.out.with_suffix(".bg.png"))
            graphics_mod.composite_check(job.still, bg, check, edl.frame_size)
            if bg:
                bg.unlink(missing_ok=True)
        except Exception:
            check = job.still
        report.append({"clip_id": job.clip_id, "ok": True, "path": str(job.out),
                       "check": str(check), "frames": job.frames})
    result = validate(edl, project.camera_ids, project.master_duration,
                      project.video_camera_ids)
    if result["ok"]:
        edl.save(project.edl_path)
    return {"ok": result["ok"] and all(x["ok"] for x in report),
            "saved": result["ok"], "rendered": sum(x["ok"] for x in report),
            "items": report, "errors": result["errors"],
            "warnings": (result["warnings"] + graphics_mod.stale_graphics(edl)
                         + graphics_mod.hook_conflicts(edl))}


@mcp.tool()
def set_broll_candidates(project_id: str, clip_id: str, broll_id: str,
                         candidates: List[dict]) -> dict:
    """Record the stock shortlist for a footage placeholder.

    Each candidate is {url, title, note}: the item page, its title as the site
    shows it, and one line on why it fits. They travel into the placeholder's
    Premiere marker, and `collect_broll` uses them to match downloads back to
    this entry — so record them for every placeholder you shortlist for, in the
    order you hand them to the user.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    clip = _clip_or_raise(project, edl, clip_id)
    b = next((x for x in clip.broll if x.id == broll_id), None)
    if b is None:
        raise ValueError(f"no b-roll {broll_id!r} in clip {clip_id!r}")
    cleaned = []
    for i, c in enumerate(candidates):
        unknown = sorted(set(c) - {"url", "title", "note"})
        if unknown or not c.get("url"):
            raise ValueError(f"candidate #{i}: needs a url; allowed fields are "
                             f"url, title, note (got {sorted(c)})")
        cleaned.append({k: str(v) for k, v in c.items() if v})
    b.candidates = cleaned or None
    return _save_graphics_edit(project, edl, clip, updated=broll_id)


@mcp.tool()
def collect_broll(project_id: str, assign: Optional[List[dict]] = None,
                  folders: Optional[List[str]] = None,
                  since_hours: float = 12.0) -> dict:
    """Pick up stock footage the user downloaded and attach it to placeholders.

    **Without `assign`** — look, don't touch: lists video files that arrived in
    `folders` (default: the user's Downloads) in the last `since_hours`, each
    with its size, rate, length and a `sheet` — three frames side by side — plus
    the footage placeholders still waiting and a suggested pairing. **Read every
    sheet** before assigning: names on stock downloads rarely match the item,
    and suggestions marked "download order" are guesses.

    **With `assign`** — [{file, clip_id, broll_id, source_in?}]: moves each file
    into the episode's `broll/` folder, conforms its frame rate to the sequence
    if it differs, records its size so the export scales it to fill the vertical
    frame, and attaches it. `source_in` (seconds into the file) defaults to 1s
    in, where there is room. Rejected edits are not saved.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved — call set_edl first")
    broll_dir = project.media_dir / "broll"

    if not assign:
        dirs = [Path(f) for f in folders] if folders else stock_mod.default_folders()
        since = time.time() - since_hours * 3600
        files = stock_mod.scan(dirs, since, broll_dir / "_unzipped")
        listed = []
        for f in files:
            try:
                info = stock_mod.media_info(f)
            except Exception as e:
                listed.append({"file": str(f), "error": f"could not probe: {e}"})
                continue
            sheet = stock_mod.contact_sheet(
                f, project.dir / "stock_sheets" / f"{f.stem}.jpg", info["duration"])
            listed.append({"file": str(f),
                           "size_mb": round(f.stat().st_size / 1e6, 1),
                           **info, "sheet": str(sheet) if sheet else None})
        slots = stock_mod.pending_slots(edl)
        return {
            "files": listed,
            "waiting": [{"clip_id": c.id, "broll_id": b.id, "query": b.query,
                         "seconds": round(b.end - b.start, 2),
                         "candidates": b.candidates or []} for c, b in slots],
            "suggested": stock_mod.suggest(files, slots),
            "searched": [str(d) for d in dirs],
        }

    results, touched = [], {}
    for i, a in enumerate(assign):
        unknown = sorted(set(a) - {"file", "clip_id", "broll_id", "source_in"})
        if unknown:
            raise ValueError(f"assign #{i}: unknown field(s) {', '.join(unknown)}")
        f = Path(a.get("file", ""))
        if not f.is_file():
            raise ValueError(f"assign #{i}: {f} is not a file")
        clip = _clip_or_raise(project, edl, a.get("clip_id", ""))
        b = next((x for x in clip.broll if x.id == a.get("broll_id")), None)
        if b is None:
            raise ValueError(f"assign #{i}: no b-roll {a.get('broll_id')!r} on "
                             f"clip {clip.id!r}")
        with _quiet():
            results.append(stock_mod.take(f, broll_dir, clip, b, edl.timebase,
                                          a.get("source_in")))
        touched[clip.id] = clip

    result = validate(edl, project.camera_ids, project.master_duration,
                      project.video_camera_ids)
    if result["ok"]:
        edl.save(project.edl_path)
    return {"ok": result["ok"], "saved": result["ok"], "attached": results,
            "errors": result["errors"], "warnings": result["warnings"]}


@mcp.tool()
def list_graphic_templates(project_id: Optional[str] = None) -> dict:
    """The animated graphics `render_graphics` can make, with their props.

    Each renders as an alpha ProRes overlay sized to the sequence and timed to
    the b-roll entry it fills, with its entrance and exit animation baked in —
    so nothing needs a dissolve applied by hand in Premiere.

    Scoped to the project's show, because the two shows have two looks and a
    Gashtak reel wearing an OTG chart is a mistake nobody catches until it is
    published. Omit `project_id` for the OTG set.
    """
    show_id = _load(project_id).show_id if project_id else ""
    return {"show": show_id or "otg", "templates": {
        name: {k: spec[k] for k in ("description", "props", "required", "example")}
        for name, spec in graphics_mod.for_show(show_id).items()}}


@mcp.tool()
def render_graphics(project_id: str, items: List[dict]) -> dict:
    """Render animated graphics onto overlay b-roll entries and attach them.

    Each item is {clip_id, broll_id, template, props}. The entry must already
    exist (`add_broll` with kind="overlay"); its length on the finished short
    decides the file's length, frame-exact, and size and rate come from the
    sequence. Omit `template`/`props` to **re-render** an entry from what it was
    last rendered with — the thing to do after moving or resizing one.

    Image props (a screenshot, a logo) take an absolute path on disk.

    Batch them: the renderer bundles once per call, which is most of the cost.
    Every item is checked before anything renders, and nothing is attached
    unless the whole batch validates.

    Returns per item the .mov and a `check` PNG — the graphic composited over
    the camera frame it will sit on. **Look at the checks** before calling it
    done: that is where a card covering a face or an overflowing headline shows.
    """
    project = _load(project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        raise ValueError("no EDL saved — call set_edl first")

    # Fill re-render requests from what each entry was last rendered with.
    resolved = []
    for i, item in enumerate(items):
        item = dict(item)
        if not item.get("template"):
            clip = edl.clip(item.get("clip_id", ""))
            b = clip and next((x for x in clip.broll
                               if x.id == item.get("broll_id")), None)
            if not b or not b.graphic:
                raise ValueError(f"item #{i}: no template given and "
                                 f"{item.get('clip_id')}/{item.get('broll_id')} "
                                 f"has never been rendered")
            item["template"] = b.graphic["template"]
            item.setdefault("props", b.graphic.get("props") or {})
        resolved.append(item)

    out_dir = project.dir / "graphics"
    jobs, errors = graphics_mod.plan_jobs(edl, resolved, out_dir)
    if errors:
        return {"ok": False, "rendered": 0, "errors": errors}

    with _quiet():
        results = graphics_mod.render(jobs, edl)

    # Re-read before writing: a render takes minutes, and the EDL on disk is the
    # one to attach to, not the copy loaded before it started.
    edl = EDL.load(project.edl_path)
    compiled = {}
    report, touched = [], set()
    for job, r in zip(jobs, results):
        entry = {"clip_id": job.clip_id, "broll_id": job.broll_id,
                 "template": job.template}
        if not r.get("ok"):
            report.append({**entry, "ok": False, "error": r.get("error")})
            continue
        clip = edl.clip(job.clip_id)
        b = clip and next((x for x in clip.broll if x.id == job.broll_id), None)
        if b is None:
            report.append({**entry, "ok": False,
                           "error": "entry was removed while rendering"})
            continue
        b.source, b.source_in, b.status = str(job.out), 0.0, "attached"
        b.graphic = {"template": job.template, "props": job.props,
                     "frames": job.frames}
        # Known exactly, so no probe: the renderer was told all of it.
        b.media = {"width": edl.frame_size[0], "height": edl.frame_size[1],
                   "fps": round(float(edl.timebase.fps), 5),
                   "duration": round(edl.timebase.to_seconds(job.frames), 3),
                   "has_audio": False}
        touched.add(job.clip_id)

        # The check image: the still over the frame it will cover.
        mid = job.program_start + int(job.frames * 0.6)
        if job.clip_id not in compiled:
            try:
                compiled[job.clip_id] = compile_for_monitor(
                    project, edl, [job.clip_id])[0]
            except Exception:  # a check image is a nicety, never a failure
                compiled[job.clip_id] = None
        check, check_note = job.out.with_suffix(".check.png"), None
        try:
            bg = (graphics_mod.grab_program_frame(
                      compiled[job.clip_id], mid,
                      job.out.with_suffix(".bg.png"))
                  if compiled[job.clip_id] else None)
            if bg is None:
                check_note = "camera frame unavailable — check is over grey"
            graphics_mod.composite_check(job.still, bg, check, edl.frame_size)
            if bg:
                bg.unlink(missing_ok=True)
        except Exception as e:
            check, check_note = job.still, f"check composite failed ({e}); bare still"
        report.append({**entry, "ok": True, "path": str(job.out),
                       "check": str(check), "frames": job.frames,
                       "seconds": round(edl.timebase.to_seconds(job.frames), 2),
                       **({"check_note": check_note} if check_note else {})})

    result = validate(edl, project.camera_ids, project.master_duration,
                      project.video_camera_ids)
    if touched and result["ok"]:
        edl.save(project.edl_path)
    return {"ok": result["ok"] and all(x["ok"] for x in report),
            "saved": bool(touched) and result["ok"],
            "rendered": sum(1 for x in report if x["ok"]),
            "items": report, "errors": result["errors"],
            "warnings": result["warnings"] + graphics_mod.stale_graphics(edl)}


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
