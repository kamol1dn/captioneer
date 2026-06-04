"""WhisperX backend.

Runs faster-whisper for the transcript, then does forced alignment with a
phoneme model (wav2vec2) to pin each word to the actual audio. Word timestamps
tighten to roughly ±20-50ms. This is the right choice when the words are
correct but the timing is off. Install: pip install whisperx
"""
from typing import List, Optional
import warnings

from .word import Word


def transcribe_whisperx(
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
