"""Multilingual forced alignment (Meta MMS via torchaudio) for word timings.

Kotib — and Whisper generally — produce accurate Uzbek *text* but no reliable
word-level timing. We recover timing exactly the way WhisperX does for English:
force-align the transcript to the audio. torchaudio's `MMS_FA` bundle covers
1100+ languages (incl. Uzbek); we romanize Uzbek's Latin orthography
(`oʻ`, `gʻ`, …) down to the aligner's 28-letter dictionary with `uroman`.

This uses the torch / torchaudio that are already installed (pulled in by
WhisperX) — no torch-clobbering install. The only new dependency is `uroman`,
which is pure Python.

Note: on torchaudio ≥ 2.9 the underlying `forced_align` op is slated for
removal (it is merely deprecated on 2.8). Pin torchaudio < 2.9 until this is
revisited.
"""
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
import torch
from torchaudio.pipelines import MMS_FA as _BUNDLE

from .audio import load_audio, SAMPLE_RATE

# Lazily-loaded singletons — model load is slow, so do it once per process.
_MODEL = None
_TOKENIZER = None
_ALIGNER = None
_DICT_CHARS: Optional[set] = None
_UROMAN = None


def _ensure_loaded(device: str):
    """Load (once) the MMS acoustic model, tokenizer, aligner and uroman."""
    global _MODEL, _TOKENIZER, _ALIGNER, _DICT_CHARS, _UROMAN
    if _DICT_CHARS is None:
        # '*' is the star/out-of-vocab token; never emit it during normalization.
        _DICT_CHARS = set(_BUNDLE.get_dict().keys()) - {"*"}
    if _UROMAN is None:
        import uroman
        _UROMAN = uroman.Uroman()
    if _TOKENIZER is None:
        _TOKENIZER = _BUNDLE.get_tokenizer()
        _ALIGNER = _BUNDLE.get_aligner()
    if _MODEL is None or getattr(_MODEL, "_ce_device", None) != device:
        _MODEL = _BUNDLE.get_model().to(device).eval()
        _MODEL._ce_device = device  # remember placement so we don't re-.to() each call
    return _MODEL, _TOKENIZER, _ALIGNER


def _normalize(word: str) -> str:
    """Romanize one word and keep only characters in the aligner's dictionary."""
    romanized = _UROMAN.romanize_string(word).lower()
    return "".join(ch for ch in romanized if ch in _DICT_CHARS)


def align_words(
    audio: Union[str, np.ndarray, torch.Tensor],
    words: List[str],
    device: str = "cpu",
) -> List[Tuple[float, float, float]]:
    """Force-align `words` to `audio`; return (start_s, end_s, score) per word.

    The result is always 1:1 with `words`. Words that romanize to nothing
    (digits, lone symbols) have no acoustic anchor, so their timing is
    interpolated from neighbours — mirroring how the WhisperX backend fills
    unplaceable tokens.
    """
    if not words:
        return []

    model, tokenizer, aligner = _ensure_loaded(device)
    waveform = _to_waveform(audio).to(device)
    total_dur = waveform.size(1) / SAMPLE_RATE

    norm = [_normalize(w) for w in words]
    keep = [i for i, n in enumerate(norm) if n]
    if not keep:
        # Nothing is alignable — spread the words evenly across the clip.
        step = total_dur / len(words)
        return [(i * step, (i + 1) * step, 0.0) for i in range(len(words))]

    with torch.inference_mode():
        emission, _ = model(waveform)
    num_frames = emission.size(1)
    sec_per_frame = waveform.size(1) / num_frames / SAMPLE_RATE

    token_spans = aligner(emission[0], tokenizer([norm[i] for i in keep]))

    timed: Dict[int, Tuple[float, float, float]] = {}
    for idx, spans in zip(keep, token_spans):
        start = spans[0].start * sec_per_frame
        end = spans[-1].end * sec_per_frame
        score = float(sum(float(s.score) for s in spans) / len(spans))
        timed[idx] = (start, end, score)

    return _interpolate(len(words), timed, total_dur)


def _to_waveform(audio: Union[str, np.ndarray, torch.Tensor]) -> torch.Tensor:
    """Coerce a path / numpy array / tensor into a [1, time] float32 tensor."""
    if isinstance(audio, str):
        audio = load_audio(audio)
    if isinstance(audio, np.ndarray):
        audio = torch.from_numpy(audio)
    audio = audio.to(torch.float32)
    if audio.dim() == 1:
        audio = audio.unsqueeze(0)
    return audio


def _interpolate(
    n: int,
    timed: Dict[int, Tuple[float, float, float]],
    total_dur: float,
) -> List[Tuple[float, float, float]]:
    """Fill timings for words that had no acoustic anchor.

    Each maximal run of unanchored words is spread evenly between the previous
    anchored end and the next anchored start, keeping the sequence monotonic.
    """
    result: List[Optional[Tuple[float, float, float]]] = [timed.get(i) for i in range(n)]
    anchored = sorted(timed)
    first_start = timed[anchored[0]][0]
    last_end = timed[anchored[-1]][1]

    i = 0
    while i < n:
        if result[i] is not None:
            i += 1
            continue
        j = i
        while j < n and result[j] is None:
            j += 1
        lo = result[i - 1][1] if i > 0 else first_start   # previous anchored end
        hi = result[j][0] if j < n else last_end          # next anchored start
        hi = max(hi, lo)
        span = (hi - lo) / (j - i)
        for k in range(i, j):
            result[k] = (lo + span * (k - i), lo + span * (k - i + 1), 0.0)
        i = j

    return result  # type: ignore[return-value]
