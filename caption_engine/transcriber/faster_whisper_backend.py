"""faster-whisper backend.

Fast, low RAM, good transcript text. But its word timestamps are *inferred*
from cross-attention, so they drift (often ±100-300ms, and the error is not
constant). Install: pip install faster-whisper
"""
from typing import List, Optional

from .word import Word


def transcribe_faster_whisper(
    audio_path: str,
    model_size: str,
    language: Optional[str],
    device: str,
    compute_type: str,
    vad_filter: bool,
) -> List[Word]:
    """faster-whisper with its built-in word timestamps."""
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
