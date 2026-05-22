"""Whisper-based transcription producing word-level timestamps.

Uses `faster-whisper` because it's ~4x faster than openai-whisper and uses less RAM.
Install: pip install faster-whisper
"""
from dataclasses import dataclass, asdict
from typing import List, Optional
import json
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


def transcribe(
    audio_path: str,
    model_size: str = "base",
    language: Optional[str] = None,
    device: str = "auto",
    compute_type: str = "auto",
    vad_filter: bool = True,
) -> List[Word]:
    """Transcribe an audio/video file to word-level timestamps.

    Args:
        audio_path: Path to audio or video file.
        model_size: tiny, base, small, medium, large-v3.
                   `base` is the sweet spot for English reels.
        language: ISO code (e.g. "en"). None = auto-detect.
        device: "cpu", "cuda", or "auto".
        compute_type: "int8", "float16", "float32", or "auto".
        vad_filter: Skip silent sections automatically.

    Returns:
        List of Word objects with start/end times in seconds.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ImportError(
            "faster-whisper is required for transcription.\n"
            "Install it with:  pip install faster-whisper"
        ) from e

    # Smart defaults: int8 on CPU is fast and accurate enough for captions
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"

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


def save_words(words: List[Word], path: str) -> None:
    """Save word list to JSON. Useful for caching and for re-running renders
    without re-transcribing (slow part)."""
    data = [w.to_dict() for w in words]
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_words(path: str) -> List[Word]:
    """Load word list from JSON."""
    data = json.loads(Path(path).read_text())
    return [Word(**d) for d in data]
