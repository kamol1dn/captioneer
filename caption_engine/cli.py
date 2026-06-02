"""Command-line interface for the caption engine.

Examples:
    # Full pipeline
    python -m caption_engine.cli reel.mp4 -o captions.mov --preset reels_classic

    # Transcribe only (save JSON, no render)
    python -m caption_engine.cli reel.mp4 --transcribe-only -j words.json

    # Render from cached JSON (fast iteration on style)
    python -m caption_engine.cli --from-json words.json -o captions.mov --preset punchy_green
"""
import argparse
import sys
import time
from . import engine, presets


def _make_test_words():
    from .transcriber import Word
    return [
        Word("This",      0.20, 0.45),
        Word("is",        0.45, 0.60),
        Word("a",         0.60, 0.70),
        Word("test",      0.70, 1.00),
        Word("render",    1.00, 1.40),
        # gap → new phrase
        Word("Check",     1.90, 2.20),
        Word("your",      2.20, 2.45),
        Word("style",     2.45, 2.75),
        Word("and",       2.75, 2.95),
        Word("settings",  2.95, 3.40),
        # gap → new phrase
        Word("Adjust",    3.90, 4.25),
        Word("and",       4.25, 4.45),
        Word("re-run",    4.45, 4.85),
        Word("to",        4.85, 5.00),
        Word("iterate",   5.00, 5.50),
        Word("fast",      5.50, 5.90),
    ]


def _progress(current: int, total: int):
    pct = current / total * 100 if total else 0
    bar_len = 30
    filled = int(bar_len * current / total) if total else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    sys.stdout.write(f"\r  [{bar}] {pct:5.1f}%  ({current}/{total} frames)")
    sys.stdout.flush()
    if current == total:
        sys.stdout.write("\n")


def main():
    ap = argparse.ArgumentParser(description="Offline word-by-word caption engine")
    ap.add_argument("input", nargs="?", help="Input video or audio file")
    ap.add_argument("-o", "--output", default="captions.mov",
                    help="Output .mov path (ProRes 4444 with alpha)")
    ap.add_argument("--preset", default="reels_classic",
                    choices=list(presets.PRESETS.keys()),
                    help="Style preset")
    ap.add_argument("--model", default="base",
                    choices=["tiny", "base", "small", "medium", "large-v3"],
                    help="Whisper model size")
    ap.add_argument("--language", default=None,
                    help="ISO language code (en, es...). Default: auto-detect.")
    ap.add_argument("--no-align", dest="align", action="store_false",
                    help="Disable WhisperX forced alignment (use faster-whisper's "
                         "less accurate word timings).")
    ap.add_argument("-j", "--json", default=None,
                    help="Cache transcription to this JSON path")
    ap.add_argument("--from-json", default=None,
                    help="Skip transcription, load words from this JSON")
    ap.add_argument("--transcribe-only", action="store_true",
                    help="Just transcribe and save JSON. Don't render.")
    ap.add_argument("--test-render", action="store_true",
                    help="Render mock words to preview style. No input file needed.")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--fps", type=int, default=None)
    ap.add_argument("--duration", type=float, default=None,
                    help="Override clip duration in seconds")
    args = ap.parse_args()

    style = presets.get(args.preset)
    if args.width:  style.width = args.width
    if args.height: style.height = args.height
    if args.fps:    style.fps = args.fps

    t0 = time.time()

    if args.test_render:
        print(f"→ Test render (preset={args.preset}, font={style.font_path}, {style.width}x{style.height}@{style.fps}fps)")
        output = engine.make_captions(
            words=_make_test_words(),
            output_mov=args.output,
            style=style,
            duration=args.duration or 7.0,
            progress_cb=_progress,
        )
        print(f"✓ Done in {time.time() - t0:.1f}s → {output}")
        return

    if args.transcribe_only:
        if not args.input:
            ap.error("Need input file for --transcribe-only")
        if not args.json:
            ap.error("Need -j/--json for --transcribe-only")
        print(f"→ Transcribing {args.input} with model={args.model}"
              f"{' + WhisperX align' if args.align else ''}...")
        words = engine.transcribe(args.input, model_size=args.model,
                                  language=args.language, align=args.align)
        engine.save_words(words, args.json)
        print(f"✓ Saved {len(words)} words to {args.json}")
        return

    if not args.input and not args.from_json:
        ap.error("Need an input file, --from-json, or --test-render")

    print(f"→ Engine starting (preset={args.preset}, {style.width}x{style.height}@{style.fps}fps)")
    output = engine.make_captions(
        input_audio_video=args.input,
        output_mov=args.output,
        words_json=args.from_json,
        style=style,
        model_size=args.model,
        language=args.language,
        align=args.align,
        duration=args.duration,
        cache_words_to=args.json,
        progress_cb=_progress,
    )
    print(f"✓ Done in {time.time() - t0:.1f}s → {output}")


if __name__ == "__main__":
    main()
