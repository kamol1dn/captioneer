"""Captions for a compiled clip, without re-transcribing anything.

The manual workflow this replaces was: export the finished clip's audio, run it
through the caption engine, copy the word JSON plus a refinement prompt into a
chat, paste the polished JSON back, render the overlay. Two of those steps are
avoidable here:

* **No re-transcription.** The project already holds word-level, forced-aligned
  timings for the whole master timeline. A clip is just a concatenation of kept
  segments, so its captions are the master words remapped onto program time —
  the same arithmetic ``compile.py`` does for picture. That saves a full Whisper
  pass per clip, which at 14 clips an episode is the difference between minutes
  and an hour.

* **No copy-paste.** The agent driving the MCP server *is* the model the prompt
  was written for, so it reads the words and the prompt via one tool and writes
  the polished result back via another.

Program offsets are computed in **frames**, not seconds, and by the same
round-then-accumulate rule the compiler uses. Deriving them independently in
floating-point seconds would drift a frame or two across a multi-segment clip,
and captions that lag picture by a frame are exactly the kind of thing you'd
notice but struggle to name.
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from caption_engine import presets
from caption_engine.prompt import build_prompt
from caption_engine.style import CaptionStyle
from caption_engine.transcriber.word import Word, load_words, save_words

from .edl import EDL, Clip
from .timebase import Timebase

# Captions render as a **strip** by default: a canvas just tall enough for the
# caption block, positioned by hand in Premiere. That's the established
# workflow here, and it keeps the preset's hand-tuned design untouched.
#
# full_frame renders the whole sequence frame so the overlay needs no
# positioning at all. It costs about 1.5x the file size, measured — far less
# than the ~18x pixel-count difference suggests, because ProRes 4444 compresses
# the large uniform transparent region efficiently. So size is a real but
# modest consideration; the reason strip is the default is that positioning by
# hand is the preferred workflow, not that full-frame is expensive.
#
# Only used when full_frame=True; strip mode keeps the preset's own anchor.
DEFAULT_VERTICAL_ANCHOR = 0.78

# What a clip renders with when neither the call nor the project names a preset.
# gashtak_2 is the house style for these shorts; the English projects set
# ``caption_preset`` on the project instead of relying on this.
DEFAULT_PRESET = "gashtak_2"


def program_ranges(clip: Clip, tb: Timebase) -> List[Tuple[float, float, int]]:
    """(master_start, master_end, program_start_frame) per kept segment.

    Mirrors the running-sum-of-integer-lengths rule in ``compile.compile_clip``
    so caption time and picture time cannot disagree.
    """
    out, prog = [], 0
    for seg in sorted(clip.segments, key=lambda s: s.start):
        length = tb.to_frames(seg.end) - tb.to_frames(seg.start)
        if length <= 0:
            continue
        out.append((seg.start, seg.end, prog))
        prog += length
    return out


def words_for_clip(master_words: List[Word], clip: Clip,
                   tb: Timebase) -> List[Word]:
    """Remap master-timeline words onto a clip's program timeline.

    Words in discarded regions vanish. A word straddling a segment boundary is
    clamped to the part that survived — dropping it outright would silently lose
    the first or last word of a clip, which is usually the hook.
    """
    ranges = program_ranges(clip, tb)
    out: List[Word] = []
    for w in master_words:
        for m_start, m_end, p_start in ranges:
            if w.end <= m_start or w.start >= m_end:
                continue
            start = max(w.start, m_start)
            end = min(w.end, m_end)
            if end - start <= 1e-6:
                continue
            offset = tb.to_seconds(p_start - tb.to_frames(m_start))
            out.append(Word(
                text=w.text,
                start=round(start + offset, 3),
                end=round(end + offset, 3),
                probability=w.probability,
            ))
            break
    out.sort(key=lambda w: w.start)
    return out


# ── storage ──────────────────────────────────────────────────────────────────

def captions_dir(project) -> Path:
    d = project.dir / "captions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def words_path(project, clip_id: str) -> Path:
    return captions_dir(project) / f"{clip_id}.words.json"


def mov_path(project, clip_id: str) -> Path:
    return captions_dir(project) / f"{clip_id}.captions.mov"


def load_clip_words(project, clip_id: str) -> Optional[List[Word]]:
    """Polished words for a clip, if they've been written back yet."""
    p = words_path(project, clip_id)
    return load_words(str(p)) if p.exists() else None


def save_clip_words(project, clip_id: str, words: List[Word]) -> Path:
    p = words_path(project, clip_id)
    save_words(words, str(p))
    return p


def words_from_payload(payload: List[dict]) -> List[Word]:
    """Parse the polished JSON coming back from the model.

    Tolerant on purpose: the model returns objects with text/start/end and
    optionally line_break, and anything else it invents is ignored rather than
    raising. ``probability`` is absent by design — the prompt strips it so the
    model can't trip over it.
    """
    out = []
    for d in payload:
        if "text" not in d or "start" not in d or "end" not in d:
            raise ValueError(f"caption word missing text/start/end: {d!r}")
        out.append(Word(
            text=str(d["text"]),
            start=float(d["start"]),
            end=float(d["end"]),
            probability=float(d.get("probability", 1.0)),
            line_break=bool(d.get("line_break", False)),
        ))
    out.sort(key=lambda w: w.start)
    return out


