"""Transcribe one file in a child process, writing word-level JSON.

WhisperX pulls in sklearn/scipy, which map a third OpenMP runtime
(``vcomp140.dll``) into a process where torch and ctranslate2 have each already
mapped their own ``libiomp5md.dll``. On Windows that deadlocks on the loader
lock partway through ``scipy.interpolate._fitpack`` — the ingest thread parks
at 0% CPU and never returns. A fresh interpreter has no such conflict, so
transcription happens out-of-process and hands back a file.

Invoked by ``ingest._transcribe_out_of_process``; not meant to be run by hand.
"""
import argparse

from caption_engine.transcriber import transcribe
from caption_engine.transcriber.word import save_words


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model-size", default="large-v3")
    ap.add_argument("--language", default="")
    # Smaller batch keeps large-v3 within an 8 GB GPU (default 16 OOMs here).
    ap.add_argument("--batch-size", type=int, default=4)
    args = ap.parse_args()

    words = transcribe(
        args.audio,
        model_size=args.model_size,
        language=args.language or None,
        batch_size=args.batch_size,
    )
    save_words(words, args.out)


if __name__ == "__main__":
    main()
