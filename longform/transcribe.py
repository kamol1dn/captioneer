"""Word timings for a long-form render: WhisperX, and/or the YouTube captions.

    python -m longform.transcribe MEDIA OUT_DIR [--model large-v3] [--language en]
    python -m longform.transcribe MEDIA OUT_DIR --verbatim
    python -m longform.transcribe --youtube URL OUT_DIR

The first writes ``whisperx.words.json`` (+ a word-level ``whisperx.vtt``)
with forced alignment, through ``long_captions``. ``--verbatim`` writes
``verbatim.words.json`` instead: every "um"/"uh" kept as ``[um]``/``[uh]`` and
each word's extent measured from the audio — the one to cut from. The last
pulls the upload's auto-captions with yt-dlp (json3 keeps per-word offsets) and
writes ``youtube.words.json``. All are on the render's own timeline, so they
agree to ~0.1 s and cross-check each other's proper nouns.

``--batch-size 4`` keeps WhisperX large-v3 inside an 8 GB card.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def whisperx(media: str, out: Path, model: str, language: str, batch_size: int,
             backend: str = "whisperx") -> Path:
    from caption_engine.transcriber.word import is_filler
    from long_captions.subtitle_gen import render_word_level_vtt, segment_into_cues, transcribe_long

    t0 = time.time()
    words = transcribe_long(media, language=language, backend=backend,
                            model_size=model, batch_size=batch_size)
    name = "verbatim" if backend == "verbatim" else "whisperx"
    path = out / f"{name}.words.json"
    path.write_text(json.dumps([w.to_dict() for w in words], ensure_ascii=False), encoding="utf-8")
    spoken = [w for w in words if not is_filler(w.text)]    # subtitles never show fillers
    cues = segment_into_cues(spoken, max_chars_per_line=42, max_lines=2, max_cue_dur=6.0,
                             max_gap=0.8, min_cue_dur=1.0)
    (out / f"{name}.vtt").write_text(render_word_level_vtt(cues, 42, 2), encoding="utf-8")
    print(f"{len(words)} words in {time.time() - t0:.0f}s -> {path}")
    return path


def youtube(url: str, out: Path) -> Path:
    subprocess.run(["yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs",
                    "--sub-langs", "en.*,en", "--sub-format", "json3",
                    "-o", str(out / "youtube.%(ext)s"), url], check=True)
    src = next(p for p in (out / "youtube.en.json3", out / "youtube.en-orig.json3") if p.exists())
    words = []
    for ev in json.loads(src.read_text(encoding="utf-8")).get("events", []):
        t0 = ev.get("tStartMs", 0)
        for seg in ev.get("segs", []):
            text = seg.get("utf8", "").strip()
            if text:
                words.append({"text": text, "start": (t0 + seg.get("tOffsetMs", 0)) / 1000})
    for i, w in enumerate(words):  # json3 has starts only: end at the next word
        w["end"] = min(words[i + 1]["start"], w["start"] + 1.5) if i + 1 < len(words) else w["start"] + 0.5
    path = out / "youtube.words.json"
    path.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    print(f"{len(words)} words -> {path}")
    return path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m longform.transcribe")
    ap.add_argument("media", nargs="?", help="the long-form render (omit with --youtube)")
    ap.add_argument("out_dir")
    ap.add_argument("--youtube", metavar="URL", help="pull the upload's captions instead")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--language", default="en")
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--verbatim", action="store_true",
                    help="CrisperWhisper: keep fillers, time words to the audio")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if a.youtube:
        youtube(a.youtube, out)
    else:
        if not a.media:
            ap.error("MEDIA is required unless --youtube is given")
        whisperx(a.media, out, a.model, a.language, a.batch_size,
                 backend="verbatim" if a.verbatim else "whisperx")


if __name__ == "__main__":
    main()
