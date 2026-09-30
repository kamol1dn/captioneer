"""Verbatim backend: every word as it was said, fillers included, timed to the audio.

WhisperX is the wrong tool for *editing*. Whisper's training targets had
disfluencies normalised out, so it does not merely miss "um" and "uh", it
removes them — and the duration of each one is absorbed into the words either
side. The transcript then shows a clean pause where the speaker actually said
"uhhh", and a cut placed in that "pause" lands in the middle of the filler. On
OTG EP21 WhisperX found 25 fillers in 7,944 guest words (0.3%); conversational
speech runs 2-6%.

This backend keeps them, in four steps:

1. **Chunk on silence.** The audio is split into <=29 s windows, each cut at the
   quietest point near its end. Sequential decoding cuts fixed 30 s windows
   instead, which slices words at the seams and transcribes them twice or
   garbles them ("And that's." / "That's what we try"). Nothing is dropped: no
   VAD, which would discard exactly the quiet, non-lexical sounds we want.

2. **Transcribe with CrisperWhisper** (``nyralabs/faster_CrisperWhisper``, a
   Whisper large-v3 fine-tune trained for verbatim output), batched through
   faster-whisper. Fillers come back as ``[UH]`` / ``[UM]`` and are stored as
   ``[uh]`` / ``[um]`` — see ``word.is_filler``.

   One trap: faster-whisper's default ``suppress_tokens`` builds its
   "non-speech" list partly by encoding ``" -"`` and taking the first token.
   CrisperWhisper's tokenizer makes the space its *own* token, so that suppresses
   the space itself: the model is forced to separate words with "," or ".", its
   confidence collapses, and every window falls back through the temperature
   ladder (2x realtime instead of ~6x, with garbled text). The list is rebuilt
   here without the space and without the brackets the fillers are spelled
   with.

3. **Force-align each chunk** with MMS (``mms_align``). CrisperWhisper's own word
   times come from cross-attention DTW and are glued end to end — every pause
   is swallowed by the word before it — so they are only a fallback.

4. **Measure each token's extent from the audio.** CTC alignment is spiky: it
   marks where a character is most likely, not how long it lasts, so its word
   ends land early — inside the final consonant, which is precisely where an
   editor would cut. Each token's onset is walked back and its end walked
   forward until the audio actually falls quiet, bounded by its neighbours. The
   gaps between tokens are then real silence, which is what makes a word-level
   cut safe.

The model weights are under Nyra Health's non-commercial licence (the code is
MIT); fine for this project's private use.
"""
from typing import Callable, List, Optional, Sequence, Tuple
import re

import numpy as np

from .word import Word, FILLER_LABEL
from .audio import load_audio, SAMPLE_RATE

DEFAULT_MODEL = "nyralabs/faster_CrisperWhisper"

# The fine-tune was trained on English and German only.
SUPPORTED_LANGUAGES = {"en", "de"}

# Chunking. Whisper's receptive field is 30 s; the cut is searched for in the
# last stretch of each window so there is room to find a real pause.
MAX_CHUNK_S = 29.0
MIN_CHUNK_S = 18.0
# The quiet point is judged over a window this long, not a single frame: a
# plosive's closure is 30-80 ms of near-silence *inside* a word.
QUIET_WINDOW_S = 0.25

# Envelope resolution for boundary refinement.
HOP_S = 0.01
HOP = int(HOP_S * SAMPLE_RATE)

# A token's sound has stopped when the audio stays below its threshold this
# long. Shorter would end words at a stop closure ("ki|t").
QUIET_RUN_S = 0.04
# How far a word's end may be pushed past its CTC end. A final consonant or
# decay outlasts the spike by ~50-200 ms; anything further is more likely the
# next speaker's bleed on this mic than the same word.
MAX_WORD_EXTEND_S = 0.30
# Fillers are drawn out ("uhhhh") and CTC pins only their first letters.
MAX_FILLER_EXTEND_S = 1.5
# Onsets from CTC run late: a nasal or soft consonant ("M" of "Most", a
# breathy "h") murmurs for 100-200 ms before the letter's spike. Measured
# 170 ms on EP21.
MAX_ONSET_WALKBACK_S = 0.25

# CrisperWhisper spells fillers in brackets; this also catches ones glued to a
# neighbour inside a single timed token ("[UM][UH]", "[UH]there").
_BRACKET = re.compile(r"\[([A-Za-z_ -]+)\]")
_EDGE_PUNCT = " .,!?;:-—…\"'`"

