"""Whisper-based transcription producing word-level timestamps.

Two backends:

* **faster-whisper** — fast, low RAM, good transcript text. But its word
  timestamps are *inferred* from cross-attention, so they drift (often
  ±100-300ms, and the error is not constant).
  Install: pip install faster-whisper

* **WhisperX** (default) — runs faster-whisper for the transcript, then does
  forced alignment with a phoneme model (wav2vec2) to pin each word to the
  actual audio. Word timestamps tighten to roughly ±20-50ms. This is the right
  choice when the words are correct but the timing is off.
  Install: pip install whisperx

`transcribe(..., align=True)` uses WhisperX and transparently falls back to
faster-whisper (with a warning) if WhisperX is not installed.
"""
from dataclasses import dataclass, asdict
from typing import List, Optional
import json
import warnings
from pathlib import Path


@dataclass
class Word:
    """One transcribed word with timing."""
    text: str
    start: float   # seconds
    end: float     # seconds
    probability: float = 1.0
    line_break: bool = False   # if True, the on-screen line ends after this word

    def to_dict(self) -> dict:
        return asdict(self)


def _resolve_device(device: str) -> str:
    """Resolve 'auto' to 'cuda' if available, else 'cpu'."""
    if device != "auto":
        return device
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _resolve_compute_type(compute_type: str, device: str) -> str:
    """Resolve 'auto'. float16 on GPU, int8 on CPU (float16 is unsupported there)."""
    if compute_type != "auto":
        return compute_type
    return "float16" if device == "cuda" else "int8"


def transcribe(
    audio_path: str,
    model_size: str = "base",
    language: Optional[str] = None,
    device: str = "auto",
    compute_type: str = "auto",
    vad_filter: bool = True,
    align: bool = True,
    batch_size: int = 16,
) -> List[Word]:
    """Transcribe an audio/video file to word-level timestamps.

    Args:
        audio_path: Path to audio or video file.
        model_size: tiny, base, small, medium, large-v3.
                   `large-v3` is best for accuracy; `base` is the fast default.
        language: ISO code (e.g. "en"). None = auto-detect.
        device: "cpu", "cuda", or "auto".
        compute_type: "int8", "float16", "float32", or "auto".
        vad_filter: Skip silent sections automatically (faster-whisper path).
        align: Use WhisperX forced alignment for accurate word timings.
               Falls back to faster-whisper if WhisperX isn't installed.
        batch_size: WhisperX batch size (higher = faster, more VRAM).

    Returns:
        List of Word objects with start/end times in seconds.
    """
    device = _resolve_device(device)
    compute_type = _resolve_compute_type(compute_type, device)

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
            return _transcribe_whisperx(
                audio_path, model_size, language, device, compute_type, batch_size
            )

    return _transcribe_faster_whisper(
        audio_path, model_size, language, device, compute_type, vad_filter
    )


def _transcribe_faster_whisper(
    audio_path: str,
    model_size: str,
    language: Optional[str],
    device: str,
    compute_type: str,
    vad_filter: bool,
) -> List[Word]:
    """Original backend: faster-whisper with its built-in word timestamps."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ImportError(
            "faster-whisper is required for transcription.\n"
            "Install it with:  pip install faster-whisper"
        ) from e

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    segments, _info = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=True,
        vad_filter=vad_filter,
        beam_size=5,
    )

    words: List[Word] = []
    for segment in segments:
        if segment.words is None:
            continue
        for w in segment.words:
            # faster-whisper includes leading whitespace; strip and skip empties
            text = w.word.strip()
            if not text:
                continue
            words.append(Word(
                text=text,
                start=float(w.start),
                end=float(w.end),
                probability=float(w.probability),
            ))
    return words


def _transcribe_whisperx(
    audio_path: str,
    model_size: str,
    language: Optional[str],
    device: str,
    compute_type: str,
    batch_size: int,
) -> List[Word]:
    """WhisperX backend: transcribe, then force-align for accurate timings."""
    import whisperx

    audio = whisperx.load_audio(audio_path)

    model = whisperx.load_model(
        model_size, device, compute_type=compute_type, language=language
    )
    result = model.transcribe(audio, batch_size=batch_size, language=language)
    detected_language = result.get("language", language)

    # Forced alignment. Not every language has an alignment model; if it's
    # missing we keep the (less precise) segment-derived word timings.
    try:
        align_model, metadata = whisperx.load_align_model(
            language_code=detected_language, device=device
        )
        result = whisperx.align(
            result["segments"], align_model, metadata, audio, device,
            return_char_alignments=False,
        )
    except (ValueError, KeyError) as e:
        warnings.warn(
            f"WhisperX alignment unavailable for language '{detected_language}' "
            f"({e}); using unaligned word timings.",
            stacklevel=2,
        )

    raw = [w for seg in result.get("segments", []) for w in seg.get("words", [])]
    return _words_from_whisperx(raw)


def _words_from_whisperx(raw: List[dict]) -> List[Word]:
    """Convert WhisperX word dicts to Word, filling any missing timestamps.

    The alignment model can't always place a token (digits, symbols, etc.), so
    such words come back without start/end. We interpolate from neighbours so
    every word still gets a monotonic, sensible time span.
    """
    words: List[Word] = []
    for w in raw:
        text = str(w.get("word", "")).strip()
        if not text:
            continue
        words.append(Word(
            text=text,
            start=w["start"] if w.get("start") is not None else None,  # type: ignore[arg-type]
            end=w["end"] if w.get("end") is not None else None,        # type: ignore[arg-type]
            probability=float(w.get("score", 1.0) or 1.0),
        ))

    if not words:
        return words

    # Fill missing starts forward from the previous end, missing ends backward
    # from the next start. Anchor the very edges so nothing stays None.
    first_known = next((w.start for w in words if w.start is not None), 0.0)
    last_known = next((w.end for w in reversed(words) if w.end is not None), first_known)

    prev_end = first_known
    for i, w in enumerate(words):
        if w.start is None:
            w.start = prev_end
        if w.end is None:
            nxt = next(
                (words[j].start for j in range(i + 1, len(words))
                 if words[j].start is not None),
                None,
            )
            w.end = nxt if nxt is not None else max(w.start, last_known)
        if w.end < w.start:
            w.end = w.start
        prev_end = w.end

    return words


def save_words(words: List[Word], path: str) -> None:
    """Save word list to JSON. Useful for caching and for re-running renders
    without re-transcribing (slow part)."""
    data = [w.to_dict() for w in words]
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_words(path: str) -> List[Word]:
    """Load word list from JSON."""
    data = json.loads(Path(path).read_text())
    return [Word(**d) for d in data]
