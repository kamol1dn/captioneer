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


def _collapse_repetitions(tokens, max_cycle: int = 6, max_repeats: int = 3):
    """Collapse runaway repetition loops (a Whisper hallucination failure mode).

    Detects a short cycle of words repeated consecutively many times and keeps
    only `max_repeats` copies. The shortest cycle is tried first so we collapse
    on the loop's true period (e.g. a 3-word phrase, not its 6-word doubling).
    The `max_repeats` floor preserves legitimate consecutive repeats (e.g.
    "mana mana", "katta katta") while capping the pathological loops (e.g. the
    same 3-word phrase emitted 30 times).
    """
    result = []
    i = 0
    n = len(tokens)
    while i < n:
        collapsed = False
        for L in range(1, min(max_cycle, n - i) + 1):
            cycle = tokens[i:i + L]
            reps = 1
            j = i + L
            while tokens[j:j + L] == cycle:
                reps += 1
                j += L
            if reps > max_repeats:
                for _ in range(max_repeats):
                    result.extend(cycle)
                i = j
                collapsed = True
                break
        if not collapsed:
            result.append(tokens[i])
            i += 1
    return result


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
        generate_kwargs={
            "language": language,
            "task": "transcribe",
            # Suppress Whisper's decoding-loop hallucination, where it emits the
            # same phrase over and over (e.g. "stresslar ham bo'lgan," x30).
            # no_repeat_ngram_size hard-bans repeating any 3-token window within
            # a chunk; repetition_penalty discourages it softly.
            "no_repeat_ngram_size": 3,
            "repetition_penalty": 1.15,
        },
    )
    text = (result.get("text") or "").strip()
    tokens = _WORD_RE.findall(text)
    if not tokens:
        return []

    # Safety net: collapse any runaway repetition that slipped through. Alignment
    # would otherwise smear the phantom tokens across real audio.
    tokens = _collapse_repetitions(tokens)

    timings = mms_align.align_words(waveform, tokens, device=device)
    return [
        Word(text=tok, start=float(s), end=float(e), probability=float(score))
        for tok, (s, e, score) in zip(tokens, timings)
    ]
