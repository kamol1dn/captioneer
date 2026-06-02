"""Public API for the caption engine.

This is what a GUI wrapper (or CLI, or Premiere extension) will import.
Keeps the messy details (Whisper, layout algo, ffmpeg) hidden behind a
clean entry point.
"""
from typing import Optional, Callable, List
from pathlib import Path

from .transcriber import Word, transcribe, save_words, load_words
from .layout import build_phrases, Phrase
from .renderer import render_to_mov
from .style import CaptionStyle
from . import presets


def make_captions(
    input_audio_video: Optional[str] = None,
    output_mov: str = "captions.mov",
    words: Optional[List[Word]] = None,
    words_json: Optional[str] = None,
    style: Optional[CaptionStyle] = None,
    preset: Optional[str] = None,
    model_size: str = "base",
    language: Optional[str] = None,
    align: bool = True,
    duration: Optional[float] = None,
    progress_cb: Optional[Callable] = None,
    cache_words_to: Optional[str] = None,
) -> str:
    """End-to-end: file -> transcribe -> layout -> render alpha .mov.

    You can skip transcription by passing either `words` (in-memory) or
    `words_json` (cached path from a previous run). This is huge for iterating
    on style without re-running Whisper.

    Returns the output path.
    """
    # ── resolve style ───────────────────────────────────────────────────────
    if style is None:
        style = presets.get(preset) if preset else presets.reels_classic()

    # ── get words (3 sources: explicit, JSON cache, fresh transcribe) ──────
    if words is None and words_json is not None:
        words = load_words(words_json)
    elif words is None:
        if input_audio_video is None:
            raise ValueError(
                "Provide one of: words=, words_json=, or input_audio_video="
            )
        words = transcribe(
            input_audio_video, model_size=model_size, language=language,
            align=align,
        )
        if cache_words_to:
            save_words(words, cache_words_to)

    # ── layout ──────────────────────────────────────────────────────────────
    phrases = build_phrases(words, style)
    if not phrases:
        raise RuntimeError("No phrases produced - is the audio silent?")

    # ── render ──────────────────────────────────────────────────────────────
    Path(output_mov).parent.mkdir(parents=True, exist_ok=True)
    render_to_mov(
        phrases, style, output_mov,
        duration=duration, progress_cb=progress_cb,
    )
    return output_mov


# Convenience: expose key types/functions at top level
__all__ = [
    "make_captions",
    "CaptionStyle",
    "Word",
    "Phrase",
    "transcribe",
    "build_phrases",
    "render_to_mov",
    "save_words",
    "load_words",
    "presets",
]
