# Caption Engine

Offline word-by-word caption generator. Produces transparent **ProRes 4444 .mov**
files you drop into Premiere / DaVinci Resolve / Final Cut as an overlay.

- 100% offline (uses `faster-whisper` / `whisperx` locally)
- Accurate word timing via WhisperX forced alignment (default)
- Word-level highlighting (scale pop, color, or box modes)
- Style presets + full custom control
- Editor-agnostic output (alpha .mov works everywhere)

## Install

```bash
pip install whisperx pillow      # whisperx pulls in faster-whisper + alignment models
# or, without forced alignment (less accurate timings):
pip install faster-whisper pillow
# ffmpeg must be on PATH
```

By default transcription runs WhisperX forced alignment for accurate word
timings. Pass `--no-align` (CLI) or untick "Align timings" (GUI) to use plain
faster-whisper. If WhisperX isn't installed, the engine warns and falls back to
faster-whisper automatically.

## Quick start

```bash
# Full pipeline: video -> transparent caption .mov
python -m caption_engine.cli my_reel.mp4 -o captions.mov --preset reels_classic

# Iterate on style without re-running Whisper (10x faster):
python -m caption_engine.cli my_reel.mp4 --transcribe-only -j words.json
python -m caption_engine.cli --from-json words.json -o v1.mov --preset punchy_green
python -m caption_engine.cli --from-json words.json -o v2.mov --preset bold_yellow_box
```

## Presets

- `reels_classic` — White text, black stroke, yellow highlight + pop
- `bold_yellow_box` — White text, yellow box behind active word
- `minimal_white` — Clean, with subtle dark background bar
- `punchy_green` — High-energy green highlight, bigger pop

## Python API

```python
from caption_engine import make_captions, CaptionStyle, presets

# Easy mode
make_captions("reel.mp4", "out.mov", preset="reels_classic")

# Custom style
style = presets.reels_classic()
style.font_size = 100
style.highlight_color = (255, 100, 200, 255)  # pink
style.max_chars_per_line = 14
make_captions("reel.mp4", "out.mov", style=style)

# Cache transcription, render multiple variants
from caption_engine import transcribe, save_words
words = transcribe("reel.mp4", model_size="base")
save_words(words, "words.json")

for preset_name in ["reels_classic", "punchy_green", "bold_yellow_box"]:
    make_captions(words_json="words.json",
                  output_mov=f"out_{preset_name}.mov",
                  preset=preset_name)
```

## Architecture

```
transcriber.py   →  Whisper → word-level JSON
layout.py        →  group words into phrases & lines (max chars, gaps)
style.py         →  CaptionStyle dataclass (all settings)
presets.py       →  pre-made style packs
renderer.py      →  Pillow frames → ffmpeg → ProRes 4444 .mov
engine.py        →  orchestrator (public API for GUI wrappers)
cli.py           →  command-line interface
```

Each module is independent — easy to swap pieces (e.g. ASS-file
renderer instead of frame renderer, or whisper.cpp instead of faster-whisper).

## Performance

- Transcription: ~1-2x realtime on CPU (faster-whisper `base` int8)
- Rendering: ~30-60 fps render speed on a modern laptop
- A 60s reel → ~30s transcribe + ~30s render = under a minute total

## Next steps

- [ ] Audio waveform-aware emphasis (louder = bigger pop)
- [ ] Emoji injection by keyword
- [ ] GUI wrapper (Tkinter or web)
- [ ] Premiere extension (UXP) that triggers this as backend
