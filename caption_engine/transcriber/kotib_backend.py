"""Kotib Uzbek STT (a Whisper-medium fine-tune) via HuggingFace transformers.

Kotib transcribes Uzbek (Latin script) accurately but emits no word-level
timing, so we pair it with MMS forced alignment (`mms_align`) to recover
per-word timestamps. The audio is decoded once and shared between the two.

Model card: https://huggingface.co/Kotib/uzbek_stt_v1
"""
from typing import List
import re

from .word import Word
from .audio import load_audio, SAMPLE_RATE
from . import mms_align

DEFAULT_MODEL = "Kotib/uzbek_stt_v1"

# Cache the loaded ASR pipeline across calls (model load is slow).
_PIPE = None
_PIPE_KEY = None

_WORD_RE = re.compile(r"\S+")


def _get_pipe(model_name: str, device: str):
    global _PIPE, _PIPE_KEY
    key = (model_name, device)
    if _PIPE_KEY != key:
        import torch
        from transformers import pipeline
        _PIPE = pipeline(
            "automatic-speech-recognition",
            model=model_name,
            chunk_length_s=30,                       # Whisper's 30s receptive field
            device=0 if device == "cuda" else -1,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        )
        _PIPE_KEY = key
    return _PIPE


def transcribe_kotib(
    audio_path: str,
    model_name: str = DEFAULT_MODEL,
    language: str = "uz",
    device: str = "cpu",
) -> List[Word]:
    """Transcribe Uzbek audio with Kotib, then force-align for word timings."""
    waveform = load_audio(audio_path)
    pipe = _get_pipe(model_name, device)

    result = pipe(
        {"array": waveform, "sampling_rate": SAMPLE_RATE},
        generate_kwargs={"language": language, "task": "transcribe"},
    )
    text = (result.get("text") or "").strip()
    tokens = _WORD_RE.findall(text)
    if not tokens:
        return []

    timings = mms_align.align_words(waveform, tokens, device=device)
    return [
        Word(text=tok, start=float(s), end=float(e), probability=float(score))
        for tok, (s, e, score) in zip(tokens, timings)
    ]