# Speech sounds for alignment: the MMS dictionary has letters, not brackets.
_FILLER_SPELLING = {"uh": "uh", "um": "um", "uhm": "um", "hm": "hm", "hmm": "hm",
                    "mm": "mm", "mhm": "mhm", "ah": "ah", "er": "er", "erm": "erm",
                    "eh": "eh"}

# Model load is the slow part; reuse it across calls in one process.
_MODEL = None
_MODEL_KEY = None


def transcribe_verbatim(
    audio_path: str,
    language: Optional[str] = "en",
    device: str = "cuda",
    compute_type: str = "float16",
    batch_size: int = 4,
    beam_size: int = 5,
    align_device: Optional[str] = None,
    model_name: str = DEFAULT_MODEL,
    progress: Optional[Callable[[str], None]] = None,
    keep_model: bool = False,
) -> List[Word]:
    """Transcribe ``audio_path`` verbatim, with fillers, to acoustically timed words.

    ``batch_size`` 4 keeps large-v3 inside an 8 GB card with the aligner loaded.
    ``align_device`` defaults to ``device``. ``keep_model`` holds the recogniser
    in memory for another call in the same process; by default it is freed
    before alignment.
    """
    say = progress or (lambda _msg: None)
    language = (language or "en").lower()
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"the verbatim model is trained on {sorted(SUPPORTED_LANGUAGES)} only, "
            f"not {language!r} — use the whisperx or kotib backend")

    audio = load_audio(audio_path)
    duration = audio.size / SAMPLE_RATE
    env = _envelope(audio)
    chunks = chunk_bounds(env)
    say(f"verbatim: {duration:.0f}s in {len(chunks)} chunks")

    raw = _decode(audio, chunks, language, device, compute_type, batch_size,
                  beam_size, model_name, say)
    if not keep_model:
        # ~3 GB of VRAM the aligner doesn't need, on an 8 GB card that is
        # often shared with Premiere.
        release_model()

    from . import mms_align
    align_device = align_device or device
    timed_all: List[Tuple[str, float, float, float, float]] = []
    n_aligned = 0
    for ci, (c0, c1) in enumerate(chunks):
        tokens = raw[ci]
        if not tokens:
            continue
        seg = audio[int(c0 * SAMPLE_RATE):int(c1 * SAMPLE_RATE)]
        timed = _align_chunk(mms_align, seg, tokens, c0, align_device)
        if timed is None:
            timed = [(t, s, e, 0.0, s) for t, s, e in tokens]   # DTW fallback
        else:
            n_aligned += 1
        timed_all.extend(timed)
        if progress and (ci + 1) % 20 == 0:
            say(f"aligned {ci + 1}/{len(chunks)} chunks")

    timed_all.sort(key=lambda x: (x[1], x[2]))
    words = [Word(text=t, start=s, end=e, probability=p) for t, s, e, p, _ in timed_all]
    refine_extents(words, env, chunks, last_char=[lc for *_, lc in timed_all])
    say(f"verbatim: {len(words)} tokens, "
        f"{sum(1 for w in words if FILLER_LABEL.fullmatch(w.text))} fillers, "
        f"{n_aligned}/{sum(1 for r in raw if r)} chunks force-aligned")
    return words


# ── 1. chunking ──────────────────────────────────────────────────────────────

def _envelope(audio: np.ndarray) -> np.ndarray:
    """RMS per 10 ms hop."""
    n = audio.size // HOP
    if n == 0:
        return np.zeros(0)
    frames = audio[:n * HOP].reshape(n, HOP).astype(np.float64)
    return np.sqrt((frames ** 2).mean(axis=1) + 1e-12)


def chunk_bounds(env: np.ndarray, max_s: float = MAX_CHUNK_S,
                 min_s: float = MIN_CHUNK_S) -> List[Tuple[float, float]]:
    """Cover the whole file with <= ``max_s`` windows cut at quiet points.

    Each cut is the centre of the quietest ``QUIET_WINDOW_S`` stretch between
    ``min_s`` and ``max_s`` after the previous cut. Every sample lands in exactly
    one window, so nothing — a lone "uh" in a long pause included — is skipped.
    """
    total = env.size * HOP_S
    if total <= max_s:
        return [(0.0, total)] if total > 0 else []
    win = max(1, int(QUIET_WINDOW_S / HOP_S))
    power = env ** 2
    smooth = np.convolve(power, np.ones(win) / win, mode="same")

    cuts = [0.0]
    while total - cuts[-1] > max_s:
        lo = int((cuts[-1] + min_s) / HOP_S)
        hi = int((cuts[-1] + max_s) / HOP_S)
        cuts.append((lo + int(np.argmin(smooth[lo:hi]))) * HOP_S)
    cuts.append(total)
    return [(round(a, 3), round(b, 3)) for a, b in zip(cuts, cuts[1:])]


