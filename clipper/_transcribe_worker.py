"""Transcribe one file in a child process, writing word-level JSON.

WhisperX pulls in sklearn/scipy, which map a third OpenMP runtime
(``vcomp140.dll``) into a process where torch and ctranslate2 have each already
mapped their own ``libiomp5md.dll``. On Windows that deadlocks on the loader
lock partway through ``scipy.interpolate._fitpack`` — the ingest thread parks
at 0% CPU and never returns. A fresh interpreter has no such conflict, so
transcription happens out-of-process and hands back a file.

Transcription goes through ``long_captions.transcribe_long`` rather than the
engine's ``transcribe`` directly. The Uzbek (Kotib) path recovers word timings
with MMS forced alignment, and the engine runs that model over the *whole*
waveform in one forward pass — fine for the 30s reel it was built for, fatal
for an episode: a 2-hour file asks for ~45 GiB of VRAM and dies. Clips come
from episode-length sources by definition, so this path always needs the
windowed variant, which slices on silence and offsets the timings back onto the
global timeline. Peak VRAM is then set by the window, not the episode.
Non-Uzbek languages are delegated to the engine unchanged.

Invoked by ``ingest._transcribe_out_of_process``; not meant to be run by hand.
"""
import argparse
import sys

from caption_engine.transcriber.word import save_words
from long_captions.subtitle_gen import DEFAULT_WINDOW_S, transcribe_long


def main() -> None:
    # Progress goes to a log file the parent opened, so stdout is not a console
    # and defaults to the locale encoding — which cannot represent the status
    # line's arrows and ellipses. Without this the job dies on a UnicodeEncodeError
    # having done all the work.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model-size", default="large-v3")
    ap.add_argument("--language", default="")
    # Smaller batch keeps large-v3 within an 8 GB GPU (default 16 OOMs here).
    ap.add_argument("--batch-size", type=int, default=4)
    # Uzbek only: how much audio MMS aligns at once. Lower it if VRAM is tight.
    ap.add_argument("--window", type=float, default=DEFAULT_WINDOW_S)
    args = ap.parse_args()

    words = transcribe_long(
        args.audio,
        language=args.language or None,
        model_size=args.model_size,
        batch_size=args.batch_size,
        window_s=args.window,
        progress=True,
    )
    save_words(words, args.out)


if __name__ == "__main__":
    main()
