"""Media in -> subtitle file (.srt / .vtt) out.

    python long_captions/subtitle_gen.py lecture.mp4 -o lecture.srt --language uz
    python -m long_captions.subtitle_gen podcast.mp3 -o podcast.vtt

This reuses `caption_engine`'s transcription engine as-is: Kotib + MMS forced
alignment for Uzbek, WhisperX / faster-whisper for everything else. The one
thing it adds is *bounded VRAM for long media*.

Why a separate module instead of calling `caption_engine`'s `transcribe()`?
    The Kotib (Uzbek) path force-aligns word timings with Meta's MMS model
    (`mms_align.align_words`). That model is a wav2vec2 encoder with full
    O(n^2) self-attention, and the engine runs it over the *whole* waveform in
    a single forward pass. That is fine for a 30s reel — the engine's normal
    input — but an hour of audio would blow up GPU memory.

    So for the Uzbek path we slice the audio into short, silence-snapped
    windows and run transcription + alignment per window, offsetting the
    timestamps back onto the global timeline. MMS therefore never sees more
    than `window_s` (~30s) of audio at once, so peak VRAM is flat regardless of
    total length. The non-Uzbek backends (faster-whisper / WhisperX) already
    stream / VAD-chunk internally, so those are delegated to the engine
    unchanged.

Nothing in `caption_engine` is modified or imported for its side effects; we
only call its public building blocks.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

# Allow running as a loose script (`python long_captions/subtitle_gen.py ...`)
# as well as a module (`python -m long_captions.subtitle_gen ...`). In script
# mode sys.path[0] is this folder, not the repo root, so caption_engine would
# not import — add the repo root explicitly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from caption_engine.transcriber import Word  # noqa: E402
from caption_engine.transcriber.audio import load_audio, SAMPLE_RATE  # noqa: E402
from caption_engine.transcriber.device import resolve_device  # noqa: E402

# Mirror the engine's Uzbek routing (transcriber/__init__.py::_use_kotib).
_UZBEK_CODES = {"uz", "uzb", "uzbek"}

# Kept short so MMS forced alignment (O(n^2) attention) stays cheap on VRAM.
# 30s matches Whisper's own receptive field, so we lose no transcription
# context by cutting here.
DEFAULT_WINDOW_S = 30.0
# How far on either side of a window boundary we may slide the cut to land it in
# a quiet spot, so we avoid slicing through the middle of a word.
DEFAULT_BAND_S = 3.0


# ─────────────────────────────── routing ────────────────────────────────────


def _use_kotib(backend: str, language: Optional[str]) -> bool:
    """Same decision the engine makes: route Uzbek to Kotib + MMS."""
    if backend == "kotib":
        return True
    if backend == "auto":
        return bool(language) and language.lower() in _UZBEK_CODES
    return False


# ───────────────────────── silence-snapped windowing ────────────────────────


def _quietest_index(waveform: np.ndarray, lo: int, hi: int, frame: int) -> int:
    """Return the start sample of the lowest-energy `frame` within [lo, hi)."""
    best_i, best_e = lo, None
    i = lo
    while i < hi:
        seg = waveform[i:i + frame]
        e = float(np.dot(seg, seg))
        if best_e is None or e < best_e:
            best_e, best_i = e, i
        i += frame
    return best_i


def _split_points(
    waveform: np.ndarray,
    window_s: float,
    band_s: float,
    sample_rate: int = SAMPLE_RATE,
) -> List[int]:
    """Sample indices that cut `waveform` into ~`window_s` windows.

    Each interior boundary is nudged, within +/-`band_s`, onto the quietest
    20 ms frame so cuts fall in silence rather than mid-word.
    """
    n = len(waveform)
    win = int(window_s * sample_rate)
    band = int(band_s * sample_rate)
    frame = max(1, int(0.02 * sample_rate))  # 20 ms energy frames
    if n <= win:
        return [0, n]

    points = [0]
    k = 1
    while k * win < n:
        target = k * win
        lo = max(points[-1] + frame, target - band)
        hi = min(n - frame, target + band)
        cut = _quietest_index(waveform, lo, hi, frame) if hi > lo else min(target, n)
        if cut > points[-1]:
            points.append(cut)
        k += 1
    points.append(n)
    # Guarantee strictly increasing (a snapped cut can collide with the tail).
    return [p for i, p in enumerate(points) if i == 0 or p > points[i - 1]]


# ────────────────────────── Uzbek windowed backend ──────────────────────────

# Reuse the exact decoding config the engine's Kotib backend uses (repetition
# suppression against Whisper's decoding-loop hallucinations). Defined here as a
# constant so the per-window loop below stays readable; kept in sync with
# caption_engine/transcriber/kotib_backend.py::transcribe_kotib.
_KOTIB_GEN_KWARGS = {
    "task": "transcribe",
    "no_repeat_ngram_size": 3,
    "repetition_penalty": 1.15,
}


def _transcribe_uzbek_windowed(
    waveform: np.ndarray,
    device: str,
    window_s: float = DEFAULT_WINDOW_S,
    band_s: float = DEFAULT_BAND_S,
    model_name: Optional[str] = None,
    progress: bool = True,
) -> List[Word]:
    """Kotib transcription + MMS alignment, one silence-snapped window at a time.

    Peak GPU memory is set by `window_s`, not by the length of `waveform`, so an
    hour-long file costs the same VRAM as a 30-second one.
    """
    # Imported lazily (heavy: transformers, torch, torchaudio, uroman) so callers
    # that only ever touch the English path never pay for them.
    from caption_engine.transcriber import mms_align
    from caption_engine.transcriber.kotib_backend import (
        DEFAULT_MODEL,
        _WORD_RE,
        _collapse_repetitions,
        _get_pipe,
    )

    pipe = _get_pipe(model_name or DEFAULT_MODEL, device)
    points = _split_points(waveform, window_s, band_s)
    n_windows = len(points) - 1

    words: List[Word] = []
    for w in range(n_windows):
        a, b = points[w], points[w + 1]
        offset = a / SAMPLE_RATE
        chunk = waveform[a:b]

        result = pipe(
            {"array": chunk, "sampling_rate": SAMPLE_RATE},
            generate_kwargs={"language": "uz", **_KOTIB_GEN_KWARGS},
        )
        text = (result.get("text") or "").strip()
        tokens = _collapse_repetitions(_WORD_RE.findall(text))
        if tokens:
            timings = mms_align.align_words(chunk, tokens, device=device)
            for tok, (s, e, score) in zip(tokens, timings):
                words.append(Word(
                    text=tok,
                    start=offset + float(s),
                    end=offset + float(e),
                    probability=float(score),
                ))

        if progress:
            pct = (w + 1) / n_windows * 100
            sys.stdout.write(
                f"\r  transcribing… {pct:5.1f}%  "
                f"(window {w + 1}/{n_windows}, {len(words)} words)"
            )
            sys.stdout.flush()
    if progress and n_windows:
        sys.stdout.write("\n")

    return _enforce_monotonic(words)


def _enforce_monotonic(words: List[Word]) -> List[Word]:
    """Keep timings non-decreasing across window seams (subtitles must not
    overlap or run backwards)."""
    prev_end = 0.0
    for w in words:
        if w.start < prev_end:
            w.start = prev_end
        if w.end < w.start:
            w.end = w.start
        prev_end = w.end
    return words


# ─────────────────────────── transcription entry ────────────────────────────


def transcribe_long(
    media_path: str,
    language: Optional[str] = None,
    backend: str = "auto",
    device: str = "auto",
    model_size: str = "base",
    window_s: float = DEFAULT_WINDOW_S,
    band_s: float = DEFAULT_BAND_S,
    progress: bool = True,
) -> List[Word]:
    """Transcribe (with word timings) any-length media, bounding VRAM.

    Uzbek routes to the windowed Kotib + MMS path above. Every other language
    delegates to `caption_engine`'s `transcribe()`, whose backends
    (faster-whisper / WhisperX) already process long audio in streamed /
    VAD-selected chunks.
    """
    device = resolve_device(device)

    if _use_kotib(backend, language):
        if progress:
            print(f"→ Uzbek (Kotib + MMS), windowed at {window_s:g}s on {device}")
        waveform = load_audio(media_path)
        return _transcribe_uzbek_windowed(
            waveform, device, window_s, band_s, progress=progress,
        )

    from caption_engine.transcriber import transcribe as engine_transcribe
    if progress:
        print(f"→ {language or 'auto'} (backend={backend}, model={model_size}) on {device}")
    return engine_transcribe(
        media_path,
        model_size=model_size,
        language=language,
        device=device,
        backend=backend,
    )


# ──────────────────────────── cue segmentation ──────────────────────────────


@dataclass
class Cue:
    """One subtitle entry."""
    index: int
    start: float          # seconds
    end: float            # seconds
    text: str             # may contain '\n' between lines


def _joined_len(words: List[Word]) -> int:
    return sum(len(w.text) for w in words) + max(0, len(words) - 1)


def _wrap_lines(words: List[Word], max_chars: int, max_lines: int) -> str:
    """Greedily pack `words` into up to `max_lines` lines of <= `max_chars`."""
    lines: List[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w.text) > max_chars:
            lines.append(cur)
            cur = w.text
        else:
            cur = w.text if not cur else f"{cur} {w.text}"
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        # Overflow (a single very long word run): fold the rest into the last line.
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return "\n".join(lines)


def segment_into_cues(
    words: List[Word],
    max_chars_per_line: int = 42,
    max_lines: int = 2,
    max_cue_dur: float = 6.0,
    max_gap: float = 0.8,
    min_cue_dur: float = 1.0,
) -> List[Cue]:
    """Group timed words into readable subtitle cues.

    A new cue starts on any of: a silence gap > `max_gap`, the running text
    exceeding what fits in `max_lines` x `max_chars_per_line`, or the cue
    reaching `max_cue_dur`. Short cues are stretched to `min_cue_dur` without
    overlapping the next one.
    """
    if not words:
        return []

    max_total = max_chars_per_line * max_lines
    groups: List[List[Word]] = []
    cur: List[Word] = []
    for w in words:
        if cur:
            gap = w.start - cur[-1].end
            projected = _joined_len(cur) + 1 + len(w.text)
            duration = w.end - cur[0].start
            if gap > max_gap or projected > max_total or duration > max_cue_dur:
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)

    cues = [
        [g[0].start, g[-1].end, _wrap_lines(g, max_chars_per_line, max_lines)]
        for g in groups
    ]

    # Enforce a minimum on-screen time, but never past the next cue's start.
    for i, c in enumerate(cues):
        if c[1] - c[0] < min_cue_dur:
            wanted = c[0] + min_cue_dur
            if i + 1 < len(cues):
                wanted = min(wanted, cues[i + 1][0])
            c[1] = max(c[0], wanted)

    return [Cue(i + 1, s, e, t) for i, (s, e, t) in enumerate(cues)]


# ──────────────────────────────── writers ───────────────────────────────────


def _format_timestamp(t: float, vtt: bool) -> str:
    """Seconds -> 'HH:MM:SS,mmm' (SRT) or 'HH:MM:SS.mmm' (VTT)."""
    ms = max(0, int(round(t * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    sep = "." if vtt else ","
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def render_subtitles(cues: List[Cue], fmt: str) -> str:
    """Serialize cues to an SRT or VTT document string."""
    vtt = fmt == "vtt"
    blocks: List[str] = ["WEBVTT"] if vtt else []
    for c in cues:
        lines = [] if vtt else [str(c.index)]
        lines.append(f"{_format_timestamp(c.start, vtt)} --> {_format_timestamp(c.end, vtt)}")
        lines.append(c.text)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _resolve_format(output: str, fmt: Optional[str]) -> str:
    if fmt:
        return fmt.lower()
    return "vtt" if output.lower().endswith(".vtt") else "srt"


# ───────────────────────────── public entry ─────────────────────────────────


def generate_subtitles(
    media_path: str,
    output: Optional[str] = None,
    language: Optional[str] = None,
    backend: str = "auto",
    device: str = "auto",
    model_size: str = "base",
    fmt: Optional[str] = None,
    window_s: float = DEFAULT_WINDOW_S,
    band_s: float = DEFAULT_BAND_S,
    max_chars_per_line: int = 42,
    max_lines: int = 2,
    max_cue_dur: float = 6.0,
    max_gap: float = 0.8,
    min_cue_dur: float = 1.0,
    progress: bool = True,
) -> str:
    """End-to-end: media file -> transcribe (bounded VRAM) -> subtitle file.

    Args:
        media_path: Any audio/video file ffmpeg can read.
        output: Output path. Defaults to `media_path` with a .srt extension.
        language: ISO code. "uz" routes to the windowed Kotib + MMS path;
                  None = auto-detect (non-Uzbek backends).
        backend: "auto" (route by language), "kotib", "whisperx", or "faster".
        fmt: "srt" or "vtt". Inferred from `output`'s extension if omitted.
        window_s / band_s: Uzbek windowing — window length and silence-snap band.
        The remaining knobs tune cue segmentation (readability).

    Returns:
        The output path written.
    """
    if output is None:
        output = str(Path(media_path).with_suffix(".srt"))

    words = transcribe_long(
        media_path, language=language, backend=backend, device=device,
        model_size=model_size, window_s=window_s, band_s=band_s, progress=progress,
    )
    if not words:
        raise RuntimeError(
            f"No speech transcribed from {media_path!r} — silent, or wrong language?"
        )

    cues = segment_into_cues(
        words,
        max_chars_per_line=max_chars_per_line,
        max_lines=max_lines,
        max_cue_dur=max_cue_dur,
        max_gap=max_gap,
        min_cue_dur=min_cue_dur,
    )

    fmt = _resolve_format(output, fmt)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(render_subtitles(cues, fmt), encoding="utf-8")
    if progress:
        print(f"✓ {len(cues)} cues → {output}")
    return output


# ──────────────────────────────── CLI ───────────────────────────────────────


def main() -> None:
    # Status lines use a couple of non-ASCII glyphs; make them safe on legacy
    # Windows consoles (cp1252) instead of crashing on encode.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        description="Turn media into a subtitle file (.srt / .vtt), reusing the "
                    "caption engine. Handles hour-long input without exhausting VRAM."
    )
    ap.add_argument("input", help="Input audio or video file")
    ap.add_argument("-o", "--output", default=None,
                    help="Output path (.srt or .vtt). Default: input name with .srt")
    ap.add_argument("--language", default=None,
                    help="ISO code (e.g. uz, en). 'uz' uses the Uzbek engine. "
                         "Default: auto-detect.")
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "kotib", "whisperx", "faster"],
                    help="Transcription backend routing. Default: auto (by language).")
    ap.add_argument("--model", default="base",
                    choices=["tiny", "base", "small", "medium", "large-v3"],
                    help="Whisper model size (ignored by the Kotib/Uzbek backend).")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--format", dest="fmt", default=None, choices=["srt", "vtt"],
                    help="Override output format (else inferred from --output).")
    ap.add_argument("--window", type=float, default=DEFAULT_WINDOW_S,
                    help=f"Uzbek windowing length in seconds (default {DEFAULT_WINDOW_S:g}). "
                         "Lower this if you still hit VRAM limits.")
    ap.add_argument("--max-line-chars", type=int, default=42,
                    help="Max characters per subtitle line (default 42).")
    ap.add_argument("--max-lines", type=int, default=2,
                    help="Max lines per cue (default 2).")
    ap.add_argument("--max-cue-dur", type=float, default=6.0,
                    help="Max seconds a single cue stays on screen (default 6).")
    args = ap.parse_args()

    t0 = time.time()
    output = generate_subtitles(
        args.input,
        output=args.output,
        language=args.language,
        backend=args.backend,
        device=args.device,
        model_size=args.model,
        fmt=args.fmt,
        window_s=args.window,
        max_chars_per_line=args.max_line_chars,
        max_lines=args.max_lines,
        max_cue_dur=args.max_cue_dur,
    )
    print(f"  done in {time.time() - t0:.1f}s → {output}")


if __name__ == "__main__":
    main()