# ── 2. decoding ──────────────────────────────────────────────────────────────

def _load_model(model_name: str, device: str, compute_type: str):
    global _MODEL, _MODEL_KEY
    key = (model_name, device, compute_type)
    if _MODEL is None or _MODEL_KEY != key:
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(model_name, device=device, compute_type=compute_type)
        _MODEL_KEY = key
    return _MODEL


def release_model() -> None:
    """Drop the cached recogniser and its VRAM."""
    global _MODEL, _MODEL_KEY
    _MODEL = _MODEL_KEY = None
    import gc
    gc.collect()


def suppress_list(model, language: str) -> List[int]:
    """faster-whisper's non-speech suppression minus the space and brackets.

    See the module docstring: the stock list suppresses CrisperWhisper's
    stand-alone space token, and ``[`` / ``]`` are how it spells fillers.
    """
    from faster_whisper.tokenizer import Tokenizer
    tok = Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                    task="transcribe", language=language)
    keep = set(tok.encode(" ")[:1]) | set(tok.encode("[")) | set(tok.encode("]"))
    # Non-empty and without -1, so faster-whisper adds only the task/SOT tokens.
    return sorted(set(tok.non_speech_tokens) - keep)


def _decode(audio, chunks, language, device, compute_type, batch_size,
            beam_size, model_name, say) -> List[List[Tuple[str, float, float]]]:
    """Per chunk: (text, start, end) tokens, fillers split out and normalised."""
    from faster_whisper import BatchedInferencePipeline

    model = _load_model(model_name, device, compute_type)
    pipe = BatchedInferencePipeline(model)
    segments, _info = pipe.transcribe(
        audio,
        language=language,
        word_timestamps=True,
        clip_timestamps=[{"start": a, "end": b} for a, b in chunks],
        batch_size=batch_size,
        beam_size=beam_size,
        suppress_tokens=suppress_list(model, language),
    )

    starts = np.array([a for a, _ in chunks])
    out: List[List[Tuple[str, float, float]]] = [[] for _ in chunks]
    done = 0
    for seg in segments:
        ci = int(np.searchsorted(starts, float(seg.start) + 1e-3, side="right")) - 1
        ci = min(max(ci, 0), len(chunks) - 1)
        for w in seg.words or []:
            out[ci].extend(split_token(w.word, float(w.start), float(w.end)))
        done += 1
        if done % 40 == 0:
            say(f"decoded {done} segments")
    return out


def split_token(text: str, start: float, end: float) -> List[Tuple[str, float, float]]:
    """One timed model token -> separately alignable units.

    The recogniser sometimes glues a filler to its neighbour ("[UM][UH]",
    "[UH]there"); splitting lets the aligner place each on its own. The glued
    token's time is shared out evenly — alignment replaces it anyway.
    """
    text = text.strip()
    parts: List[str] = []
    pos = 0
    for m in _BRACKET.finditer(text):
        before = text[pos:m.start()]
        if before.strip(_EDGE_PUNCT):
            parts.append(before.strip())
        parts.append(f"[{m.group(1).strip().lower().replace(' ', '_')}]")
        pos = m.end()
    rest = text[pos:]
    if rest.strip(_EDGE_PUNCT):
        # After a filler, leading punctuation was the filler's ("[UH].So").
        parts.append(rest.strip().lstrip(".,;:") if parts else rest.strip())
    if not parts:
        return []
    if len(parts) == 1:
        return [(parts[0], start, end)]
    step = (end - start) / len(parts)
    return [(p, start + i * step, start + (i + 1) * step) for i, p in enumerate(parts)]


# ── 3. alignment ─────────────────────────────────────────────────────────────

def _spell(text: str) -> str:
    """What the aligner should listen for: a filler's sound, not its brackets."""
    m = FILLER_LABEL.fullmatch(text)
    if m:
        return _FILLER_SPELLING.get(m.group(1), m.group(1).replace("_", ""))
    return text


