"""End-to-end test using mock word data (skips Whisper for now)."""
import sys
sys.path.insert(0, "/home/claude/caption-engine")

from caption_engine import (
    Word, CaptionStyle, build_phrases, render_to_mov, save_words, presets,
)

# A short reel-like script with realistic word timings
MOCK_WORDS = [
    Word("Stop",         0.30, 0.55),
    Word("scrolling",    0.55, 1.05),
    Word("for",          1.10, 1.25),
    Word("a",            1.25, 1.32),
    Word("second.",      1.32, 1.85),

    # natural pause -> new phrase

    Word("This",         2.50, 2.75),
    Word("tool",         2.78, 3.05),
    Word("is",           3.08, 3.20),
    Word("completely",   3.22, 3.85),
    Word("offline.",     3.88, 4.55),

    Word("And",          5.10, 5.30),
    Word("totally",      5.32, 5.75),
    Word("free.",        5.78, 6.30),
]

def main():
    out_dir = "/home/claude/caption-engine/output"
    import os; os.makedirs(out_dir, exist_ok=True)

    # save the mock words as JSON (this is what whisper would produce)
    save_words(MOCK_WORDS, f"{out_dir}/words.json")
    print("✓ Mock word JSON saved")

    # render each preset to its own .mov
    for name in presets.PRESETS:
        style = presets.get(name)
        # smaller canvas for fast testing
        style.width = 720
        style.height = 1280
        style.fps = 24
        style.font_size = 64
        phrases = build_phrases(MOCK_WORDS, style)
        print(f"\n→ Preset '{name}': {len(phrases)} phrases")
        for i, p in enumerate(phrases):
            print(f"    Phrase {i}: '{' | '.join(l.text for l in p.lines)}'")
            print(f"             {p.start:.2f}s → {p.end:.2f}s")
        out = f"{out_dir}/test_{name}.mov"
        render_to_mov(phrases, style, out, duration=7.0)
        size_kb = os.path.getsize(out) / 1024
        print(f"  ✓ Rendered {out} ({size_kb:.0f} KB)")

if __name__ == "__main__":
    main()
