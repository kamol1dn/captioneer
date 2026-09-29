"""Plain-function tool surface for agents, plus a CLI mirror.

``caption_engine.mcp_server`` wraps exactly these functions, so the whole
surface is testable from a shell with real tracebacks:

    python -m caption_engine.toolkit transcribe reel.mp4
    python -m caption_engine.toolkit align voice.wav --text-file script.txt
    python -m caption_engine.toolkit render voice.words.json -o captions.mov --preset otg_cyan
    python -m caption_engine.toolkit research https://www.instagram.com/reel/XXXX/ -o research/

Every command prints one JSON object on stdout (logs go to stderr).
"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .transcriber import Word, save_words, load_words, transcribe
from .transcriber.device import resolve_device


def _words_path(media: str, out_json: Optional[str]) -> str:
    if out_json:
        return out_json
    p = Path(media)
    return str(p.with_name(f"{p.stem}.words.json"))


def summarize(words: List[Word], words_json: str) -> dict:
    return {
        "words_json": str(Path(words_json).resolve()),
        "word_count": len(words),
        "speech_start": round(words[0].start, 3) if words else None,
        "speech_end": round(words[-1].end, 3) if words else None,
        "text": " ".join(w.text for w in words),
    }


def transcribe_media(path: str, language: Optional[str] = "en",
                     model: str = "large-v3",
                     out_json: Optional[str] = None) -> dict:
    """Transcribe any audio/video to word-level timings (WhisperX aligned).
    Writes ``<stem>.words.json`` next to the input unless ``out_json`` is set."""
    words = transcribe(path, model_size=model, language=language, align=True)
    out = _words_path(path, out_json)
    save_words(words, out)
    return summarize(words, out)


def align_script(audio_path: str, text: str, language: str = "en",
                 out_json: Optional[str] = None) -> dict:
    """Force-align a *known* script to its audio: no speech recognition, so the
    words are exactly the script's words and nothing can be misheard. This is
    the right tool for TTS output or a voiceover read from a script.

    Tokens the aligner can't place (digits, symbols) get interpolated times and
    are counted in ``interpolated``. Spell numbers out in the spoken script.
    """
    import whisperx
    from .transcriber.audio import load_audio, SAMPLE_RATE
    from .transcriber.whisperx_backend import _words_from_whisperx

    device = resolve_device("auto")
    audio = load_audio(audio_path)
    duration = len(audio) / SAMPLE_RATE
    script = " ".join(text.split())

    model, metadata = whisperx.load_align_model(language_code=language, device=device)
    result = whisperx.align(
        [{"text": script, "start": 0.0, "end": duration}],
        model, metadata, audio, device, return_char_alignments=False,
    )
    raw = [w for seg in result.get("segments", []) for w in seg.get("words", [])]
    interpolated = sum(1 for w in raw if w.get("start") is None)
    words = _words_from_whisperx(raw)

    out = _words_path(audio_path, out_json)
    save_words(words, out)
    return {**summarize(words, out), "audio_duration": round(duration, 3),
            "script_words": len(script.split()), "interpolated": interpolated}


def render_overlay(words_json: str, output_mov: str, preset: str = "reels_classic",
                   width: Optional[int] = None, height: Optional[int] = None,
                   fps: Optional[int] = None, duration: Optional[float] = None) -> dict:
    """Render word-by-word captions from a words.json to a transparent overlay
    using a caption preset: ProRes 4444 for .mov, VP9+alpha for .webm."""
    from . import engine, presets

    style = presets.get(preset)
    if width:
        style.width = width
    if height:
        style.height = height
    if fps:
        style.fps = fps
    out = engine.make_captions(words_json=words_json, output_mov=output_mov,
                               style=style, duration=duration)
    return {"output": str(Path(out).resolve()), "preset": preset,
            "size": f"{style.width}x{style.height}@{style.fps}"}


def list_presets() -> dict:
    from . import presets
    return {"presets": presets.names(), "groups": presets.groups()}


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m caption_engine.toolkit",
                                 description="Captioneer agent tools (JSON out)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("transcribe", help="media -> aligned words.json")
    t.add_argument("path")
    t.add_argument("--language", default="en", help="ISO code; 'auto' to detect")
    t.add_argument("--model", default="large-v3")
    t.add_argument("-j", "--json", dest="out_json")

    a = sub.add_parser("align", help="known script + audio -> words.json")
    a.add_argument("audio")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--text-file")
    a.add_argument("--language", default="en")
    a.add_argument("-j", "--json", dest="out_json")

    r = sub.add_parser("render", help="words.json -> alpha ProRes .mov")
    r.add_argument("words_json")
    r.add_argument("-o", "--output", required=True)
    r.add_argument("--preset", default="reels_classic")
    r.add_argument("--width", type=int)
    r.add_argument("--height", type=int)
    r.add_argument("--fps", type=int)

    rs = sub.add_parser("research", help="URL or file -> cuts, frames, transcript, pacing report")
    rs.add_argument("source")
    rs.add_argument("-o", "--out", default="research")
    rs.add_argument("--language", default="en")
    rs.add_argument("--model", default="large-v3")
    rs.add_argument("--scene-threshold", type=float, default=0.3)
    rs.add_argument("--cookies-from-browser", default=None,
                    help="Passed to yt-dlp for sites that need a login (e.g. 'chrome')")

    sub.add_parser("presets", help="list caption presets")

    args = ap.parse_args(argv)
    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # keep library chatter off the JSON channel
    try:
        if args.cmd == "transcribe":
            lang = None if args.language == "auto" else args.language
            res = transcribe_media(args.path, lang, args.model, args.out_json)
        elif args.cmd == "align":
            text = args.text if args.text is not None else Path(args.text_file).read_text(encoding="utf-8")
            res = align_script(args.audio, text, args.language, args.out_json)
        elif args.cmd == "render":
            res = render_overlay(args.words_json, args.output, args.preset,
                                 args.width, args.height, args.fps)
        elif args.cmd == "research":
            from .research import research_video
            res = research_video(args.source, args.out, args.language, args.model,
                                 args.scene_threshold, args.cookies_from_browser)
        else:
            res = list_presets()
    finally:
        sys.stdout = real_stdout
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