def _align_chunk(mms_align, seg_audio: np.ndarray,
                 tokens: Sequence[Tuple[str, float, float]], offset: float,
                 device: str) -> Optional[List[Tuple[str, float, float, float, float]]]:
    """Force-align one chunk's tokens: (text, start, end, score, last-letter
    start) each. None when the chunk can't be aligned."""
    if seg_audio.size < SAMPLE_RATE // 10:
        return None
    try:
        timed = mms_align.align_words(seg_audio, [_spell(t) for t, _, _ in tokens],
                                      device=device, last_char=True)
    except Exception:          # CTC needs >= 1 frame per token; garbage in, fall back
        return None
    if len(timed) != len(tokens):
        return None
    return [(t, offset + s, offset + e, float(p), offset + lc)
            for (t, _, _), (s, e, p, lc) in zip(tokens, timed)]


# ── 4. acoustic extents ──────────────────────────────────────────────────────

def refine_extents(words: List[Word], env: np.ndarray,
                   chunks: Sequence[Tuple[float, float]],
                   last_char: Optional[Sequence[float]] = None) -> None:
    """Stretch each token from its CTC spikes to where its sound starts and stops.

    In place. Every end is decided before any start, from the untouched CTC
    times, so one word's extension cannot block its neighbour's. Where two words
    run together with no sustained quiet between them, both meet at the deepest
    dip in the audio between their spikes — the place an editor would cut —
    rather than at either spike.

    ``last_char`` (per token, where its final letter starts) is where the search
    for a word's end begins. CTC holds a word's last letter until the next word
    fires, so its end can run straight over a quiet onset like the "M" of
    "Most"; searching only after that end finds nothing. Starting at the last
    letter also keeps the search out of a stop closure earlier in the word (the
    silence before the "t" of "about").

    Thresholds are per token — a floor from the surrounding chunk and a level
    from the token itself — because a quiet guest and a loud host differ by
    20 dB, and a filler is quieter than the word after it.
    """
    if not words or env.size == 0:
        return
    floors = _chunk_floors(env, chunks)
    starts = np.array([a for a, _ in chunks])
    n = env.size
    total = n * HOP_S
    smooth = np.sqrt(np.convolve(env ** 2, np.ones(3) / 3, mode="same"))
    ctc = [(w.start, w.end) for w in words]

    thr = []
    for w in words:
        a = max(0, min(n - 1, int(w.start / HOP_S)))
        b = min(n, max(a + 1, int(np.ceil(w.end / HOP_S))))
        level = float(np.percentile(env[a:b], 90))
        ci = max(0, int(np.searchsorted(starts, w.start, side="right")) - 1)
        thr.append(max(floors[min(ci, len(floors) - 1)] * 3.2,   # +10 dB over the floor
                       level * 0.063))                           # -24 dB under the token

    ends = []
    for i, w in enumerate(words):
        s0, e0 = ctc[i]
        nxt = ctc[i + 1][0] if i + 1 < len(words) else total
        # Never search before the word's own middle: a one-letter word's "last
        # letter" is its first.
        tail = max(last_char[i] if last_char else e0, (s0 + e0) / 2.0)
        tail = min(tail, e0)
        reach = MAX_FILLER_EXTEND_S if FILLER_LABEL.fullmatch(w.text) else MAX_WORD_EXTEND_S
        hi = max(e0, min(nxt, e0 + reach))
        end = _sound_end(env, tail, hi, thr[i])
        if end is None:
            # No pause: the words run together (or the sound outlasts the reach
            # — bleed, a drawl). Either way the quietest moment is the boundary.
            end = _dip(smooth, tail, hi)
        ends.append(end)

    for i, w in enumerate(words):
        s0 = ctc[i][0]
        prev_end = ends[i - 1] if i > 0 else 0.0
        lo = min(s0, max(prev_end, s0 - MAX_ONSET_WALKBACK_S))
        start = _sound_start(env, lo, s0, thr[i])
        if start is None:
            start = prev_end if lo <= prev_end else _dip(smooth, lo, s0)
        w.start = round(max(prev_end, min(start, s0)), 3)
        w.end = round(max(ends[i], w.start), 3)

    trim_overlong(words, env, thr)


# A word never holds this much silence inside it — a stop closure is < 100 ms.
INTERNAL_QUIET_S = 0.25


def max_token_s(text: str) -> float:
    """The longest a token can plausibly sound: fillers drawl, words don't."""
    if FILLER_LABEL.fullmatch(text):
        return 2.0
    letters = sum(ch.isalpha() for ch in text)
    return min(1.5, 0.3 + 0.1 * max(letters, 1))


