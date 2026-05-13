"""Offline word-by-word caption engine. See engine.make_captions()."""
from .engine import (
    make_captions, CaptionStyle, Word, Phrase,
    transcribe, build_phrases, render_to_mov,
    save_words, load_words, presets,
)

__version__ = "0.1.0"
__all__ = [
    "make_captions", "CaptionStyle", "Word", "Phrase",
    "transcribe", "build_phrases", "render_to_mov",
    "save_words", "load_words", "presets",
]