def validate_words(words: List[Word], clip_duration: float) -> dict:
    """Sanity-check polished captions before they're saved.

    The failure this is really guarding against is a model quietly dropping or
    reordering words, or inventing timings past the end of the clip.
    """
    errors, warnings = [], []
    if not words:
        errors.append("no words")
        return {"ok": False, "errors": errors, "warnings": warnings}

    for w in words:
        if w.end <= w.start:
            errors.append(f"word {w.text!r} has end <= start "
                         f"({w.start:.3f}-{w.end:.3f})")
        if w.start < -0.05:
            errors.append(f"word {w.text!r} starts before the clip ({w.start:.3f})")
        if w.end > clip_duration + 0.25:
            errors.append(f"word {w.text!r} ends at {w.end:.3f}s, past the "
                         f"{clip_duration:.2f}s clip")
    for a, b in zip(words, words[1:]):
        if b.start < a.start - 1e-6:
            errors.append(f"words out of order at {b.text!r}")
    if not any(w.line_break for w in words):
        warnings.append("no line_break set on any word — every caption line "
                       "will be packed by character count alone")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "n_words": len(words)}


# ── prompt ───────────────────────────────────────────────────────────────────

def refinement_prompt(words: List[Word], use_emojis: bool = True,
                      language: Optional[str] = None) -> str:
    """The project's own refinement prompt, verbatim.

    Deliberately reuses ``caption_engine.prompt.build_prompt`` rather than
    restating the rules here: that template lives in ``prompts.txt``, is tuned
    by hand (Uzbek orthography, emoji placement, number handling), and is
    re-read on every call. Duplicating it would mean the MCP path silently
    drifts from the web UI path.
    """
    return build_prompt(words, use_emojis=use_emojis, language=language)


# ── rendering ────────────────────────────────────────────────────────────────

def build_style(preset: Optional[str], frame_size: Tuple[int, int],
                fps: int, full_frame: bool = False,
                vertical_anchor: Optional[float] = None,
                scale_to_width: bool = False,
                overrides: Optional[dict] = None) -> CaptionStyle:
    """Resolve a caption preset for a clip.

    Strip mode (the default) leaves the preset almost entirely alone — only
    ``fps`` is forced, because a mismatch there makes word highlighting drift
    against picture. Presets are hand-tuned at their own canvas width, so
    silently rewriting width or anchor would change how they look for no reason
    when the overlay is going to be positioned by hand anyway.

    ``scale_to_width`` opts into resizing the strip to the sequence width,
    scaling typography proportionally so the design survives the change.
    """
    style = presets.get(preset or DEFAULT_PRESET)
    style = CaptionStyle.from_dict(style.to_dict())     # copy, don't mutate
    style.fps = int(fps)

    if full_frame:
        style.width, style.height = int(frame_size[0]), int(frame_size[1])
        # A preset's anchor is relative to its own strip, where 0.5 means
        # "centered in the strip". Against a full 1920-tall frame that would put
        # captions dead center, so drop to a lower third unless told otherwise.
        style.vertical_anchor = (vertical_anchor if vertical_anchor is not None
                                 else DEFAULT_VERTICAL_ANCHOR)
    else:
        if scale_to_width and style.width != frame_size[0]:
            factor = frame_size[0] / style.width
            style.width = int(frame_size[0])
            # Scale everything that carries a pixel dimension, or the design
            # drifts: text would keep its size while the canvas around it moved.
            style.height = int(round(style.height * factor))
            style.font_size = max(1, int(round(style.font_size * factor)))
            style.horizontal_padding = int(round(style.horizontal_padding * factor))
            style.bg_padding = int(round(style.bg_padding * factor))
            style.bg_radius = int(round(style.bg_radius * factor))
            style.text_stroke_width = int(round(style.text_stroke_width * factor))
        if vertical_anchor is not None:
            style.vertical_anchor = vertical_anchor

    for key, value in (overrides or {}).items():
        if hasattr(style, key):
            setattr(style, key, value)
    return style


def render_captions(project, clip_id: str, words: List[Word],
                    duration: float, style: CaptionStyle,
                    out_path: Optional[Path] = None,
                    progress_cb=None) -> Path:
    """Render the alpha ProRes overlay for one clip.

    ``duration`` is the clip's full program length so the .mov spans the whole
    timeline — without it the overlay would end at the last word and the
    clipitem in the XML would be shorter than the picture it sits over.
    """
    from caption_engine.layout import build_phrases
    from caption_engine.renderer import render_to_mov

    phrases = build_phrases(words, style)
    if not phrases:
        raise RuntimeError(f"clip {clip_id!r} produced no caption phrases")
    out = Path(out_path) if out_path else mov_path(project, clip_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    render_to_mov(phrases, style, str(out), duration=duration,
                  progress_cb=progress_cb)
    return out


def caption_movs(project, edl: EDL) -> Dict[str, str]:
    """Rendered caption overlays, keyed by clip id — what export_xml lays on the
    top video track. Clips without one simply don't get a caption track."""
    out = {}
    for clip in edl.clips:
        p = mov_path(project, clip.id)
        if p.exists():
            out[clip.id] = str(p)
    return out


def caption_file_meta(movs: Dict[str, str], frame_size: Tuple[int, int],
                      tb: Timebase, durations: Dict[str, int]) -> Dict[str, dict]:
    """xmeml <file> metadata for the caption overlays, keyed by absolute path.

    The dimensions are probed rather than assumed: a strip overlay is much
    shorter than the sequence frame, and declaring it full-height would make
    Premiere scale it to fit and throw the hand-positioning off.

    Declaring ``has_audio: False`` matters too — without it the writer's default
    would claim an audio stream on a video-only ProRes file, and Premiere shows
    an empty audio channel it can never fill.
    """
    from caption_engine.media import probe

    out = {}
    for clip_id, path in movs.items():
        info = probe(path)
        out[str(Path(path).resolve())] = {
            "width": info.get("width") or frame_size[0],
            "height": info.get("height") or frame_size[1],
            "has_video": True, "has_audio": False,
            "duration_frames": durations.get(clip_id),
        }
    return out