def trim_overlong(words: List[Word], env: np.ndarray,
                  thr: Optional[Sequence[float]] = None) -> int:
    """Cut back tokens whose letters were spread over more than one sound.

    On an isolated mic the other speakers are still faintly there, and a lone
    low-confidence "Yeah." or "The." — often transcribed from that bleed — can
    be aligned with its letters seconds apart: EP21 had a "hmm" 11.5 s long and
    a "Yeah." 7 s long, each blocking every cut point in that stretch and
    tripping false cuts_word flags. The last-letter anchor can't help there,
    since the last letter is the misplaced one. Physically, a word neither
    contains a quarter second of silence nor outlasts its letters by much; when
    one does, it is kept to the first sound from its onset. In place; returns
    how many were trimmed.
    """
    n = 0
    hop = HOP_S
    for i, w in enumerate(words):
        limit = max_token_s(w.text)
        a, b = int(w.start / hop), min(env.size, int(np.ceil(w.end / hop)))
        if b <= a + 1:
            continue
        t = thr[i] if thr is not None else float(np.percentile(env[a:b], 90)) * 0.063
        quiet_at = _sound_end_run(env, a + 5, b, t, INTERNAL_QUIET_S)
        if w.end - w.start <= limit and quiet_at is None:
            continue
        cap = w.start + limit
        end = quiet_at if quiet_at is not None else None
        if end is None or end > cap:
            end = _sound_end(env, w.start + 0.05, cap, t)
        if end is None:
            end = cap
        w.end = round(max(w.start + 0.05, min(end, w.end)), 3)
        n += 1
    return n


def _sound_end_run(env: np.ndarray, a: int, b: int, thr: float,
                   run_s: float) -> Optional[float]:
    """Start of the first quiet run of ``run_s`` inside frames [a, b), if any."""
    need = max(1, int(round(run_s / HOP_S)))
    quiet = 0
    for j in range(a, b):
        if env[j] < thr:
            quiet += 1
            if quiet >= need:
                return (j - need + 1) * HOP_S
        else:
            quiet = 0
    return None


def _chunk_floors(env: np.ndarray, chunks) -> List[float]:
    """Each chunk's room tone: the 10th percentile of its own level.

    Local, not global: gain and background change over an hour, and an isolated
    mic's floor while its speaker is quiet is not the floor under their voice.
    """
    glob = float(np.percentile(env, 5)) if env.size else 1e-6
    out = []
    for c0, c1 in chunks:
        seg = env[int(c0 / HOP_S):int(c1 / HOP_S)]
        out.append(max(glob, float(np.percentile(seg, 10))) if seg.size else glob)
    return out or [glob]


def _sound_end(env: np.ndarray, start: float, limit: float,
               thr: float) -> Optional[float]:
    """First moment after ``start`` where the audio stays under ``thr`` for
    ``QUIET_RUN_S`` — the token's own sound has stopped. None if it never does
    before ``limit``."""
    need = max(1, int(round(QUIET_RUN_S / HOP_S)))
    a = int(start / HOP_S)
    b = min(env.size, int(np.ceil(limit / HOP_S)))
    quiet = 0
    for j in range(a, b):
        if env[j] < thr:
            quiet += 1
            if quiet >= need:
                return max(start, min(limit, (j - need + 1) * HOP_S))
        else:
            quiet = 0
    return None


def _sound_start(env: np.ndarray, limit: float, start: float,
                 thr: float) -> Optional[float]:
    """Walking back from ``start``: where the last sustained quiet before it
    ends — the token's sound begins there. None if there is none after
    ``limit``."""
    need = max(1, int(round(QUIET_RUN_S / HOP_S)))
    a = max(0, int(limit / HOP_S))
    b = min(env.size, int(start / HOP_S))
    quiet = 0
    for j in range(b - 1, a - 1, -1):
        if env[j] < thr:
            quiet += 1
            if quiet >= need:
                return min(start, (j + quiet) * HOP_S)
        else:
            quiet = 0
    return None


def _dip(smooth: np.ndarray, a: float, b: float) -> float:
    """The quietest 10 ms between ``a`` and ``b`` (``a`` when they meet)."""
    i, j = int(a / HOP_S), int(np.ceil(b / HOP_S))
    if j <= i + 1 or i >= smooth.size:
        return a
    j = min(j, smooth.size)
    return (i + int(np.argmin(smooth[i:j]))) * HOP_S
