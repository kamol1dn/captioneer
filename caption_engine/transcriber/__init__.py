"""Transcription producing word-level timestamps, with three backends.

* **faster-whisper** — fast, low RAM, good transcript text, but its word
  timestamps are *inferred* and drift (±100-300ms). See
  `faster_whisper_backend`.

* **WhisperX** (default for non-Uzbek) — transcribes with faster-whisper, then
  force-aligns with a phoneme model so timestamps tighten to ~±20-50ms. See
  `whisperx_backend`.

* **Kotib** (Uzbek) — a transformers Whisper fine-tune for Uzbek text, paired
  with MMS forced alignment for word timing (Whisper's own word timings are the
  jittery kind WhisperX exists to fix). See `kotib_backend` / `mms_align`.

`transcribe()` routes to Kotib automatically when `language="uz"`, or when
`backend="kotib"` is passed explicitly. Otherwise it uses WhisperX (with a
transparent fall back to faster-whisper if WhisperX isn't installed).
"""
from typing import List, Optional
import warnings

from .word import Word, save_words, load_words
from .device import resolve_device, resolve_compute_type
from .faster_whisper_backend import transcribe_faster_whisper
from .whisperx_backend import transcribe_whisperx

_UZBEK_CODES = {"uz", "uzb", "uzbek"}


def _use_kotib(backend: str, language: Optional[str]) -> bool:
    if backend == "kotib":
        return True
    if backend == "auto":
        return bool(language) and language.lower() in _UZBEK_CODES
    return False


def transcribe(
    audio_path: str,
    model_size: str = "base",
    language: Optional[str] = None,
    device: str = "auto",
    compute_type: str = "auto",
    vad_filter: bool = True,
    align: bool = True,
    batch_size: int = 16,
    backend: str = "auto",
) -> List[Word]:
    """Transcribe an audio/video file to word-level timestamps.

    Args:
        audio_path: Path to audio or video file.
        model_size: tiny, base, small, medium, large-v3 (ignored by the Kotib
                   backend, which has a fixed model).
        language: ISO code (e.g. "en", "uz"). None = auto-detect. "uz" routes
                  to the Kotib backend.
        device: "cpu", "cuda", or "auto".
        compute_type: "int8", "float16", "float32", or "auto".
        vad_filter: Skip silent sections automatically (faster-whisper path).
        align: Use WhisperX forced alignment for accurate word timings.
               Falls back to faster-whisper if WhisperX isn't installed.
               (The Kotib backend always aligns, via MMS.)
        batch_size: WhisperX batch size (higher = faster, more VRAM).
        backend: "auto" (route by language), "whisperx"/"faster" (honour
                 `align`), or "kotib" (force the Uzbek backend).

    Returns:
        List of Word objects with start/end times in seconds.
    """
    device = resolve_device(device)
    compute_type = resolve_compute_type(compute_type, device)

    if _use_kotib(backend, language):
        # Imported lazily so the English path needs no transformers / uroman.
        from .kotib_backend import transcribe_kotib
        return transcribe_kotib(audio_path, language=(language or "uz"), device=device)

    if align:
        try:
            import whisperx  # noqa: F401
        except ImportError:
            warnings.warn(
                "align=True requested but WhisperX is not installed; falling back "
                "to faster-whisper (less accurate word timings). "
                "Install it with:  pip install whisperx",
                stacklevel=2,
            )
        else:
            return transcribe_whisperx(
                audio_path, model_size, language, device, compute_type, batch_size
            )

    return transcribe_faster_whisper(
        audio_path, model_size, language, device, compute_type, vad_filter
    )


__all__ = ["Word", "transcribe", "save_words", "load_words"]
